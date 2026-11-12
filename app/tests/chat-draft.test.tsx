import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { Chat } from "../src/components/Chat";
import { action } from "../src/data";
import { useUI } from "../src/store";

vi.mock("../src/data", () => ({
  action: vi.fn(),
  run: (work: () => Promise<unknown>) => { void work(); },
  useSession: () => ({ data: { id: "s", messages: [], pending_approvals: [], steps: [], turn_running: false } }),
}));
vi.mock("../src/components/Viewer", () => ({ ArtifactThumb: ({ id }: { id: string }) => <span>{id}</span> }));

it("keeps a new draft and newly attached image while the previous message starts", async () => {
  useUI.getState().set({ status: "ready" });
  let finish!: () => void;
  vi.mocked(action).mockReturnValue(new Promise<void>((resolve) => { finish = resolve; }) as never);
  const onAttachments = vi.fn();
  const props = { onAttachments, onImport: vi.fn(), onPaste: vi.fn() };
  const client = new QueryClient();
  const view = render(<QueryClientProvider client={client}><Chat {...props} attachments={["sent-image"]} /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Message your agent"), { target: { value: "First request" } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  fireEvent.change(screen.getByLabelText("Message your agent"), { target: { value: "My next request" } });
  view.rerender(<QueryClientProvider client={client}><Chat {...props} attachments={["sent-image", "next-image"]} /></QueryClientProvider>);
  await act(async () => finish());
  expect(screen.getByLabelText("Message your agent")).toHaveValue("My next request");
  expect(onAttachments).toHaveBeenLastCalledWith(["next-image"]);
});
