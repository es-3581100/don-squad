# Structured agent I/O and SHA provenance — v1

## Mandatory serialization

- Agent-authored task prompts, delegation requests, handoffs, and terminal returns MUST be one valid JSON object (default) or one YAML 1.2 mapping. Existing JSON-only contracts remain JSON-only. No Markdown fences or prose outside the payload. Put explanations and code in string fields. Ordinary progress updates and clarification questions may remain prose; human input need not be structured.
- YAML uses only JSON-compatible values and string keys; reject duplicate keys, custom tags, anchors, aliases, and multiple documents. Quote hashes and identifiers. JSON must have no comments, trailing commas, duplicate keys, or non-finite numbers.
- Preserve existing role-specific fields, status vocabularies, routing, and authority restrictions. This contract overrides presentation-only prose/Markdown return preferences, not tool schemas or higher-priority instructions. Tool calls retain their native schema; serialize delegated instructions inside the tool's prompt string.
- Read this policy before generating or accepting a handoff. Check required fields, types, status, task identity, and evidence before acting. Use an available permitted parser for mechanical validation; if unavailable, report that limitation rather than claiming parser validation.

## Envelope

Every prompt and return includes:

- `schema_version`: `"agent-io/v1"`.
- `kind`: `"prompt"` or `"return"`.
- `task_id`: nonempty string, preserved in the matching return. IDs are correlation labels, not hashes.
- `sender`, `recipient`: agent IDs or `"user"`, as appropriate.
- `provenance`: mapping with `artifacts` (array), `git` (mapping or null), and `limitations` (array of strings). Empty arrays are legitimate when no artifact is involved; never fabricate evidence to fill them.

Prompts additionally include `objective` (string), `scope` (array of paths or bounded descriptions), `constraints` (array), `acceptance_criteria` (array), `inputs` (array of references), and `return_format` (`"json"` or `"yaml"`). Plain-language human requests are normalized without inventing authorization or requirements.

Returns additionally include `status` (existing role's vocabulary), `reason` (string), `evidence` (array), `next_owner` (string or null), and `verification` (array). Preserve required role fields such as `summary`, `files_touched`, `limitations`, `next`, or `learn`. Verification records contain `command`, `cwd`, `exit_code` (integer or null), `result`, and an evidence reference when available. A command not run has null exit code and an explicit not-run result.

## SHA rules

1. Artifact records contain `path` (absolute, or relative to an explicit `root`), `phase` (`input`, `before`, or `after`), `algorithm` (`sha256`), `digest` (64 lowercase hexadecimal characters or null), `verification` (`computed`, `matched`, `mismatch`, or `unavailable`), and `reason` (string or null). Include `expected_digest` when comparing a supplied digest. Label upstream-only hashes as unverified: use `digest: null`, `verification: unavailable`, and put the supplied value in `expected_digest` until recomputed locally.
2. Compute SHA-256 over exact file bytes with permitted tooling such as `sha256sum -- <path>`; do not hash a filename, summary, rendered Markdown, or presumed contents. Never invent, shorten, pad, or reuse a stale digest. Rehash after the final edit. Capture before/after separately for changed files; additions lack before bytes and deletions lack after bytes—record the absent side explicitly, never as an empty-file hash.
3. Hash relevant input artifacts and changed/output artifacts, not an unrelated entire workspace. A directory needs an established deterministic manifest/snapshot scheme with its scope and algorithm identified; do not pretend a directory has a raw file SHA.
4. Persisted prompts/returns are hashed as exact bytes using a separate receipt or parent envelope. Do not embed a digest of the entire envelope inside that same envelope. Inline payloads without a defined byte representation get no invented digest; record the limitation. Do not silently convert YAML to JSON and claim the original hash still applies.
5. Git provenance contains `root`, `object_format` (`sha1` or `sha256`), `commit` (full object ID or null), and `dirty` (boolean or null). Obtain object format and full commit with `git rev-parse --show-object-format` and `git rev-parse --verify 'HEAD^{commit}'`; inspect status including untracked files in the relevant scope. SHA-1 Git IDs have 40 hex characters; SHA-256 Git IDs have 64. A Git object ID is not a raw file SHA-256. HEAD does not identify dirty or untracked bytes; use artifact hashes for those. No repository/unborn HEAD/unavailable inspection must be explicit, not guessed clean state.
6. Recompute required incoming artifact hashes before relying on them. A mismatch stops dependent work and is reported as blocked or the role's equivalent, with expected and observed values. Missing tooling, inaccessible bytes, or denied permissions produce null plus a reason; never bypass permissions. If integrity is required for acceptance, unresolved verification blocks acceptance; unrelated bounded work may continue.
7. A matching hash proves byte identity only—not trust, correctness, authorization, approval, signature validity, or successful testing. Keep reported evidence distinct from independently verified evidence.

## Minimal return example (no artifact available)

```json
{
  "schema_version": "agent-io/v1",
  "kind": "return",
  "task_id": "task-001",
  "sender": "coder-worker",
  "recipient": "don-squad",
  "status": "blocked",
  "reason": "Required input artifact was not supplied.",
  "evidence": [],
  "next_owner": "don-squad",
  "verification": [],
  "provenance": {
    "artifacts": [],
    "git": null,
    "limitations": ["No input bytes or repository available to inspect."]
  }
}
```
