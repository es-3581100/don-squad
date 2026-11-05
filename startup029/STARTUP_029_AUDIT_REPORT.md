# STARTUP-029 — Permission-service and normal-session hook audit checkpoint

**Status:** SOURCE-EVALUATOR PRECEDENCE RISK CORROBORATED; REAL EFFECT SERVICE AND NORMAL WRAPPER EXECUTION PENDING.

## Target identity

`anomalyco/opencode` exact `v1.18.35` commit `53d1eabb61e21162157817bf677da0a4ad3332e3` (not an unpinned moving tag). The production V1 service is `packages/opencode/src/permission/index.ts`, Git blob SHA-1 `2e27ff2424dbb000ea9ed7f73471769716ba40a1`. Production normal-session wrapper is `packages/opencode/src/session/tools.ts`, Git blob SHA-1 `99f7aec4fdfdfc857702b50b0ca3ce7c8651af4c`.

The exact STARTUP-020 guard copied into this kit hashes to SHA-256 `f57863c063253b0708d4215d752a54250dc9aecdcdbe2ad60dbc398b6ef624c5`.

## Evidence obtained in assistant environment

- Read exact full upstream `Permission.Service.ask` and `reply` implementation, `InstanceState`, `SessionTools.resolve`, and production plugin triggers.
- Read-only source excerpts of upstream `evaluate()` and `Wildcard.match()` were independently hash-pinned, then *executed directly* in Node 22. A `read` deny without a prior approval evaluated to `deny`. Adding a later in-memory `read` allow rule caused `evaluate()` to return **`allow`**. This corroborates the approval-order concern, but did not execute `Permission.Service.ask` itself.
- Prepared three Bun test files: Gate B directly instantiates the real Effect permission-service Layer with real deferred approvals and per-instance state; C1 runs the actual production normal-session tool wrapper with a synthetic rejection hook; C2 injects the byte-pinned STARTUP-020 guard through that same wrapper. All three TypeScript files passed syntax/transpilation diagnostics via locally installed TypeScript. **They have NOT run under Bun/Effect.**
- Prepared a pinned GitHub Actions runner (not installed or executed) using immutable upstream commit SHA, Bun `1.3.14`, and no model/provider invocations. Expected security disposition if Gate B reproduces the override is **BLOCKED**, even if its functional regression tests pass.
- Verified the ZIP manifest, candidate guard hash, and archive CRCs. No files in the installed user configuration or user's home Git repo were modified. No model or agent tool execution occurred.

## Critical conditionality

An `always` approval must already have been granted for the same permission while a request was askable. Later tightening rules to `deny` while keeping the same per-instance in-memory approved state can be superseded under the existing `findLast` selection. The result does **not** demonstrate bypass of a fresh no-read quarantine with no historical approval. The approval cache is in-process; persistence across restarts has **not** been demonstrated.

## Remaining gates

1. Run Gate B against the **actual** source's Effect dependencies and record observed `ask`/`reply` outcomes. A function-only replay is insufficient to close Gate B.
2. Run the C1 and C2 source tests through the production `SessionTools.resolve` wrapper. These are **not** `debug agent --tool` calls.
3. Independently run a true normal-session integration case verifying OpenCode auto-loads the candidate plugin and the tool hook fires from `SessionPrompt`/LLM stream. A deterministic local model stub is an optional later test but was not executed or silently authorized here.
4. No promotion until approval-order race, config-override path, the other 14 agents, and 11 critical integrity mismatches are resolved and independently reviewed. PR #3 remains draft/unmerged and STARTUP-020 uninstalled.

**Current disposition:** `STARTUP_029_SOURCE_EVALUATOR_PRECEDENCE_RISK_CORROBORATED__EFFECT_SERVICE_AND_SESSION_WRAPPER_EXECUTION_PENDING__DO_NOT_INSTALL`.
