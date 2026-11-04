# Don-Squad STARTUP-001 — integrity and MCP path hardening candidate

**Status:** `ISOLATED_SOURCE_TEST_PASS__LIVE_OPENCODE_NOT_VERIFIED`  
**Frozen parent:** `239a9a326779b1db2b4b811bfeb74b0938f078d9` (November 4 source snapshot)  
**Scope:** `plugins/don-squad-guard/index.js` and its isolated startup regression tests. This is not permission to merge, release, install, or update the active user's configuration.

## Source-level reproduction (original snapshot)

- Exactly **11 of 15** expected agent digests disagree with the installed-byte snapshot. Only `go`, `project-planner-hygiene`, `python`, and `verifier` match.
- In an isolated Node harness that replaces only the external `Plugin.define` import with a mock, the unmodified source reports `critical` for the 11 mismatches and denies `shell`, but retains only the *last* mismatch in its active health issues.
- The same unmodified source reports **no critical issue** for a missing, malformed, or partial manifest. It allows the `shell` action in those synthetic cases because the integrity loop becomes empty.
- If `health.json` is made malformed **after** startup, the unmodified source falls back to `minor` and permits `shell` in the synthetic permission hook.
- The unmodified source registers an MCP command whose executable path does not exist if `tools/don-squad/don-squad-control.mjs` is missing.

These are **isolated source-contract reproductions**, not a live OpenCode runtime result, and do not prove that OpenCode's own permission layer would have allowed a shell command.

## Changes proposed

1. Define the 15 required agent IDs independently of the editable manifest and policy; validate the complete manifest schema, roster and SHA-256 value format before accepting any digests.
2. Collect and expose separate critical findings for every mismatched/missing agent; reconcile *only* integrity-related prior issues after a completed rescan. Preserve unrelated critical findings.
3. Treat missing/corrupt/structurally-invalid health as critical for guard permission evaluation; do not trust a `minor` summary when an active issue remains critical.
4. Treat missing/malformed policy or an unsafe critical-safe-action list as critical. Critical-mode action permissions cannot exceed the original read-only ceiling, even if policy is edited to include a privileged action.
5. Test the actual MCP control executable path before registration. A missing executable becomes a critical finding and is **not registered** as a broken MCP command.
6. Preserve the existing session-override mechanism, role authority boundaries, and unresolved hash mismatches. No expected SHA-256 values are updated.

## Isolated verification

Run from repository root:

```bash
node --check plugins/don-squad-guard/index.js
node --test plugins/don-squad-guard/startup.test.mjs
```

The current local candidate passes **17/17** isolated Node tests: unchanged snapshot mismatch behavior, fully matching *synthetic* manifest, missing/malformed/partial/unexpected/malformed-digest manifests, missing agent, missing control executable, missing/unsafe policy, missing/corrupt/structurally invalid runtime health, critical summary downgrade, startup rescan recovery and MCP initialization.

Test harness limitations: the OpenCode `Plugin.define` and `ctx` interfaces are mocked; no installed OpenCode instance or actual agent permissions are exercised. Tests create private temporary directories, and do not touch `~/.config/opencode`, Engram, user sessions, or GitHub state.

## Path-resolution findings and blocked decisions

- The plugin resolves its configuration from `$XDG_CONFIG_HOME/opencode` or `~/.config/opencode`, and the MCP command from `tools/don-squad/don-squad-control.mjs` under that root.
- `agents/don-squad.md` contains the distinct shell-permission example `node .opencode/mcp/don-squad-control.mjs *`. That target is absent in the source snapshot; the plugin uses the **tools** path, which was proven to answer the MCP `initialize` and `tools/list` messages in isolation.
- OpenCode supports project `.opencode` folders and `OPENCODE_CONFIG_DIR` overrides. The guard currently hashes only global configuration-path agent files. A project-specific override may not be the same effective definition. The intended trust/lookup precedence must be decided from a live read-only startup inspection before changing that rule.
- The snapshot is not the whole installation. It does not contain the installed plugin manifest, launch environment or global config, so actual plugin API compatibility (`@opencode/plugin` / `Plugin.define` / `ctx.*.transform`) and effective MCP registration remain **unverified**.

Relevant public OpenCode documentation: https://opencode.ai/v2/docs/agents and https://docs.dev.opencode.ai/docs/config/ . Product versions and API contracts must be checked against the user's installed version, not presumed from current docs.

## Next gates before runtime promotion

1. Inspect exact on-device OpenCode version, plugin loading logs, `OPENCODE_CONFIG_DIR`, `XDG_CONFIG_HOME`, project `.opencode` ancestry, resolved command target, and read-only guard health; do not expose secrets.
2. Independently review how the 11 stale digest entries arose. **Do not bulk-update the trust baseline.** Approve individual file bytes and then create a separate manifest-reconciliation commit with provenance.
3. Validate real fresh-session startup with the guard enabled: valid manifest, mismatched agent, partial manifest, missing control file, read-only actions, denied privileged actions, no spinner on missing MCP, and explicit per-session override behavior.
4. Require an independent review and owner promotion decision before installation, merging or release. The main branch and installed runtime remain unchanged.

**Candidate disposition:** `STARTUP_001_FAIL_CLOSED_HARDENING_CANDIDATE__OWNER_REVIEW_PENDING`.
