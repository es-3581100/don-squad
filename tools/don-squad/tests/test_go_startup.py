"""Startup boundary tests use synthetic config and fake CLI observations only."""

import copy
import importlib.util
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest


spec = importlib.util.spec_from_file_location("go_startup", Path(__file__).parents[1] / "go_startup.py")
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


def installation(tmp_path):
    config = tmp_path / "config"
    agents = config / "agents"
    tools = config / "tools/don-squad"
    agents.mkdir(parents=True)
    tools.mkdir(parents=True)
    helper = tools / "go_startup.py"
    helper.write_bytes(b"reviewed helper fixture\n")
    body = f"# Go\nStartup helper SHA-256: `{startup.sha256(helper.read_bytes())}`.\n"
    go_file = agents / "go.md"
    go_file.write_text("---\nmode: subagent\n---\n" + body)
    (tools / "integrity.json").write_text(json.dumps({"agents": {"go": startup.sha256(go_file.read_bytes())}}))
    permissions = [{"permission": "*", "pattern": "*", "action": "allow"},
                   {"permission": "bash", "pattern": "*", "action": "ask"}]
    for pattern in ("sha256sum *", "zipinfo *", "unzip *", "mkdir *", "cp -n *", "bash -n *",
                    "gofmt *", "go *", "GOOS=js GOARCH=wasm go build*", "/usr/bin/env -i * /usr/bin/go *",
                    f"python3 {helper} --root *"):
        permissions.append({"permission": "bash", "pattern": pattern, "action": "allow"})
    # A later rule is necessary because the synthetic 'go *' fixture also permits go run.
    permissions.append({"permission": "bash", "pattern": "go run *", "action": "ask"})
    permissions.append({"permission": "task", "pattern": "*", "action": "deny"})
    go = {"name": "go", "mode": "subagent", "hidden": True, "prompt": body, "permission": permissions}
    lead = {"name": "don-squad", "mode": "primary", "permission": [
        {"permission": "task", "pattern": "*", "action": "deny"},
        {"permission": "task", "pattern": "go", "action": "allow"},
    ]}
    calls = []

    def runner(argv, root):
        calls.append(argv)
        if argv == ["go", "version"]:
            return b"go version go1.26.8 linux/amd64\n"
        if argv == ["opencode", "--version"]:
            return b"1.18.35\n"
        if argv == ["opencode", "debug", "agent", "go"]:
            return json.dumps(go).encode()
        if argv == ["opencode", "debug", "agent", "don-squad"]:
            return json.dumps(lead).encode()
        raise AssertionError(f"unexpected execution: {argv}")

    return config, go, lead, runner, calls


def failures(report):
    return {check["name"] for check in report["checks"] if check["status"] == "FAIL"}


class StartupTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="don-squad-go-startup-", dir="/tmp/opencode")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config, self.go, self.lead, self.runner, self.calls = installation(self.root)

    def report(self, runner=None):
        return startup.inspect_startup(self.root, self.config, runner or self.runner)

    def test_native_startup_needs_no_standalone_bundle(self):
        report = self.report()
        self.assertEqual(report["status"], "PASS")
        self.assertIs(report["is_session_receipt"], False)
        self.assertNotIn("session_id", report)
        self.assertEqual(self.calls, [["go", "version"], ["opencode", "--version"],
                                     ["opencode", "debug", "agent", "go"], ["opencode", "debug", "agent", "don-squad"]])
        self.assertFalse((self.root / ".opencode").exists())

    def test_go_hash_mismatch_cannot_pass(self):
        with (self.config / "agents/go.md").open("a") as stream:
            stream.write("unreviewed change\n")
        self.assertIn("go_integrity", failures(self.report()))

    def test_helper_hash_mismatch_cannot_pass(self):
        (self.config / "tools/don-squad/go_startup.py").write_bytes(b"different helper")
        self.assertIn("helper_integrity", failures(self.report()))

    def test_native_override_cannot_impersonate_sealed_agent(self):
        self.go["prompt"] = "project override"
        self.assertIn("loaded_go_prompt", failures(self.report()))

    def test_native_route_denied_blocks_startup(self):
        self.lead["permission"].append({"permission": "task", "pattern": "go", "action": "deny"})
        self.assertIn("lead_route_to_go", failures(self.report()))

    def test_specialist_delegation_override_blocks_startup(self):
        self.go["permission"].append({"permission": "task", "pattern": "coder-worker", "action": "allow"})
        self.assertIn("no_specialist_delegation", failures(self.report()))

    def test_blanket_shell_allow_blocks_startup(self):
        self.go["permission"].append({"permission": "bash", "pattern": "*", "action": "allow"})
        self.assertIn("unlisted_shell_asks", failures(self.report()))

    def test_missing_tool_is_failure_not_startup_success(self):
        def missing_go(argv, root):
            if argv == ["go", "version"]:
                raise startup.StartupError("command unavailable")
            return self.runner(argv, root)

        self.assertIn("go_toolchain", failures(self.report(missing_go)))

    def test_duplicate_json_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            startup.strict_json(b'{"agents":{},"agents":{"go":"unreviewed"}}')

    def test_config_drift_during_probes_blocks_startup(self):
        def drift(argv, root):
            result = self.runner(argv, root)
            if argv == ["go", "version"]:
                (self.config / "agents/go.md").write_text("changed during startup\n")
            return result

        self.assertIn("stable_go_agent", failures(self.report(drift)))

    def test_report_is_exclusive_private_and_exactly_hashed(self):
        report = self.report()
        first, digest = startup.write_report(self.root, copy.deepcopy(report))
        original = first.read_bytes()
        second, _ = startup.write_report(self.root, copy.deepcopy(report))
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(startup.sha256(original), digest)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        self.assertEqual(json.loads(original)["status"], "PASS")
        self.assertNotIn("sha256", json.loads(original))  # No recursive self-hash.

    def test_symlinked_report_directory_cannot_redirect_writes(self):
        project = self.root / "project"
        outside = self.root / "outside"
        (project / ".opencode").mkdir(parents=True)
        outside.mkdir()
        (project / ".opencode/recorded").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            startup.write_report(project, {"status": "FAIL"})
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_root_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError):
            startup.open_directory(link)

    def test_planning_cpi_distinguishes_estimates_from_session_telemetry(self):
        result = startup.planning_cpi({"expected_files": 18, "expected_tool_calls": 48,
                                       "external_sources": 12, "mutation_phases": 4, "risk": "high"})
        self.assertEqual(result["score"], 22)
        self.assertEqual(result["planning_class"], "long")
        self.assertIsNone(result["recorded_context_requests"])
        self.assertIsNone(result["elapsed_minutes"])
        self.assertIn("/compact", result["action"])

    def test_partial_or_negative_planning_estimates_rejected(self):
        for extra in (["--expected-files", "1"], ["--expected-files", "-1"]):
            with self.assertRaises(SystemExit) as error:
                startup.main(["--root", str(self.root), *extra])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
