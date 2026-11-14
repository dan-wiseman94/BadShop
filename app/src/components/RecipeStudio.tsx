import { useState } from "react";
import type { RJSFSchema } from "@rjsf/utils";
import { action, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import { useOperation } from "../useOperation";
import type { Recipe, RecipeRowResult, Tool } from "../types";
import { rpc } from "../rpc";
import { ToolForm } from "./ToolForm";
import { ArtifactThumb } from "./Viewer";

function recipeTool(tool: Tool, index: number, recipe: Recipe): Tool {
  const schema = structuredClone(tool.schema);
  function visit(node: RJSFSchema) {
    if (node.format === "badshop-image") {
      delete node.format;
      node.enum = ["$input", ...Object.entries(recipe.inputs ?? {}).filter(([, item]) => item.kind === "image").map(([name]) => `$input:${name}`), ...Array.from({ length: index }, (_, i) => `$step${i}`)];
      node.description = "Use the new input picture or the output of an earlier recipe step.";
    }
    for (const child of Object.values(node.properties ?? {})) if (typeof child === "object") visit(child);
    for (const child of node.anyOf ?? []) if (typeof child === "object") visit(child);
    if (Array.isArray(node.items)) node.items.forEach(child => { if (typeof child === "object") visit(child); });
    else if (typeof node.items === "object") visit(node.items);
  }
  visit(schema);
  return { ...tool, schema };
}

export function RecipeStudio() {
  const { data: session } = useSession();
  const { data: tools = [] } = useCoreQuery("tools.list");
  const { data: settings } = useCoreQuery("settings.get");
  const selectedStep = useUI(s => s.selectedStep);
  const { busy, error, notice, setNotice, perform } = useOperation();
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [inputs, setInputs] = useState<string[]>([]);
  const [editing, setEditing] = useState(-1);
  const [rows, setRows] = useState<Record<string, string>[]>([{}]);
  const [results, setResults] = useState<RecipeRowResult[]>([]);
  const inputFields: NonNullable<Recipe["inputs"]> = { ...(recipe?.version === 2 && JSON.stringify(recipe.steps).includes('"$input"') ? { input: { kind: "image" as const } } : {}), ...recipe?.inputs };
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;
  const artifacts = Object.values(session?.artifacts ?? {}).filter(a => !Object.values(session?.artifacts ?? {}).some(b => b.original_id === a.id));
  return <section aria-label="Visual recipes">
    <h3>Make the next joke easier</h3>
    <p>Capture a completed step and keep its picture roles and text defaults. Save to the design library to reuse it in other projects. $step0 means the first recipe result.</p>
    <button disabled={disabled || !selectedStep} onClick={() => void perform(async () => {
      setRecipe(await action("recipes.capture", { step_id: selectedStep! })); setEditing(0); setRows([{}]); setResults([]);
    })}>Capture selected step</button>
    <label>Saved recipes<select value="" disabled={disabled} onChange={e => {
      const saved = session?.recipes?.find(r => r.name === e.target.value);
      if (saved) { setRecipe(structuredClone(saved)); setEditing(-1); setRows([{}]); setResults([]); }
    }}><option value="">Choose a recipe</option>{session?.recipes?.map(r => <option key={r.name}>{r.name}</option>)}</select></label>
    <label>Design library<select value="" disabled={disabled} onChange={event => {
      const saved = settings?.saved_designs?.find(item => item.name === event.target.value);
      if (saved) { setRecipe(structuredClone(saved)); setEditing(-1); setRows([{}]); setResults([]); }
    }}><option value="">Choose a reusable design</option>{settings?.saved_designs?.map(item => <option key={item.name}>{item.name}</option>)}</select></label>
    {recipe && <>
      <label>Recipe name<input maxLength={100} value={recipe.name} disabled={disabled} onChange={e => setRecipe({ ...recipe, name: e.target.value })} /></label>
      {recipe.steps.map((step, index) => {
        const tool = tools.find(t => t.name === step.tool);
        return <article key={index} className="recipe-step">
          <button disabled={disabled} onClick={() => setEditing(editing === index ? -1 : index)}>Edit recipe step {index + 1}: {step.tool}</button>
          {editing === index && tool && <ToolForm key={`${index}-${step.tool}`} tool={recipeTool(tool, index, recipe)} initial={step.params}
            disabled={disabled} submitLabel="Keep these recipe controls" onSubmit={async params => {
              setRecipe({ ...recipe, steps: recipe.steps.map((s, i) => i === index ? { ...s, params } : s) }); setEditing(-1);
            }} />}
        </article>;
      })}
      <button disabled={disabled || !selectedStep || recipe.steps.length >= 40 || editing >= 0} onClick={() => void perform(async () => {
        const next = await action("recipes.capture", { step_id: selectedStep! });
        setRecipe({ ...recipe, version: Math.max(recipe.version, next.version), inputs: { ...next.inputs, ...recipe.inputs }, steps: [...recipe.steps, ...next.steps] }); setEditing(recipe.steps.length);
      })}>Append selected step</button>
      <button disabled={disabled || recipe.steps.length < 2 || editing >= 0} onClick={() => setRecipe({ ...recipe, steps: recipe.steps.slice(0, -1) })}>Remove last recipe step</button>
      <button disabled={disabled || !recipe.name.trim() || editing >= 0} onClick={() => void perform(async () => {
        await action("recipes.save", { recipe }); setNotice("Recipe saved in this project. Save the project to keep it on disk.");
      })}>Save recipe</button>
      <button disabled={disabled || !recipe.name.trim() || editing >= 0} onClick={() => void perform(async () => {
        const latest = await rpc.request("settings.get");
        await action("settings.set", { values: { saved_designs: [...(latest.saved_designs ?? []).filter(item => item.name !== recipe.name), recipe] } });
        setNotice("Design saved for use in any project.");
      })}>Save to design library</button>
      {settings?.saved_designs?.some(item => item.name === recipe.name) && <button disabled={disabled}
        onClick={() => void perform(async () => {
          const latest = await rpc.request("settings.get");
          await action("settings.set", { values: { saved_designs: latest.saved_designs?.filter(item => item.name !== recipe.name) } });
          setNotice("Design removed from the library. Project recipes and images are unchanged.");
        })}>Remove from design library</button>}
      {editing >= 0 && <p>Keep the current step controls before saving or running the recipe.</p>}
      {recipe.version === 2 ? <>
        <h4>Text defaults</h4>
        {Object.entries(recipe.inputs ?? {}).filter(([, item]) => item.kind === "text").map(([name, item]) => <label key={name}>
          Default {name}<textarea disabled={disabled} maxLength={1000} value={item.default ?? ""}
            onChange={event => setRecipe({ ...recipe, inputs: { ...recipe.inputs, [name]: { ...item, default: event.target.value } } })} />
        </label>)}
        <h4>Batch rows</h4>
        {rows.map((row, index) => <fieldset key={index} disabled={disabled}><legend>Row {index + 1}</legend>
          {Object.entries(inputFields).map(([name, item]) => <label key={name}>Row {index + 1}: {name}
            {item.kind === "image" ? <select value={row[name] ?? ""} onChange={event => setRows(rows.map((value, i) => i === index ? { ...value, [name]: event.target.value } : value))}>
              <option value="">Choose image</option>{artifacts.map(image => <option key={image.id} value={image.id}>{image.label}</option>)}
            </select> : <textarea maxLength={1000} value={row[name] ?? item.default ?? ""} onChange={event => setRows(rows.map((value, i) => i === index ? { ...value, [name]: event.target.value } : value))} />}
          </label>)}
          {results[index]?.output_id && <ArtifactThumb id={results[index].output_id!} label={`Row ${index + 1} preview`} />}
          {results[index] && <p>{results[index].status}: {results[index].error}</p>}
          <button disabled={rows.length === 1} onClick={() => { setRows(rows.filter((_, i) => i !== index)); setResults([]); }}>Remove row {index + 1}</button>
          {results[index] && <button onClick={() => void perform(async () => {
            const result = await action("recipes.run", { recipe, inputs: [row] });
            const updated = result.rows?.[0];
            if (updated) setResults(previous => previous.map((value, i) => i === index ? { ...updated, index } : value));
          })}>Retry row {index + 1}</button>}
        </fieldset>)}
        <button disabled={disabled || rows.length >= 12} onClick={() => { setRows([...rows, {}]); setResults([]); }}>Add batch row</button>
        <button disabled={disabled || editing >= 0 || rows.length * recipe.steps.length > 60} onClick={() => void perform(async () => {
          const result = await action("recipes.run", { recipe, inputs: rows });
          setResults(result.rows ?? []);
          setNotice(`${result.completed.length} steps completed${result.cancelled ? " · stopped" : ""}. ${result.errors.map(e => e.message).join("; ")}`);
        })}>Run design rows</button>
      </> : <><fieldset disabled={disabled}><legend>Pictures to use (up to 12)</legend><div className="retro-inputs">
        {artifacts.map(a => <label key={a.id}><input type="checkbox" checked={inputs.includes(a.id)}
          disabled={!inputs.includes(a.id) && inputs.length >= 12}
          onChange={e => setInputs(e.target.checked ? [...inputs, a.id] : inputs.filter(id => id !== a.id))} />
          <ArtifactThumb id={a.id} /><span>{a.label}</span></label>)}
      </div></fieldset>
      <button disabled={disabled || !inputs.length || editing >= 0 || inputs.length * recipe.steps.length > 60}
        onClick={() => void perform(async () => {
          const result = await action("recipes.run", { recipe, inputs });
          setNotice(`${result.completed.length} steps completed${result.cancelled ? " · stopped" : ""}. ${result.errors.map(e => e.message).join("; ")}`);
        })}>Run recipe on selected pictures</button></>}
      <p>A batch allows up to 60 steps. Completed images stay in History if you stop.</p>
    </>}
    <button disabled={!session?.batch_running && !busy} onClick={() => void action("recipes.stop").catch(error => setNotice(String(error)))}>Stop recipe batch</button>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
