
import unittest
from unittest.mock import patch, MagicMock

from llm_proposal import ProposalError
from gitops_remediation import RemediationResult
from main import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_INCIDENT = {
    "incident_id": "INC-demo-app-xyz",
    "incident_type": "pod_failure",
    "severity": "medium",
    "namespace": "ai-remediation",
    "resource_type": "Pod",
    "resource_name": "demo-app-xyz",
    "status": "detected",
    "detected_at": "2026-01-01T00:00:00+00:00",
    "evidence": {
        "pod_phase": "Running",
        "container_ready": False,
        "restart_count": 5,
        "failure_reason": "CrashLoopBackOff",
    },
}

VALID_PROPOSAL = {
    "incident": "pod_failure",
    "action": "restart_pod",
    "description": "Restart the failed pod.",
    "confidence": 0.90,
    "uncertainty": 0.10,
    "policy_compliance": 1.00,
    "reversibility": 0.90,
    "blast_radius": 0.10,
}


def _successful_gitops_result():
    return RemediationResult(
        success=True,
        commit="abc1234567890abcdef1234567890abcdef123456",
        branch="implementation-baseline",
        message="Remediation committed and pushed",
    )


def _failed_gitops_result():
    return RemediationResult(
        success=False,
        commit=None,
        branch="implementation-baseline",
        message="Git push failed",
    )


# All patches target the *names as imported by main.py*
PATCH_DETECT = "main.detect_incident"
PATCH_SELECT = "main.select_primary_incident"
PATCH_GENERATE = "main.generate_remediation"
PATCH_CALCULATE = "main.calculate_risk"
PATCH_GITOPS = "main.apply_gitops_remediation"
PATCH_VALIDATE = "main.validate_remediation"
PATCH_INPUT = "builtins.input"


# ===================================================================
# Test cases
# ===================================================================


class TestNoIncidentDetected(unittest.TestCase):
    """Workflow exits without proposal or execution when no incidents."""

    @patch(PATCH_GENERATE)
    @patch(PATCH_DETECT, return_value=[])
    def test_empty_incident_list(self, mock_detect, mock_generate):
        main()
        mock_detect.assert_called_once()
        mock_generate.assert_not_called()

    @patch(PATCH_GENERATE)
    @patch(PATCH_SELECT, return_value=None)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_no_valid_primary_incident(
        self, mock_detect, mock_select, mock_generate
    ):
        main()
        mock_select.assert_called_once()
        mock_generate.assert_not_called()


class TestLLMProposalFailure(unittest.TestCase):
    """Fail safely when the LLM proposal is rejected or unreachable."""

    @patch(PATCH_GITOPS)
    @patch(PATCH_CALCULATE)
    @patch(PATCH_GENERATE, side_effect=ProposalError("Connection refused"))
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_ollama_connection_failure(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_gitops,
    ):
        main()
        mock_generate.assert_called_once()
        mock_calculate.assert_not_called()
        mock_gitops.assert_not_called()

    @patch(PATCH_GITOPS)
    @patch(PATCH_CALCULATE)
    @patch(
        PATCH_GENERATE,
        side_effect=ProposalError("Unsupported incident type: unknown"),
    )
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_unsupported_incident_type(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_gitops,
    ):
        main()
        mock_calculate.assert_not_called()
        mock_gitops.assert_not_called()


class TestRejectDecision(unittest.TestCase):
    """Remediation is blocked when risk engine returns REJECT."""

    @patch(PATCH_GITOPS)
    @patch(PATCH_INPUT)
    @patch(PATCH_CALCULATE, return_value=(0.80, "REJECT"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_reject_blocks_execution(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
    ):
        main()
        mock_input.assert_not_called()
        mock_gitops.assert_not_called()


class TestAutoExecuteDowngrade(unittest.TestCase):
    """AUTO_EXECUTE is always downgraded to HUMAN_APPROVAL."""

    @patch(PATCH_GITOPS, return_value=_successful_gitops_result())
    @patch(PATCH_VALIDATE, return_value=True)
    @patch(PATCH_INPUT, return_value="yes")
    @patch(PATCH_CALCULATE, return_value=(0.10, "AUTO_EXECUTE"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_auto_execute_still_requires_human_approval(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_validate,
        mock_gitops,
    ):
        """Human input must be solicited even when risk is AUTO_EXECUTE."""
        main()
        mock_input.assert_called_once()
        mock_gitops.assert_called_once()

    @patch(PATCH_GITOPS)
    @patch(PATCH_INPUT, return_value="no")
    @patch(PATCH_CALCULATE, return_value=(0.10, "AUTO_EXECUTE"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_auto_execute_denied_blocks_execution(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
    ):
        """Even AUTO_EXECUTE can be denied by the human."""
        main()
        mock_input.assert_called_once()
        mock_gitops.assert_not_called()


class TestHumanApprovalDenied(unittest.TestCase):
    """No GitOps execution when human denies approval."""

    @patch(PATCH_GITOPS)
    @patch(PATCH_INPUT, return_value="no")
    @patch(PATCH_CALCULATE, return_value=(0.40, "HUMAN_APPROVAL"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_denial_blocks_gitops(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
    ):
        main()
        mock_input.assert_called_once()
        mock_gitops.assert_not_called()

    @patch(PATCH_GITOPS)
    @patch(PATCH_INPUT, return_value="  NO  ")
    @patch(PATCH_CALCULATE, return_value=(0.40, "HUMAN_APPROVAL"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_non_yes_input_blocks_gitops(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
    ):
        """Any input other than exact 'yes' (case-insensitive) is denial."""
        main()
        mock_gitops.assert_not_called()


class TestHumanApprovalGranted(unittest.TestCase):
    """GitOps is invoked and validation receives exact commit and branch."""

    @patch(PATCH_VALIDATE, return_value=True)
    @patch(PATCH_GITOPS, return_value=_successful_gitops_result())
    @patch(PATCH_INPUT, return_value="yes")
    @patch(PATCH_CALCULATE, return_value=(0.40, "HUMAN_APPROVAL"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_full_success_path(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
        mock_validate,
    ):
        main()

        # GitOps invoked with the proposal action
        mock_gitops.assert_called_once_with("restart_pod")

        # Validation receives the exact commit and branch from GitOps
        mock_validate.assert_called_once()
        call_kwargs = mock_validate.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("expected_commit")
            or call_kwargs[1].get("expected_commit"),
            "abc1234567890abcdef1234567890abcdef123456",
        )
        self.assertEqual(
            call_kwargs.kwargs.get("expected_branch")
            or call_kwargs[1].get("expected_branch"),
            "implementation-baseline",
        )

    @patch(PATCH_VALIDATE, return_value=True)
    @patch(PATCH_GITOPS, return_value=_successful_gitops_result())
    @patch(PATCH_INPUT, return_value="  Yes  ")
    @patch(PATCH_CALCULATE, return_value=(0.40, "HUMAN_APPROVAL"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_case_insensitive_yes(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
        mock_validate,
    ):
        """'Yes', ' YES ', etc. are all accepted."""
        main()
        mock_gitops.assert_called_once()
        mock_validate.assert_called_once()


class TestGitOpsExecutionFailure(unittest.TestCase):
    """Validation is NOT reported as successful after GitOps failure."""

    @patch(PATCH_VALIDATE)
    @patch(PATCH_GITOPS, return_value=_failed_gitops_result())
    @patch(PATCH_INPUT, return_value="yes")
    @patch(PATCH_CALCULATE, return_value=(0.40, "HUMAN_APPROVAL"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_gitops_failure_skips_validation(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
        mock_validate,
    ):
        main()
        mock_gitops.assert_called_once()
        # Validation must NOT be called after GitOps failure
        mock_validate.assert_not_called()


class TestInvalidOrUnsupportedProposal(unittest.TestCase):
    """Fail closed when proposal validation rejects the LLM output."""

    @patch(PATCH_GITOPS)
    @patch(PATCH_CALCULATE)
    @patch(
        PATCH_GENERATE,
        side_effect=ProposalError("Unsupported remediation action: delete_namespace"),
    )
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_unsupported_action_fails_closed(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_gitops,
    ):
        main()
        mock_calculate.assert_not_called()
        mock_gitops.assert_not_called()

    @patch(PATCH_GITOPS)
    @patch(PATCH_CALCULATE)
    @patch(
        PATCH_GENERATE,
        side_effect=ProposalError("LLM response has missing or unexpected fields."),
    )
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_invalid_schema_fails_closed(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_gitops,
    ):
        main()
        mock_calculate.assert_not_called()
        mock_gitops.assert_not_called()

    @patch(PATCH_GITOPS)
    @patch(PATCH_CALCULATE)
    @patch(
        PATCH_GENERATE,
        side_effect=ProposalError("Invalid Ollama response: Expecting value"),
    )
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_malformed_llm_json_fails_closed(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_gitops,
    ):
        main()
        mock_calculate.assert_not_called()
        mock_gitops.assert_not_called()


class TestCustomWorkloadWorkflow(unittest.TestCase):
    """Workflow supports isolated namespaces and custom workloads."""

    @patch(PATCH_VALIDATE, return_value=True)
    @patch(PATCH_GITOPS, return_value=_successful_gitops_result())
    @patch(PATCH_INPUT, return_value="yes")
    @patch(PATCH_CALCULATE, return_value=(0.10, "AUTO_EXECUTE"))
    @patch(PATCH_GENERATE, return_value=VALID_PROPOSAL)
    @patch(PATCH_SELECT, return_value=SAMPLE_INCIDENT)
    @patch(PATCH_DETECT, return_value=[SAMPLE_INCIDENT])
    def test_custom_parameters_forwarded(
        self,
        mock_detect,
        mock_select,
        mock_generate,
        mock_calculate,
        mock_input,
        mock_gitops,
        mock_validate,
    ):
        from pathlib import Path
        custom_manifest = Path("gitops-lab/lab-app.yaml")
        main(
            namespace="kube-guard-lab",
            deployment_name="lab-app",
            manifest_path=custom_manifest,
            container_name="nginx",
            application_name="kube-guard-lab"
        )
        mock_detect.assert_called_once_with(namespace="kube-guard-lab")
        mock_gitops.assert_called_once_with(
            "restart_pod",
            manifest_path=custom_manifest,
            deployment_name="lab-app",
            container_name="nginx"
        )
        mock_validate.assert_called_once()
        self.assertEqual(
            mock_validate.call_args.kwargs.get("namespace"),
            "kube-guard-lab"
        )
        self.assertEqual(
            mock_validate.call_args.kwargs.get("deployment_name"),
            "lab-app"
        )
        self.assertEqual(
            mock_validate.call_args.kwargs.get("application_name"),
            "kube-guard-lab"
        )


if __name__ == "__main__":
    unittest.main()
