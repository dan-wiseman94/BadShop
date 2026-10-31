import type { RJSFSchema } from "@rjsf/utils";
export type Params = Record<string, unknown>;
export type ApprovalMode = "auto" | "ask_changes" | "ask_all";
export interface Artifact {
  id: string;
  label: string;
  width: number;
  height: number;
  format: string;
  mime: string;
  produced_by?: string;
  original_id?: string;
  source?: {
    kind: string;
    url?: string;
    page?: string;
    license?: string;
    creator?: string;
  };
}
export interface Step {
  id: string;
  index: number;
  tool: string;
  params: Params;
  actor: string;
  status:
    | "proposed"
    | "approved"
    | "running"
    | "done"
    | "error"
    | "rejected"
    | "stale";
  outputs: string[];
  result_text: string;
  data?: Params;
  reason?: string;
  edited?: boolean;
  error?: { message: string; hint?: string };
  started_at?: number;
  finished_at?: number;
}
export interface Message {
  id: string;
  role: "user" | "assistant" | "system_note";
  content: { type: "text" | "image"; text?: string; artifact_id?: string }[];
  step_ids: string[];
}
export interface Session {
  unsaved_changes: boolean;
  document_revision: number;
  /** Transient event-cache state, never sent to or saved by the core. */
  stream_text?: string;
  id: string;
  name: string;
  path: string | null;
  provider_profile_id: string | null;
  approval_mode: ApprovalMode;
  messages: Message[];
  steps: Step[];
  artifacts: Record<string, Artifact>;
  turn_running: boolean;
  pending_approvals: string[];
  restorable: string | null;
}
export interface Tool {
  name: string;
  summary: string;
  description: string;
  category: string;
  mutates: boolean;
  network: boolean;
  read_only: boolean;
  cli_positionals?: string[];
  cli_flags?: Record<string, string>;
  schema: RJSFSchema;
}
export interface CLIDetection {
  cli: "claude" | "codex" | "gemini";
  executable: string | null;
  version: string | null;
  available: boolean;
  supported: boolean;
  experimental: boolean;
  error?: string;
}
export interface Profile {
  id: string;
  kind: "api" | "local" | "openai_compatible" | "cli";
  label: string;
  model: string;
  api_base?: string | null;
  api_key_ref?: string | null;
  api_key_env?: string | null;
  cli?: "claude" | "codex" | "gemini";
  executable?: string | null;
  capability_overrides: Record<string, boolean>;
}
export interface Settings {
  approval_mode: ApprovalMode;
  auto_replay: boolean;
  output_dir: string | null;
  step_budget: number;
  tool_timeout_s: number;
  tool_memory_mb: number;
  fake_provider_script: string | null;
}
export interface Asset {
  name: string;
  label: string;
  approx_mb: number;
  present: boolean;
}
export interface Connection {
  port: number;
  token: string;
  log_path?: string;
}
export interface ArtifactPayload {
  meta: Artifact;
  mime: string;
  data: string;
}
export interface MethodMap {
  "session.get": [undefined, Session];
  "session.new": [{ name?: string; expected_revision?:number; discard_unsaved?:boolean }, Session];
  "session.open": [{ path: string; expected_revision?:number; discard_unsaved?:boolean }, Session];
  "session.restore": [{expected_revision?:number;discard_unsaved?:boolean}|undefined, Session];
  "session.save": [{ expected_revision?: number } | undefined, { path: string }];
  "session.save_as": [{ path: string; expected_revision?: number }, { path: string }];
  "session.export_recipe": [{ path: string }, { path: string }];
  "session.set_approval_mode": [{ mode: ApprovalMode }, Session];
  "chat.send": [{ text: string; attachments?: string[] }, { started: boolean }];
  "chat.stop": [undefined, { stopped: boolean }];
  "chat.retry": [undefined, { started: boolean }];
  "tools.list": [undefined, Tool[]];
  "tools.run": [{ tool: string; params: Params }, Step];
  "steps.edit": [{ step_id: string; params: Params }, { stale: string[] }];
  "steps.replay_from": [{ step_id: string; use_cache?: boolean }, Step[]];
  "steps.delete": [{ step_id: string }, { deleted: string }];
  "approval.respond": [
    {
      step_id: string;
      decision: "approve" | "reject" | "edit";
      params?: Params;
      note?: string;
    },
    { ok: boolean },
  ];
  "artifacts.get": [{ id: string; max_px?: number }, ArtifactPayload];
  "artifacts.import": [
    { path?: string; data?: string; name?: string },
    { working: Artifact; original: Artifact },
  ];
  export: [{ artifact_id: string; name?: string }, { path: string }];
  "providers.list": [undefined, Profile[]];
  "providers.save": [{ profile: Partial<Profile>; api_key?: string }, Profile];
  "providers.delete": [{ profile_id: string }, { deleted: boolean }];
  "providers.select": [{ profile_id: string }, Session];
  "providers.test": [
    { profile_id: string; probe?: boolean },
    {
      status: string;
      error?: string;
      capabilities?: Params;
      warnings?: string[];
      probed?: boolean;
    },
  ];
  "providers.detect": [undefined, CLIDetection[]];
  "settings.get": [undefined, Settings];
  "settings.set": [{ values: Partial<Settings> }, Settings];
  "assets.status": [undefined, Asset[]];
  "assets.download": [{ name: string }, { path: string }];
  "assets.cancel": [{ name: string }, { cancelled: boolean }];
}
export interface CoreEvent {
  method: string;
  params: Params;
}
