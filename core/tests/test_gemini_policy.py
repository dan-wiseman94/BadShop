"""Opt-in offline policy contract against an isolated modern Gemini package.

Install with npm --prefix PRIVATE_DIR install --ignore-scripts @google/gemini-cli@0.66.0,
then set BADSHOP_GEMINI_PACKAGE=PRIVATE_DIR/node_modules/@google/gemini-cli.
No authenticated completion, network model request, or global config modification occurs.
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from badshop.providers.cli_provider import CLIProvider
from badshop.providers.profiles import Profile


@pytest.mark.skipif(not os.environ.get("BADSHOP_GEMINI_PACKAGE"), reason="isolated modern Gemini settings opt-in")
def test_actual_gemini_accepts_private_settings_and_disables_hooks():
    package = Path(os.environ["BADSHOP_GEMINI_PACKAGE"])
    settings_module = next(p for p in (package / "bundle").glob("chunk-*.js")
                           if "function loadSettings(workspaceDir" in p.read_text())
    executable = package.parent.parent / ".bin/gemini"
    provider = CLIProvider(Profile(kind="cli", cli="gemini", label="settings",
                                   executable=str(executable)), "ws://127.0.0.1:1234", "test-secret")
    try:
        script = '''
const {loadSettings}=await import(process.argv[1]);
const settings=loadSettings(process.argv[2]);
console.log(JSON.stringify({errors:settings.errors, hooksEnabled:settings.merged.hooksConfig?.enabled}));
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script,
                                 settings_module.as_uri(), str(provider.cwd)],
                                cwd=provider.cwd, env=provider.env,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr[-3000:]
        loaded = json.loads(result.stdout.strip().splitlines()[-1])
        assert loaded["errors"] == [], loaded["errors"]
        assert loaded["hooksEnabled"] is False
    finally:
        asyncio.run(provider.close())


@pytest.mark.skipif(not os.environ.get("BADSHOP_GEMINI_PACKAGE"), reason="isolated modern Gemini policy opt-in")
def test_actual_gemini_policy_allows_only_badshop_mcp(tmp_path):
    package = Path(os.environ["BADSHOP_GEMINI_PACKAGE"])
    bundle = next((package / "bundle").glob("core-*.js"))
    executable = package.parent.parent / ".bin/gemini"
    provider = CLIProvider(Profile(kind="cli", cli="gemini", label="policy",
                                   executable=str(executable)), "ws://127.0.0.1:1234", "test-secret")
    try:
        settings_path = str(Path(provider.env["GEMINI_CLI_HOME"]) / ".gemini/settings.json")
        command = provider.command("offline policy probe")
        policy_dir = command[command.index("--policy") + 1]
        script = '''
import fs from 'node:fs';
const {createPolicyEngineConfig,PolicyEngine,ApprovalMode,ALL_BUILTIN_TOOL_NAMES}=await import(process.argv[1]);
const settings=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
settings.policyPaths=[process.argv[3]];
const config=await createPolicyEngineConfig(settings,ApprovalMode.DEFAULT,undefined,false);
const engine=new PolicyEngine(config);
const decisions=[];
for(const [name,server] of [['mcp_badshop_view','badshop'],['mcp_other_view','other'],
                          ['mcp_badshop_view','other'],...[...ALL_BUILTIN_TOOL_NAMES].map(name=>[name,undefined])]) {
 const result=await engine.check({name,args:{}},server);
 decisions.push({name,server,decision:result.decision,priority:result.rule?.priority});
}
console.log(JSON.stringify(decisions));
'''
        result = subprocess.run(["node", "--input-type=module", "-e", script, bundle.as_uri(), settings_path,
                                 policy_dir], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr[-3000:]
        decisions = json.loads(result.stdout.strip().splitlines()[-1])
        assert decisions[0]["decision"] == "allow" and decisions[0]["priority"] > 4.24
        assert len(decisions) > 10
        assert all(d["decision"] == "deny" for d in decisions[1:]), decisions
    finally:
        asyncio.run(provider.close())
