# DonSquad

DonSquad is a local-first OpenCode control-plane agent family for routing planning, implementation, verification, review, documentation, and deployment work across bounded specialist roles.

This repository is seeded from the active `~/.config/opencode/` DonSquad snapshot captured on 2026-10-06. The runtime roster contains one primary `don-squad` orchestrator and fourteen specialist subagents. Shared skills and reference metadata provide capability/context only and do not grant authority.

Source snapshot archive SHA-256:

```text
42ac298c2d44d1305d4aa7d30d7555dfd7deda896fa541e6598b3f0a29f49840
```

## Layout

- `agents/` — active DonSquad agent profiles.
- `tools/don-squad/` — control-plane tool, policy, integrity, context, and record-condensing helpers.
- `policies/structured-agent-io.md` — structured prompt/return contract used for agent handoffs.
- `opencode.jsonc` — minimal OpenCode config shell from the captured installation.

The initial public seed intentionally excludes local backups, unrelated OpenCode agents/configuration, and the large local `tools/don-squad/reference/` artifact-internal provenance mirror. Runtime authority does not depend on that mirror.

`tools/don-squad/integrity.json` is preserved from the captured installation as metadata. Its values are not asserted here as raw SHA-256 checksums of the published agent Markdown files.

## License

BSD-2-Clause. See `LICENSE`.
