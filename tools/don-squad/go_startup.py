#!/usr/bin/env python3
"""Native Don-Squad Go startup check; never executes project code.

Uses the installed OpenCode CLI to inspect the resolved Go/lead definitions.
Writes an exclusive project-local report, not a signed session receipt.
The standalone bundle's six agents, plugin, and receipt secret are not used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable


CONFIG_ROOT = Path(__file__).resolve().parents[2]
COMMAND_TIMEOUT = 45
OUTPUT_LIMIT = 2 * 1024 * 1024
HELPER_PIN = re.compile(r"^Startup helper SHA-256: `([0-9a-f]{64})`\.$", re.MULTILINE)
BASELINE_COMMANDS = (
    "sha256sum -- input.zip",
    "zipinfo -v input.zip",
    "unzip input.zip -d isolated",
    "mkdir isolated",
    "cp -n source destination",
    "bash -n build.sh",
    "gofmt -l source.go",
    "go version",
    "go env GOOS GOARCH",
    "go list -m -json all",
    "go mod download -json all",
    "go mod tidy",
    "go mod verify",
    "go test -mod=readonly ./...",
    "go vet -mod=readonly ./...",
    "go build -mod=readonly ./...",
    "GOOS=js GOARCH=wasm go build ./...",
    "/usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/go test -mod=readonly ./...",
    "/usr/bin/env -i PATH=/usr/bin:/bin GOOS=js GOARCH=wasm /usr/bin/go build ./...",
)


class StartupError(Exception):
    """A bounded check failed; messages must not include raw config/output."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value: str) -> Any:
        raise ValueError("non-finite JSON number")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def run_command(argv: list[str], root: Path) -> bytes:
    env = dict(os.environ, GOENV="off", GOTOOLCHAIN="local")
    try:
        result = subprocess.run(
            argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=COMMAND_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise StartupError("command timed out") from exc
    except OSError as exc:
        raise StartupError("command unavailable") from exc
    if result.returncode:
        raise StartupError(f"command exited {result.returncode}")
    if len(result.stdout) + len(result.stderr) > OUTPUT_LIMIT:
        raise StartupError("command output exceeded acceptance limit")
    return result.stdout


def wildcard_match(value: str, pattern: str) -> bool:
    # OpenCode patterns use * and ?; bracket characters remain literal.
    expression = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(expression, value, re.DOTALL) is not None


def permission(rules: list[dict[str, str]], tool: str, resource: str) -> str:
    result = "ask"
    for rule in rules:
        if wildcard_match(tool, rule["permission"]) and wildcard_match(resource, rule["pattern"]):
            result = rule["action"]
    return result


def resolved_rules(agent: Any, name: str) -> list[dict[str, str]]:
    if not isinstance(agent, dict) or agent.get("name") != name:
        raise StartupError("resolved agent identity mismatch")
    rules = agent.get("permission")
    if not isinstance(rules, list) or not rules:
        raise StartupError("resolved permission rules missing")
    for rule in rules:
        if not isinstance(rule, dict) or any(
            not isinstance(rule.get(key), str) for key in ("permission", "pattern", "action")
        ) or rule["action"] not in ("allow", "ask", "deny"):
            raise StartupError("resolved permission rule malformed")
    return rules


def planning_cpi(estimates: dict[str, Any]) -> dict[str, Any]:
    """Retain bundle planning weights without inventing session telemetry."""
    score = (
        min(6, estimates["expected_files"] // 3)
        + min(6, estimates["expected_tool_calls"] // 8)
        + min(4, estimates["external_sources"] // 3)
        + min(4, estimates["mutation_phases"])
        + (2 if estimates["risk"] == "high" else 0)
    )
    level = "short" if score <= 7 else "medium" if score <= 15 else "long"
    return {
        "coverage": "plan_only_lower_bound",
        "score": score,
        "planning_class": level,
        "inputs": dict(estimates, subagents=0),
        "recorded_context_requests": None,
        "elapsed_minutes": None,
        "action": "checkpoint_then_request_native_/compact_before_next_major_phase"
        if level == "long" else "checkpoint_before_next_major_phase",
        "limitation": "No session telemetry; this is not measured context-window usage.",
    }


def inspect_startup(
    root: Path,
    config_root: Path = CONFIG_ROOT,
    runner: Callable[[list[str], Path], bytes] = run_command,
    estimates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "don-squad.go-startup/v1",
        "kind": "startup_report",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(root),
        "agent": "go",
        "is_session_receipt": False,
        "checks": [],
        "artifacts": {},
        "limitations": [
            "Point-in-time native Go preflight, not a product build/test result.",
            "No session, provider, model, or HMAC identity is asserted.",
            "Other agents and the separate Don-Squad guard are outside this integrity check.",
            "Task authorization, B2/B3, and project runtime restrictions still apply.",
        ],
    }

    def check(name: str, ok: bool, detail: Any) -> None:
        report["checks"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    go_path = config_root / "agents/go.md"
    helper_path = config_root / "tools/don-squad/go_startup.py"
    manifest_path = config_root / "tools/don-squad/integrity.json"
    go_text = ""
    try:
        go_bytes = go_path.read_bytes()
        go_text = go_bytes.decode("utf-8")
        manifest_bytes = manifest_path.read_bytes()
        manifest = strict_json(manifest_bytes)
        expected = manifest["agents"]["go"]
        observed = sha256(go_bytes)
        report["artifacts"]["go_agent"] = {"path": str(go_path), "sha256": observed}
        report["artifacts"]["integrity_manifest"] = {"path": str(manifest_path), "sha256": sha256(manifest_bytes)}
        check("go_integrity", observed == expected, {"expected": expected, "observed": observed})
        pin = HELPER_PIN.search(go_text)
        helper_sha = sha256(helper_path.read_bytes())
        report["artifacts"]["startup_helper"] = {"path": str(helper_path), "sha256": helper_sha}
        check("helper_integrity", pin is not None and pin[1] == helper_sha, "helper must match the hash pinned in go.md")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check("configuration_artifacts", False, type(exc).__name__)

    for label, argv in (
        ("go_toolchain", ["go", "version"]),
        ("opencode_version", ["opencode", "--version"]),
    ):
        try:
            output = runner(argv, root).decode("utf-8").strip()
            ok = output.startswith("go version go") if label == "go_toolchain" else bool(re.fullmatch(r"\d+\.\d+\.\d+[^\s]*", output))
            check(label, ok, output if ok else "unexpected version output")
        except (StartupError, ValueError) as exc:
            check(label, False, str(exc))

    for name in ("go", "don-squad"):
        try:
            output = runner(["opencode", "debug", "agent", name], root)
            agent = strict_json(output)
            rules = resolved_rules(agent, name)
            report["artifacts"][f"resolved_{name}"] = {"sha256": sha256(output), "source": "native CLI stdout bytes"}
            if name == "go":
                check("go_role", agent.get("mode") == "subagent" and agent.get("hidden") is True, "hidden Go specialist")
                _, separator, body = go_text.partition("\n---\n")
                check("loaded_go_prompt", bool(separator) and agent.get("prompt", "").strip() == body.strip(), "resolved prompt must match the sealed agent file")
                task_rules = [r for r in rules if wildcard_match("task", r["permission"])]
                last_task = task_rules[-1] if task_rules else {}
                check("no_specialist_delegation", last_task.get("pattern") == "*" and last_task.get("action") == "deny", "final task rule must deny every child")
                required = (*BASELINE_COMMANDS, f"python3 {helper_path} --root {root}")
                missing = [command for command in required if permission(rules, "bash", command) != "allow"]
                check("baseline_shell_permissions", not missing, {"commands_checked": len(required), "not_allowed": missing})
                unlisted = ("python3 -c pass", "docker ps", "rm -rf isolated", "go run ./cmd/workbench")
                check("unlisted_shell_asks", all(permission(rules, "bash", command) == "ask" for command in unlisted), "unlisted execution still requires approval")
            else:
                check("lead_route_to_go", agent.get("mode") == "primary" and permission(rules, "task", "go") == "allow", "native lead task permission allows go")
        except (OSError, StartupError, ValueError, KeyError, TypeError, AttributeError) as exc:
            check(f"resolved_{name}", False, str(exc) if isinstance(exc, StartupError) else type(exc).__name__)

    # Detect config drift across the CLI probes before admitting the report.
    for key in ("go_agent", "integrity_manifest", "startup_helper"):
        artifact = report["artifacts"].get(key)
        if artifact:
            try:
                same = sha256(Path(artifact["path"]).read_bytes()) == artifact["sha256"]
            except OSError:
                same = False
            check(f"stable_{key}", same, "exact bytes unchanged during preflight")
    if estimates is not None:
        report["continuity"] = planning_cpi(estimates)
    report["status"] = "PASS" if all(c["status"] == "PASS" for c in report["checks"]) else "FAIL"
    return report


def open_directory(path: Path) -> int:
    """Walk from / by directory fd, rejecting symlinked ancestors."""
    if not path.is_absolute() or ".." in path.parts:
        raise StartupError("root must be an absolute path without '..'")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_report(root: Path, report: dict[str, Any]) -> tuple[Path, str]:
    """Exclusive, private output; never follows symlinked report directories."""
    fd = open_directory(root)
    try:
        for part in (".opencode", "recorded", "go-startup"):
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        name = f"startup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(8)}.json"
        path = root / ".opencode/recorded/go-startup" / name
        report["report_path"] = str(path)
        data = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        output = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(output, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(fd)
        return path, sha256(data)
    finally:
        os.close(fd)


def nonnegative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("estimate must be nonnegative")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    for name in ("expected-files", "expected-tool-calls", "external-sources", "mutation-phases"):
        parser.add_argument(f"--{name}", type=nonnegative)
    parser.add_argument("--risk", choices=("normal", "high"), default="normal")
    args = parser.parse_args(argv)
    estimates = {key: getattr(args, key) for key in ("expected_files", "expected_tool_calls", "external_sources", "mutation_phases")}
    if any(value is not None for value in estimates.values()):
        if any(value is None for value in estimates.values()):
            parser.error("provide all four planning estimates together")
        estimates["risk"] = args.risk
    else:
        estimates = None
    try:
        root_fd = open_directory(args.root)
        os.close(root_fd)
        report = inspect_startup(args.root, estimates=estimates)
        path, digest = write_report(args.root, report)
    except (OSError, StartupError) as exc:
        print(json.dumps({"status": "FAIL", "error": type(exc).__name__, "report_path": None}))
        return 2
    print(json.dumps({
        "status": report["status"], "report_path": str(path), "sha256": digest,
        "failed_checks": [c["name"] for c in report["checks"] if c["status"] == "FAIL"],
    }))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
