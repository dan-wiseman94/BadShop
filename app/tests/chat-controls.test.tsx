import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { Chat } from "../src/components/Chat";
import * as data from "../src/data";
import * as native from "../src/native";
import { useUI } from "../src/store";
import type { Session } from "../src/types";
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
