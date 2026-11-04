#!/usr/bin/env python3
"""DonSquad live final-emission binding (producer-side, fail-closed).

Developer note EXECUTION_PATH_BINDING (Wave 1 minimal repair
live-path-repair-001, fallback B):
- The canonical validated artifact file written by :func:`emit_return`
  (``serialize_return`` -> ``validate_return_bytes`` -> exact bytes
  written to the artifact file, SHA-256 over those exact bytes) is the
  authoritative machine return. Only these artifact bytes may be
  published/consumed as the bound machine return.
- Live chat/transcript prose (LLM Phase 5 single return via transcript
  plus ``don-squad-control.mjs`` 9-10 ``JSON.stringify(o)+'\\n'``
  passthrough) is a non-canonical, unvalidated transcript sink. It is
  never the bound machine return, carries no byte-bound claim, and
  transcript text alone cannot produce a bound claim. No byte-bound
  property of the live transcript is claimed here: the transcript
  cannot be machine-intercepted, so the last machine byte proof is the
  artifact LF.
- Bypass paths closed or documented with enforcement
  (``load_bound_return``/``verify_bound_artifact`` below):
  (1) publishing transcript/chat text without an ``emit_return``
  artifact -> unbound (no artifact file; binding requires exact
  artifact bytes on disk plus ``validate_return_bytes`` plus matching
  SHA-256); (2) hand-copied/manual-transcription excerpts,
  ``JSON.stringify`` passthrough bytes, or surrogate-only proofs
  presented as transcript text -> unbound (never validated canonical
  artifact bytes; non-canonical bytes fail ``validate_return_bytes``
  closed); (3) tampered artifact bytes -> ``validate_return_bytes``
  fails closed and SHA-256 mismatch blocks acceptance.

Live-emission finding (live-emission-inspect-001):
- Effective live final path is LLM Phase 5 single return via transcript
  (``don-squad.md`` 151-153) plus ``don-squad-control.mjs`` 9-10
  ``JSON.stringify(o)+'\\n'`` passthrough. Neither calls
  ``agent_io.serialize_return`` / ``validate_return_bytes`` (zero callers).
- This module is the smallest programmatic binding for the artifact
  path: callers build a return mapping, call :func:`emit_return`, and
  publish/consume exactly the returned artifact bytes alongside their
  SHA-256. Any violation raises, never emits. Chat prose rendered next
  to those bytes stays non-canonical.

Portfolio transport specimen semantics unchanged. Squawk Box
lifecycle/reducer/schema, migration semantics, and portfolio paths are
untouched. ``agent_io.py`` is reused unchanged (``serialize_return``
plus ``validate_return_bytes`` only).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_io import serialize_return, validate_return_bytes

# EXECUTION_PATH_BINDING: only artifact bytes produced by emit_return
# are the authoritative machine return. Transcript/chat prose sinks are
# non-canonical and can never satisfy this binding.
EXECUTION_PATH_BINDING = "EXECUTION_PATH_BINDING"
CANONICAL_PRODUCER = "emit_final_return.emit_return"
NON_CANONICAL_SINKS = (
    "phase5-transcript",
    "don-squad-control.mjs-passthrough",
    "chat-prose",
)

# Phase 5 chat template (non-canonical, never the machine return; see
# don-squad.md Phase 5 chat form). Chat sink stays non-canonical.
CHAT_TEMPLATE = "Done — canonical return at {path} SHA-256 {sha256} status {status}. Chat is non-canonical; authoritative machine return is the artifact bytes only."
def format_chat_prose(path, sha256_hex, status):
    """Render non-canonical Phase 5 chat prose (never JSON, never canonical)."""
    text = CHAT_TEMPLATE.format(path=str(path), sha256=sha256_hex, status=status)
    assert not text.lstrip().startswith("{")
    assert "schema_version" not in text and "agent-io/v1" not in text
    return text


def load_bound_return(path: str | Path) -> tuple[dict, bytes, str]:
    """Load the bound machine return from its canonical artifact file.

    Reads exact artifact bytes from ``path``, validates them with
    ``validate_return_bytes`` (real JSON parser + envelope/array checks),
    and returns ``(obj, data, sha256_hex)``. Raw transcript/chat text
    has no artifact file and therefore cannot produce a bound claim
    through this function: missing, unvalidated, or tampered bytes
    raise instead of binding.
    """
    raw = Path(path).read_bytes()
    obj = validate_return_bytes(raw)
    return obj, raw, hashlib.sha256(raw).hexdigest()


def verify_bound_artifact(path: str | Path, expected_sha256: str | None = None) -> dict:
    """Verify a canonical artifact file carries the bound machine return.

    Fails closed (raises) when the file is missing, the bytes are not
    canonical agent-io/v1 JSON, or the SHA-256 does not match
    ``expected_sha256``. Transcript-only content presented without an
    ``emit_return`` artifact fails here: either the file does not exist
    or its bytes/SHA do not match the bound artifact.
    """
    obj, raw, digest = load_bound_return(path)
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise ValueError(
            "agent-io/v1 emission blocked: artifact SHA-256 mismatch "
            f"(expected {expected_sha256.lower()}, observed {digest})"
        )
    return obj


def emit_return(obj: dict, out_path: str | Path) -> bytes:
    """Validate+serialize one return and write exact bytes to out_path."""
    data = serialize_return(obj)
    validated = validate_return_bytes(data)
    assert validated["task_id"] == obj["task_id"]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    reread = out.read_bytes()
    if reread != data:
        raise ValueError("agent-io/v1 emission blocked: artifact reread mismatch")
    validate_return_bytes(reread)
    return data


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: emit_final_return.py <input-return.json> <output-return.json>", flush=True)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    raw = src.read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    data = emit_return(obj, dst)
    print(f"emitted {dst} bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
