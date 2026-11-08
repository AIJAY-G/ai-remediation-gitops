import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from audit_logger import (
    GENESIS_HASH,
    log_audit_event,
    verify_audit_log_integrity,
)
from chatops import format_slack_card, send_chatops_notification
from gitops_remediation import (
    RemediationResult,
    SUPPORTED_GITOPS_ACTIONS,
    apply_gitops_remediation,
    update_manifest_action,
)
from kubeguard_operator import KubeGuardOperator
from rbac import (
    authorize_approval,
    get_current_operator,
)


class TestAuditLogger(unittest.TestCase):
    """Verifies cryptographic hash chain and tamper detection in audit log."""

    def setUp(self):
        self.test_log = Path("tests/test_audit.jsonl")
        if self.test_log.exists():
            self.test_log.unlink()

    def tearDown(self):
        if self.test_log.exists():
            self.test_log.unlink()

    def test_log_audit_event_creates_valid_chain(self):
        rec1 = log_audit_event(
            incident_id="INC-001",
            resource="test/pod-1",
            failure_reason="CrashLoopBackOff",
            action="restart_pod",
            risk_score=0.15,
            risk_vector={"c": 0.9, "u": 0.1, "p": 1.0, "r": 0.9, "b": 0.1},
            policy_status="Policy compliant",
            decision="AUTO_EXECUTE",
            authorized_by="dev-1",
            authorizer_role="Developer",
            log_path=self.test_log
        )
        self.assertEqual(rec1["previous_record_hash"], GENESIS_HASH)

        rec2 = log_audit_event(
            incident_id="INC-002",
            resource="test/pod-2",
            failure_reason="OOMKilled",
            action="update_memory_limit",
            risk_score=0.35,
            risk_vector={"c": 0.7, "u": 0.3, "p": 0.9, "r": 0.7, "b": 0.3},
            policy_status="Policy compliant",
            decision="HUMAN_APPROVAL",
            authorized_by="sre-1",
            authorizer_role="SRE-Lead",
            log_path=self.test_log
        )
        self.assertEqual(rec2["previous_record_hash"], rec1["record_hash"])

        valid, msg, count = verify_audit_log_integrity(log_path=self.test_log)
        self.assertTrue(valid)
        self.assertEqual(count, 2)

    def test_tamper_detection_catches_altered_record(self):
        # Create 2 valid entries
        log_audit_event(
            incident_id="INC-001",
            resource="test/pod-1",
            failure_reason="CrashLoopBackOff",
            action="restart_pod",
            risk_score=0.15,
            risk_vector={"c": 0.9, "u": 0.1, "p": 1.0, "r": 0.9, "b": 0.1},
            policy_status="Policy compliant",
            decision="AUTO_EXECUTE",
            authorized_by="dev-1",
            authorizer_role="Developer",
            log_path=self.test_log
        )
        log_audit_event(
            incident_id="INC-002",
            resource="test/pod-2",
            failure_reason="OOMKilled",
            action="update_memory_limit",
            risk_score=0.35,
            risk_vector={"c": 0.7, "u": 0.3, "p": 0.9, "r": 0.7, "b": 0.3},
            policy_status="Policy compliant",
            decision="HUMAN_APPROVAL",
            authorized_by="sre-1",
            authorizer_role="SRE-Lead",
            log_path=self.test_log
        )

        # Tamper with record 1 (change decision)
        lines = self.test_log.read_text(encoding="utf-8").splitlines()
        altered = json.loads(lines[0])
        altered["decision"] = "TAMPERED_ACTION"
        lines[0] = json.dumps(altered)
        self.test_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

        valid, msg, count = verify_audit_log_integrity(log_path=self.test_log)
        self.assertFalse(valid)
        self.assertIn("Tamper detected", msg)


class TestEnterpriseRBAC(unittest.TestCase):
    """Verifies Role-Based Access Control authorization boundaries."""

    def test_sre_lead_can_authorize_medium_risk(self):
        allowed, msg = authorize_approval("SRE-Lead", "HUMAN_APPROVAL")
        self.assertTrue(allowed)
        self.assertIn("Authorized", msg)

    def test_developer_cannot_authorize_medium_risk(self):
        allowed, msg = authorize_approval("Developer", "HUMAN_APPROVAL")
        self.assertFalse(allowed)
        self.assertIn("Authorization Denied", msg)

    def test_developer_can_authorize_low_risk(self):
        allowed, msg = authorize_approval("Developer", "AUTO_EXECUTE")
        self.assertTrue(allowed)

    def test_viewer_cannot_authorize_any_action(self):
        allowed_low, _ = authorize_approval("Viewer", "AUTO_EXECUTE")
        allowed_med, _ = authorize_approval("Viewer", "HUMAN_APPROVAL")
        self.assertFalse(allowed_low)
        self.assertFalse(allowed_med)

    def test_reject_tier_cannot_be_approved_by_any_role(self):
        for role in ["Developer", "SRE-Lead", "Platform-Admin"]:
            allowed, msg = authorize_approval(role, "REJECT")
            self.assertFalse(allowed)
            self.assertIn("cannot be authorized", msg)

    def test_get_current_operator_defaults(self):
        user, role = get_current_operator()
        self.assertTrue(len(user) > 0)
        self.assertIn(role, ["Developer", "SRE-Lead", "Platform-Admin", "Auditor", "Viewer"])


class TestChatOps(unittest.TestCase):
    """Verifies ChatOps alert formatting and local fallback."""

    def test_format_slack_card_fields(self):
        inc = {
            "incident_type": "pod_failure",
            "resource_type": "Pod",
            "resource_name": "demo-app-123",
            "evidence": {"failure_reason": "CrashLoopBackOff"}
        }
        prop = {"action": "restart_pod", "description": "Restart pod"}
        card = format_slack_card(inc, prop, 0.20, "AUTO_EXECUTE", commit_sha="abc1234567")

        self.assertIn("text", card)
        attachments = card["attachments"]
        self.assertEqual(len(attachments), 1)
        fields = {f["title"]: f["value"] for f in attachments[0]["fields"]}
        self.assertEqual(fields["Failure Reason"], "CrashLoopBackOff")
        self.assertEqual(fields["Proposed Action"], "restart_pod")

    def test_send_chatops_local_fallback(self):
        inc = {"incident_type": "pod_failure", "evidence": {}}
        prop = {"action": "restart_pod"}
        # Without webhook URL, logs locally and returns True
        success = send_chatops_notification(inc, prop, 0.15, "AUTO_EXECUTE", webhook_url=None)
        self.assertTrue(success)

    @patch("chatops.urllib.request.urlopen")
    def test_send_chatops_webhook_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        inc = {"incident_type": "pod_failure", "evidence": {}}
        prop = {"action": "restart_pod"}
        success = send_chatops_notification(inc, prop, 0.15, "AUTO_EXECUTE", webhook_url="https://hooks.slack.com/services/mock")
        self.assertTrue(success)


class TestExpandedGitOpsActions(unittest.TestCase):
    """Verifies that gitops_remediation supports expanded actions."""

    def test_supported_gitops_actions_contains_enterprise_set(self):
        self.assertIn("restart_pod", SUPPORTED_GITOPS_ACTIONS)
        self.assertIn("rollback_image", SUPPORTED_GITOPS_ACTIONS)
        self.assertIn("scale_replicas", SUPPORTED_GITOPS_ACTIONS)
        self.assertIn("update_memory_limit", SUPPORTED_GITOPS_ACTIONS)

    def test_scale_replicas_updates_document(self):
        doc = {
            "kind": "Deployment",
            "metadata": {"name": "test-app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "metadata": {"annotations": {}},
                    "spec": {"containers": [{"name": "nginx"}]}
                }
            }
        }
        with patch("gitops_remediation.parse_manifest_documents", return_value=[doc]):
            docs, old_val, annot = update_manifest_action(
                manifest_path=Path("dummy.yaml"),
                action="scale_replicas",
                deployment_name="test-app",
                container_name="nginx",
                restart_id="test-restart"
            )
            self.assertEqual(docs[0]["spec"]["replicas"], 2)
            self.assertEqual(old_val, 1)

    def test_rollback_image_updates_document(self):
        doc = {
            "kind": "Deployment",
            "metadata": {"name": "test-app"},
            "spec": {
                "template": {
                    "metadata": {"annotations": {}},
                    "spec": {"containers": [{"name": "nginx", "image": "nginx:bad-tag"}]}
                }
            }
        }
        with patch("gitops_remediation.parse_manifest_documents", return_value=[doc]):
            docs, old_val, annot = update_manifest_action(
                manifest_path=Path("dummy.yaml"),
                action="rollback_image",
                deployment_name="test-app",
                container_name="nginx",
                restart_id="test-restart"
            )
            self.assertEqual(docs[0]["spec"]["template"]["spec"]["containers"][0]["image"], "nginx:latest")
            self.assertEqual(old_val, "nginx:bad-tag")

    def test_update_memory_limit_updates_document(self):
        doc = {
            "kind": "Deployment",
            "metadata": {"name": "test-app"},
            "spec": {
                "template": {
                    "metadata": {"annotations": {}},
                    "spec": {"containers": [{"name": "nginx", "resources": {"limits": {"memory": "64Mi"}}}]}
                }
            }
        }
        with patch("gitops_remediation.parse_manifest_documents", return_value=[doc]):
            docs, old_val, annot = update_manifest_action(
                manifest_path=Path("dummy.yaml"),
                action="update_memory_limit",
                deployment_name="test-app",
                container_name="nginx",
                restart_id="test-restart"
            )
            limits = docs[0]["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
            self.assertEqual(limits["memory"], "256Mi")
            self.assertEqual(old_val, "64Mi")


class TestOperatorDaemon(unittest.TestCase):
    """Verifies KubeGuardOperator tick loop and deduplication."""

    @patch("kubeguard_operator.detect_incident", return_value=[])
    def test_operator_tick_no_incident(self, mock_detect):
        op = KubeGuardOperator(namespace="test-ns", interval=5)
        processed = op.run_tick()
        self.assertFalse(processed)

    @patch("kubeguard_operator.run_pipeline", return_value=True)
    @patch("kubeguard_operator.select_primary_incident")
    @patch("kubeguard_operator.detect_incident")
    def test_operator_tick_processes_incident_and_cooldown(
        self, mock_detect, mock_select, mock_pipe
    ):
        inc = {"incident_id": "INC-TEST-99", "resource_name": "app-pod"}
        mock_detect.return_value = [inc]
        mock_select.return_value = inc

        op = KubeGuardOperator(namespace="test-ns", interval=5)
        # First tick processes incident
        processed1 = op.run_tick()
        self.assertTrue(processed1)
        mock_pipe.assert_called_once()

        # Immediate second tick is skipped by cooldown cache
        processed2 = op.run_tick()
        self.assertFalse(processed2)
        # pipeline still only called once
        mock_pipe.assert_called_once()



class TestDemoRunner(unittest.TestCase):
    """Verifies helper functions in the demo CLI runner."""

    @patch("builtins.input", return_value="")
    @patch("risk_engine.calculate_risk", return_value=(0.12, "AUTO_EXECUTE"))
    def test_run_risk_simulator_executes_scenarios(self, mock_calc, mock_in):
        import demo
        demo.run_risk_simulator()
        self.assertGreaterEqual(mock_calc.call_count, 3)

    @patch("builtins.input", return_value="")
    @patch("audit_logger.verify_audit_log_integrity", return_value=(True, "Audit log verified", 10))
    def test_run_audit_verification_success(self, mock_verify, mock_in):
        import demo
        demo.run_audit_verification()
        mock_verify.assert_called_once()

    @patch("builtins.input", return_value="")
    @patch("subprocess.run")
    def test_run_test_suite_invokes_subprocess(self, mock_sub, mock_in):
        import demo
        demo.run_test_suite()
        mock_sub.assert_called_once()


if __name__ == "__main__":
    unittest.main()

