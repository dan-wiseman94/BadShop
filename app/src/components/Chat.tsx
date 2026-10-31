import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import {
  ArrowUp,
  Square,
  Paperclip,
  Sparkles,
  Check,
  X,
  SlidersHorizontal,
  RotateCcw,
} from "lucide-react";
import { action, run, useSession } from "../data";
import { useUI } from "../store";
import { ArtifactThumb } from "./Viewer";
import { openLink } from "../native";
import type { Params } from "../types";
export function Chat({
  attachments,
  onAttachments,
  onImport,
  onPaste,
}: {
  attachments: string[];
  onAttachments: (next: string[]) => void;
  onImport: () => void;
  onPaste: (event: React.ClipboardEvent) => void;
}) {
  const { data: session } = useSession();
  const [text, setText] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
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
  useEffect(() => {
    const node = history.current;
    if (!node) return;
    if (viewedSession.current !== session?.id) {
      viewedSession.current = session?.id;
      following.current = true;
      node.scrollTop = 0;
    }
    if (
      !session?.messages.length &&
      !stream &&
      !session?.pending_approvals.length
    )
      return;
    if (following.current) node.scrollTop = node.scrollHeight;
  }, [
    session?.id,
    session?.messages.length,
    stream,
    session?.pending_approvals.length,
  ]);
  const send = () =>
    run(async () => {
      if (
        (!text.trim() && !attachments.length) ||
        sending ||
        session?.turn_running ||
        !ready
      )
        return;
      following.current = true;
      setSending(true);
      try {
        await action("chat.send", { text, attachments });
        setText("");
        onAttachments([]);
      } finally {
        setSending(false);
      }
    });
  return (
    <section className="chat pane" aria-label="Chat">
      <div className="pane-heading">
        <span>Art direction</span>
        <span className={`connection-dot ${ready ? "online" : ""}`}>
          {ready ? "Connected" : "Connecting"}
        </span>
      </div>
      <div
        className="chat-history"
        ref={history}
        onScroll={() => {
          const node = history.current;
          if (node)
            following.current =
              node.scrollHeight - node.clientHeight - node.scrollTop < 40;
        }}
      >
        {!session?.messages.length && (
          <div className="chat-welcome">
            <div className="little-logo">
              b<span>✱</span>
            </div>
            <h1>
              Good tools.
              <br />
              Bad intentions.
            </h1>
            <p>
              Tell your agent what to cut, paste, caption, or absolutely ruin.
            </p>
            <div className="example-prompts">
              {[
                "Put laser eyes on this.",
                "Make it look like a 2005 forum signature.",
                "Find a cat. Deep fry it. Add “stonks”.",
              ].map((prompt) => (
                <button key={prompt} onClick={() => setText(prompt)}>
                  {prompt}
                  <ArrowUp size={13} />
                </button>
              ))}
            </div>
            <div className="welcome-note">
              <Sparkles size={14} />
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
                  onClick={() =>
                    useUI
                      .getState()
                      .set({ selectedArtifact: part.artifact_id! })
                  }
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
                      onClick={() =>
                        useUI
                          .getState()
                          .set({ selectedStep: id, selectedArtifact: null })
                      }
                    >
                      {step?.status === "done" ? (
                        <Check size={12} />
                      ) : (
                        <SlidersHorizontal size={12} />
                      )}{" "}
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
                <button
                  className="primary"
                  onClick={() =>
                    run(() =>
                      action("approval.respond", {
                        step_id: id,
                        decision: "approve",
                      }),
                    )
                  }
                >
                  <Check size={14} />
                  Approve
                </button>
                <button
                  onClick={() =>
                    useUI
                      .getState()
                      .set({ selectedStep: id, selectedArtifact: null })
                  }
                >
                  <SlidersHorizontal size={14} />
                  Edit
                </button>
                <button
                  onClick={() =>
                    run(() =>
                      action("approval.respond", {
                        step_id: id,
                        decision: "reject",
                        note: notes[id] || "Rejected by the user",
                      }),
                    )
                  }
                >
                  <X size={14} />
                  Reject
                </button>
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
        <div className="attachments">
          {attachments.map((id) => (
            <div key={id}>
              <ArtifactThumb id={id} />
              <button
                title="Remove attachment"
                onClick={() =>
                  onAttachments(attachments.filter((a) => a !== id))
                }
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
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              send();
            }
          }}
        />
        <div className="composer-actions">
          <button
            aria-label="Attach images"
            title="Attach images"
            onClick={onImport}
          >
            <Paperclip size={17} />
          </button>
          <span>Enter to send</span>
          {session?.turn_running || sending ? (
            <button
              className="stop"
              onClick={() => run(() => action("chat.stop"))}
            >
              <Square size={13} fill="currentColor" />
              Stop
            </button>
          ) : (
            <button
              className="send"
              aria-label="Send message"
              disabled={
                !ready || (!text.trim() && !attachments.length) || sending
              }
              onClick={send}
            >
              <ArrowUp size={19} />
            </button>
          )}
        </div>
      </div>
      <div className="chat-foot">
        <span>You can change every step.</span>
        {errorAction === "retry-turn" && (
          <button
            disabled={session?.turn_running || sending}
            title="Retry failed provider turn"
            onClick={() => run(() => action("chat.retry"))}
          >
            <RotateCcw size={11} />
            Retry turn
          </button>
        )}
      </div>
    </section>
  );
}
