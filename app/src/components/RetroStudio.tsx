import { Button } from "./Button";
import { useOperation } from "../useOperation";
import { InputField, SelectField, TextAreaField } from "./Fields";
import { useState } from "react";
import { action, run, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import { openLink } from "../native";
import { ArtifactThumb } from "./Viewer";
import { ShareImage } from "./ShareImage";
import type { Params, Recipe, Step } from "../types";
import "../retro.css";

function finished(step: Step) {
  if (step.status !== "done") throw new Error(step.error?.message ?? "The tool did not finish.");
  return step;
}
export function RetroStudio({
  onAttach,
  onDraft,
}: {
  onAttach: (id: string) => void;
  onDraft: (text: string) => void;
}) {
  const { busy, error, notice: message, setNotice: setMessage, perform } = useOperation();
  const { data: session } = useSession();
  const { data: styles = [], error: catalogError } = useCoreQuery("retro.list");
  const { data: branches } = useCoreQuery("branches.list");
  const prefs = session?.creative;
  const [section, setSection] = useState("styles");
  const [filter, setFilter] = useState("");
  const [era, setEra] = useState("all");
  const [favorites, setFavorites] = useState(false);
  const [style, setStyle] = useState(prefs?.style ?? "geocities");
  const [title, setTitle] = useState("MY PAGE");
  const [caption, setCaption] = useState("");
  const [seed, setSeed] = useState(prefs?.seed ?? 1);

  const [source, setSource] = useState("iiif");
  const [identifier, setIdentifier] = useState("");
  const [candidates, setCandidates] = useState<Params[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [colors, setColors] = useState<string[]>([]);
  const [recipeText, setRecipeText] = useState("");
  const [batchInputs, setBatchInputs] = useState<string[]>([]);
  const [role, setRole] = useState("subject");
  const [cleanBase, setCleanBase] = useState("");
  const [fryLevel, setFryLevel] = useState(2);
  const [jpegQuality, setJpegQuality] = useState(35);
  const [jpegPasses, setJpegPasses] = useState(2);
  const [comparison, setComparison] = useState<string[]>([]);
  const chosen = useUI((s) => s.selectedArtifact);
  const selectedStep = useUI((s) => s.selectedStep);
  const artifacts = Object.values(session?.artifacts ?? {});
  const image =
    chosen ?? session?.steps.find((s) => s.id === selectedStep)?.outputs[0] ?? artifacts.at(-1)?.id;
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;

  const change = (values: Params) => run(() => action("creative.set", { values }));
  async function tool(name: string, params: Params) {
    const s = finished(await action("tools.run", { tool: name, params }));
    if (s.outputs[0]) {
      useUI.getState().set({ selectedArtifact: s.outputs[0], selectedStep: s.id });
      onAttach(s.outputs[0]);
    }
    return s;
  }
  async function browse(offset = 0) {
    const s = finished(
      await action("tools.run", {
        tool: "collection_items",
        params: { kind: source, identifier, offset },
      }),
    );
    setCandidates((s.data?.candidates ?? []) as Params[]);
    setColors((s.data?.colors ?? []) as string[]);
    setNextOffset((s.data?.next_offset ?? null) as number | null);
    setMessage(s.result_text);
  }
  return (
    <div className="retro-studio">
      <nav aria-label="Retro workbench" className="studio-tabs">
        {["styles", "sources", "recipes", "compare", "worse", "export"].map((id) => (
          <Button
            key={id}
            aria-pressed={section === id}
            onClick={() => setSection(id)}
            label={id[0].toUpperCase() + id.slice(1)}
          />
        ))}
      </nav>
      {(error || catalogError) && (
        <p className="error-banner" role="alert">
          {error || String(catalogError)}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {section === "styles" && (
        <>
          <p>
            28 layouts with real frames, slots and pixel lettering. Each result becomes an editable timeline
            step.
          </p>
          <div className="retro-controls">
            <InputField label="Filter styles" bind={[filter, setFilter]} />
            <SelectField
              label="Era"
              bind={[era, setEra]}
              options={[
                ["all", "Every era"] as const,
                ...[...new Set(styles.map((s) => s.era))].map((v) => v),
              ]}
            />
            <label>
              <input type="checkbox" checked={favorites} onChange={(e) => setFavorites(e.target.checked)} />{" "}
              Favorites only
            </label>
          </div>
          <div className="retro-grid">
            {styles
              .filter(
                (s) =>
                  (era === "all" || s.era === era) &&
                  `${s.name} ${s.family}`.toLowerCase().includes(filter.toLowerCase()) &&
                  (!favorites || prefs?.favorite_styles.includes(s.id)),
              )
              .map((s) => (
                <article key={s.id} className={style === s.id ? "selected" : ""}>
                  <button
                    className="retro-pick"
                    aria-pressed={style === s.id}
                    onClick={() => {
                      setStyle(s.id);
                      change({ style: s.id });
                    }}
                  >
                    <img loading="lazy" src={s.preview} alt={`${s.name} layout preview`} />
                    <strong>{s.name}</strong>
                    <small>
                      {s.era} · {s.width} × {s.height}
                    </small>
                  </button>
                  <Button
                    className="retro-star"
                    aria-label={`Favorite ${s.name}`}
                    aria-pressed={prefs?.favorite_styles.includes(s.id) ?? false}
                    onClick={() =>
                      change({
                        favorite_styles: prefs?.favorite_styles.includes(s.id)
                          ? prefs.favorite_styles.filter((v) => v !== s.id)
                          : [...(prefs?.favorite_styles ?? []), s.id],
                      })
                    }
                    label={prefs?.favorite_styles.includes(s.id) ? "★" : "☆"}
                  />
                </article>
              ))}
          </div>
          <form
            className="retro-controls"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () => {
                await tool("retro_layout", {
                  style,
                  title,
                  caption,
                  seed,
                  images: image ? [image] : [],
                });
              });
            }}
          >
            <InputField label="Title" maxLength={240} bind={[title, setTitle]} />
            <TextAreaField label="Caption" maxLength={1000} bind={[caption, setCaption]} />
            <InputField label="Seed" type="number" bind={[seed, setSeed]} />
            <SelectField
              label="Clutter"
              value={prefs?.density ?? "balanced"}
              onChange={(e) => change({ density: e.target.value })}
              options={["sparse", "balanced", "chaotic"]}
            />
            <SelectField
              label="Image fit"
              value={prefs?.fit ?? "contain"}
              onChange={(e) => change({ fit: e.target.value })}
              options={["contain", "cover", "stretch"]}
            />
            <label>
              <input
                type="checkbox"
                checked={prefs?.exact_text ?? true}
                onChange={(e) => change({ exact_text: e.target.checked })}
              />{" "}
              Refuse overflowing captions
            </label>
            <Button disabled={disabled} label="Build retro layout" />
            <Button
              type="button"
              disabled={disabled}
              onClick={() =>
                onDraft(
                  `Create a ${style} composition. Era mode: ${prefs?.era_strictness ?? "inspired"}. Use retro_layout with style=${style}, title=${JSON.stringify(title)}, caption=${JSON.stringify(caption)}, seed=${seed}. Preserve the selected subject. Inspect the result.`,
                )
              }
              label="Draft an art direction"
            />
          </form>
          <p className="muted">
            Uses the selected image, or an empty frame. Bitmap captions support Latin-1; other scripts use the
            Text tool. Tiny buttons need short labels.
          </p>
          <div className="retro-controls">
            <SelectField
              label="Era fidelity"
              value={prefs?.era_strictness ?? "inspired"}
              onChange={(e) => change({ era_strictness: e.target.value })}
              options={["inspired", "strict", "mashup"]}
            />
            <Button
              disabled={!prefs || disabled}
              onClick={() =>
                run(() =>
                  action("settings.set", {
                    values: { creative_defaults: prefs },
                  }),
                )
              }
              label="Use these defaults for new projects"
            />
            <SelectField
              label="Pin image as"
              bind={[role, setRole]}
              options={["subject", "background", "sticker", "reference"]}
            />
            <Button
              disabled={!image || disabled}
              onClick={() =>
                change({
                  source_roles: { ...prefs?.source_roles, [role]: image },
                })
              }
              label="Pin selected image"
            />
          </div>
          {Object.entries(prefs?.source_roles ?? {}).map(([name, id]) => (
            <button key={name} onClick={() => useUI.getState().set({ selectedArtifact: id })}>
              {name}: {session?.artifacts[id]?.label ?? "unavailable"}
            </button>
          ))}
        </>
      )}
      {section === "sources" && (
        <>
          <p>
            Browse one collection item, inspect its credits, then import a chosen file. Chicago and OpenMoji
            also appear in Find images.
          </p>
          <form
            className="retro-controls"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(() => browse());
            }}
          >
            <SelectField
              label="Collection"
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setCandidates([]);
                setColors([]);
                setNextOffset(null);
              }}
              options={[
                ["iiif", "IIIF manifest (v2 / v3)"] as const,
                ["archive", "Internet Archive item"] as const,
                ["lospec", "Lospec palette"] as const,
              ]}
            />
            <InputField
              label="Manifest URL, item ID or palette slug"
              required
              bind={[identifier, setIdentifier]}
            />
            <Button disabled={disabled} label="Browse selected item" />
            <Button
              type="button"
              disabled={!identifier || disabled}
              onClick={() =>
                change({
                  saved_searches: [
                    ...new Set([...(prefs?.saved_searches ?? []), `${source}|${identifier}`]),
                  ].slice(-50),
                })
              }
              label="Save lookup"
            />
          </form>
          <div className="retro-controls">
            {prefs?.saved_searches.map((s) => (
              <Button
                key={s}
                onClick={() => {
                  const split = s.indexOf("|");
                  setSource(s.slice(0, split));
                  setIdentifier(s.slice(split + 1));
                  setCandidates([]);
                  setNextOffset(null);
                }}
                label={s.slice(0, 70)}
              />
            ))}
          </div>
          <div className="retro-grid">
            {candidates.map((c, i) => (
              <article key={String(c.id ?? i)}>
                <strong>{String(c.title)}</strong>
                <p>{String((c.source as Params)?.license ?? "Rights unknown")}</p>
                <p>{String((c.source as Params)?.creator ?? "Creator unknown")}</p>
                <Button
                  disabled={disabled}
                  onClick={() =>
                    void perform(async () => {
                      await tool("acquire", {
                        ...(c.source as Params),
                        url: c.url,
                        source_kind: (c.source as Params)?.kind,
                        kind: undefined,
                      });
                    })
                  }
                  label="Import selected file"
                />
                {!!c.page && (
                  <Button onClick={() => run(() => openLink(String(c.page)))} label="Source & rights" />
                )}
              </article>
            ))}
          </div>
          {nextOffset !== null && (
            <Button
              disabled={disabled}
              onClick={() => void perform(() => browse(nextOffset))}
              label="Next files"
            />
          )}
          {!!colors.length && (
            <>
              <div className="palette-swatches">
                {colors.map((c) => (
                  <span key={c} style={{ background: c }} title={c} />
                ))}
              </div>
              <Button
                disabled={!image || disabled}
                onClick={() =>
                  void perform(async () => {
                    await tool("palette", { image, palette: "custom", colors });
                  })
                }
                label="Apply this palette"
              />
            </>
          )}
          <p>
            More collections:{" "}
            {Object.entries({
              "Kenney (CC0)": "https://kenney.nl/assets",
              "Game-icons": "https://game-icons.net/",
              GifCities: "https://gifcities.org/",
              Rijksmuseum: "https://www.rijksmuseum.nl/en/collection",
            }).map(([name, url]) => (
              <Button key={name} onClick={() => run(() => openLink(url))} label={name} />
            ))}
          </p>
          <p className="muted">
            For these collections, select and download an image in your browser, then use Import or Local
            media. Keep the source page and license with it; these links are not search adapters.
          </p>
        </>
      )}
      {section === "recipes" && (
        <>
          <p>
            Save local tool steps as reusable recipes. Image knobs use $input or $step0, $step1 for earlier
            outputs. Batches stop between steps and keep completed outputs.
          </p>
          <div className="retro-controls">
            <Button
              disabled={!selectedStep || disabled}
              onClick={() =>
                void perform(async () => {
                  setRecipeText(
                    JSON.stringify(
                      await action("recipes.capture", {
                        step_id: selectedStep!,
                      }),
                      null,
                      2,
                    ),
                  );
                })
              }
              label="Capture selected step"
            />
            <SelectField
              label="Saved recipes"
              defaultValue=""
              onChange={(e) => {
                const r = session?.recipes?.find((r) => r.name === e.target.value);
                if (r) setRecipeText(JSON.stringify(r, null, 2));
              }}
              options={[["", "Choose a recipe"], ...(session?.recipes?.map((r) => r.name) ?? [])]}
            />
          </div>
          <TextAreaField
            label="Recipe and exposed parameters"
            className="recipe-editor"
            spellCheck={false}
            bind={[recipeText, setRecipeText]}
          />
          <Button
            disabled={!recipeText || disabled}
            onClick={() =>
              void perform(async () => {
                await action("recipes.save", {
                  recipe: JSON.parse(recipeText) as Recipe,
                });
                setMessage("Recipe saved in this project.");
              })
            }
            label="Save recipe"
          />
          <fieldset>
            <legend>Batch input images (up to 12)</legend>
            <div className="retro-inputs">
              {artifacts.map((a) => (
                <label key={a.id}>
                  <input
                    type="checkbox"
                    checked={batchInputs.includes(a.id)}
                    onChange={(e) =>
                      setBatchInputs(
                        e.target.checked
                          ? [...batchInputs, a.id].slice(0, 12)
                          : batchInputs.filter((id) => id !== a.id),
                      )
                    }
                  />
                  <ArtifactThumb id={a.id} />
                  <span>{a.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <Button
            disabled={disabled || !recipeText || !batchInputs.length}
            onClick={() =>
              void perform(async () => {
                const result = await action("recipes.run", {
                  recipe: JSON.parse(recipeText) as Recipe,
                  inputs: batchInputs,
                });
                setMessage(
                  `${result.completed.length} steps completed${result.cancelled ? " · stopped" : ""}. ${result.errors.map((e) => e.message).join("; ")}`,
                );
              })
            }
            label="Run batch"
          />
          <Button
            disabled={!busy && !session?.batch_running}
            onClick={() => run(() => action("recipes.stop"))}
            label="Stop batch"
          />
        </>
      )}
      {section === "compare" && (
        <>
          <p>Choose up to four branch results to compare without switching the active direction.</p>
          <div className="retro-controls">
            {branches?.branches
              .filter((b) => b.preview_id)
              .map((b) => (
                <label key={b.id}>
                  <input
                    type="checkbox"
                    checked={comparison.includes(b.preview_id!)}
                    onChange={(e) =>
                      setComparison(
                        e.target.checked
                          ? [...comparison, b.preview_id!].slice(-4)
                          : comparison.filter((id) => id !== b.preview_id),
                      )
                    }
                  />
                  {b.name}
                </label>
              ))}
          </div>
          <div className="retro-compare">
            {comparison.map((id) => (
              <div key={id}>
                <ArtifactThumb id={id} />
                <Button
                  onClick={() => useUI.getState().set({ selectedArtifact: id })}
                  label="Inspect full size"
                />
              </div>
            ))}
          </div>
        </>
      )}
      {section === "worse" && (
        <>
          <p>
            Choose a clean starting image. Every variation below starts from that image so you can compare
            results without stacking damage accidentally.
          </p>
          <SelectField
            label="Clean starting image"
            bind={[cleanBase, setCleanBase]}
            options={[["", "Choose an image"] as const, ...artifacts.map((a) => [a.id, a.label] as const)]}
          />
          <div className="retro-controls">
            <label>
              Fry level
              <input
                type="range"
                min={1}
                max={5}
                value={fryLevel}
                onChange={(e) => setFryLevel(Number(e.target.value))}
              />
              <output>{fryLevel}</output>
            </label>
            <InputField label="Seed" type="number" bind={[seed, setSeed]} />
            <Button
              disabled={disabled || !cleanBase}
              onClick={() =>
                void perform(async () => {
                  await tool("deepfry", {
                    image: cleanBase,
                    level: fryLevel,
                    seed,
                  });
                })
              }
              label="Make a fried variation"
            />
          </div>
          <div className="retro-controls">
            <label>
              JPEG quality
              <input
                type="range"
                min={1}
                max={95}
                value={jpegQuality}
                onChange={(e) => setJpegQuality(Number(e.target.value))}
              />
              <output>{jpegQuality}</output>
            </label>
            <InputField
              label="Compression passes"
              type="number"
              min={1}
              max={20}
              bind={[jpegPasses, setJpegPasses]}
            />
            <Button
              disabled={disabled || !cleanBase}
              onClick={() =>
                void perform(async () => {
                  await tool("save", {
                    image: cleanBase,
                    quality: jpegQuality,
                    passes: jpegPasses,
                  });
                })
              }
              label="Make a crunchy variation"
            />
          </div>
        </>
      )}
      {section === "export" && (image ? <ShareImage key={image} id={image} /> : <p>Select an image on the canvas to share it.</p>)}
    </div>
  );
}
