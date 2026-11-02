import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from gitops_remediation import (
    apply_gitops_remediation,
    RemediationResult,
    generate_restart_annotation,
    update_manifest_for_restart,
    is_valid_branch_name,
    is_commit_pushed,
    get_current_branch,
    get_head_commit,
    MANIFEST
)


class TestGitOpsRemediation(unittest.TestCase):

    def test_two_consecutive_restart_requests_produce_different_annotations(self):
        # Two consecutive calls to generate_restart_annotation must produce distinct values
        ann1 = generate_restart_annotation()
        ann2 = generate_restart_annotation()
        self.assertNotEqual(ann1, ann2)

        # Updating manifest documents produces distinct annotations without modifying repo file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as tmp:
            tmp.write(MANIFEST.read_text(encoding="utf-8"))
            tmp_path = Path(tmp.name)

        try:
            docs1, old1, new1 = update_manifest_for_restart(tmp_path)
            docs2, old2, new2 = update_manifest_for_restart(tmp_path)
            self.assertNotEqual(new1, new2)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_remediation_result_bool_and_fields(self):
        res_ok = RemediationResult(
            success=True,
            commit="abc1234",
            branch="dev",
            message="OK"
        )
        self.assertTrue(res_ok)
        self.assertEqual(res_ok.commit, "abc1234")
        self.assertEqual(res_ok.branch, "dev")
        self.assertIsNone(res_ok.unpushed_commit)

        res_fail = RemediationResult(
            success=False,
            commit="abc1234",
            branch="dev",
            message="Push failed",
            unpushed_commit="abc1234"
        )
        self.assertFalse(res_fail)
        self.assertEqual(res_fail.unpushed_commit, "abc1234")

    def test_unsupported_action_rejected(self):
        result = apply_gitops_remediation("invalid_action")
        self.assertFalse(result)
        self.assertIn("Unsupported", result.message)

    @patch("gitops_remediation.get_current_branch")
    def test_refuses_execution_on_main_branch(self, mock_branch):
        mock_branch.return_value = "main"
        result = apply_gitops_remediation("restart_pod")
        self.assertFalse(result)
        self.assertIn("main", result.message)

    @patch("gitops_remediation.get_current_branch")
    def test_refuses_execution_on_empty_branch(self, mock_branch):
        mock_branch.return_value = ""
        result = apply_gitops_remediation("restart_pod")
        self.assertFalse(result)
        self.assertIn("main or detached", result.message)

    @patch("gitops_remediation.get_current_branch")
    @patch("gitops_remediation.subprocess.run")
    def test_refuses_execution_with_unrelated_staged_changes(self, mock_run, mock_branch):
        mock_branch.return_value = "implementation-baseline"
        mock_staged_proc = MagicMock()
        mock_staged_proc.returncode = 1
        mock_run.return_value = mock_staged_proc

        result = apply_gitops_remediation("restart_pod")
        self.assertFalse(result)
        self.assertIn("staged", result.message.lower())

    @patch("gitops_remediation.get_current_branch", return_value="implementation-baseline")
    @patch("gitops_remediation.run_command")
    @patch("gitops_remediation.subprocess.run")
    @patch("gitops_remediation.get_head_commit", return_value="abc1234567890abcdef1234567890abcdef12")
    @patch("gitops_remediation.write_manifest_documents")
    @patch("gitops_remediation.update_manifest_for_restart", return_value=([], "old", "new"))
    def test_git_push_failure_cannot_return_success(
        self,
        mock_update,
        mock_write_docs,
        mock_head,
        mock_subproc,
        mock_run_cmd,
        mock_branch
    ):
        def subproc_side_effect(cmd, *args, **kwargs):
            mock_proc = MagicMock()
            if cmd == ["git", "diff", "--cached", "--quiet"]:
                if not hasattr(subproc_side_effect, "called_diff"):
                    subproc_side_effect.called_diff = True
                    mock_proc.returncode = 0
                else:
                    mock_proc.returncode = 1
                return mock_proc
            if cmd == ["git", "diff", "--cached", "--name-only"]:
                mock_proc.stdout = MANIFEST.as_posix()
                mock_proc.returncode = 0
                return mock_proc
            mock_proc.returncode = 0
            return mock_proc

        mock_subproc.side_effect = subproc_side_effect

        def run_cmd_side_effect(cmd):
            if cmd[0] == "git" and cmd[1] == "push":
                raise subprocess.CalledProcessError(1, cmd, stderr="Network error: connection refused")
            return MagicMock()

        mock_run_cmd.side_effect = run_cmd_side_effect

        result = apply_gitops_remediation("restart_pod")
        self.assertFalse(result)
        self.assertEqual(result.unpushed_commit, "abc1234567890abcdef1234567890abcdef12")
        self.assertIn("push failed", result.message.lower())

    @patch("gitops_remediation.get_current_branch", return_value="implementation-baseline")
    @patch("gitops_remediation.run_command")
    @patch("gitops_remediation.subprocess.run")
    @patch("gitops_remediation.get_head_commit", return_value="abc1234567890abcdef1234567890abcdef12")
    @patch("gitops_remediation.is_commit_pushed", return_value=False)
    @patch("gitops_remediation.write_manifest_documents")
    @patch("gitops_remediation.update_manifest_for_restart", return_value=([], "old", "new"))
    def test_unpushed_local_commit_cannot_be_accepted(
        self,
        mock_update,
        mock_write_docs,
        mock_is_pushed,
        mock_head,
        mock_subproc,
        mock_run_cmd,
        mock_branch
    ):
        def subproc_side_effect(cmd, *args, **kwargs):
            mock_proc = MagicMock()
            if cmd == ["git", "diff", "--cached", "--quiet"]:
                if not hasattr(subproc_side_effect, "called_diff"):
                    subproc_side_effect.called_diff = True
                    mock_proc.returncode = 0
                else:
                    mock_proc.returncode = 1
                return mock_proc
            if cmd == ["git", "diff", "--cached", "--name-only"]:
                mock_proc.stdout = MANIFEST.as_posix()
                mock_proc.returncode = 0
                return mock_proc
            mock_proc.returncode = 0
            return mock_proc

        mock_subproc.side_effect = subproc_side_effect
        mock_run_cmd.return_value = MagicMock()

        result = apply_gitops_remediation("restart_pod")
        self.assertFalse(result)
        self.assertIn("not confirmed", result.message)
        self.assertEqual(result.unpushed_commit, "abc1234567890abcdef1234567890abcdef12")

    @patch("gitops_remediation.get_current_branch", return_value="implementation-baseline")
    @patch("gitops_remediation.subprocess.run")
    @patch("gitops_remediation.write_manifest_documents")
    @patch("gitops_remediation.update_manifest_for_restart", return_value=([], "old", "new"))
    def test_no_desired_state_change_cannot_return_success(
        self,
        mock_update,
        mock_write_docs,
        mock_subproc,
        mock_branch
    ):
        def subproc_side_effect(cmd, *args, **kwargs):
            mock_proc = MagicMock()
            if cmd == ["git", "diff", "--cached", "--quiet"]:
                mock_proc.returncode = 0  # No diff
                return mock_proc
            if cmd == ["git", "diff", "--cached", "--name-only"]:
                mock_proc.stdout = MANIFEST.as_posix()
                mock_proc.returncode = 0
                return mock_proc
            mock_proc.returncode = 0
            return mock_proc

        mock_subproc.side_effect = subproc_side_effect

        result = apply_gitops_remediation("restart_pod")
        self.assertFalse(result)
        self.assertIn("no desired-state change", result.message.lower())

    # Direct unit tests for branch name validation and is_commit_pushed
    def test_is_valid_branch_name(self):
        # Valid branch names
        self.assertTrue(is_valid_branch_name("implementation-baseline"))
        self.assertTrue(is_valid_branch_name("feature/remediation-v1"))
        self.assertTrue(is_valid_branch_name("dev"))

        # Invalid branch names
        self.assertFalse(is_valid_branch_name("invalid..branch"))
        self.assertFalse(is_valid_branch_name("-invalid"))
        self.assertFalse(is_valid_branch_name("branch~1"))
        self.assertFalse(is_valid_branch_name("branch with spaces"))
        self.assertFalse(is_valid_branch_name(""))
        self.assertFalse(is_valid_branch_name("   "))
        self.assertFalse(is_valid_branch_name(None))
        self.assertFalse(is_valid_branch_name(12345))

    @patch("gitops_remediation.subprocess.run")
    def test_is_commit_pushed_successful_fetch_with_explicit_refspec(self, mock_run):
        branch = "implementation-baseline"
        commit_sha = "abc1234567890abcdef1234567890abcdef12"
        expected_refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"

        def side_effect(cmd, *args, **kwargs):
            proc = MagicMock()
            if cmd[:3] == ["git", "check-ref-format", "--branch"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "fetch", "origin"]:
                # Verify that the explicit refspec was requested
                self.assertEqual(cmd[3], expected_refspec)
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                self.assertEqual(cmd[3], f"origin/{branch}^{{commit}}")
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
                self.assertEqual(cmd[3], commit_sha)
                self.assertEqual(cmd[4], f"origin/{branch}")
                proc.returncode = 0
                return proc
            proc.returncode = 0
            return proc

        mock_run.side_effect = side_effect
        self.assertTrue(is_commit_pushed(commit_sha, branch))

    @patch("gitops_remediation.subprocess.run")
    def test_is_commit_pushed_invalid_branch_name_rejected(self, mock_run):
        # When branch name syntax is invalid, is_commit_pushed must return False without fetching
        result = is_commit_pushed("abc1234567890abcdef", "invalid..branch")
        self.assertFalse(result)

        # Verify git fetch was never called
        called_commands = [call.args[0] for call in mock_run.call_args_list if call.args]
        self.assertTrue(all("fetch" not in cmd for cmd in called_commands))

    @patch("gitops_remediation.subprocess.run")
    def test_is_commit_pushed_fetch_failure_returns_false(self, mock_run):
        branch = "implementation-baseline"
        commit_sha = "abc1234567890abcdef"

        def side_effect(cmd, *args, **kwargs):
            proc = MagicMock()
            if cmd[:3] == ["git", "check-ref-format", "--branch"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.returncode = 1
                proc.stderr = "fatal: unable to access: Could not resolve host"
                return proc
            proc.returncode = 0
            return proc

        mock_run.side_effect = side_effect
        # If fetch fails, is_commit_pushed MUST return False immediately
        self.assertFalse(is_commit_pushed(commit_sha, branch))
        # Verify rev-parse and merge-base were NEVER called
        called_commands = [call.args[0] for call in mock_run.call_args_list if call.args]
        self.assertTrue(all("rev-parse" not in cmd and "merge-base" not in cmd for cmd in called_commands))

    @patch("gitops_remediation.subprocess.run")
    def test_is_commit_pushed_missing_remote_tracking_ref_returns_false(self, mock_run):
        branch = "feature-test"
        commit_sha = "abc1234567890abcdef"

        def side_effect(cmd, *args, **kwargs):
            proc = MagicMock()
            if cmd[:3] == ["git", "check-ref-format", "--branch"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                proc.returncode = 128  # Ref does not exist
                return proc
            proc.returncode = 1
            return proc

        mock_run.side_effect = side_effect
        self.assertFalse(is_commit_pushed(commit_sha, branch))

    @patch("gitops_remediation.subprocess.run")
    def test_is_commit_pushed_commit_is_ancestor_of_remote_branch(self, mock_run):
        branch = "implementation-baseline"
        commit_sha = "abc1234567890abcdef"

        def side_effect(cmd, *args, **kwargs):
            proc = MagicMock()
            if cmd[:3] == ["git", "check-ref-format", "--branch"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
                proc.returncode = 0  # Ancestor confirmed
                return proc
            proc.returncode = 0
            return proc

        mock_run.side_effect = side_effect
        self.assertTrue(is_commit_pushed(commit_sha, branch))

    @patch("gitops_remediation.subprocess.run")
    def test_is_commit_pushed_commit_is_not_ancestor_of_remote_branch(self, mock_run):
        branch = "implementation-baseline"
        commit_sha = "abc1234567890abcdef"

        def side_effect(cmd, *args, **kwargs):
            proc = MagicMock()
            if cmd[:3] == ["git", "check-ref-format", "--branch"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "fetch", "origin"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                proc.returncode = 0
                return proc
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
                proc.returncode = 1  # Not ancestor
                return proc
            proc.returncode = 1
            return proc

        mock_run.side_effect = side_effect
        self.assertFalse(is_commit_pushed(commit_sha, branch))

    def test_is_commit_pushed_empty_or_invalid_inputs_return_false(self):
        self.assertFalse(is_commit_pushed("", "dev"))
        self.assertFalse(is_commit_pushed("   ", "dev"))
        self.assertFalse(is_commit_pushed(None, "dev"))
        self.assertFalse(is_commit_pushed("abc", ""))
        self.assertFalse(is_commit_pushed("abc", "   "))
        self.assertFalse(is_commit_pushed("abc", None))
        self.assertFalse(is_commit_pushed(None, None))
        self.assertFalse(is_commit_pushed(12345, "dev"))
        self.assertFalse(is_commit_pushed("abc", 12345))


if __name__ == "__main__":
    unittest.main()
