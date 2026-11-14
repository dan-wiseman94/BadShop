import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AssetRow, Settings, Welcome } from "../src/components/Settings";
import { action, queries } from "../src/data";
import { rpc } from "../src/rpc";
import { useUI } from "../src/store";
import type { Profile, Session } from "../src/types";
const session: Session = {
  id: "s",
  name: "Settings",
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
const profile: Profile = {
  id: "saved",
  kind: "local",
  label: "Saved local",
  model: "ollama_chat/llava",
  capability_overrides: { vision: true, tool_calls: true },
};
function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queries}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  queries.clear();
  useUI.getState().set({ status: "ready", error: null, errorAction: null });
  queries.setQueryData(["session.get"], session);
  queries.setQueryData(["providers.list"], [profile]);
});
afterEach(() => vi.restoreAllMocks());
it("keeps shared manual download cancellation available across widget unmount and remount", async () => {
  let complete!: (value: unknown) => void;
  vi.spyOn(rpc, "request").mockImplementation(
    (method) =>
      (method === "assets.download"
        ? new Promise((resolve) => {
            complete = resolve;
          })
        : Promise.resolve(method === "session.get" ? session : [])) as never,
  );
  const pending = action("assets.download", { name: "rembg/u2net.onnx" });
  const asset = {
    name: "rembg/u2net.onnx",
    label: "U2-Net",
    approx_mb: 168,
    present: false,
  };
  const view = render(
    <>
      <AssetRow asset={asset} />
      <AssetRow asset={asset} />
    </>,
    { wrapper },
  );
  expect(screen.getAllByRole("button", { name: "Cancel" })).toHaveLength(2);
  view.unmount();
  render(<AssetRow asset={asset} />, { wrapper });
  expect(screen.getByRole("button", { name: "Cancel" })).toBeVisible();
  await act(async () => {
    complete({ path: "/tmp/u2net.onnx" });
    await pending;
  });
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument(),
  );
});

it("keeps setup checks offline and only sends a paid-capable probe on explicit Test connection", async () => {
  let probed = false;
  const request = vi.spyOn(rpc, "request").mockImplementation(
    (method) =>
      Promise.resolve(
        method === "providers.test"
          ? { status: "ready", probed }
          : method === "session.get"
            ? session
            : method === "providers.list"
              ? [profile]
              : method === "settings.get"
                ? {
                    approval_mode: "auto",
                    auto_replay: true,
                    step_budget: 40,
                    tool_timeout_s: 90,
                    tool_memory_mb: 3072,
                  }
                : [],
      ) as never,
  );
  render(<Settings updates={{ automatic: true, track: "stable", setTrack: () => {}, info: null, phase: "idle", error: "", progress: null,
    check: async () => {}, install: async () => {}, cancel: async () => {}, localOnly: false, setAutomatic: () => {} }} />, { wrapper });
  expect(screen.getByText(/provider may charge/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Check setup" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("providers.test", {
      profile_id: profile.id,
    }, undefined, undefined),
  );
  await waitFor(() =>
    expect(screen.getByText(/No test request was sent/)).toBeVisible(),
  );
  probed = true;
  fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("providers.test", {
      profile_id: profile.id,
      probe: true,
    }, undefined, undefined),
  );
  await waitFor(() =>
    expect(screen.getByText("Connection succeeded.")).toBeVisible(),
  );
});

it("finishing on-device setup after leaving onboarding preserves the chosen workspace", async () => {
  let finish!: () => void;
  let activated = false;
  const local = { ...profile, id: "badshop-on-device", label: "On-device AI" };
  const snapshot = () => ({ ...session, provider_profile_id: activated ? local.id : null });
  const assets = [{ name: "local-vision/test.gguf", label: "Test model", approx_mb: 1, present: true }];
  queries.setQueryData(["providers.list"], []);
  queries.setQueryData(["assets.status"], assets);
  vi.spyOn(rpc, "request").mockImplementation(method => {
    if (method === "providers.on_device") return new Promise(resolve => {
      finish = () => { activated = true; resolve(snapshot()); };
    }) as never;
    return Promise.resolve(method === "session.get" ? snapshot()
      : method === "providers.list" ? (activated ? [local] : [])
        : method === "assets.status" ? assets : []) as never;
  });
  function Workspace() {
    const [workspace, setWorkspace] = useState("welcome");
    return workspace === "welcome"
      ? <Welcome onQuick={() => setWorkspace("Quick ideas")} onAdvanced={() => setWorkspace("Art director")} />
      : <p>{workspace}</p>;
  }
  render(<Workspace />, { wrapper });
  fireEvent.click(screen.getByRole("button", { name: "Use on-device AI" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Setting up…" })).toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Start with a quick idea" }));
  expect(screen.getByText("Quick ideas", { exact: true })).toBeVisible();
  await act(async () => { finish(); });
  expect(screen.getByText("Quick ideas", { exact: true })).toBeVisible();
});
