import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from risk_engine import evaluate_policy_compliance, calculate_risk
from gitops_remediation import apply_gitops_rollback, RemediationResult
from k8s_monitor import detect_incident
from llm_proposal import generate_remediation, ProposalError


class TestPolicyCompliance(unittest.TestCase):
    """Verifies Policy-as-Code (OPA / Admission Control) evaluation."""

    def test_allowed_action_is_compliant(self):
        score, msg = evaluate_policy_compliance("restart_pod", namespace="ai-remediation")
        self.assertEqual(score, 1.0)
        self.assertIn("Policy compliant", msg)

    def test_disallowed_action_is_rejected(self):
        score, msg = evaluate_policy_compliance("delete_namespace", namespace="ai-remediation")
        self.assertEqual(score, 0.0)
        self.assertIn("Policy violation", msg)

    def test_protected_namespace_is_rejected(self):
        for ns in ["kube-system", "argocd", "cert-manager"]:
            score, msg = evaluate_policy_compliance("restart_pod", namespace=ns)
            self.assertEqual(score, 0.0)
            self.assertIn("protected", msg)

    def test_privileged_container_in_manifest_rejected(self):
        manifest_dict = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "test", "securityContext": {"privileged": True}}
                        ]
                    }
                }
            }
        }
        score, msg = evaluate_policy_compliance("restart_pod", manifest_dict=manifest_dict)
        self.assertEqual(score, 0.0)
        self.assertIn("Privileged container", msg)

    def test_host_network_in_manifest_rejected(self):
        manifest_dict = {
            "spec": {
                "template": {
                    "spec": {
                        "hostNetwork": True,
                        "containers": [{"name": "test"}]
                    }
                }
            }
        }
        score, msg = evaluate_policy_compliance("restart_pod", manifest_dict=manifest_dict)
        self.assertEqual(score, 0.0)
        self.assertIn("hostNetwork", msg)


class TestGitOpsRollback(unittest.TestCase):
    """Verifies GitOps automated rollback behavior."""

    @patch("gitops_remediation.get_current_branch", return_value="main")
    def test_refuses_rollback_on_main_branch(self, mock_branch):
        result = apply_gitops_rollback()
        self.assertFalse(result.success)
        self.assertIn("Refusing rollback on main", result.message)

    @patch("gitops_remediation.get_current_branch", return_value="phase2-ollama-integration")
    @patch("gitops_remediation.get_head_commit", return_value="")
    def test_refuses_rollback_when_no_commit(self, mock_head, mock_branch):
        result = apply_gitops_rollback()
        self.assertFalse(result.success)
        self.assertIn("No commit available", result.message)

    @patch("gitops_remediation.get_current_branch", return_value="phase2-ollama-integration")
    @patch("gitops_remediation.get_head_commit", return_value="rollback1234567890")
    @patch("gitops_remediation.run_command")
    @patch("gitops_remediation.is_commit_pushed", return_value=True)
    def test_successful_rollback(self, mock_pushed, mock_run, mock_head, mock_branch):
        result = apply_gitops_rollback(target_commit="rev1234567890abcdef")
        self.assertTrue(result.success)
        self.assertEqual(result.commit, "rollback1234567890")
        self.assertIn("Rollback committed and pushed", result.message)


class TestIncidentLogEnrichment(unittest.TestCase):
    """Verifies that k8s_monitor captures pod logs and events defensively."""

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    @patch("k8s_monitor.client.AppsV1Api")
    def test_pod_logs_and_events_captured(self, mock_apps_cls, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_apps = mock_apps_cls.return_value

        # Mock pod with crash
        pod = MagicMock()
        pod.metadata.name = "crash-pod"
        pod.status.phase = "Running"
        container = MagicMock()
        container.name = "nginx"
        container.ready = False
        container.restart_count = 4
        container.state.waiting.reason = "CrashLoopBackOff"
        container.state.terminated = None
        pod.status.container_statuses = [container]

        mock_core.list_namespaced_pod.return_value.items = [pod]
        mock_apps.list_namespaced_deployment.return_value.items = []
        mock_core.read_namespaced_pod_log.return_value = "Fatal error: segmentation fault\nexit 1"

        mock_evt = MagicMock()
        mock_evt.type = "Warning"
        mock_evt.reason = "BackOff"
        mock_evt.message = "Back-off restarting failed container"
        mock_core.list_namespaced_event.return_value.items = [mock_evt]

        incidents = detect_incident()
        self.assertGreaterEqual(len(incidents), 1)
        evidence = incidents[0]["evidence"]
        self.assertIn("pod_logs", evidence)
        self.assertIn("segmentation fault", evidence["pod_logs"])
        self.assertIn("events", evidence)
        self.assertEqual(len(evidence["events"]), 1)


class TestMainWorkflowAutoExecuteAndRollback(unittest.TestCase):
    """Verifies Auto-Execute and Rollback integration in main workflow."""

    @patch("main.validate_remediation", return_value=False)
    @patch("main.apply_gitops_rollback")
    @patch("main.apply_gitops_remediation")
    @patch("main.calculate_risk", return_value=(0.15, "AUTO_EXECUTE"))
    @patch("main.generate_remediation", return_value={
        "incident": "pod_failure",
        "action": "restart_pod",
        "description": "Restart",
        "confidence": 0.9,
        "uncertainty": 0.1,
        "policy_compliance": 1.0,
        "reversibility": 0.9,
        "blast_radius": 0.1,
    })
    @patch("main.select_primary_incident", return_value={"incident_type": "pod_failure", "evidence": {}})
    @patch("main.detect_incident", return_value=[{"incident_type": "pod_failure", "evidence": {}}])
    def test_auto_execute_and_rollback_on_failure(
        self, mock_detect, mock_select, mock_gen, mock_calc, mock_remed, mock_rollback, mock_val
    ):
        from main import main
        mock_remed.return_value = RemediationResult(
            success=True, commit="abc1234567890abcdef1234567890abcdef123456", branch="test-branch"
        )
        mock_rollback.return_value = RemediationResult(
            success=True, commit="roll1234567890abcdef1234567890abcdef123456", branch="test-branch", message="Rollback ok"
        )

        res = main(auto_execute=True, max_retries=1)
        self.assertFalse(res)
        mock_remed.assert_called_once()
        mock_val.assert_called_once()
        mock_rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
