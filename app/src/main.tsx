import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queries } from "./data";
import App from "./App";
import { FeatureBoundary } from "./components/FeatureBoundary";
import "./style.css";
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queries}>
      <FeatureBoundary name="Workspace"><App /></FeatureBoundary>
    </QueryClientProvider>
  </StrictMode>,
);
