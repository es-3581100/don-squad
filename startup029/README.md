# Don-Squad STARTUP-029 — source-exact service and session-wrapper tests

**Status: PREPARED, NOT EXECUTED under OpenCode's real Bun/Effect dependencies.**
Do not install, merge or release STARTUP-020 based on this package.

## Target and pins

- OpenCode repository: `anomalyco/opencode`, **exact commit** `53d1eabb61e21162157817bf677da0a4ad3332e3` (`v1.18.35`). Bun `1.3.14` from that commit's root `package.json`.
- Actual V1 Effect permission service: `packages/opencode/src/permission/index.ts`, Git blob SHA-1 `2e27ff2424dbb000ea9ed7f73471769716ba40a1`.
- Actual production tool wrapper: `packages/opencode/src/session/tools.ts`, Git blob SHA-1 `99f7aec4fdfdfc857702b50b0ca3ce7c8651af4c`.
- Actual `InstanceState`: Git blob SHA-1 `b40168fbc2d7a53110cd8ba115ba8ee6acd91b80`.
- STARTUP-020 guard: SHA-256 `f57863c063253b0708d4215d752a54250dc9aecdcdbe2ad60dbc398b6ef624c5`, copied **byte-identically** from the pinned STARTUP-020 candidate ZIP.
- Frozen Don-Squad source ZIP and candidate ZIP are not modified. Exactly 11 integrity mismatches remain unresolved.

## What each test actually exercises

**Gate B (`startup029-permission-service.test.ts`)** invokes the real `Permission.node.implementation` Effect layer with real `InstanceState`, deferred pending requests, `ask`, `reply`, and cached `approved` rules. An isolated fake event sink is injected to prevent external event delivery. No model, filesystem tool, CLI, HTTP or normal chat loop is used. Test B02 deliberately first issues an `ask` request, replies `always`, then tests a **new request with a native `deny` rule** against the same live permission service. If V1 still evaluates `approved` after the native deny, B02 expects and reports that the request is **allowed**. Test B03 confirms `once` does not grant persistent access. The CI **intentionally fails the security gate when this vulnerability is reproduced**; a source-level test PASS must not be misread as release approval.

**Gate C1 (`startup029-normal-wrapper.test.ts`)** invokes real `SessionTools.resolve` and its production AI-SDK tool `execute` callback with injected in-process test services, a synthetic tool whose only effect is incrementing a counter, and a synthetic rejecting `tool.execute.before` hook. The hook must fire once and the tool body must remain at zero calls. This is not `debug agent --tool`.

**Gate C2 (`startup029-pinned-guard-wrapper.test.ts`)** injects the *exact pinned STARTUP-020 guard's* `tool.execute.before` callback through the production wrapper to block a synthetic tool. It does not exercise plugin auto-discovery/loader or the full `SessionPrompt` model-driven loop. No external provider is contacted.

## Execution options

Prefer an independent disposable CI runner, not the host's home-level Git checkout. The included `.github/workflows/startup-029-source-service-audit.yml` is manual (`workflow_dispatch`) and uses the exact upstream commit and Bun version. It requires uploading/copying this kit to a **separate audit branch**, preserving existing draft PR #3. It deliberately returns a nonzero final status on the expected reproduced approval override.

For a pre-existing **detached, explicitly verified** OpenCode v1.18.35 source checkout with Bun dependencies already installed, copy the three `tests/*.test.ts` files to `packages/opencode/test/donsquad-startup029/`; pass `DS029_GUARD_FILE` as an absolute path to the kit's `fixtures/don-squad-v1-guard.js` and `DS029_GUARD_SHA256` as the exact pin, and from `packages/opencode` run:

```bash
bun test --timeout 30000 test/donsquad-startup029/*.test.ts
```

Do **not** run these tests in a checkout found by walking upward from `~`: the operator's entire home is itself a Git repo. Do not install dependencies or run a source checkout outside an explicitly isolated/approved environment. The included CI workflow is a design handoff, not evidence of a completed CI execution.

## Security limitations / next decisions

1. The vulnerability requires a prior `always` approval made when the permission was askable, followed by a later or different agent-level deny while the same per-instance approval cache survives. It is not evidence that a fresh no-read quarantine with no approval history is bypassed.
2. Approval state is **in-memory per InstanceState directory**, not demonstrated persistent across application restarts.
3. Gate B tests the actual service layer *when run with Bun/Effect dependencies*, but does not use the installed standalone binary or normal user chat loop.
4. Gate C1/C2 test the real normal-session **wrapper** while directly injecting the hook; they do not certify automatic guard discovery, normal-session hook loading failure, or a complete model-driven tool cycle.
5. Do not promote agent permissions until an independent source patch addresses approval precedence, an external startup boundary rejects privilege-elevating config, and separate negative tests cover all 15 agents.
