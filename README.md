# DonSquad

DonSquad is a local-first OpenCode control-plane agent family for routing planning, implementation, verification, review, documentation, and deployment work across bounded specialist roles.

This repository is seeded from the active `~/.config/opencode/` DonSquad snapshot captured on 2026-10-06. The runtime roster contains one primary `don-squad` orchestrator and fourteen specialist subagents. Shared skills and reference metadata provide capability/context only and do not grant authority.

## Layout

- `agents/` — active DonSquad agent profiles.
- `tools/don-squad/` — control-plane tool, policy, integrity, context, and record-condensing helpers.
- `policies/structured-agent-io.md` — structured prompt/return contract used for agent handoffs.
- `opencode.jsonc` — minimal OpenCode config shell from the captured installation.

The initial public seed intentionally excludes local backups and unrelated OpenCode agents/configuration.

## License

BSD-2-Clause. See `LICENSE`.
