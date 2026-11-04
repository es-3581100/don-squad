"""Regression: user-visible return bytes come from the live emission path.

Exercises the SAME path that produces the user-visible return:
``emit_final_return.emit_return`` (which internally runs
``serialize_return`` then ``validate_return_bytes`` then exact-byte write).
A direct ``serialize_return`` unit assertion alone would not satisfy
live-emission-bind-001; this test fails if the emission wrapper is
bypassed, if arrays are mangled, or if artifact bytes differ from
returned bytes.
"""
import json
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from emit_final_return import emit_return  # noqa: E402
from agent_io import validate_return_bytes  # noqa: E402


def _specimen_envelope() -> dict:
    return {
        "schema_version": "agent-io/v1",
        "kind": "return",
        "task_id": "live-emission-bind-001-regression",
        "sender": "python",
        "recipient": "don-squad",
        "status": "completed",
        "reason": "regression exercises live emission wrapper byte path",
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


def test_emit_return_is_validated_serializer_bytes(tmp_path: Path | None = None) -> None:
    outdir = Path(tempfile.mkdtemp(prefix="live-emit-regression-")) if tmp_path is None else tmp_path
    out = outdir / "regression-return.json"
    obj = _specimen_envelope()
    data = emit_return(obj, out)  # same live path as production emission
    exact = out.read_bytes()
    assert exact == data, "artifact bytes must equal user-visible return bytes"
    parsed = validate_return_bytes(exact)  # real parser on exact bytes
    assert isinstance(parsed["evidence"], list) and len(parsed["evidence"]) >= 2
    assert isinstance(parsed["verification"], list) and len(parsed["verification"]) >= 2
    assert isinstance(parsed["provenance"]["artifacts"], list) and len(parsed["provenance"]["artifacts"]) >= 1
    assert isinstance(parsed["provenance"]["limitations"], list) and len(parsed["provenance"]["limitations"]) >= 2
    assert json.loads(exact.decode("utf-8"))["task_id"] == "live-emission-bind-001-regression"


if __name__ == "__main__":
    test_emit_return_is_validated_serializer_bytes()
    print("live emission regression PASS: emit_return bytes validated", flush=True)
