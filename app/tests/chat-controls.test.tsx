import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { Chat } from "../src/components/Chat";
import { useUI } from "../src/store";
import * as native from "../src/native";
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
