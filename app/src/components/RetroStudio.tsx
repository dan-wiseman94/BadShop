import { useState } from "react";
import { action, run, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import { openLink } from "../native";
import { ArtifactThumb } from "./Viewer";
import type { Params, Recipe, Step } from "../types";
import "../retro.css";

function finished(step: Step) {
  if (step.status !== "done")
    throw new Error(step.error?.message ?? "The tool did not finish.");
  return step;
}
export function RetroStudio({
  onAttach,
  onDraft,
}: {
  onAttach: (id: string) => void;
  onDraft: (text: string) => void;
}) {
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
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [source, setSource] = useState("iiif");
  const [identifier, setIdentifier] = useState("");
  const [candidates, setCandidates] = useState<Params[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [colors, setColors] = useState<string[]>([]);
  const [recipeText, setRecipeText] = useState("");
  const [batchInputs, setBatchInputs] = useState<string[]>([]);
  const [role, setRole] = useState("subject");
  const [profile, setProfile] = useState(prefs?.export_profile ?? "original");
  const [cleanBase, setCleanBase] = useState("");
  const [fryLevel, setFryLevel] = useState(2);
  const [jpegQuality, setJpegQuality] = useState(35);
  const [jpegPasses, setJpegPasses] = useState(2);
  const [format, setFormat] = useState("PNG");
  const [maxBytes, setMaxBytes] = useState("");
  const [comparison, setComparison] = useState<string[]>([]);
  const chosen = useUI((s) => s.selectedArtifact);
  const selectedStep = useUI((s) => s.selectedStep);
  const artifacts = Object.values(session?.artifacts ?? {});
  const image =
    chosen ??
    session?.steps.find((s) => s.id === selectedStep)?.outputs[0] ??
    artifacts.at(-1)?.id;
  const disabled = busy || !!session?.turn_running || !!session?.batch_running;
  async function perform(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const change = (values: Params) =>
    run(() => action("creative.set", { values }));
  async function tool(name: string, params: Params) {
    const s = finished(await action("tools.run", { tool: name, params }));
    if (s.outputs[0]) {
      useUI
        .getState()
        .set({ selectedArtifact: s.outputs[0], selectedStep: s.id });
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
        {["styles", "sources", "recipes", "compare", "worse", "export"].map(
          (id) => (
            <button
              key={id}
              aria-pressed={section === id}
              onClick={() => setSection(id)}
            >
              {id[0].toUpperCase() + id.slice(1)}
            </button>
          ),
        )}
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
            28 layouts with real frames, slots and pixel lettering. Each result
            becomes an editable timeline step.
          </p>
          <div className="retro-controls">
            <label>
              Filter styles
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </label>
            <label>
              Era
              <select value={era} onChange={(e) => setEra(e.target.value)}>
                <option value="all">Every era</option>
                {[...new Set(styles.map((s) => s.era))].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={favorites}
                onChange={(e) => setFavorites(e.target.checked)}
              />{" "}
              Favorites only
            </label>
          </div>
          <div className="retro-grid">
            {styles
              .filter(
                (s) =>
                  (era === "all" || s.era === era) &&
                  `${s.name} ${s.family}`
                    .toLowerCase()
                    .includes(filter.toLowerCase()) &&
                  (!favorites || prefs?.favorite_styles.includes(s.id)),
              )
              .map((s) => (
                <article
                  key={s.id}
                  className={style === s.id ? "selected" : ""}
                >
                  <button
                    className="retro-pick"
                    aria-pressed={style === s.id}
                    onClick={() => {
                      setStyle(s.id);
                      change({ style: s.id });
                    }}
                  >
                    <img
                      loading="lazy"
                      src={s.preview}
                      alt={`${s.name} layout preview`}
                    />
                    <strong>{s.name}</strong>
                    <small>
                      {s.era} · {s.width} × {s.height}
                    </small>
                  </button>
                  <button
                    className="retro-star"
                    aria-label={`Favorite ${s.name}`}
                    aria-pressed={
                      prefs?.favorite_styles.includes(s.id) ?? false
                    }
                    onClick={() =>
                      change({
                        favorite_styles: prefs?.favorite_styles.includes(s.id)
                          ? prefs.favorite_styles.filter((v) => v !== s.id)
                          : [...(prefs?.favorite_styles ?? []), s.id],
                      })
                    }
                  >
                    {prefs?.favorite_styles.includes(s.id) ? "★" : "☆"}
                  </button>
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
            <label>
              Title
              <input
                value={title}
                maxLength={240}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              Caption
              <textarea
                value={caption}
                maxLength={1000}
                onChange={(e) => setCaption(e.target.value)}
              />
            </label>
            <label>
              Seed
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
              />
            </label>
            <label>
              Clutter
              <select
                value={prefs?.density ?? "balanced"}
                onChange={(e) => change({ density: e.target.value })}
              >
                {["sparse", "balanced", "chaotic"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Image fit
              <select
                value={prefs?.fit ?? "contain"}
                onChange={(e) => change({ fit: e.target.value })}
              >
                {["contain", "cover", "stretch"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={prefs?.exact_text ?? true}
                onChange={(e) => change({ exact_text: e.target.checked })}
              />{" "}
              Refuse overflowing captions
            </label>
            <button disabled={disabled}>Build retro layout</button>
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                onDraft(
                  `Create a ${style} composition. Era mode: ${prefs?.era_strictness ?? "inspired"}. Use retro_layout with style=${style}, title=${JSON.stringify(title)}, caption=${JSON.stringify(caption)}, seed=${seed}. Preserve the selected subject. Inspect the result.`,
                )
              }
            >
              Draft an art direction
            </button>
          </form>
          <p className="muted">
            Uses the selected image, or an empty frame. Bitmap captions support
            Latin-1; other scripts use the Text tool. Tiny buttons need short
            labels.
          </p>
          <div className="retro-controls">
            <label>
              Era fidelity
              <select
                value={prefs?.era_strictness ?? "inspired"}
                onChange={(e) => change({ era_strictness: e.target.value })}
              >
                {["inspired", "strict", "mashup"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <button
              disabled={!prefs || disabled}
              onClick={() =>
                run(() =>
                  action("settings.set", {
                    values: { creative_defaults: prefs },
                  }),
                )
              }
            >
              Use these defaults for new projects
            </button>
            <label>
              Pin image as
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {["subject", "background", "sticker", "reference"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <button
              disabled={!image || disabled}
              onClick={() =>
                change({
                  source_roles: { ...prefs?.source_roles, [role]: image },
                })
              }
            >
              Pin selected image
            </button>
          </div>
          {Object.entries(prefs?.source_roles ?? {}).map(([name, id]) => (
            <button
              key={name}
              onClick={() => useUI.getState().set({ selectedArtifact: id })}
            >
              {name}: {session?.artifacts[id]?.label ?? "unavailable"}
            </button>
          ))}
        </>
      )}
      {section === "sources" && (
        <>
          <p>
            Browse one collection item, inspect its credits, then import a
            chosen file. Chicago and OpenMoji also appear in Find images.
          </p>
          <form
            className="retro-controls"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(() => browse());
            }}
          >
            <label>
              Collection
              <select
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  setCandidates([]);
                  setColors([]);
                  setNextOffset(null);
                }}
              >
                <option value="iiif">IIIF manifest (v2 / v3)</option>
                <option value="archive">Internet Archive item</option>
                <option value="lospec">Lospec palette</option>
              </select>
            </label>
            <label>
              Manifest URL, item ID or palette slug
              <input
                required
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
              />
            </label>
            <button disabled={disabled}>Browse selected item</button>
            <button
              type="button"
              disabled={!identifier || disabled}
              onClick={() =>
                change({
                  saved_searches: [
                    ...new Set([
                      ...(prefs?.saved_searches ?? []),
                      `${source}|${identifier}`,
                    ]),
                  ].slice(-50),
                })
              }
            >
              Save lookup
            </button>
          </form>
          <div className="retro-controls">
            {prefs?.saved_searches.map((s) => (
              <button
                key={s}
                onClick={() => {
                  const split = s.indexOf("|");
                  setSource(s.slice(0, split));
                  setIdentifier(s.slice(split + 1));
                  setCandidates([]);
                  setNextOffset(null);
                }}
              >
                {s.slice(0, 70)}
              </button>
            ))}
          </div>
          <div className="retro-grid">
            {candidates.map((c, i) => (
              <article key={String(c.id ?? i)}>
                <strong>{String(c.title)}</strong>
                <p>
                  {String((c.source as Params)?.license ?? "Rights unknown")}
                </p>
                <p>
                  {String((c.source as Params)?.creator ?? "Creator unknown")}
                </p>
                <button
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
                >
                  Import selected file
                </button>
                {!!c.page && (
                  <button onClick={() => run(() => openLink(String(c.page)))}>
                    Source & rights
                  </button>
                )}
              </article>
            ))}
          </div>
          {nextOffset !== null && (
            <button
              disabled={disabled}
              onClick={() => void perform(() => browse(nextOffset))}
            >
              Next files
            </button>
          )}
          {!!colors.length && (
            <>
              <div className="palette-swatches">
                {colors.map((c) => (
                  <span key={c} style={{ background: c }} title={c} />
                ))}
              </div>
              <button
                disabled={!image || disabled}
                onClick={() =>
                  void perform(async () => {
                    await tool("palette", { image, palette: "custom", colors });
                  })
                }
              >
                Apply this palette
              </button>
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
              <button key={name} onClick={() => run(() => openLink(url))}>
                {name}
              </button>
            ))}
          </p>
          <p className="muted">
            For these collections, select and download an image in your browser,
            then use Import or Local media. Keep the source page and license
            with it; these links are not search adapters.
          </p>
        </>
      )}
      {section === "recipes" && (
        <>
          <p>
            Save local tool steps as reusable recipes. Image knobs use $input or
            $step0, $step1 for earlier outputs. Batches stop between steps and
            keep completed outputs.
          </p>
          <div className="retro-controls">
            <button
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
            >
              Capture selected step
            </button>
            <label>
              Saved recipes
              <select
                defaultValue=""
                onChange={(e) => {
                  const r = session?.recipes?.find(
                    (r) => r.name === e.target.value,
                  );
                  if (r) setRecipeText(JSON.stringify(r, null, 2));
                }}
              >
                <option value="">Choose a recipe</option>
                {session?.recipes?.map((r) => (
                  <option key={r.name}>{r.name}</option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Recipe and exposed parameters
            <textarea
              className="recipe-editor"
              value={recipeText}
              onChange={(e) => setRecipeText(e.target.value)}
              spellCheck={false}
            />
          </label>
          <button
            disabled={!recipeText || disabled}
            onClick={() =>
              void perform(async () => {
                await action("recipes.save", {
                  recipe: JSON.parse(recipeText) as Recipe,
                });
                setMessage("Recipe saved in this project.");
              })
            }
          >
            Save recipe
          </button>
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
          <button
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
          >
            Run batch
          </button>
          <button
            disabled={!busy && !session?.batch_running}
            onClick={() => run(() => action("recipes.stop"))}
          >
            Stop batch
          </button>
        </>
      )}
      {section === "compare" && (
        <>
          <p>
            Choose up to four branch results to compare without switching the
            active direction.
          </p>
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
                <button
                  onClick={() => useUI.getState().set({ selectedArtifact: id })}
                >
                  Inspect full size
                </button>
              </div>
            ))}
          </div>
        </>
      )}
      {section === "worse" && (
        <>
          <p>
            Choose a clean starting image. Every variation below starts from
            that image so you can compare results without stacking damage
            accidentally.
          </p>
          <label>
            Clean starting image
            <select
              value={cleanBase}
              onChange={(e) => setCleanBase(e.target.value)}
            >
              <option value="">Choose an image</option>
              {artifacts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
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
            <label>
              Seed
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
              />
            </label>
            <button
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
            >
              Make a fried variation
            </button>
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
            <label>
              Compression passes
              <input
                type="number"
                min={1}
                max={20}
                value={jpegPasses}
                onChange={(e) => setJpegPasses(Number(e.target.value))}
              />
            </label>
            <button
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
            >
              Make a crunchy variation
            </button>
          </div>
        </>
      )}
      {section === "export" && (
        <>
          <p>
            Prepare exact dimensions, then export the selected result with a
            credits sidecar tracing every source image.
          </p>
          <form
            className="retro-controls"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () => {
                await tool("export_profile", {
                  image,
                  profile,
                  format,
                  ...(maxBytes ? { max_bytes: Number(maxBytes) } : {}),
                });
              });
            }}
          >
            <label>
              Output preset
              <select
                value={profile}
                onChange={(e) => {
                  setProfile(e.target.value);
                  change({ export_profile: e.target.value });
                }}
              >
                {[
                  "original",
                  "web-button",
                  "blinkie",
                  "forum-signature",
                  "avatar",
                  "wallpaper",
                ].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </label>
            <label>
              Format
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              >
                {["PNG", "JPEG", "GIF"].map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </label>
            <label>
              Maximum bytes (optional)
              <input
                type="number"
                min={100}
                value={maxBytes}
                onChange={(e) => setMaxBytes(e.target.value)}
              />
            </label>
            <button disabled={!image || disabled}>Prepare output</button>
          </form>
          <button
            disabled={!image || disabled}
            onClick={() =>
              void perform(async () => {
                const r = await action("credits.export", {
                  artifact_id: image!,
                });
                setMessage(`Saved ${r.path} and ${r.credits}`);
              })
            }
          >
            Export selected image + credits
          </button>
        </>
      )}
    </div>
  );
}
