"""Admission/process-bound tests: synthetic sources, never KoL product execution."""

from contextlib import redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("kol_remediation_review", Path(__file__).parents[1] / "kol_remediation_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class RemediationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="kol-remediation-unit-", dir="/tmp/opencode")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.module = self.root / review.base.MODULE_REL
        self.module.mkdir(parents=True)
        self.original = {}
        for name in review.REQUIRED:
            path = self.module / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic fixture " + name + "\n")
            self.original[name] = review.base.file_digest(path)
        self.plan = self.root / review.PLAN_REL
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text("synthetic plan, not an approval\n")
        self.plan_patch = patch.object(review, "PLAN_SHA", review.base.file_digest(self.plan))
        self.plan_patch.start()
        self.addCleanup(self.plan_patch.stop)
        self.pinned_patch = patch.object(review, "PINNED", {k: v for k, v in self.original.items() if k not in review.MUTABLE})
        self.pinned_patch.start()
        self.addCleanup(self.pinned_patch.stop)
        (self.module / ".baseline-isolated/modcache/cache/download").mkdir(parents=True)
        self.admission = self.root / review.VERIFY_REL / "admission-unit.json"
        self.admission.parent.mkdir(parents=True)
        self.payload = {
            "schema_version": "don-squad.kol-remediation-admission/v1", "reviewer": "verifier",
            "task_id": "test-only", "attempt_id": "test-attempt", "project_root": str(self.root),
            "plan": review.verified_plan(self.root), "source_manifest": review.inventory(self.root),
            "approved_checks": list(review.CHECKS), "review": dict.fromkeys(review.REVIEW_FIELDS, True),
            "limitations": ["Synthetic test fixture; no real-world approval."],
        }
        self.calls = []
        self.save_admission()

    def save_admission(self):
        self.admission.write_text(json.dumps(self.payload))
        self.admission_sha = review.base.file_digest(self.admission)

    def fake_runner(self, argv, cwd, env):
        self.calls.append((argv, cwd, env))
        self.assertEqual(cwd, self.module)
        if argv == ["/usr/bin/go", "version"]:
            stdout = "go version go1.26.8 linux/amd64\n"
        else:
            self.assertNotIn("run", argv)
            if argv[1] == "build":
                Path(argv[argv.index("-o") + 1]).write_bytes(b"synthetic build artifact, never executed\n")
            stdout = "" if argv[0] == "/usr/bin/gofmt" else "synthetic successful check\n"
        return {"exit_code": 0, "timed_out": False, "output_limit_exceeded": False,
                "stdout": stdout, "stderr": "", "captured_bytes": len(stdout)}

    def execute(self, check="host-tests", runner=None):
        return review.run_check(check, self.admission, self.admission_sha, self.root, runner or self.fake_runner)

    def test_reviewed_changed_source_and_new_test_are_admitted_but_old_freeze_is_not(self):
        (self.module / "internal/host/api.go").write_text("reviewed changed fixture\n")
        (self.module / "internal/host/api_test.go").write_text("reviewed new fixture\n")
        self.payload["source_manifest"] = review.inventory(self.root)
        self.save_admission()
        self.assertEqual(self.execute()["status"], "PASS")
        with self.assertRaises(review.ReviewError):
            review.base.source_snapshot(self.root, self.original)

    def test_missing_or_false_review_assertions_block_before_outputs(self):
        for name in review.REVIEW_FIELDS:
            with self.subTest(name=name):
                self.payload["review"][name] = False
                self.save_admission()
                with self.assertRaisesRegex(review.ReviewError, "assertions"):
                    self.execute()
                self.payload["review"][name] = True
        self.assertFalse((self.root / ".workbench-verify").exists())
        self.assertEqual(self.calls, [])

    def test_admission_hash_drift_and_unapproved_check_block(self):
        self.admission.write_text("changed after review\n")
        with self.assertRaisesRegex(review.ReviewError, "identity"):
            self.execute()
        self.payload["approved_checks"] = ["format"]
        self.save_admission()
        with self.assertRaisesRegex(review.ReviewError, "not admitted"):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_missing_task_identity_or_wrong_plan_block(self):
        self.payload["task_id"] = ""
        self.save_admission()
        with self.assertRaisesRegex(review.ReviewError, "task/attempt"):
            self.execute()
        self.payload["task_id"] = "test-only"
        self.payload["plan"]["sha256"] = "0" * 64
        self.save_admission()
        with self.assertRaisesRegex(review.ReviewError, "binding"):
            self.execute()

    def test_plan_drift_blocks_before_commands(self):
        self.plan.write_text("different plan\n")
        with self.assertRaisesRegex(review.ReviewError, "plan identity"):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_pinned_inputs_unknown_code_and_source_drift_block(self):
        (self.module / "go.mod").write_text("changed module\n")
        with self.assertRaisesRegex(review.ReviewError, "pinned"):
            self.execute()
        (self.module / "go.mod").write_text("synthetic fixture go.mod\n")
        extra = self.module / "internal/host/unapproved.go"
        extra.write_text("unexpected source\n")
        with self.assertRaisesRegex(review.ReviewError, "unapproved"):
            self.execute()
        extra.unlink()
        (self.module / "internal/host/api.go").write_text("changed but not reviewed\n")
        with self.assertRaisesRegex(review.ReviewError, "differs"):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_symlink_admission_and_source_hardlink_rejected(self):
        original = self.admission.read_bytes()
        self.admission.unlink()
        target = self.root / "elsewhere.json"
        target.write_bytes(original)
        self.admission.symlink_to(target)
        with self.assertRaises(OSError):
            self.execute()
        self.admission.unlink()
        self.save_admission()
        import os
        os.link(self.module / "internal/host/api.go", self.root / "hardlinked.go")
        with self.assertRaisesRegex(review.ReviewError, "hard-linked"):
            self.execute()

    def test_all_fixed_checks_produce_separate_bound_records_and_private_outputs(self):
        scratches = set()
        for check in review.CHECKS:
            with self.subTest(check=check):
                result = self.execute(check)
                raw = Path(result["report_path"]).read_bytes()
                record = json.loads(raw)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(review.base.digest(raw), result["sha256"])
                self.assertTrue(record["source_and_admission_stable"])
                self.assertIsNone(record["independent_safety_verdict"])
                self.assertNotIn(record["scratch"], scratches)
                scratches.add(record["scratch"])
                self.assertTrue(record["environment"]["GOPROXY"].startswith("file://"))
                self.assertEqual(record["environment"]["CGO_ENABLED"], "0")
                if check == "host-tests":
                    self.assertEqual(record["argv"][-1], "./internal/host")
                for output in record["outputs"]:
                    self.assertFalse(output["executed"])

    def test_drift_after_command_and_format_output_produce_failures(self):
        def dirty(argv, cwd, env):
            result = self.fake_runner(argv, cwd, env)
            if argv[0] == "/usr/bin/gofmt":
                result["stdout"] = "internal/host/api.go\n"
            return result

        self.assertEqual(self.execute("format", dirty)["status"], "FAIL")

        def drift(argv, cwd, env):
            result = self.fake_runner(argv, cwd, env)
            if argv[1] != "version":
                (self.module / "internal/host/api.go").write_text("source drift\n")
            return result

        self.assertEqual(self.execute("host-tests", drift)["status"], "FAIL")

    def test_overflow_exit_zero_cannot_be_a_success(self):
        def overflow(argv, cwd, env):
            result = self.fake_runner(argv, cwd, env)
            if argv[1] != "version":
                result["output_limit_exceeded"] = True
            return result

        self.assertEqual(self.execute("vet", overflow)["status"], "FAIL")

    def test_plan_drift_after_command_is_saved_as_failed_evidence(self):
        def drift_plan(argv, cwd, env):
            result = self.fake_runner(argv, cwd, env)
            if argv[1] != "version":
                self.plan.write_text("plan changed during command\n")
            return result

        result = self.execute("host-tests", drift_plan)
        self.assertEqual(result["status"], "FAIL")
        record = json.loads(Path(result["report_path"]).read_bytes())
        self.assertFalse(record["source_and_admission_stable"])
        self.assertEqual(record["plan"], self.payload["plan"])

    def test_real_capture_is_bounded_across_stdout_and_stderr(self):
        result = review.bounded_process(
            [sys.executable, "-I", "-c", "import os; os.write(1,b'x'*200000); os.write(2,b'y'*200000)"],
            self.root, {"PATH": "/usr/bin:/bin"}, timeout=5, output_limit=10000,
        )
        self.assertTrue(result["output_limit_exceeded"])
        self.assertLessEqual(result["captured_bytes"], 10000)
        self.assertLessEqual(len(result["stdout"]) + len(result["stderr"]), 10000)

    def test_real_timeout_terminates_process_group(self):
        result = review.bounded_process(
            [sys.executable, "-I", "-c", "import time; time.sleep(5)"],
            self.root, {"PATH": "/usr/bin:/bin"}, timeout=0.1, output_limit=10000,
        )
        self.assertTrue(result["timed_out"])
        self.assertNotEqual(result["exit_code"], 0)

    def test_missing_admission_or_full_application_tests_rejected_by_cli(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            review.main(["--check", "full-tests"])
        self.assertEqual(error.exception.code, 2)
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            code = review.main(["--check", "host-tests"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
