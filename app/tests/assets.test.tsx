import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it } from "vitest";
import { AssetRow } from "../src/components/Settings";
it("shows automatic transfer progress and uses agent Stop rather than manual download cancellation", () => {
  const client = new QueryClient();
  client.setQueryData(["progress", "rembg/u2net.onnx"], {
    done: 50,
    total: 100,
    active: true,
  });
  client.setQueryData(["session.get"], { turn_running: true });
  render(
    <QueryClientProvider client={client}>
      <AssetRow
        asset={{
          name: "rembg/u2net.onnx",
          label: "U2-Net",
          approx_mb: 168,
          present: false,
        }}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "50");
  expect(screen.getByRole("button", { name: "Stop agent" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /^Cancel$/ }),
  ).not.toBeInTheDocument();
});
it("offers Cancel when download-all owns the active download", () => {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <AssetRow
        active
        asset={{
          name: "rembg/u2net.onnx",
          label: "U2-Net",
          approx_mb: 168,
          present: false,
        }}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("button", { name: /^Cancel$/ })).toBeVisible();
});
