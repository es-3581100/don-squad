# STARTUP-004 — OpenCode V1 guard discovery and lead quarantine

**Candidate status:** `ISOLATED_TEST_PASS__V1_RUNTIME_NOT_PROVEN__NO_INSTALL_OR_MERGE`  
**Frozen source parent:** `239a9a326779b1db2b4b811bfeb74b0938f078d9`  
**Target runtime:** OpenCode `1.18.35` (V1); global `@opencode-ai/plugin` `1.18.32`  
**Origin:** owner's STARTUP-001, STARTUP-002 and STARTUP-003 read-only probes on 2026-11-04.

## Evidence, not assumptions

1. The installed V2 guard is nested at `~/.config/opencode/plugins/don-squad-guard/index.js`, but no checked config explicitly registers it and none of the 5 top-level JavaScript plugin files imports it. There is **no evident V1 discovery route**. Direct runtime import was not traced.
2. The guard uses `@opencode/plugin`, `Plugin.define`, and V2 `ctx.*.hook/transform`; the V1.18.35 installation has `@opencode-ai/plugin`, not `@opencode/plugin`.
3. Expected state `~/.local/state/don-squad/{health.json,events/events.jsonl,latest.json}` is absent in the read-only probes. This is consistent with a non-loaded guard, but is not conclusive without a loader trace.
4. The 15-agent manifest is complete; **11 installed agent SHA-256 hashes mismatch**, exactly as in the uploaded frozen snapshot. No hash has been silently refreshed or declared legitimate.
5. The global V1-capable `permission:` block exists in 4 of 15 captured role definitions. **11 have only V2 `permissions:`**; V1 cannot be assumed to honor the latter. The lead has a V1 `permission.task` allowlist alongside a V2 `permissions` deny list. This is a real enforcement-contract mismatch.
6. The historical lead shell path `.opencode/mcp/don-squad-control.mjs` is absent under the checked project. The global file `tools/don-squad/don-squad-control.mjs` exists. This candidate does **not** register the MCP server; V1 MCP registration must be established separately.

## Candidate changes

- `plugins/don-squad-v1-guard.js`: an **immediate plugin-directory `.js` file** with one named V1 factory. No V2 SDK dependency. On initialization and before each tool invocation, it validates the manifest, hashes all 15 agents, checks policy and required MCP target, and writes a state-level health report. On critical health, it throws for every tool except the seven original documented read-only tools. It detects a disappeared/corrupted health report and unreviewed project/ancestor agent overrides and runtime configuration overlays. It does not alter agents, policy, or expected hashes and provides no override token or auto-approval.
- `agents/don-squad.md`: **temporary V1-native quarantine**: deny-all first, allow read-only actions, explicitly deny `bash`, `edit`, `task`, and `external_directory`; mark historical dispatch and mutation instructions inactive. This is an independent protection if the plugin fails to load.
- `plugins/don-squad-v1-guard.test.mjs`: isolated contract tests for discovery form, integrity state, fail-closed behavior, native lead permissions, overrides and state tampering.

## Local isolated verification

```sh
node --check plugins/don-squad-v1-guard.js
node --test plugins/don-squad-v1-guard.test.mjs
```

- **22/22 tests passed** in isolated fixtures using Node.js v22.16.0.
- Replayed the **actual frozen November 4 36-file snapshot** in a temporary config/state directory: exact 11 mismatches observed, health severity `critical`, read allowed, bash denied.
- Frontmatter parsed in PyYAML; the V1 `permission` map contains `"*": deny`, `bash: deny`, `edit: deny`, `task: deny`, and `external_directory: deny`.
- These are **source/mock contract results only**. They do not establish that installed OpenCode loads the new plugin, calls its hook, or computes the same effective permissions.

## Non-goals, limitations, remaining blockers

- **DO NOT INSTALL OR MERGE THIS DRAFT AS A RUNNABLE FIX.** It intentionally disables Don-Squad lead delegation and mutation pending trust reconciliation. It is not a new default release.
- The V1 plugin `tool.execute.before` is **not a universal permission hook**. It does not capture non-tool permission checks such as `external_directory`, which requires native V1 permission denies. V1's `permission.ask` is documented as unreliable/unwired; this candidate does not rely on it.
- **The other 14 agents are unchanged**: 11 V2-only permission definitions still require a separate V1-native conversion/audit; manually invoking a specialist may bypass the lead's quarantine. Do not use the installed specialist fleet for privileged actions until independently checked.
- Existing global/project `opencode.jsonc` config, inline permission overrides, external MCP tool permissions, and the five other local plugins have not been fully audited. The plugin blocks potential project agent overrides only when it is loaded and its V1 hook is called.
- A file-based hash registry stored next to the files cannot authenticate itself against a same-user attacker who can rewrite both; this is an integrity drift detector, not a cryptographic signing boundary.
- No actual OpenCode V1 binary was executed in the isolated tests. No plugin or config was installed into the user's `~/.config/opencode/` directory, and no live shell/delegation attempt occurred.
- `main`, source-snapshot PR #1 and V2-only draft PR #2 remain unchanged.

## Independent live acceptance sequence (separate future gate)

1. Owner reviews the intended native lead permission lockdown and its effect on the existing workflow.
2. Run a **disposable config-root experiment** with OpenCode `1.18.35`, ideally without other global or project plugins. Confirm the exact `.js` plugin is discovered and its V1 hooks execute; use synthetic/no-network tools, not real privileged commands.
3. Confirm native `permission.task`, `permission.bash`, `permission.edit`, and `permission.external_directory` denies are effective even when the plugin fails to initialize. Do not trust mere source-parsing as proof.
4. Independently reconcile each of the 11 hash mismatches; do not auto-sign their current contents. Audit each V2-only specialist role and design a separately reviewed V1 policy migration.
5. Validate config precedence and any project overrides, then provide a scoped rollback and **explicit owner approval** before any active-system installation, merge, or release.

**Disposition:** `STARTUP_004_V1_QUARANTINE_CANDIDATE__INDEPENDENT_RUNTIME_REVIEW_PENDING`
