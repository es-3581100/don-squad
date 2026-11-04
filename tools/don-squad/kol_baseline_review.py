#!/usr/bin/env python3
"""Bounded evidence operations and fixed offline checks for one KoL baseline.

No arbitrary commands, alternative project roots, source edits, or application
launch. --describe is read-only. --check creates fresh scratch and command
evidence; it never constitutes an independent safety verdict by itself.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import signal
import stat
import subprocess
import sys
from typing import Any
from zipfile import ZipFile


PROJECT = Path("/home/sticky-ricky/repos/donCannoli-burns/don_kolmafia/Mafia-Builds/kolmafia-go")
MODULE_REL = Path("dev/kol-workbench-v0.1")
CHECKPOINT = "kolmafia-go-isolated-baseline-resume-checkpoint.json"
CHECKPOINT_SHA = "d7e320e88a5f6edca49822c244ab40ef399ee10ff870df1aa51a750d12442712"
STARTER_SHA = "5be5c49b32c17b020ed14b5bf34a747652421e3ad0877c9052e9213410c6564a"
RECORDS = Path(".opencode/recorded/kol-workbench-20261101")
DOCS = Path("docs/isolated-baseline/evidence")
CONFIG = Path(__file__).resolve().parents[2]
EXTERNAL_INPUTS = frozenset(Path(p) for p in (
    "/tmp/opencode/kol-resume-go-return-v2.json",
    "/tmp/opencode/kol-recovery-recon-capture.json",
    "/tmp/opencode/kol-resume-verification-capture.json",
    "/tmp/opencode/kolmafia-go-audit-20261101/audit-report.json",
    "/tmp/opencode/kolmafia-go-audit-20261101/archive-admission-reviewed.json",
    "/tmp/opencode/kolmafia-go-audit-20261101/staged-files.json",
    str(CONFIG / "agents/verifier.md"),
    str(CONFIG / "agents/project-planner-hygiene.md"),
    str(CONFIG / "tools/don-squad/integrity.json"),
    str(CONFIG / "tools/don-squad/kol_baseline_review.py"),
    str(CONFIG / "policies/structured-agent-io.md"),
))
EXPECTED_SOURCE = {
    "README.md": "31adccfdabedd39af5ae74d79830b3e455720be717d1691825ae2f80e45054a9",
    "build.sh": "68973177602f481b852f98ed9a1fdb1c86017ef7c7114ca1e6460339b7d79c38",
    "cmd/workbench/main.go": "ba86ef9e380744749a09d63bb018f223641cf2d0bac248b86cf73155aa28f19d",
    "internal/host/api.go": "0ca8f561627cfdff402f4a956be629964f1f85a291a5bc578ae4cb8769da6e0a",
    "internal/host/status.go": "6a1ebb514dcb8b2612a8ef3c10eadc66240a516f820e77123de63b0af8bf2f76",
    "internal/host/status_test.go": "0aa12bdb33c555020a01b9e6c3d7235852586ee42eab7b8025f257246bb07bea",
    "go.mod": "179a4677026bc67d1768a409c450ee732e4dc507a9671b814cd1ae192dbfbc35",
    "go.sum": "c568613576a899ea396068a9e511fc8ff03256b03c14083b923e471f6a145be0",
    "web/style.css": "1cb8d6c1dc4ad19f29a70af0f96b6b4006b1f570e6231e3f4488b85927def5b6",
}
CHECKS = ("host-tests", "native", "wasm", "vet", "format")
MAX_EVIDENCE = 5 * 1024 * 1024


class ReviewError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ReviewError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ReviewError("non-finite JSON number")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


@contextmanager
def directory(path: Path, create: bool = False):
    """Descriptor-relative traversal rejects symlinked ancestors and '..'."""
    if not path.is_absolute() or ".." in path.parts:
        raise ReviewError("absolute canonical paths required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def regular_file(path: Path):
    with directory(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ReviewError("regular files required")
        yield stream


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with regular_file(path) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_evidence(path: Path) -> bytes:
    with regular_file(path) as stream:
        data = stream.read(MAX_EVIDENCE + 1)
    if len(data) > MAX_EVIDENCE:
        raise ReviewError("evidence size limit exceeded")
    return data


def input_path(raw: str, project: Path = PROJECT) -> Path:
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise ReviewError("absolute canonical input required")
    if not path.is_relative_to(project) and path not in EXTERNAL_INPUTS:
        raise ReviewError("input outside approved project/evidence set")
    if any(part in (".sessions", ".receipt_secret", "session.json") for part in path.parts):
        raise ReviewError("private session/secret input excluded")
    return path


def exclusive_write(path: Path, data: bytes) -> None:
    with directory(path.parent, create=True) as parent:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)


def preserve(raw: str, name: str, project: Path = PROJECT) -> dict[str, str]:
    if not name or PurePosixPath(name).name != name or name in (".", "..") or "\\" in name:
        raise ReviewError("destination must be one evidence filename")
    if Path(name).suffix not in (".json", ".md", ".txt"):
        raise ReviewError("only JSON/Markdown/text evidence may be preserved")
    with directory(project):
        pass
    source = input_path(raw, project)
    data = read_evidence(source)
    data.decode("utf-8")
    if source.suffix == ".json":
        strict_json(data)
    target = project / DOCS / name
    exclusive_write(target, data)
    return {"source": str(source), "destination": str(target), "sha256": digest(data)}


def source_snapshot(project: Path, expected: dict[str, str] = EXPECTED_SOURCE) -> dict[str, str]:
    module = project / MODULE_REL
    with directory(module):
        pass
    observed = {}
    for base, dirs, files in os.walk(module, followlinks=False):
        base_path = Path(base)
        if base_path == module:
            dirs[:] = [d for d in dirs if d not in (".baseline-isolated", ".baseline-resume-c181c24d")]
        for child in dirs:
            if (base_path / child).is_symlink():
                raise ReviewError("symlink in source tree")
        for name in files:
            path = base_path / name
            relative = path.relative_to(module).as_posix()
            if relative not in expected:
                raise ReviewError("unreviewed source-tree file")
            observed[relative] = file_digest(path)
    if observed != expected:
        raise ReviewError("source does not match the frozen baseline; re-review required")
    return observed


def check_inputs(project: Path, expected: dict[str, str] = EXPECTED_SOURCE, checkpoint_sha: str = CHECKPOINT_SHA):
    if file_digest(project / CHECKPOINT) != checkpoint_sha:
        raise ReviewError("baseline checkpoint identity mismatch")
    proxy = project / MODULE_REL / ".baseline-isolated/modcache/cache/download"
    with directory(proxy):
        pass
    return source_snapshot(project, expected), proxy


def command(check: str, scratch: Path) -> tuple[list[str], Path | None]:
    go = "/usr/bin/go"
    if check == "host-tests":
        return [go, "test", "-p=1", "-mod=readonly", "-count=1", "-timeout=30s", "-v", "./internal/host"], None
    if check in ("native", "wasm"):
        output = scratch / "out" / ("workbench-native" if check == "native" else "workbench.wasm")
        return [go, "build", "-p=1", "-mod=readonly", "-o", str(output), "./cmd/workbench"], output
    if check == "vet":
        return [go, "vet", "-p=1", "-mod=readonly", "./..."], None
    if check == "format":
        return ["/usr/bin/gofmt", "-l", "cmd/workbench/main.go", "internal/host/api.go", "internal/host/status.go", "internal/host/status_test.go"], None
    raise ReviewError("unsupported check")


def environment(scratch: Path, proxy: Path, check: str) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(scratch / "home"),
        "TMPDIR": str(scratch / "tmp"), "GOTMPDIR": str(scratch / "tmp"),
        "GOPATH": str(scratch / "gopath"), "GOMODCACHE": str(scratch / "modcache"),
        "GOCACHE": str(scratch / "gocache"), "GOENV": "off", "GOWORK": "off",
        "GOTOOLCHAIN": "local", "CGO_ENABLED": "0", "GOMAXPROCS": "2",
        "GOPROXY": proxy.as_uri(), "GOSUMDB": "off", "GOPRIVATE": "",
        "GONOPROXY": "", "GONOSUMDB": "", "GOFLAGS": "",
        "DOCKER_CONFIG": str(scratch / "docker-empty"),
        "DOCKER_HOST": "unix://" + str(scratch / "no-daemon.sock"),
        "LANG": "C.UTF-8", "TZ": "UTC",
    }
    if check == "wasm":
        env.update(GOOS="js", GOARCH="wasm")
    return env


def run_process(argv: list[str], cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    with subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True) as child:
        timed_out = False
        try:
            stdout, stderr = child.communicate(timeout=240)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGKILL)
            stdout, stderr = child.communicate()
        if len(stdout) + len(stderr) > MAX_EVIDENCE:
            raise ReviewError("command output exceeded acceptance limit")
        return {"exit_code": child.returncode, "timed_out": timed_out,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace")}


def execute_check(check: str, project: Path = PROJECT, runner=run_process,
                  expected: dict[str, str] = EXPECTED_SOURCE, checkpoint_sha: str = CHECKPOINT_SHA):
    # Validate the operation and frozen inputs before creating any outputs.
    command(check, Path("/unused"))
    before, proxy = check_inputs(project, expected, checkpoint_sha)
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(8)
    scratch = project / ".workbench-verify" / token
    with directory(scratch.parent, create=True) as parent:
        os.mkdir(scratch.name, 0o700, dir_fd=parent)
    for leaf in ("home", "tmp", "gopath", "modcache", "gocache", "docker-empty", "out"):
        with directory(scratch / leaf, create=True):
            pass
    argv, output = command(check, scratch)
    env = environment(scratch, proxy, check)
    version = runner(["/usr/bin/go", "version"], project / MODULE_REL, env)
    if version["exit_code"] or version["timed_out"] or not version["stdout"].startswith("go version go"):
        raise ReviewError("local Go toolchain identity unavailable")
    result = runner(argv, project / MODULE_REL, env)
    try:
        after = source_snapshot(project, expected)
        stable = after == before
    except (ReviewError, OSError):
        after, stable = None, False
    ok = result["exit_code"] == 0 and not result["timed_out"] and stable
    if check == "format" and result["stdout"].strip():
        ok = False
    artifacts = []
    if output is not None:
        if output.exists():
            artifacts.append({"path": str(output), "sha256": file_digest(output), "executed": False})
        else:
            ok = False
    report = {
        "schema_version": "don-squad.kol-baseline-check/v1", "kind": "command_evidence",
        "status": "PASS" if ok else "FAIL", "check": check,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project), "cwd": str(project / MODULE_REL),
        "argv": argv, "environment": env, "scratch": str(scratch),
        "go_version": version["stdout"].strip(),
        "runner_sha256": file_digest(Path(__file__).resolve()),
        "checkpoint_sha256": checkpoint_sha,
        "source_before": before, "source_after": after, "source_unchanged": stable,
        "result": result, "outputs": artifacts,
        "independent_safety_verdict": None,
        "limitations": [
            "Execution evidence only; the verifier must independently inspect source, tests, and safety boundaries.",
            "Only host tests may execute. Full application tests and generated applications are not run.",
            "Offline file proxy and frozen go.sum; dependency admission history is not audited by this helper.",
            "Sanitized environment and source checks are not an OS filesystem/process sandbox.",
        ],
    }
    path = project / RECORDS / "verification" / f"check-{check}-{token}.json"
    report["report_path"] = str(path)
    data = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    exclusive_write(path, data)
    return {"status": report["status"], "report_path": str(path), "sha256": digest(data)}


def archive_member(member: str, project: Path = PROJECT) -> dict[str, str]:
    relative = PurePosixPath(member)
    if relative.is_absolute() or ".." in relative.parts or "\\" in member:
        raise ReviewError("invalid archive member")
    archive = project / "kol-workbench-v0.1.zip"
    # Hash and inspect the same open descriptor.
    with regular_file(archive) as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != STARTER_SHA:
            raise ReviewError("starter archive identity mismatch")
        stream.seek(0)
        with ZipFile(stream) as source:
            info = source.getinfo(member)
            if info.file_size > MAX_EVIDENCE or info.is_dir():
                raise ReviewError("archive member is not bounded file evidence")
            data = source.read(info)
    return {"member": member, "sha256": digest(data), "text": data.decode("utf-8")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--hash", nargs="+")
    action.add_argument("--read")
    action.add_argument("--validate-json")
    action.add_argument("--archive-member")
    action.add_argument("--preserve", nargs=2, metavar=("SOURCE", "FILENAME"))
    action.add_argument("--describe", action="store_true")
    action.add_argument("--check", choices=CHECKS)
    args = parser.parse_args(argv)
    try:
        if args.hash:
            result = {"artifacts": [{"path": str(input_path(p)), "sha256": file_digest(input_path(p))} for p in args.hash]}
        elif args.read:
            path = input_path(args.read)
            data = read_evidence(path)
            result = {"path": str(path), "sha256": digest(data), "text": data.decode("utf-8")}
        elif args.validate_json:
            path = input_path(args.validate_json)
            data = read_evidence(path)
            value = strict_json(data)
            result = {"status": "VALID_JSON", "path": str(path), "sha256": digest(data), "json_type": type(value).__name__}
        elif args.archive_member:
            result = archive_member(args.archive_member)
        elif args.preserve:
            result = preserve(*args.preserve)
        elif args.describe:
            sources, _ = check_inputs(PROJECT)
            result = {"status": "READY_FOR_REVIEW", "project_root": str(PROJECT), "source_manifest": sources,
                      "checks": {c: command(c, PROJECT / ".workbench-verify/FRESH_RUN")[0] for c in CHECKS},
                      "note": "Read-only description; no scratch, commands, tests, or safety verdict created."}
        else:
            result = execute_check(args.check)
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get("status") == "FAIL" else 0
    except (ReviewError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
