"""Exercise loaded edit rules against native worktree-relative resources.

Read-only integration checks: no patch/write tool is invoked and no product
checks run. Native edit/write/apply_patch submit paths relative to the Git
worktree, which is distinct from this project's working directory.
"""

import json
from pathlib import Path
import subprocess
import sys
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from go_startup import permission  # noqa: E402


PROJECT = Path("/home/sticky-ricky/repos/donCannoli-burns/don_kolmafia/Mafia-Builds/kolmafia-go")


class NativeEditPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worktree = Path(subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=PROJECT, text=True,
        ).strip())
        cls.agents = {}
        for name in ("verifier", "project-planner-hygiene"):
            raw = subprocess.check_output(
                ["opencode", "debug", "agent", name], cwd=PROJECT, timeout=90,
            )
            cls.agents[name] = json.loads(raw)

    def action(self, role, path):
        native_resource = path.relative_to(self.worktree).as_posix()
        return permission(self.agents[role]["permission"], "edit", native_resource)

    def test_expected_worktree_and_native_resource_shape(self):
        self.assertEqual(self.worktree, Path("/home/sticky-ricky"))
        resource = (PROJECT / "docs/isolated-baseline/README.md").relative_to(self.worktree).as_posix()
        self.assertEqual(resource, "repos/donCannoli-burns/don_kolmafia/Mafia-Builds/kolmafia-go/docs/isolated-baseline/README.md")
        self.assertFalse(resource.startswith("/"))

    def test_frontmatter_is_loaded_for_both_roles(self):
        for role, agent in self.agents.items():
            with self.subTest(role=role):
                self.assertEqual(agent["name"], role)
                self.assertEqual(agent["mode"], "subagent")
                self.assertTrue(agent["hidden"])
                self.assertFalse(agent["prompt"].startswith("---"))

    def test_verifier_can_create_approved_review_json(self):
        path = PROJECT / ".opencode/recorded/kol-workbench-20261101/verification/b2-independent-review-9a803770.json"
        self.assertEqual(self.action("verifier", path), "allow")

    def test_patch_header_resolution_is_not_permission_pattern_resolution(self):
        # Patch filenames are cwd-relative. Permission resources are worktree-relative.
        relative_to_project = ".opencode/recorded/kol-workbench-20261101/verification/audit-plan-review-d915b075.json"
        correct_absolute = PROJECT / relative_to_project
        copied_permission_resource = correct_absolute.relative_to(self.worktree)
        wrong_absolute = PROJECT / copied_permission_resource
        self.assertEqual((PROJECT / relative_to_project).resolve(), correct_absolute)
        self.assertEqual(self.action("verifier", correct_absolute), "allow")
        self.assertNotEqual(wrong_absolute, correct_absolute)
        self.assertEqual(self.action("verifier", wrong_absolute), "deny")
        self.assertIn("use absolute patch headers", self.agents["verifier"]["prompt"])

    def test_documenter_can_create_approved_readme_and_handoff(self):
        for relative in ("docs/isolated-baseline/README.md",
                         ".opencode/recorded/kol-workbench-20261101/documentation/b3-handoff.json"):
            with self.subTest(path=relative):
                self.assertEqual(self.action("project-planner-hygiene", PROJECT / relative), "allow")

    def test_both_roles_still_deny_source_configuration_and_neighbor_project(self):
        paths = (
            PROJECT / "dev/kol-workbench-v0.1/internal/host/status.go",
            self.worktree / ".config/opencode/agents/go.md",
            PROJECT.parent / "unapproved-project/docs/isolated-baseline/README.md",
        )
        for role in self.agents:
            for path in paths:
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.action(role, path), "deny")

    def test_verifier_still_cannot_write_documentation_or_non_json_reports(self):
        for relative in ("docs/isolated-baseline/README.md",
                         ".opencode/recorded/kol-workbench-20261101/verification/source.go"):
            with self.subTest(path=relative):
                self.assertEqual(self.action("verifier", PROJECT / relative), "deny")

    def test_delegation_remains_denied(self):
        for role, agent in self.agents.items():
            with self.subTest(role=role):
                self.assertEqual(permission(agent["permission"], "task", "go"), "deny")


if __name__ == "__main__":
    unittest.main()
