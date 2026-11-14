import { Button } from "./Button";
import { SelectField } from "./Fields";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import { ArrowUp, Square, Paperclip, Scissors, Check, X, SlidersHorizontal, RotateCcw } from "lucide-react";
import { action, run, useSession } from "../data";
import { useUI } from "../store";
import { ArtifactThumb } from "./Viewer";
import { openLink } from "../native";
import type { Params, NoveltyMode } from "../types";
import { creativeRequest, creativeStyles } from "../creative";
import "../creative.css";
import { ON_DEVICE } from "../constants";

export function Chat({
  attachments,
  onAttachments,
  onImport,
  onPaste,
  onConnect,
  onViewImage,
  onViewStep,
  draft,
  onDraftConsumed,
}: {
  attachments: string[];
  onAttachments: (next: string[]) => void;
  onImport: () => void;
  onPaste: (event: React.ClipboardEvent) => void;
  onConnect?: () => void;
  onViewImage?: () => void;
  onViewStep?: () => void;
  draft?: { id: string; text: string };
  onDraftConsumed?: (id: string) => void;
}) {
  const { data: session } = useSession();
  const text = useUI(state => state.chatDraft);
  const setText = useUI(state => state.setChatDraft);
  const [style, setStyle] = useState("");
  const [novelty, setNovelty] = useState<NoveltyMode | "">("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const currentAttachments = useRef(attachments);
  currentAttachments.current = attachments;
  const lastDraft = useRef<string | null>(null);
  useEffect(() => {
    if (!draft || draft.id === lastDraft.current || sending) return;
    lastDraft.current = draft.id;
    setText((previous) => (previous.trim() ? `${previous}\n\n${draft.text}` : draft.text));
    onDraftConsumed?.(draft.id);
  }, [draft, sending, onDraftConsumed]);
  const history = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const viewedSession = useRef<string | undefined>(undefined);
  const errorAction = useUI((state) => state.errorAction);
  const stream = session?.stream_text ?? "";
  const { data: providerEvents } = useQuery<Params[]>({
    queryKey: ["provider-events"],
    queryFn: () => [],
    enabled: false,
  });
  const ready = useUI((s) => s.status === "ready");
  const hasProvider = !!session?.provider_profile_id;
  const needsProvider = ready && !!session && !hasProvider && !session.scripted_provider;
  const canResume = session?.last_turn_outcome?.reason === "paused" ||
    (session?.last_turn_outcome?.reason === "stopped" && !!session?.undo_branch_id);
  useEffect(() => {
    const node = history.current;
    if (!node) return;
    if (viewedSession.current !== session?.id) {
      viewedSession.current = session?.id;
      following.current = true;
      node.scrollTop = 0;
    }
    if (!session?.messages.length && !stream && !session?.pending_approvals.length) return;
    if (following.current) node.scrollTop = node.scrollHeight;
  }, [session?.id, session?.messages.length, stream, session?.pending_approvals.length]);
  const send = (takes: 1 | 3 = 1) =>
    run(async () => {
      if ((!text.trim() && !attachments.length) || sending || session?.turn_running || !ready || needsProvider) return;
      following.current = true;
      setSending(true);
      const generation = useUI.getState().documentGeneration;
      try {
        await action("chat.send", {
          text: creativeRequest(text, style, takes),
          attachments,
          ...(novelty ? { novelty } : {}),
        });
        if (useUI.getState().documentGeneration === generation) {
          setText((current) => current === text ? "" : current);
          onAttachments(currentAttachments.current.filter((id) => !attachments.includes(id)));
        }
      } finally {
        setSending(false);
      }
    });
  return (
    <section className="chat pane" aria-label="Chat">
      <div className="pane-heading">
        <span>Art direction</span>
        <span className={`connection-dot ${ready && !needsProvider ? "online" : ""}`}>
          {!ready ? "Connecting" : needsProvider ? "AI not connected" : "Ready"}
        </span>
      </div>
      {(session?.turn_running || session?.undo_branch_id || canResume) && (
        <div className="manual-turn-controls">
          {session?.turn_running && <button onClick={() => run(() => action("chat.pause"))}>Pause after operation</button>}
          {!session?.turn_running && session?.undo_branch_id && <button onClick={() => run(() => action("chat.undo"))}>Undo last AI turn</button>}
          {!session?.turn_running && canResume && !needsProvider && (
            <button disabled={sending} onClick={() => run(async () => {
              if (session?.pause_before_finish) await action("chat.finish_checkpoint", { enabled: false });
              await action("chat.send", {
                text: "Resume the previous request using the current corrected images and locked settings. Finishing effects are now allowed."
              });
            })}>Resume and allow finishing</button>
          )}
        </div>
      )}
      <div
        className="chat-history"
        ref={history}
        onScroll={() => {
          const node = history.current;
          if (node) following.current = node.scrollHeight - node.clientHeight - node.scrollTop < 40;
        }}
      >
        {needsProvider && <div className="chat-provider">
          <p>Connect a provider to direct edits from chat.</p>
          <button className="primary" onClick={onConnect}>Connect AI</button>
        </div>}
        {!needsProvider && !session?.messages.length && (
          <div className="chat-welcome">
            <div className="welcome-label">The cut &amp; paste department</div>
            <h1>
              Cut. Paste.
              <br />
              <span>Make it worse.</span>
            </h1>
            <p>
              {session?.provider_profile_id === ON_DEVICE
                ? "Add a photo, then describe one edit you want to make."
                : "Tell your agent what to cut, paste, caption, or absolutely ruin."}
            </p>
            <div className="example-prompts">
              {(session?.provider_profile_id === ON_DEVICE
                ? ["Put laser eyes on the person on the left.", "Deep fry this photo.", "Add a caption that says “MONDAY”."]
                : [
                    "Put laser eyes on this.",
                    "Make it look like a 2005 forum signature.",
                    "Find a cat. Deep fry it. Add “stonks”.",
                  ]
              ).map((prompt) => (
                <button key={prompt} onClick={() => setText(prompt)}>
                  {prompt}
                  <ArrowUp size={13} />
                </button>
              ))}
            </div>
            <div className="welcome-note">
              <Scissors size={14} />
              Real pixels. No image generation.
            </div>
          </div>
        )}
        {session?.messages.map((message) => (
          <article key={message.id} className={`message ${message.role}`}>
            <div className="message-name">
              {message.role === "user"
                ? "You"
                : message.role === "system_note"
                  ? "Session update"
                  : "badshop"}
              <span>{message.role === "assistant" ? "Art director" : ""}</span>
            </div>
            {message.content.map((part, i) =>
              part.type === "text" ? (
                <Markdown
                  key={i}
                  allowedElements={[
                    "p",
                    "strong",
                    "em",
                    "code",
                    "pre",
                    "ul",
                    "ol",
                    "li",
                    "blockquote",
                    "h1",
                    "h2",
                    "h3",
                    "hr",
                    "br",
                    "a",
                  ]}
                  components={{
                    a: ({ href, children }) => (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(event) => {
                          if (href && /^https?:\/\//.test(href)) {
                            event.preventDefault();
                            run(() => openLink(href));
                          }
                        }}
                      >
                        {children}
                      </a>
                    ),
                  }}
                >
                  {part.text ?? ""}
                </Markdown>
              ) : part.artifact_id ? (
                <ArtifactThumb
                  key={i}
                  id={part.artifact_id}
                  onClick={() => { useUI.getState().set({ selectedArtifact: part.artifact_id! }); onViewImage?.(); }}
                />
              ) : null,
            )}
            {message.step_ids.length > 0 && (
              <div className="tool-chips">
                {message.step_ids.map((id) => {
                  const step = session.steps.find((s) => s.id === id);
                  return (
                    <button
                      key={id}
                      onClick={() => { useUI.getState().set({ selectedStep: id, selectedArtifact: null }); onViewStep?.(); }}
                    >
                      {step?.status === "done" ? <Check size={12} /> : <SlidersHorizontal size={12} />}{" "}
                      {step?.tool ?? id}
                    </button>
                  );
                })}
              </div>
            )}
          </article>
        ))}
        {stream && (
          <article className="message assistant streaming">
            <div className="message-name">
              badshop<span>Art director</span>
            </div>
            <Markdown>{stream}</Markdown>
          </article>
        )}
        {session?.pending_approvals.map((id) => {
          const step = session.steps.find((s) => s.id === id);
          if (!step) return null;
          return (
            <div key={id} className="approval-card">
              <div className="approval-heading">
                <span className="pending-dot" />
                Your call
              </div>
              <h3>{step.tool}</h3>
              {step.reason && <p>{step.reason}</p>}
              <pre>{JSON.stringify(step.params, null, 2)}</pre>
              <input
                aria-label={`Rejection note for ${step.id}`}
                placeholder="Optional note for the agent"
                value={notes[id] ?? ""}
                onChange={(e) => setNotes({ ...notes, [id]: e.target.value })}
              />
              <div className="approval-actions">
                <Button
                  className="primary"
                  onClick={() =>
                    run(() =>
                      action("approval.respond", {
                        step_id: id,
                        decision: "approve",
                      }),
                    )
                  }
                  label="Approve"
                  icon={Check}
                  iconSize={14}
                />
                <Button
                  onClick={() => { useUI.getState().set({ selectedStep: id, selectedArtifact: null }); onViewStep?.(); }}
                  label="Edit"
                  icon={SlidersHorizontal}
                  iconSize={14}
                />
                <Button
                  onClick={() =>
                    run(() =>
                      action("approval.respond", {
                        step_id: id,
                        decision: "reject",
                        note: notes[id] || "Rejected by the user",
                      }),
                    )
                  }
                  label="Reject"
                  icon={X}
                  iconSize={14}
                />
              </div>
            </div>
          );
        })}
        {session?.turn_running && !stream && (
          <div className="working">
            <span />
            Agent is working…
          </div>
        )}
        {!!providerEvents?.length && (
          <details className="provider-events">
            <summary>CLI event log ({providerEvents.length})</summary>
            {providerEvents.map((event, index) => (
              <pre key={index}>
                {String(event.cli)}
                {event.parse_error ? " / could not parse event" : ""}\n
                {String(event.raw)}
              </pre>
            ))}
          </details>
        )}
        <div aria-hidden="true" />
      </div>
      <div className="composer">
        <details className="chat-options">
          <summary>Direction options</summary>
          <label><input type="checkbox" checked={session?.pause_before_finish ?? false}
            disabled={!ready || needsProvider || session?.turn_running}
            onChange={(event) => run(() => action("chat.finish_checkpoint", { enabled: event.target.checked }))} /> Pause before finishing effects</label>
        <SelectField
          label="Novelty"
          labelClassName="creative-direction"
          aria-label="Novelty direction"
          value={novelty}
          disabled={sending || session?.turn_running}
          onChange={(event) => setNovelty(event.target.value as NoveltyMode | "")}
          options={[
            ["", "Follow my request"] as const,
            ["different-format", "Different visual format"] as const,
            ["change-setting", "Keep joke, change setting"] as const,
            ["another-era", "Another era"] as const,
            ["avoid-recent", "Avoid recent images / formats"] as const,
          ]}
        />
        <SelectField
          label="Style"
          labelClassName="creative-direction"
          aria-label="Creative style"
          disabled={sending || session?.turn_running}
          title={creativeStyles.find((item) => item.id === style)?.summary}
          bind={[style, setStyle]}
          options={[
            ["", "Follow my prompt"] as const,
            ...creativeStyles.map((item) => [item.id, item.name] as const),
          ]}
        />
        </details>
        <div className="attachments">
          {attachments.map((id) => (
            <div key={id}>
              <ArtifactThumb id={id} />
              <button
                title="Remove attachment"
                onClick={() => onAttachments(attachments.filter((a) => a !== id))}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
        <textarea
          aria-label="Message your agent"
          placeholder="Make something terrible…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={onPaste}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              send();
            }
          }}
        />
        <div className="composer-actions">
          <button aria-label="Attach images" title="Attach images" onClick={onImport}>
            <Paperclip size={17} />
          </button>
          <span>Enter to send</span>
          <Button
            type="button"
            title="Make three different compositions; uses more steps"
            disabled={!ready || needsProvider || (!text.trim() && !attachments.length) || sending || session?.turn_running}
            onClick={() => send(3)}
            label="Three takes"
          />
          {session?.turn_running || sending ? (
            <button className="stop" onClick={() => run(() => action("chat.stop"))}>
              <Square size={13} fill="currentColor" />
              Stop
            </button>
          ) : (
            <button
              className="send"
              aria-label="Send message"
              disabled={!ready || needsProvider || (!text.trim() && !attachments.length) || sending}
              onClick={() => send()}
            >
              <ArrowUp size={19} />
            </button>
          )}
        </div>
      </div>
      <div className="chat-foot">
        <span>You can change every step.</span>
        {errorAction === "retry-turn" && (
          <Button
            disabled={needsProvider || session?.turn_running || sending}
            title="Retry failed provider turn"
            onClick={() => run(() => action("chat.retry"))}
            label="Retry turn"
            icon={RotateCcw}
            iconSize={11}
          />
        )}
      </div>
    </section>
  );
}
