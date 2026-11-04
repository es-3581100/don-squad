#!/usr/bin/env python3
"""DonSquad final agent-io/v1 return serialization boundary (fail-closed).

Boundary provenance (locate finding donsquad-serializer-locate-001):
- No dedicated serializer existed. The effective boundary was prose:
  ``don-squad.md`` 82-83/152-153/155-165 (single lead return + handoff
  envelope) plus ``structured-agent-io.md`` 3-23 (mandatory JSON/YAML,
  envelope, SHA rules) as executed by the lead.
- Transports that must preserve arrays byte-for-byte:
  ``don-squad-control.mjs``:9-10 (``send``/``result`` via
  ``JSON.stringify(o)+'\\n'``), ``squawk_box/render.py``:223-253
  (``write_projections`` JSON writes), ``squawk_box/model.py``:109-114
  (``canonical_json``/``canonical_line``) and
  ``squawk_box/ledger.py``:202-269 (``submit``/``_submit_locked``).

This module is the dedicated serializer for the DonSquad final
agent-io/v1 return path. It enforces, before emission:

- ``evidence``, ``verification``, ``provenance.artifacts``,
  ``provenance.limitations`` (and any other repeated structured fields
  listed in ``ARRAY_FIELDS``) serialize as JSON arrays, never
  objects/strings/null-for-array.
- Exact final bytes are validated with a real JSON parser
  (``json.loads``) plus required-envelope checks. Malformed
  pseudo-JSON fails closed (raises, never emits).
- Semantic contents are preserved unchanged; only transport
  serialization is constrained (deterministic ``json.dumps`` with
  ``sort_keys=True``, compact separators, ``allow_nan=False``).

Squawk Box lifecycle, migration plan, and portfolio paths are untouched.
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = "agent-io/v1"
RETURN_KIND = "return"

# Collection fields that MUST be JSON arrays when present.
# Top-level return arrays + provenance arrays + prompt-side repeated
# fields (guarded so a prompt accidentally routed here also fails closed
# instead of emitting an object/string/null for a repeated field).
ARRAY_FIELDS_TOP = (
    "evidence",
    "verification",
    "scope",
    "constraints",
    "acceptance_criteria",
    "inputs",
)
ARRAY_FIELDS_PROVENANCE = (
    "artifacts",
    "limitations",
)

REQUIRED_RETURN_FIELDS = (
    "schema_version",
    "kind",
    "task_id",
    "sender",
    "recipient",
    "status",
    "reason",
    "evidence",
    "next_owner",
    "verification",
    "provenance",
)

REQUIRED_PROVENANCE_FIELDS = (
    "artifacts",
    "git",
    "limitations",
)

REQUIRED_VERIFICATION_FIELDS = (
    "command",
    "cwd",
    "exit_code",
    "result",
)


def _fail(msg: str) -> ValueError:
    return ValueError(f"agent-io/v1 return serialization blocked: {msg}")


def _require_array(field_path: str, value: Any) -> list[Any]:
    # Fail closed: only a real JSON array (Python list) is accepted.
    # dict/str/bytes/None/int (including null-for-array) are rejected.
    if not isinstance(value, list):
        raise _fail(
            f"{field_path} must be a JSON array, got {type(value).__name__}"
        )
    return value


def validate_return(obj: Any) -> dict[str, Any]:
    """Validate an agent-io/v1 return mapping. Fail closed on violation."""
    if not isinstance(obj, dict):
        raise _fail(f"return must be a JSON object, got {type(obj).__name__}")
    for field in REQUIRED_RETURN_FIELDS:
        if field not in obj:
            raise _fail(f"missing required envelope field: {field}")
    if obj.get("schema_version") != SCHEMA_VERSION:
        raise _fail(f"schema_version must be {SCHEMA_VERSION!r}")
    if obj.get("kind") != RETURN_KIND:
        raise _fail(f"kind must be {RETURN_KIND!r}")
    task_id = obj.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise _fail("task_id must be a nonempty string")
    for endpoint in ("sender", "recipient"):
        val = obj.get(endpoint)
        if not isinstance(val, str) or not val:
            raise _fail(f"{endpoint} must be a nonempty string")
    status = obj.get("status")
    if not isinstance(status, str) or not status:
        raise _fail("status must be a nonempty string (role vocabulary)")
    reason = obj.get("reason")
    if not isinstance(reason, str) or not reason:
        raise _fail("reason must be a nonempty string")
    next_owner = obj.get("next_owner")
    if next_owner is not None and not isinstance(next_owner, str):
        raise _fail("next_owner must be a string or null")

    # Array-type enforcement: never objects/strings/null-for-array.
    for field in ARRAY_FIELDS_TOP:
        if field in obj:
            _require_array(field, obj[field])
    # evidence/verification are required, so they were checked above when
    # present; require them explicitly as lists (not just when present).
    _require_array("evidence", obj["evidence"])
    _require_array("verification", obj["verification"])

    for index, record in enumerate(obj["verification"]):
        if not isinstance(record, dict):
            raise _fail(f"verification[{index}] must be an object")
        for field in REQUIRED_VERIFICATION_FIELDS:
            if field not in record:
                raise _fail(f"verification[{index}] missing field: {field}")
        if not isinstance(record["command"], str) or not record["command"]:
            raise _fail(f"verification[{index}].command must be nonempty string")
        if not isinstance(record["cwd"], str) or not record["cwd"]:
            raise _fail(f"verification[{index}].cwd must be nonempty string")
        exit_code = record["exit_code"]
        if exit_code is not None and type(exit_code) is not int:
            raise _fail(f"verification[{index}].exit_code must be integer or null")
        if not isinstance(record["result"], str) or not record["result"]:
            raise _fail(f"verification[{index}].result must be nonempty string")

    provenance = obj.get("provenance")
    if not isinstance(provenance, dict):
        raise _fail("provenance must be an object")
    for field in REQUIRED_PROVENANCE_FIELDS:
        if field not in provenance:
            raise _fail(f"missing required provenance field: {field}")
    _require_array("provenance.artifacts", provenance["artifacts"])
    _require_array("provenance.limitations", provenance["limitations"])
    for index, entry in enumerate(provenance["artifacts"]):
        if not isinstance(entry, dict):
            raise _fail(f"provenance.artifacts[{index}] must be an object")
    for index, entry in enumerate(provenance["limitations"]):
        if not isinstance(entry, str):
            raise _fail(f"provenance.limitations[{index}] must be a string")
    git = provenance.get("git")
    if git is not None and not isinstance(git, dict):
        raise _fail("provenance.git must be an object or null")
    return obj


def serialize_return(obj: dict[str, Any]) -> bytes:
    """Validate then serialize one return to exact final bytes.

    Emits deterministic JSON (``sort_keys=True``, compact separators,
    ``allow_nan=False``) plus a single trailing LF to match the
    newline-delimited transport (``don-squad-control.mjs`` send/result).
    The exact emitted bytes are re-parsed with the real JSON parser and
    re-validated (array types + envelope fields). Any mismatch or
    malformed pseudo-JSON fails closed.
    """
    validate_return(obj)
    try:
        text = json.dumps(
            obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise _fail(f"JSON serialization rejected: {exc}") from exc
    data = (text + "\n").encode("utf-8")
    # Validate the exact final bytes with a real parser (fail closed).
    validate_return_bytes(data)
    return data


def validate_return_bytes(data: bytes | bytearray) -> dict[str, Any]:
    """Parse exact final bytes with the real JSON parser and validate."""
    if not isinstance(data, (bytes, bytearray)):
        raise _fail(f"final bytes must be bytes, got {type(data).__name__}")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail(f"final bytes are not UTF-8: {exc}") from exc
    if not text.strip():
        raise _fail("final bytes are empty/whitespace-only")
    try:
        # Real parser: rejects single quotes, trailing commas, comments,
        # duplicate-key-tolerant pseudo-JSON is handled strictly below by
        # re-serialization round-trip; json.loads rejects non-finite
        # numbers only if allow_nan is False.
        parsed = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise _fail(f"final bytes are not valid JSON: {exc}") from exc
    validated = validate_return(parsed)
    # Round-trip check: parsed value must re-serialize to identical
    # canonical bytes, proving no pseudo-JSON or array-mangling survived.
    canonical = (
        json.dumps(
            validated, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if canonical != bytes(data) and canonical.rstrip(b"\n") != bytes(data).rstrip(b"\n"):
        # Canonical form differs only by insignificant whitespace/key order
        # is already normalized; a mismatch here means the emitted bytes
        # were not the validated canonical form. Fail closed.
        raise _fail("final bytes are not canonical agent-io/v1 JSON")
    return validated


def _reject_constant(value: str) -> Any:
    raise _fail(f"non-finite JSON number: {value}")


if __name__ == "__main__":  # pragma: no cover - manual CLI check
    import pathlib
    import sys

    if len(sys.argv) != 2:
        print("usage: agent_io.py <return.json>", flush=True)
        raise SystemExit(2)
    raw = pathlib.Path(sys.argv[1]).read_bytes()
    validate_return_bytes(raw)
    print("agent-io/v1 return bytes valid", flush=True)
