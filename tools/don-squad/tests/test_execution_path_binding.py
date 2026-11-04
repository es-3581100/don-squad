"""Negative bypass test: raw transcript cannot produce a bound claim.

EXECUTION_PATH_BINDING (live-path-repair-001, fallback B): the canonical
validated artifact file written by ``emit_final_return.emit_return`` is
the authoritative machine return; live chat/transcript prose is a
non-canonical, unvalidated sink. This test exercises the integration
boundary (artifact file + ``load_bound_return``/``verify_bound_artifact``
+ SHA-256 + real-parser validation), not the serializer alone: a raw
transcript that bypasses ``emit_return`` must fail to yield a bound
claim, while the ``emit_return`` artifact binds.

Portfolio transport specimen semantics unchanged; Squawk Box untouched.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from emit_final_return import (  # noqa: E402
    NON_CANONICAL_SINKS,
    emit_return,
    load_bound_return,
    verify_bound_artifact,
)
from agent_io import validate_return_bytes  # noqa: E402


def _specimen_envelope() -> dict:
    # Same specimen shape as test_live_emission_bind.py (transport
    # specimen semantics unchanged); insertion order differs from sorted
    # canonical order, mimicking transcript/JSON.stringify passthrough.
    return {
        "schema_version": "agent-io/v1",
        "kind": "return",
        "task_id": "execution-path-bind-001-regression",
        "sender": "python",
        "recipient": "don-squad",
        "status": "completed",
        "reason": "negative bypass regression for execution path binding",
        "evidence": [{"note": "e1"}, {"note": "e2"}],
        "next_owner": None,
        "verification": [
            {"command": "regression emit_return", "cwd": "/tmp", "exit_code": 0, "result": "bytes match"},
            {"command": "regression validate_return_bytes", "cwd": "/tmp", "exit_code": 0, "result": "reparse ok"},
        ],
        "provenance": {
            "artifacts": [{"path": "a", "phase": "after", "algorithm": "sha256", "digest": None, "verification": "unavailable", "reason": "regression placeholder"}],
            "git": None,
            "limitations": ["regression only", "no live transport interception"],
        },
    }


def test_transcript_bypass_cannot_claim_bound(tmp_path=None) -> None:
    outdir = Path(tempfile.mkdtemp(prefix="exec-path-bind-")) if tmp_path is None else Path(tmp_path)
    obj = _specimen_envelope()

    # Bound path: canonical artifact via emit_return (integration boundary).
    bound_path = outdir / "bound-return.json"
    bound_bytes = emit_return(obj, bound_path)
    bound_sha = hashlib.sha256(bound_bytes).hexdigest()
    bound_obj, raw, digest = load_bound_return(bound_path)
    assert raw == bound_bytes and digest == bound_sha
    assert verify_bound_artifact(bound_path, bound_sha)["task_id"] == obj["task_id"]
    # Canonical artifact parses with the real parser plus json.tool-equivalent
    # reparse, and carries all four repeated array fields.
    parsed = json.loads(bound_path.read_bytes().decode("utf-8"))
    assert isinstance(parsed["evidence"], list) and len(parsed["evidence"]) >= 2
    assert isinstance(parsed["verification"], list) and len(parsed["verification"]) >= 2
    assert isinstance(parsed["provenance"]["artifacts"], list)
    assert isinstance(parsed["provenance"]["limitations"], list) and len(parsed["provenance"]["limitations"]) >= 2
    assert "chat-prose" in NON_CANONICAL_SINKS  # prose sinks stay non-canonical

    # Bypass path 1: raw transcript bytes via JSON.stringify-style default
    # dumps (insertion order, non-compact separators), written WITHOUT
    # emit_return. Not canonical -> validate rejects at the boundary.
    transcript_bytes = (json.dumps(obj) + "\n").encode("utf-8")
    assert transcript_bytes != bound_bytes  # transcript is not artifact bytes
    with pytest.raises(ValueError):
        validate_return_bytes(transcript_bytes)
    transcript_path = outdir / "transcript-bypass.json"
    transcript_path.write_bytes(transcript_bytes)
    with pytest.raises(ValueError):
        load_bound_return(transcript_path)  # unvalidated transcript: no bind
    with pytest.raises(ValueError):
        verify_bound_artifact(transcript_path, bound_sha)  # SHA/context mismatch

    # Bypass path 2: prose-wrapped transcript (chat sink) is never bound.
    prose = b"Here is the return:\n" + transcript_bytes
    with pytest.raises(ValueError):
        validate_return_bytes(prose)

    # Bypass path 3: no transcript-only path exists -- a bound claim with no
    # artifact file is impossible.
    with pytest.raises((FileNotFoundError, OSError)):
        load_bound_return(outdir / "does-not-exist-transcript-only.json")


if __name__ == "__main__":
    test_transcript_bypass_cannot_claim_bound()
    print("execution-path-binding bypass regression PASS: transcript cannot bind", flush=True)
