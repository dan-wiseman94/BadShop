import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { Chat } from "../src/components/Chat";
import { useUI } from "../src/store";
import * as native from "../src/native";
import * as data from "../src/data";
import type { Session } from "../src/types";
import { StrictMode } from "react";
const message = (id: string, text: string) => ({
  id,
  role: "assistant" as const,
  content: [{ type: "text" as const, text }],
  step_ids: [],
});
const session: Session = {
  id: "s",
  name: "Chat",
  path: null,
  provider_profile_id: null,
  approval_mode: "auto",
  messages: [],
  steps: [],
  artifacts: {},
  turn_running: false,
  pending_approvals: [],
  restorable: null,
  unsaved_changes: false,
  document_revision: 0,
};
beforeEach(() =>
  useUI.getState().set({ status: "starting", error: null, errorAction: null }),
);
function renderChat(value: Session) {
  const client = new QueryClient();
  client.setQueryData(["session.get"], value);
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <Chat
          attachments={[]}
          onAttachments={() => {}}
          onImport={() => {}}
          onPaste={() => {}}
        />
      </QueryClientProvider>,
    ),
  };
}
it("leaves the empty welcome at the top instead of scrolling to its bottom marker", () => {
  renderChat(session);
  expect(document.querySelector(".chat-history")!.scrollTop).toBe(0);
});
it("keeps the reader position when new messages arrive while reading earlier messages", async () => {
  const { client } = renderChat({
    ...session,
    messages: [message("m1", "Earlier message")],
  });
  const history = document.querySelector<HTMLElement>(".chat-history")!;
  Object.defineProperty(history, "scrollHeight", {
    value: 1000,
    configurable: true,
  });
  Object.defineProperty(history, "clientHeight", {
    value: 200,
    configurable: true,
  });
  history.scrollTop = 100;
  fireEvent.scroll(history);
  await act(async () => {
    client.setQueryData(["session.get"], {
      ...session,
      messages: [message("m1", "Earlier message"), message("m2", "New reply")],
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(history.scrollTop).toBe(100);
});
it("routes a Markdown http link through the native external opener", () => {
  const opener = vi.spyOn(native, "openLink").mockResolvedValue();
  renderChat({
    ...session,
    messages: [message("m1", "Read the [source](https://example.com/source).")],
  });
  fireEvent.click(screen.getByRole("link", { name: "source" }));
  expect(opener).toHaveBeenCalledWith("https://example.com/source");
  opener.mockRestore();
});
it("sends the chosen style and three independent takes through the normal chat action", async () => {
  const send = vi.spyOn(data, "action").mockResolvedValue({ started: true });
  const { client } = renderChat(session);
  // Keep the fixture fresh so enabling the connection doesn't trigger a background RPC.
  client.setQueryDefaults(["session.get"], { staleTime: Infinity });
  act(() => useUI.getState().set({ status: "ready" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Creative style" }), {
    target: { value: "tabloid" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Message your agent" }), {
    target: { value: "Make my dog the boss" },
  });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Three takes" })));
  expect(send).toHaveBeenCalledWith("chat.send", {
    text: expect.stringContaining("Tabloid front page"), attachments: [],
  });
  expect(send.mock.calls[0][1]).toMatchObject({ text: expect.stringContaining("clean base") });
  expect(screen.getByRole("textbox", { name: "Message your agent" })).toHaveValue("");
  send.mockRestore();
});
it("passes the selected novelty direction without replacing the user's request", async () => {
  const send = vi.spyOn(data, "action").mockResolvedValue({ started: true });
  const { client } = renderChat(session);
  client.setQueryDefaults(["session.get"], { staleTime: Infinity });
  act(() => useUI.getState().set({ status: "ready" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Novelty direction" }), { target: { value: "another-era" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Message your agent" }), { target: { value: "Keep my cat" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send message" })));
  expect(send).toHaveBeenCalledWith("chat.send", { text: "Keep my cat", attachments: [], novelty: "another-era" });
  send.mockRestore();
});

it("adds an idea brief once, preserves the current draft, and waits for an explicit send", () => {
  const send = vi.spyOn(data, "action").mockResolvedValue({ started: true });
  const consumed = vi.fn();
  const client = new QueryClient();
  client.setQueryData(["session.get"], session);
  const content = (draft?: { id: string; text: string }) => <StrictMode><QueryClientProvider client={client}>
    <Chat attachments={[]} onAttachments={() => {}} onImport={() => {}} onPaste={() => {}} draft={draft} onDraftConsumed={consumed} />
  </QueryClientProvider></StrictMode>;
  const { rerender } = render(content());
  fireEvent.change(screen.getByRole("textbox", { name: "Message your agent" }), { target: { value: "Keep the red hat." } });
  rerender(content({ id: "idea-1", text: "Make an office comic." }));
  expect(screen.getByRole("textbox", { name: "Message your agent" })).toHaveValue("Keep the red hat.\n\nMake an office comic.");
  rerender(content({ id: "idea-1", text: "Make an office comic." }));
  expect(screen.getByRole("textbox", { name: "Message your agent" })).toHaveValue("Keep the red hat.\n\nMake an office comic.");
  expect(send).not.toHaveBeenCalled();
  expect(consumed).toHaveBeenCalledExactlyOnceWith("idea-1");
  send.mockRestore();
});

it("waits for a pending submission before acknowledging queued briefs and consumes them in order", async () => {
  let finish!: (value: { started: boolean }) => void;
  const pending = new Promise<{ started: boolean }>(resolve => { finish = resolve; });
  const send = vi.spyOn(data, "action").mockReturnValueOnce(pending);
  const consumed = vi.fn();
  const client = new QueryClient();
  client.setQueryDefaults(["session.get"], { staleTime: Infinity });
  client.setQueryData(["session.get"], session);
  const content = (draft?: { id: string; text: string }) => <QueryClientProvider client={client}>
    <Chat attachments={[]} onAttachments={() => {}} onImport={() => {}} onPaste={() => {}} draft={draft} onDraftConsumed={consumed} />
  </QueryClientProvider>;
  const { rerender } = render(content());
  act(() => useUI.getState().set({ status: "ready" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Message your agent" }), { target: { value: "First request" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send message" })));
  rerender(content({ id: "brief-a", text: "Brief A" }));
  expect(consumed).not.toHaveBeenCalled();
  await act(async () => finish({ started: true }));
  expect(consumed).toHaveBeenCalledWith("brief-a");
  rerender(content({ id: "brief-b", text: "Brief B" }));
  expect(consumed.mock.calls).toEqual([["brief-a"], ["brief-b"]]);
  expect(screen.getByRole("textbox", { name: "Message your agent" })).toHaveValue("Brief A\n\nBrief B");
  expect(send).toHaveBeenCalledTimes(1);
  send.mockRestore();
});
