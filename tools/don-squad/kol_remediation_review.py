#!/usr/bin/env python3
"""Separate, admission-bound verifier for the exact KoL remediation v2 plan.

--inventory and --describe are read-only. Execution requires an independently
reviewed exact-byte admission in the approved verification directory. The old
baseline helper is imported only for unchanged file/path primitives and fixed
argv/environment builders; its frozen-source execution path is never called.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import subprocess
import sys
import time
from typing import Any


sys.dont_write_bytecode = True
BASE_HELPER = Path(__file__).with_name("kol_baseline_review.py")
BASE_HELPER_SHA = "96213458dd464b153a1e52d9862c1d914c1125464daf9623bf9e9b20d09c3797"
if hashlib.sha256(BASE_HELPER.read_bytes()).hexdigest() != BASE_HELPER_SHA:
    raise SystemExit("BLOCKED: historical helper identity mismatch")
spec = importlib.util.spec_from_file_location("kol_frozen_primitives", BASE_HELPER)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

PROJECT = base.PROJECT
PLAN_REL = base.RECORDS / "audit-remediation-plan-v2-b0f51daa.md"
PLAN_SHA = "8e87cb0aa26836214426025cf0fd38b72de81d1a9e42c1632079dc30a1bae587"
VERIFY_REL = base.RECORDS / "verification"
CHECKS = base.CHECKS
MUTABLE = frozenset(("README.md", "cmd/workbench/main.go", "internal/host/api.go", "internal/host/status_test.go"))
OPTIONAL = frozenset(("internal/host/api_test.go",))
REQUIRED = frozenset(base.EXPECTED_SOURCE)
PINNED = {name: sha for name, sha in base.EXPECTED_SOURCE.items() if name not in MUTABLE}
MAX_SOURCE_BYTES = 2 * 1024 * 1024
OUTPUT_LIMIT = 512 * 1024
COMMAND_TIMEOUT = 240
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
REVIEW_FIELDS = (
    "plan_approved", "source_and_tests_reviewed", "selected_execution_chain_reviewed",
    "no_listeners_live_calls_or_application_start", "scratch_only_test_filesystem",
)
ReviewError = base.ReviewError


def verified_plan(project: Path) -> dict[str, str]:
    path = project / PLAN_REL
    if base.file_digest(path) != PLAN_SHA:
        raise ReviewError("remediation plan identity mismatch")
    return {"path": str(path), "sha256": PLAN_SHA}


def inventory(project: Path) -> dict[str, str]:
    module = project / base.MODULE_REL
    with base.directory(module):
        pass
    result = {}
    total = 0
    allowed = REQUIRED | OPTIONAL
    for root, dirs, files in os.walk(module, followlinks=False):
        parent = Path(root)
        if parent == module:
            dirs[:] = [d for d in dirs if d not in (".baseline-isolated", ".baseline-resume-c181c24d")]
        for child in dirs:
            if (parent / child).is_symlink():
                raise ReviewError("symlinked source directory")
        for name in files:
            path = parent / name
            relative = path.relative_to(module).as_posix()
            if relative not in allowed:
                raise ReviewError("unapproved build/source input: " + relative)
            with base.regular_file(path) as stream:
                info = os.fstat(stream.fileno())
                if info.st_nlink != 1:
                    raise ReviewError("hard-linked source file")
                data = stream.read(MAX_SOURCE_BYTES + 1)
            total += len(data)
            if total > MAX_SOURCE_BYTES:
                raise ReviewError("source inventory size limit exceeded")
            result[relative] = base.digest(data)
    if not REQUIRED.issubset(result):
        raise ReviewError("required source input missing")
    if any(result[name] != sha for name, sha in PINNED.items()):
        raise ReviewError("pinned module/dependency/build/collector/assets input changed")
    return dict(sorted(result.items()))


def admitted(path: Path, expected_sha: str, check: str, project: Path) -> tuple[dict, dict[str, str]]:
    verified_plan(project)
    if check not in CHECKS or not SHA_RE.fullmatch(expected_sha):
        raise ReviewError("invalid check or admission SHA-256")
    if path.parent != project / VERIFY_REL or not path.name.endswith(".json"):
        raise ReviewError("admission must be a direct JSON leaf in the verification directory")
    raw = base.read_evidence(path)
    if base.digest(raw) != expected_sha:
        raise ReviewError("admission exact-byte identity mismatch")
    obj = base.strict_json(raw)
    if not isinstance(obj, dict):
        raise ReviewError("admission must be an object")
    if obj.get("schema_version") != "don-squad.kol-remediation-admission/v1" or obj.get("reviewer") != "verifier":
        raise ReviewError("wrong admission contract/reviewer")
    if obj.get("project_root") != str(project) or obj.get("plan") != verified_plan(project):
        raise ReviewError("admission project/plan binding mismatch")
    if any(not isinstance(obj.get(k), str) or not obj[k].strip() for k in ("task_id", "attempt_id")):
        raise ReviewError("admission requires task/attempt identity")
    review = obj.get("review")
    if not isinstance(review, dict) or any(review.get(k) is not True for k in REVIEW_FIELDS):
        raise ReviewError("independent plan/source/execution review assertions required")
    checks = obj.get("approved_checks")
    if not isinstance(checks, list) or any(c not in CHECKS for c in checks) or len(checks) != len(set(checks)) or check not in checks:
        raise ReviewError("check is not admitted")
    source = obj.get("source_manifest")
    current = inventory(project)
    if source != current:
        raise ReviewError("admitted source differs from current exact build inputs")
    if not isinstance(obj.get("limitations"), list) or not all(isinstance(v, str) for v in obj["limitations"]):
        raise ReviewError("admission limitations must be an array of strings")
    return obj, current


def bounded_process(argv: list[str], cwd: Path, env: dict[str, str], *, timeout=COMMAND_TIMEOUT, output_limit=OUTPUT_LIMIT):
    """Bound memory while reading both pipes; terminate the whole group on limits.

    No shell is used. Runtime limits bound subprocess lifetime and captured
    output, not arbitrary filesystem/network access by the reviewed code.
    """
    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + timeout
    output = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = overflow = False
    with subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True) as child:
        def kill_group():
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            try:
                while selector.get_map():
                    left = deadline - time.monotonic()
                    if left <= 0:
                        timed_out = True
                        break
                    for key, _ in selector.select(min(left, 0.1)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        remaining = output_limit - sum(len(v) for v in output.values())
                        output[key.data].extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            overflow = True
                            break
                    if overflow:
                        break
                if timed_out or overflow:
                    kill_group()
                try:
                    child.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    kill_group()
                    child.wait(timeout=5)
            except BaseException:
                kill_group()
                child.wait(timeout=5)
                raise
            finally:
                # Reap/terminate descendants even if the parent exited and closed its pipes.
                kill_group()
        return {
            "exit_code": child.returncode, "timed_out": timed_out, "output_limit_exceeded": overflow,
            "stdout": bytes(output["stdout"]).decode("utf-8", errors="replace"),
            "stderr": bytes(output["stderr"]).decode("utf-8", errors="replace"),
            "captured_bytes": sum(len(v) for v in output.values()),
            "output_limit_bytes": output_limit, "timeout_seconds": timeout,
            "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        }


def argv_for(check: str, scratch: Path, source: dict[str, str]):
    if check == "format":
        return ["/usr/bin/gofmt", "-l", *sorted(n for n in source if n.endswith(".go"))], None
    return base.command(check, scratch)


def run_check(check: str, admission: Path, admission_sha: str, project=PROJECT, runner=bounded_process):
    _, before = admitted(admission, admission_sha, check, project)
    plan_binding = verified_plan(project)
    proxy = project / base.MODULE_REL / ".baseline-isolated/modcache/cache/download"
    with base.directory(proxy):
        pass
    token = "audit-b0f51daa-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(8)
    scratch = project / ".workbench-verify" / token
    with base.directory(scratch.parent, create=True) as parent:
        os.mkdir(scratch.name, 0o700, dir_fd=parent)
    for name in ("home", "tmp", "gopath", "modcache", "gocache", "docker-empty", "out"):
        with base.directory(scratch / name, create=True):
            pass
    env = base.environment(scratch, proxy, check)
    argv, output_path = argv_for(check, scratch, before)
    identity = []
    for executable in dict.fromkeys(("/usr/bin/go", argv[0])):
        resolved = Path(executable).resolve(strict=True)
        identity.append({"path": executable, "resolved": str(resolved), "sha256": base.file_digest(resolved)})
    version = runner(["/usr/bin/go", "version"], project / base.MODULE_REL, env)
    version_ok = (version["exit_code"] == 0 and not version["timed_out"]
                  and not version["output_limit_exceeded"] and version["stdout"].startswith("go version go"))
    result = runner(argv, project / base.MODULE_REL, env) if version_ok else None
    after = None
    stable = False
    try:
        _, after = admitted(admission, admission_sha, check, project)
        stable = after == before and all(
            Path(i["path"]).resolve(strict=True) == Path(i["resolved"])
            and base.file_digest(Path(i["resolved"])) == i["sha256"] for i in identity
        )
    except (OSError, ValueError, ReviewError):
        pass
    ok = (version_ok and result is not None and result["exit_code"] == 0
          and not result["timed_out"] and not result["output_limit_exceeded"] and stable)
    if check == "format" and result is not None and result["stdout"].strip():
        ok = False
    outputs = []
    if output_path is not None and result is not None:
        try:
            outputs.append({"path": str(output_path), "sha256": base.file_digest(output_path), "executed": False})
        except OSError:
            ok = False
    report = {
        "schema_version": "don-squad.kol-remediation-check/v1", "kind": "command_evidence",
        "status": "PASS" if ok else "FAIL", "check": check, "project_root": str(project),
        "plan": plan_binding, "admission": {"path": str(admission), "sha256": admission_sha},
        "runner_sha256": base.file_digest(Path(__file__).resolve()), "baseline_helper_sha256": BASE_HELPER_SHA,
        "cwd": str(project / base.MODULE_REL), "argv": argv, "environment": env, "scratch": str(scratch),
        "executables": identity, "toolchain_probe": version, "result": result,
        "source_before": before, "source_after": after, "source_and_admission_stable": stable,
        "outputs": outputs, "independent_safety_verdict": None,
        "limitations": [
            "Admission records are verifier-authored evidence, not cryptographic identity or human authority by themselves.",
            "No generated application or full application tests executed; only admitted host tests may run.",
            "Existing offline proxy/checksums are reused; dependency/toolchain admission history remains unaudited.",
            "Output/time/process-group limits and source hashes are not an OS filesystem/network sandbox.",
            "A PASS is command evidence, not plan approval, implementation acceptance, runtime or deployment clearance.",
        ],
    }
    path = project / VERIFY_REL / f"remediation-{check}-{token}.json"
    report["report_path"] = str(path)
    raw = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    base.exclusive_write(path, raw)
    return {"status": report["status"], "report_path": str(path), "sha256": base.digest(raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inventory", action="store_true")
    action.add_argument("--describe", action="store_true")
    action.add_argument("--check", choices=CHECKS)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--admission-sha256")
    args = parser.parse_args(argv)
    try:
        if args.check:
            if args.admission is None or args.admission_sha256 is None:
                raise ReviewError("both --admission and --admission-sha256 are required")
            result = run_check(args.check, args.admission, args.admission_sha256)
        else:
            if args.admission is not None or args.admission_sha256 is not None:
                raise ReviewError("admission arguments apply only to --check")
            plan = verified_plan(PROJECT)
            source = inventory(PROJECT)
            result = {"status": "READ_ONLY", "project_root": str(PROJECT), "plan": plan,
                      "source_manifest": source, "pinned_inputs": PINNED,
                      "admission_schema": "don-squad.kol-remediation-admission/v1",
                      "required_review_assertions": REVIEW_FIELDS,
                      "note": "No commands or admission executed/created. Independent review is required."}
            if args.describe:
                result["commands"] = {c: argv_for(c, PROJECT / ".workbench-verify/FRESH_RUN", source)[0] for c in CHECKS}
        print(json.dumps(result, sort_keys=True))
        return 1 if result["status"] == "FAIL" else 0
    except (OSError, ValueError, KeyError, TypeError, ReviewError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
