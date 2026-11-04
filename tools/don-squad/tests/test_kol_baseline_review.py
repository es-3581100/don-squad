"""Boundary tests use synthetic projects and a fake runner, never product code."""

from contextlib import redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile


spec = importlib.util.spec_from_file_location("kol_baseline_review", Path(__file__).parents[1] / "kol_baseline_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="kol-review-tests-", dir="/tmp/opencode")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "project"
        self.module = self.root / review.MODULE_REL
        self.module.mkdir(parents=True)
        self.expected = {}
        for name in review.EXPECTED_SOURCE:
            path = self.module / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = ("synthetic fixture: " + name + "\n").encode()
            path.write_bytes(data)
            self.expected[name] = review.digest(data)
        checkpoint = self.root / review.CHECKPOINT
        checkpoint.write_bytes(b'{"fixture":true}\n')
        self.checkpoint_sha = review.digest(checkpoint.read_bytes())
        (self.module / ".baseline-isolated/modcache/cache/download").mkdir(parents=True)
        self.calls = []

    def runner(self, argv, cwd, env):
        self.calls.append((argv, cwd, dict(env)))
        self.assertEqual(cwd, self.module)
        if argv == ["/usr/bin/go", "version"]:
            stdout = "go version go1.26.8 linux/amd64\n"
        else:
            self.assertIn(argv[0], ("/usr/bin/go", "/usr/bin/gofmt"))
            self.assertNotIn("run", argv)
            if "build" in argv:
                output = Path(argv[argv.index("-o") + 1])
                self.assertTrue(output.is_relative_to(self.root / ".workbench-verify"))
                output.write_bytes(b"synthetic output, never executed\n")
            stdout = "" if argv[0].endswith("gofmt") else "synthetic successful check\n"
        return {"exit_code": 0, "timed_out": False, "stdout": stdout, "stderr": ""}

    def execute(self, check, runner=None):
        return review.execute_check(check, self.root, runner or self.runner, self.expected, self.checkpoint_sha)

    def test_inputs_cannot_escape_scope_or_read_private_sessions(self):
        for path in (self.root.parent / "outside.json", self.root / "../outside.json",
                     self.root / ".opencode/recorded/ses_test/session.json", self.root / ".receipt_secret"):
            with self.subTest(path=path), self.assertRaises(review.ReviewError):
                review.input_path(str(path), self.root)

    def test_hash_rejects_symlinked_input(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("must not follow\n")
        link = self.root / "link.txt"
        link.symlink_to(outside)
        with self.assertRaises(OSError):
            review.file_digest(link)

    def test_strict_json_rejects_duplicate_and_nonfinite_values(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(review.ReviewError):
                review.strict_json(raw)

    def test_preserve_keeps_exact_bytes_and_never_overwrites(self):
        source = self.root / "evidence.json"
        raw = b'{ "reported": true, "not_verified": true }\n'
        source.write_bytes(raw)
        result = review.preserve(str(source), "worker.json", self.root)
        target = Path(result["destination"])
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(result["sha256"], review.digest(raw))
        with self.assertRaises(FileExistsError):
            review.preserve(str(source), "worker.json", self.root)
        self.assertEqual(target.read_bytes(), raw)

    def test_preserve_rejects_escape_and_binary_destination(self):
        source = self.root / "evidence.txt"
        source.write_text("evidence\n")
        for name in ("../escape.json", "/tmp/escape.json", "x\\escape.json", "output.exe"):
            with self.subTest(name=name), self.assertRaises(review.ReviewError):
                review.preserve(str(source), name, self.root)

    def test_preserve_rejects_symlinked_destination_ancestor(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        (self.root / "docs").symlink_to(outside, target_is_directory=True)
        source = self.root / "evidence.txt"
        source.write_text("evidence\n")
        with self.assertRaises(OSError):
            review.preserve(str(source), "worker.txt", self.root)
        self.assertEqual(list(outside.iterdir()), [])

    def test_changed_source_blocks_before_commands_or_scratch(self):
        (self.module / "internal/host/status.go").write_text("unreviewed source\n")
        with self.assertRaises(review.ReviewError):
            self.execute("host-tests")
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / ".workbench-verify").exists())

    def test_added_source_file_blocks_before_commands(self):
        (self.module / "internal/host/unreviewed_test.go").write_text("new test\n")
        with self.assertRaises(review.ReviewError):
            self.execute("host-tests")
        self.assertEqual(self.calls, [])

    def test_checkpoint_mismatch_blocks_before_commands(self):
        (self.root / review.CHECKPOINT).write_text("different checkpoint\n")
        with self.assertRaisesRegex(review.ReviewError, "checkpoint"):
            self.execute("native")
        self.assertEqual(self.calls, [])

    def test_five_fixed_checks_use_offline_private_outputs_and_bound_reports(self):
        scratch = set()
        for check in review.CHECKS:
            with self.subTest(check=check):
                result = self.execute(check)
                self.assertEqual(result["status"], "PASS")
                raw = Path(result["report_path"]).read_bytes()
                self.assertEqual(review.digest(raw), result["sha256"])
                report = json.loads(raw)
                self.assertIsNone(report["independent_safety_verdict"])
                self.assertTrue(report["source_unchanged"])
                self.assertNotIn(report["scratch"], scratch)
                scratch.add(report["scratch"])
                env = report["environment"]
                self.assertTrue(env["GOPROXY"].startswith("file://"))
                self.assertEqual(env["GOTOOLCHAIN"], "local")
                self.assertEqual(env["CGO_ENABLED"], "0")
                self.assertNotIn("HTTP_PROXY", env)
                self.assertNotIn("DOCKER_CONTEXT", env)
                self.assertEqual(list(Path(env["DOCKER_CONFIG"]).iterdir()), [])
                self.assertFalse((Path(report["scratch"]) / "no-daemon.sock").exists())
                if check == "host-tests":
                    self.assertEqual(report["argv"][-1], "./internal/host")
                if check == "wasm":
                    self.assertEqual((env["GOOS"], env["GOARCH"]), ("js", "wasm"))
                for output in report["outputs"]:
                    self.assertFalse(output["executed"])
                    self.assertEqual(output["sha256"], review.file_digest(Path(output["path"])))

    def test_nonempty_format_output_is_failure_despite_exit_zero(self):
        def dirty(argv, cwd, env):
            result = self.runner(argv, cwd, env)
            if argv[0].endswith("gofmt"):
                result["stdout"] = "internal/host/status.go\n"
            return result

        self.assertEqual(self.execute("format", dirty)["status"], "FAIL")

    def test_source_drift_during_execution_cannot_pass(self):
        def drift(argv, cwd, env):
            result = self.runner(argv, cwd, env)
            if argv[1] != "version":
                (self.module / "internal/host/status.go").write_text("changed during check\n")
            return result

        result = self.execute("host-tests", drift)
        report = json.loads(Path(result["report_path"]).read_bytes())
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(report["source_unchanged"])

    def test_timeout_is_failure_not_pass(self):
        def timeout(argv, cwd, env):
            result = self.runner(argv, cwd, env)
            if argv[1] != "version":
                result.update(exit_code=-9, timed_out=True)
            return result

        self.assertEqual(self.execute("vet", timeout)["status"], "FAIL")

    def test_full_application_tests_and_unknown_commands_are_rejected(self):
        for check in ("full-tests", "go run ./cmd/workbench", "host-tests; touch /tmp/x"):
            with self.subTest(check=check), self.assertRaises(review.ReviewError):
                self.execute(check)
        self.assertEqual(self.calls, [])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            review.main(["--check", "full-tests"])
        self.assertEqual(error.exception.code, 2)

    def test_pinned_archive_is_read_without_extraction(self):
        archive = self.root / "kol-workbench-v0.1.zip"
        with ZipFile(archive, "w") as writer:
            writer.writestr("starter/source.go", "synthetic source\n")
        with patch.object(review, "STARTER_SHA", review.file_digest(archive)):
            result = review.archive_member("starter/source.go", self.root)
        self.assertEqual(result["text"], "synthetic source\n")
        self.assertFalse((self.root / "starter").exists())
        with self.assertRaises(review.ReviewError):
            review.archive_member("../escape", self.root)


if __name__ == "__main__":
    unittest.main()
