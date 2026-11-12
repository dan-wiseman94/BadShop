import type { RJSFSchema } from "@rjsf/utils";
import type { Artifact, Message as WireMessage, Step as WireStep } from "./wire.generated";
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
  batch_running?: boolean;
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
  allow_insecure_http?: boolean;
  api_key_ref?: string | null;
  api_key_env?: string | null;
  cli?: "claude" | "codex" | "gemini";
  executable?: string | null;
  capability_overrides: Record<string, boolean>;
}
export interface Settings {
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
export interface ArtifactPayload {
  meta: Artifact;
  mime: string;
  data: string;
}
export interface MethodMap {
  "artifacts.frame": [{ id: string; frame: number }, ArtifactPayload];
  "sources.key": [{ source: string; api_key: string }, { saved: boolean }];
  "cache.status": [
    undefined,
    { bytes: number; files: number; budget_mb: number },
  ];
  "cache.clear": [undefined, { removed: number }];
  "retro.list": [undefined, RetroStyle[]];
  "creative.set": [{ values: Params }, CreativePreferences];
  "recipes.capture": [{ step_id: string }, Recipe];
  "recipes.save": [{ recipe: Recipe }, Recipe];
  "recipes.remove": [{ name: string }, { removed: boolean }];
  "recipes.run": [
    { recipe: Recipe; inputs: string[] },
    { completed: string[]; errors: { message: string }[]; cancelled: boolean },
  ];
  "recipes.stop": [undefined, { stopped: boolean }];
  "credits.get": [
    { artifact_id: string },
    { sources: Params[]; notice: string },
  ];
  "credits.export": [
    { artifact_id: string },
    { path: string; credits: string },
  ];
  "sources.status": [
    undefined,
    {
      id: string;
      name: string;
      configured: boolean;
      requires_key: boolean;
      env_var: string | null;
      health?: { status: "failed" | "responded" | "not checked"; results?: number; step_id?: string };
    }[],
  ];
  "novelty.recent": [
    undefined,
    { kind: string; value: string; label?: string; url?: string }[],
  ];
  "novelty.clear": [undefined, { cleared: boolean }];
  "layouts.list": [undefined, LayoutDefinition[]];
  "packs.list": [undefined, BuiltinPack[]];
  "packs.install": [{ id: string }, LibraryEntry[]];
  "packs.export": [
    { ids: string[]; path: string; name?: string },
    { path: string; count: number },
  ];
  "packs.import": [
    { path: string },
    { entries: LibraryEntry[]; name: string; count: number },
  ];
  "media.preview": [
    {
      path: string;
      kind: "video" | "document";
      start?: number;
      end?: number;
      count?: number;
      page?: number;
    },
    MediaPreview,
  ];
  "media.status": [undefined, { video: boolean; pdf: boolean }];
  "media.cancel": [undefined, { cancelled: boolean }];
  "media.import": [
    {
      preview_id: string;
      candidate_ids: string[];
      crop?: number[];
      animate?: boolean;
      delay?: number;
    },
    { artifacts: Artifact[]; provenance: Params },
  ];
  "collections.index": [
    { path: string; max_files?: number },
    CollectionSummary,
  ];
  "collections.list": [undefined, CollectionSummary[]];
  "collections.search": [
    { id: string; query?: string; limit?: number },
    CollectionEntry[],
  ];
  "collections.update": [
    {
      collection_id: string;
      id: string;
      tags?: string[];
      description?: string;
    },
    CollectionEntry,
  ];
  "collections.import": [
    { collection_id: string; id: string },
    { working: Artifact; original: Artifact },
  ];
  "collections.remove": [{ id: string }, { removed: boolean }];
  "library.list": [
    { query?: string; tags?: string[] } | undefined,
    LibraryEntry[],
  ];
  "library.save": [
    { artifact_id: string; name: string; tags?: string[]; metadata?: Params },
    LibraryEntry,
  ];
  "library.update": [
    { id: string; name?: string; tags?: string[]; metadata?: Params },
    LibraryEntry,
  ];
  "library.import": [
    { id: string },
    { working: Artifact; original: Artifact; entry: LibraryEntry },
  ];
  "library.remove": [{ id: string }, { removed: boolean }];
  "library.thumbnail": [
    { id: string; max_px?: number },
    { mime: string; data: string },
  ];
  "branches.list": [undefined, BranchList];
  "branches.create": [
    { name: string; from_step?: string; expected_revision?: number },
    Session,
  ];
  "branches.switch": [{ id: string; expected_revision?: number }, Session];
  "branches.rename": [{ id: string; name: string }, BranchList];
  "branches.remove": [{ id: string }, BranchList];
  "session.get": [undefined, Session];
  "session.new": [
    { name?: string; expected_revision?: number; discard_unsaved?: boolean },
    Session,
  ];
  "session.open": [
    { path: string; expected_revision?: number; discard_unsaved?: boolean },
    Session,
  ];
  "session.restore": [
    { expected_revision?: number; discard_unsaved?: boolean } | undefined,
    Session,
  ];
  "session.save": [
    { expected_revision?: number } | undefined,
    { path: string },
  ];
  "session.save_as": [
    { path: string; expected_revision?: number },
    { path: string },
  ];
  "session.export_recipe": [{ path: string }, { path: string }];
  "session.set_approval_mode": [{ mode: ApprovalMode }, Session];
  "chat.send": [
    { text: string; attachments?: string[]; novelty?: NoveltyMode },
    { started: boolean },
  ];
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
    { path?: string; data?: string; name?: string; source?: Artifact["source"] },
    { working: Artifact; original: Artifact },
  ];
  export: [{ artifact_id: string; name?: string }, { path: string }];
  "providers.list": [undefined, Profile[]];
  "providers.save": [{ profile: Partial<Profile>; api_key?: string }, Profile];
  "providers.delete": [{ profile_id: string }, { deleted: boolean }];
  "providers.select": [{ profile_id: string }, Session];
  "providers.on_device": [undefined, Session];
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
export interface RetroStyle {
  id: string;
  name: string;
  era: string;
  family: string;
  width: number;
  height: number;
  preview: string;
}
export interface CreativePreferences {
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
export interface Recipe {
  version: number;
  name: string;
  steps: { tool: string; params: Params }[];
}
export interface CoreEvent {
  method: string;
  params: Params;
}
export interface LibraryEntry {
  id: string;
  name: string;
  tags: string[];
  metadata: Params;
  artifact: Artifact;
  original?: Artifact;
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
export interface BuiltinPack {
  id: string;
  name: string;
  description: string;
  count: number;
}
export interface MediaCandidate {
  id: string;
  label: string;
  time_s?: number;
  page?: number;
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
export interface CollectionSummary {
  id: string;
  name: string;
  count: number;
  duplicates: number;
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
