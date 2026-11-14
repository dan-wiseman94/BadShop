import type { RJSFSchema } from "@rjsf/utils";
import type { Artifact, DocumentContext, Message as WireMessage, Step as WireStep } from "./wire.generated";
export type { Artifact } from "./wire.generated";
// Core responses include these defaults. The remaining defaults may be omitted
// by UI fixtures; field types and nullability still come from the core schemas.
export type Step = WireStep & Required<Pick<WireStep, "outputs" | "result_text">>;
export type Message = WireMessage & Required<Pick<WireMessage, "step_ids">>;
export type Params = Record<string, unknown>;
export type ApprovalMode = "auto" | "ask_changes" | "ask_all";
export type NoveltyMode =
  "different-format" | "change-setting" | "another-era" | "avoid-recent";
export interface Session {
  context?: DocumentContext;
  run_id?: string | null;
  last_turn_outcome?: { run_id: string | null; reason: string; error?: string | null } | null;

  manual_history?: { undo: string | null; redo: string | null };
  batch_running?: boolean;
  undo_branch_id?: string | null;
  pause_before_finish?: boolean;
  bypass_tools?: string[];
  creative?: CreativePreferences;
  recipes?: Recipe[];
  unsaved_changes: boolean;
  document_revision: number;
  /** Transient event-cache state, never sent to or saved by the core. */
  stream_text?: string;
  id: string;
  name: string;
  path: string | null;
  provider_profile_id: string | null;
  scripted_provider?: boolean;
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
  error?: string | null;
}
export interface Profile {
  id: string;
  kind: "api" | "local" | "openai_compatible" | "cli";
  label: string;
  model: string;
  api_base?: string | null;
  allow_insecure_http?: boolean;
  api_key_ref?: string | null;
  api_key_env?: string | null;
  cli?: "claude" | "codex" | "gemini" | null;
  executable?: string | null;
  capability_overrides: Record<string, boolean>;
}
export interface Settings {
  saved_designs?: Recipe[];
  export_presets?: { name: string; params: Params }[];
  creative_defaults?: CreativePreferences;
  no_remote?: boolean;
  remember_history?: boolean;
  source_allowlist?: string[];
  rights_filter?: string;
  source_orientation?: string;
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
export type { WireMethodMap as MethodMap } from "./wire.generated";
interface CreativePreferences {
  remember_history?: boolean;
  animation_delay?: number;
  style: string;
  density: string;
  era_strictness: string;
  exact_text: boolean;
  seed: number;
  fit: string;
  takes: number;
  export_profile: string;
  favorite_styles: string[];
  favorite_briefs: string[];
  saved_searches: string[];
  locks: Record<string, boolean>;
  mixer: Record<string, string>;
  source_roles: Record<string, string>;
}
export type Recipe = {
  version: number;
  name: string;
  steps: { tool: string; params: Params }[];
  inputs?: Record<string, { kind: "image" | "text"; default?: string | null }>;
}
export interface RecipeRowResult { index: number; status: string; output_id: string | null; error: string | null; step_ids: string[] }
export interface CoreEvent {
  method: string;
  params: Params;
  context?: DocumentContext;
  core_instance_id?: string;
  event_seq?: number;
}
export interface LibraryEntry {
  id: string;
  name: string;
  tags: string[];
  metadata: Params;
  artifact: Artifact;
  original?: Artifact | null;
  created_at: number;
  updated_at: number;
}
export interface BranchList {
  active_id: string;
  branches: {
    id: string;
    name: string;
    created_at: number;
    step_count: number;
    preview_id?: string | null;
  }[];
}
export interface LayoutDefinition {
  id: string;
  name: string;
  width: number;
  height: number;
  max_images: number;
  slots: {
    name: string;
    box: number[];
    caption_box: number[];
    mask?: string;
  }[];
}
interface MediaCandidate {
  id: string;
  label: string;
  time_s?: number | null;
  page?: number | null;
  thumbnail_data_url: string;
  width: number;
  height: number;
}
export interface MediaPreview {
  id: string;
  source_name: string;
  kind: "video" | "document";
  width: number;
  height: number;
  sheet_data_url: string;
  candidates: MediaCandidate[];
  warnings: string[];
}
export interface CollectionEntry {
  id: string;
  name: string;
  tags: string[];
  description: string;
  thumbnail_data_url: string;
  width: number;
  height: number;
  duplicate_of?: string | null;
}
