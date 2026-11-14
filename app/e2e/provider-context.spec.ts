import { test, expect } from "./fixtures";
import type { Profile } from "../src/types";

test("switching CLI tools clears the previous executable and model before saving", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI", { exact: true }).click();
  await welcome.getByRole("button", { name: /^CLI subscription/ }).click();
  await welcome.getByRole("button", { name: "Continue with CLI subscription" }).click();
  await welcome.getByLabel("Profile name").fill("My subscription");
  await welcome.getByLabel("Executable path (optional)").fill("/tmp/old-claude");
  await welcome.getByLabel("Model (optional)").fill("claude-only-model");
  await welcome.getByLabel("Command line tool").selectOption("codex");
  await expect(welcome.getByLabel("Executable path (optional)")).toHaveValue("");
  await expect(welcome.getByLabel("Model (optional)")).toHaveValue("");
  await welcome.getByLabel("Command line tool").selectOption("gemini");
  await welcome.getByRole("button", { name: "Save provider" }).click();
  await expect.poll(() => emptyCore.call("providers.list")).toEqual([expect.objectContaining({ cli: "gemini", model: "", executable: null })]);
});

test("changing provider type resets incompatible model and credentials", async ({ page, emptyCore }) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI", { exact: true }).click();
  await welcome.getByRole("button", { name: "Continue with Cloud API" }).click();
  await welcome.getByLabel("Profile name").fill("Changing setup");
  await welcome.getByLabel("Model", { exact: true }).fill("openai/gpt-4.1-mini");
  await welcome.getByLabel(/^API key/).fill("test-placeholder-not-a-real-key");
  await welcome.getByLabel("Provider type").selectOption("cli");
  await expect(welcome.getByLabel("Model (optional)")).toHaveValue("");
  await welcome.getByLabel("Provider type").selectOption("local");
  await expect(welcome.getByLabel(/^API key/)).toHaveValue("");
  await welcome.getByRole("button", { name: "Back", exact: true }).click();
  await expect(welcome.getByRole("button", { name: "Continue with Local model" })).toBeVisible();
  await welcome.getByRole("button", { name: /^Cloud API/ }).click();
  await welcome.getByRole("button", { name: "Continue with Cloud API" }).click();
  await expect(welcome.getByLabel("Provider type")).toHaveValue("api");
  await welcome.getByLabel("Provider type").selectOption("local");
  await welcome.getByLabel("Profile name").fill("Changing setup");
  await welcome.getByLabel("Model", { exact: true }).fill("ollama_chat/llava");
  await welcome.getByRole("button", { name: "Save provider" }).click();
  await expect.poll(() => emptyCore.call("providers.list")).toEqual([expect.objectContaining({ kind: "local", api_key_ref: null, api_key_env: null, model: "ollama_chat/llava" })]);
});

test("invalid preferences explain that the previous saved value is kept", async ({ page, emptyCore }) => {
  await page.addInitScript(() => localStorage.setItem("badshop.welcome", "1"));
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const settings = page.getByRole("dialog", { name: "Settings" });
  await settings.getByRole("button", { name: "Preferences", exact: true }).click();
  const initial = await emptyCore.call("settings.get") as { step_budget: number };
  await settings.getByLabel("Maximum steps per turn").fill("0");
  await settings.getByLabel("Maximum steps per turn").blur();
  await expect(settings.getByRole("alert")).toContainText("Maximum steps per turn");
  expect((await emptyCore.call("settings.get") as { step_budget: number }).step_budget).toBe(initial.step_budget);
  await expect(settings.getByLabel("Maximum steps per turn")).toHaveValue(String(initial.step_budget));
  await settings.getByLabel("Maximum steps per turn").fill("25");
  await settings.getByLabel("Maximum steps per turn").blur();
  await expect.poll(async () => (await emptyCore.call("settings.get") as { step_budget: number }).step_budget).toBe(25);
  await expect(settings.getByRole("alert")).toHaveCount(0);
});

test("Back preserves an unfinished provider form and the final screen explains saved versus tested", async ({ page, emptyCore }, info) => {
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI", { exact: true }).click();
  await welcome.getByRole("button", { name: /^Local model/ }).click();
  await welcome.getByRole("button", { name: "Continue with Local model" }).click();
  await welcome.getByLabel("Profile name").fill("My local model");
  await welcome.getByLabel("Model", { exact: true }).fill("ollama_chat/llava");
  await welcome.getByRole("button", { name: "Back", exact: true }).click();
  await welcome.getByRole("button", { name: "Continue with Local model" }).click();
  await expect(welcome.getByLabel("Profile name")).toHaveValue("My local model");
  await expect(welcome.getByLabel("Model", { exact: true })).toHaveValue("ollama_chat/llava");
  await welcome.getByRole("button", { name: "Save provider" }).click();
  await expect(welcome.getByText(/saved.*not.*tested/i)).toBeVisible();
  await expect(welcome.getByRole("button", { name: "Check setup", exact: true })).toBeVisible();
  await expect(welcome.getByRole("button", { name: "Test connection", exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("provider-saved.png") });
  const profiles = await emptyCore.call("providers.list") as Profile[];
  expect(profiles).toHaveLength(1);
  await welcome.getByRole("button", { name: "Choose another way to start" }).click();
  await welcome.getByRole("button", { name: "Continue with Local model" }).click();
  await expect(welcome.getByLabel("Profile name")).toHaveValue("");
  await welcome.getByLabel("Profile name").fill("A second local model");
  await welcome.getByLabel("Model", { exact: true }).fill("ollama_chat/llava");
  await welcome.getByRole("button", { name: "Save provider" }).click();
  await expect.poll(async () => (await emptyCore.call("providers.list") as Profile[]).length).toBe(2);
});

test("a preselected provider does not hide the first-run choices", async ({ page, emptyCore }) => {
  const profile = await emptyCore.call("providers.save", { profile: { kind: "local", label: "Existing local", model: "ollama_chat/llava" } }) as Profile;
  await emptyCore.call("providers.select", { profile_id: profile.id });
  await page.goto(`/?core_port=${emptyCore.port}&core_token=${emptyCore.token}`);
  const welcome = page.getByRole("dialog", { name: "Welcome to badshop" });
  await welcome.getByText("Connect AI", { exact: true }).click();
  await expect(welcome.getByRole("button", { name: "Start with a quick idea" })).toBeVisible();
  await welcome.getByRole("button", { name: "Start with a quick idea" }).click();
  await expect(page.getByRole("region", { name: "Quick ideas" })).toBeVisible();
});
