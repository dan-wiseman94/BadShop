import { useEffect, useRef, useState } from "react";
import {
  Check,
  Clock3,
  RotateCcw,
  Plus,
  Search,
  X,
  Code,
  Trash2,
  AlertTriangle,
  Bot,
  User,
  Terminal,
} from "lucide-react";
import { action, run, useCoreQuery, useSession } from "../data";
import { useUI } from "../store";
import { copyText, openLink } from "../native";
import { ToolForm, normalizeSchema } from "./ToolForm";
import { ArtifactThumb } from "./Viewer";
import { ErrorNotice } from "./ErrorNotice";
import type { Tool, Step, Params } from "../types";
export function parameterSummary(params: Params) {
  return Object.entries(params)
    .filter(([, v]) => v !== null && v !== false)
    .map(
      ([k, v]) =>
        `${k}: ${typeof v === "string" && /^[a-f0-9]{64}$/.test(v) ? v.slice(0, 7) : typeof v === "object" ? JSON.stringify(v) : String(v)}`,
    )
    .join(" / ");
}
export function cliCommand(step: Step, tool?: Tool) {
  const quote = (value: string) => `'${value.replaceAll("'", "'\\''")}'`;
  const positional: string[] = [];
  const flags: string[] = [];
  const normalized = tool ? normalizeSchema(tool.schema) : undefined;
  for (const [name, value] of Object.entries(step.params)) {
    const schema = normalized?.properties?.[name];
    if (
      value === null ||
      value === false ||
      value === undefined ||
      (typeof schema === "object" &&
        JSON.stringify(schema.default) === JSON.stringify(value))
    )
      continue;
    const words = Array.isArray(value)
      ? value.map((v) =>
          typeof v === "object" ? JSON.stringify(v) : String(v),
        )
      : [String(value)];
    if (tool?.cli_positionals?.includes(name)) {
      positional.push(...words);
      continue;
    }
    const flag = tool?.cli_flags?.[name] ?? `--${name.replaceAll("_", "-")}`;
    if (value === true) {
      flags.push(flag);
      continue;
    }
    const format = typeof schema === "object" ? schema.format : undefined;
    if (Array.isArray(value) && !format?.startsWith("badshop-")) {
      for (const item of value) {
        if (Array.isArray(item)) flags.push(flag, ...item.map(String));
        else flags.push(`${flag}=${String(item)}`);
      }
    } else if (words.length === 1) flags.push(`${flag}=${words[0]}`);
    else flags.push(flag, ...words);
  }
  return [
    "badshop",
    step.tool,
    ...(positional.some((word) => word.startsWith("-"))
      ? [...flags, "--", ...positional]
      : [...positional, ...flags]),
  ]
    .map((word, i) => (i < 2 ? word : quote(word)))
    .join(" ");
}
function RunningTime({ step }: { step: Step }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <span>
      {Math.max(0, Math.floor(now - (step.started_at ?? now)))}s elapsed
    </span>
  );
}
export function Timeline() {
  const { data: session } = useSession();
  const { data: tools } = useCoreQuery("tools.list");
  const selected = useUI((s) => s.selectedStep);
  const step = session?.steps.find((s) => s.id === selected);
  const tool = tools?.find((t) => t.name === step?.tool);
  const busy = session?.turn_running;
  return (
    <section className="timeline pane" aria-label="Steps timeline">
      <div className="pane-heading">
        <span>
          Steps <span className="count">{session?.steps.length ?? 0}</span>
        </span>
        <button
          className="quiet"
          title="Replay all steps"
          disabled={!session?.steps.length || busy}
          onClick={() =>
            run(() =>
              action("steps.replay_from", { step_id: session!.steps[0].id }),
            )
          }
        >
          <RotateCcw size={15} />
        </button>
      </div>
      <div className="step-list">
        {session?.steps.length ? (
          session.steps.map((s) => (
            <button
              key={s.id}
              className={`step ${s.id === selected ? "selected" : ""}`}
              onClick={() =>
                useUI
                  .getState()
                  .set({ selectedStep: s.id, selectedArtifact: null })
              }
            >
              <span className={`step-number ${s.status}`}>
                {s.status === "done" ? <Check size={14} /> : s.index}
              </span>
              <div className="step-copy">
                <div>
                  <strong>{s.tool}</strong>
                  {s.edited && <span className="edited">edited</span>}
                  <span className={`step-status ${s.status}`}>
                    {s.status === "proposed" ? "Awaiting approval" : s.status}
                  </span>
                </div>
                <p>{parameterSummary(s.params) || "No parameters"}</p>
                <small>
                  {s.actor.startsWith("agent:") ? (
                    <Bot size={11} />
                  ) : s.actor.startsWith("cli:") ? (
                    <Terminal size={11} />
                  ) : (
                    <User size={11} />
                  )}{" "}
                  {s.actor === "user"
                    ? "You"
                    : s.actor.replace("agent:", "").replace("cli:", "")}{" "}
                  {s.status === "running" ? (
                    <RunningTime step={s} />
                  ) : s.finished_at && s.started_at ? (
                    ` / ${(s.finished_at - s.started_at).toFixed(1)}s`
                  ) : (
                    ""
                  )}
                </small>
              </div>
            </button>
          ))
        ) : (
          <div className="empty-timeline">
            <Clock3 size={26} />
            <h3>
              Every questionable decision,
              <br />
              on the record.
            </h3>
            <p>
              Watch the agent work, change a parameter, or run a tool yourself.
            </p>
          </div>
        )}
      </div>
      <button
        aria-label="Run tool"
        className="run-tool"
        onClick={() => useUI.getState().set({ paletteOpen: true })}
      >
        <Plus size={16} />
        Run tool<span>{tools?.length ?? "…"} tools</span>
      </button>
      {step && tool && (
        <div className="step-detail" key={`${session?.id}-${step.id}`}>
          <div className="detail-heading">
            <h3>
              {step.index}. {step.tool}
            </h3>
            <button
              title="Close step details"
              onClick={() => useUI.getState().set({ selectedStep: null })}
            >
              <X size={16} />
            </button>
          </div>
          {step.reason && <p>{step.reason}</p>}
          {step.error && (
            <div className="inline-error">
              <AlertTriangle size={15} />
              <div>
                {step.error.message}
                <small>{step.error.hint}</small>
              </div>
            </div>
          )}
          <ToolForm
            tool={tool}
            initial={step.params}
            disabled={busy && step.status !== "proposed"}
            submitLabel={
              session?.pending_approvals.includes(step.id)
                ? "Approve with changes"
                : "Apply & replay"
            }
            onSubmit={async (params) => {
              if (session?.pending_approvals.includes(step.id))
                return action("approval.respond", {
                  step_id: step.id,
                  decision: "edit",
                  params,
                });
              await action("steps.edit", { step_id: step.id, params });
              const settings = await action("settings.get");
              if (!settings.auto_replay)
                await action("steps.replay_from", { step_id: step.id });
            }}
          />
          <div className="detail-actions">
            <button
              disabled={busy}
              onClick={() =>
                run(() => action("steps.replay_from", { step_id: step.id }))
              }
            >
              <RotateCcw size={13} />
              Replay from here
            </button>
            <button
              title="Copy CLI command"
              aria-label="Copy CLI command"
              onClick={() =>
                run(async () => {
                  const params = { ...step.params };
                  for (const [name, value] of Object.entries(params)) {
                    if (typeof value === "string" && session?.artifacts[value])
                      params[name] = (
                        await action("export", { artifact_id: value })
                      ).path;
                    else if (Array.isArray(value))
                      params[name] = await Promise.all(
                        value.map(async (item) =>
                          typeof item === "string" && session?.artifacts[item]
                            ? (await action("export", { artifact_id: item }))
                                .path
                            : item,
                        ),
                      );
                  }
                  await copyText(cliCommand({ ...step, params }, tool));
                  useUI.getState().set({
                    notice:
                      "CLI command copied. Input images exported to your output folder.",
                  });
                })
              }
            >
              <Code size={14} />
              CLI
            </button>
            {session?.steps.at(-1)?.id === step.id && (
              <button
                title="Delete last step"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await action("steps.delete", { step_id: step.id });
                    useUI.getState().set({ selectedStep: null });
                  })
                }
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
          {step.result_text && (
            <details className="result" open>
              <summary>Result</summary>
              <pre>{step.result_text}</pre>
            </details>
          )}
          {step.data && (
            <details className="result">
              <summary>Structured result</summary>
              <pre>{JSON.stringify(step.data, null, 2)}</pre>
            </details>
          )}
          {step.outputs.map((id) => {
            const artifact = session?.artifacts[id];
            return (
              <div key={id} className="provenance">
                <ArtifactThumb
                  id={id}
                  onClick={() => useUI.getState().set({ selectedArtifact: id })}
                />
                <div>
                  <strong>{artifact?.label}</strong>
                  <span>
                    {artifact?.source
                      ? (artifact.source.license ?? "License not provided")
                      : "Session artifact"}
                  </span>
                  {artifact?.source?.creator && (
                    <span>{artifact.source.creator}</span>
                  )}
                  {(artifact?.source?.page || artifact?.source?.url) && (
                    <button
                      onClick={() =>
                        run(() =>
                          openLink(
                            artifact.source!.page ?? artifact.source!.url!,
                          ),
                        )
                      }
                    >
                      View source
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
export function ToolPalette() {
  const picking = useUI((state) => !!state.pick);
  const [search, setSearch] = useState("");
  const [tool, setTool] = useState<Tool | null>(null);
  const defaults = useRef<Params>({});
  const { data: tools } = useCoreQuery("tools.list");
  const { data: session } = useSession();
  const groups = (tools ?? [])
    .filter((t) =>
      `${t.name} ${t.summary} ${t.category}`
        .toLowerCase()
        .includes(search.toLowerCase()),
    )
    .reduce<Record<string, Tool[]>>(
      (groups, t) => ({
        ...groups,
        [t.category]: [...(groups[t.category] ?? []), t],
      }),
      {},
    );
  return (
    <div
      className={`modal-backdrop ${picking ? "pick-active" : ""}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget)
          useUI.getState().set({ paletteOpen: false });
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Run a tool"
        className="modal palette"
      >
        <div className="modal-heading">
          <div>
            <h2>{tool ? tool.name : "Run a tool"}</h2>
            <p>
              {tool
                ? tool.summary
                : "The exact same tools your agent uses. Your call."}
            </p>
          </div>
          <button
            aria-label="Close tools"
            onClick={() => useUI.getState().set({ paletteOpen: false })}
          >
            <X size={20} />
          </button>
        </div>
        <ErrorNotice />
        {tool ? (
          <>
            <button className="back-link" onClick={() => setTool(null)}>
              Back to all tools
            </button>
            <ToolForm
              key={tool.name}
              tool={tool}
              initial={defaults.current}
              onSubmit={async (params) => {
                const result = await action("tools.run", {
                  tool: tool.name,
                  params,
                });
                useUI.getState().set({
                  selectedStep: result.id,
                  selectedArtifact: result.outputs[0] ?? null,
                  paletteOpen: false,
                });
              }}
            />
          </>
        ) : (
          <>
            <div className="search">
              <Search size={17} />
              <input
                aria-label="Search tools"
                autoFocus
                placeholder="Find a tool…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <kbd>Esc</kbd>
            </div>
            <div className="tool-groups">
              {Object.entries(groups).map(([category, items]) => (
                <div key={category}>
                  <h3>{category}</h3>
                  {items?.map((t) => (
                    <button
                      key={t.name}
                      className="tool-option"
                      onClick={() => {
                        const selected =
                          useUI.getState().selectedArtifact ??
                          session?.steps.at(-1)?.outputs[0] ??
                          Object.values(session?.artifacts ?? {}).find(
                            (artifact) =>
                              !Object.values(session?.artifacts ?? {}).some(
                                (other) => other.original_id === artifact.id,
                              ),
                          )?.id;
                        const schema = normalizeSchema(t.schema);
                        defaults.current = Object.fromEntries(
                          Object.entries(schema.properties ?? {}).flatMap<
                            [string, unknown]
                          >(([name, field]) => {
                            if (typeof field !== "object" || !selected)
                              return [];
                            if (field.format === "badshop-image")
                              return [[name, selected]];
                            if (
                              typeof field.items === "object" &&
                              !Array.isArray(field.items) &&
                              field.items.format === "badshop-image"
                            )
                              return [[name, [selected]]];
                            return [];
                          }),
                        );
                        setTool(t);
                      }}
                    >
                      <strong>{t.name}</strong>
                      <span>{t.summary}</span>
                      <Plus size={16} />
                    </button>
                  ))}
                </div>
              ))}
              {!Object.keys(groups).length && (
                <p className="muted">No tools match “{search}”.</p>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
