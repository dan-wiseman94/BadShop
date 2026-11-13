import { useState } from "react";
import type { RJSFSchema } from "@rjsf/utils";
import { action, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import { useOperation } from "../useOperation";
import type { Recipe, Tool } from "../types";
import { ToolForm } from "./ToolForm";
import { ArtifactThumb } from "./Viewer";

function recipeTool(tool: Tool, index: number): Tool {
  const schema = structuredClone(tool.schema);
  function visit(node: RJSFSchema) {
    if (node.format === "badshop-image") {
      delete node.format;
      node.enum = ["$input", ...Array.from({ length: index }, (_, i) => `$step${i}`)];
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
  const selectedStep = useUI(s => s.selectedStep);
  const { busy, error, notice, setNotice, perform } = useOperation();
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [inputs, setInputs] = useState<string[]>([]);
  const [editing, setEditing] = useState(-1);
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;
  const artifacts = Object.values(session?.artifacts ?? {}).filter(a => !Object.values(session?.artifacts ?? {}).some(b => b.original_id === a.id));
  return <section aria-label="Visual recipes">
    <h3>Make the next joke easier</h3>
    <p>Capture a completed step, edit its controls, and reuse it on new pictures. $input means the new picture; $step0 means the first recipe result.</p>
    <button disabled={disabled || !selectedStep} onClick={() => void perform(async () => {
      setRecipe(await action("recipes.capture", { step_id: selectedStep! })); setEditing(0);
    })}>Capture selected step</button>
    <label>Saved recipes<select value="" disabled={disabled} onChange={e => {
      const saved = session?.recipes?.find(r => r.name === e.target.value);
      if (saved) { setRecipe(structuredClone(saved)); setEditing(-1); }
    }}><option value="">Choose a recipe</option>{session?.recipes?.map(r => <option key={r.name}>{r.name}</option>)}</select></label>
    {recipe && <>
      <label>Recipe name<input maxLength={100} value={recipe.name} disabled={disabled} onChange={e => setRecipe({ ...recipe, name: e.target.value })} /></label>
      {recipe.steps.map((step, index) => {
        const tool = tools.find(t => t.name === step.tool);
        return <article key={index} className="recipe-step">
          <button disabled={disabled} onClick={() => setEditing(editing === index ? -1 : index)}>Edit recipe step {index + 1}: {step.tool}</button>
          {editing === index && tool && <ToolForm key={`${index}-${step.tool}`} tool={recipeTool(tool, index)} initial={step.params}
            disabled={disabled} submitLabel="Keep these recipe controls" onSubmit={async params => {
              setRecipe({ ...recipe, steps: recipe.steps.map((s, i) => i === index ? { ...s, params } : s) }); setEditing(-1);
            }} />}
        </article>;
      })}
      <button disabled={disabled || !selectedStep || recipe.steps.length >= 40 || editing >= 0} onClick={() => void perform(async () => {
        const next = await action("recipes.capture", { step_id: selectedStep! });
        setRecipe({ ...recipe, steps: [...recipe.steps, ...next.steps] }); setEditing(recipe.steps.length);
      })}>Append selected step</button>
      <button disabled={disabled || recipe.steps.length < 2 || editing >= 0} onClick={() => setRecipe({ ...recipe, steps: recipe.steps.slice(0, -1) })}>Remove last recipe step</button>
      <button disabled={disabled || !recipe.name.trim() || editing >= 0} onClick={() => void perform(async () => {
        await action("recipes.save", { recipe }); setNotice("Recipe saved in this project. Save the project to keep it on disk.");
      })}>Save recipe</button>
      {editing >= 0 && <p>Keep the current step controls before saving or running the recipe.</p>}
      <fieldset disabled={disabled}><legend>Pictures to use (up to 12)</legend><div className="retro-inputs">
        {artifacts.map(a => <label key={a.id}><input type="checkbox" checked={inputs.includes(a.id)}
          disabled={!inputs.includes(a.id) && inputs.length >= 12}
          onChange={e => setInputs(e.target.checked ? [...inputs, a.id] : inputs.filter(id => id !== a.id))} />
          <ArtifactThumb id={a.id} /><span>{a.label}</span></label>)}
      </div></fieldset>
      <button disabled={disabled || !inputs.length || editing >= 0 || inputs.length * recipe.steps.length > 60}
        onClick={() => void perform(async () => {
          const result = await action("recipes.run", { recipe, inputs });
          setNotice(`${result.completed.length} steps completed${result.cancelled ? " · stopped" : ""}. ${result.errors.map(e => e.message).join("; ")}`);
        })}>Run recipe on selected pictures</button>
      <p>A batch allows up to 60 steps. Completed images stay in History if you stop.</p>
    </>}
    <button disabled={!session?.batch_running && !busy} onClick={() => void action("recipes.stop").catch(error => setNotice(String(error)))}>Stop recipe batch</button>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
