
import io
import json
import unittest
from unittest.mock import patch

from llm_proposal import (
    ProposalError,
    _validate_proposal,
    generate_remediation,
)


def valid_proposal():
    return {
        "incident": "pod_failure",
        "action": "restart_pod",
        "description": "Restart the failed pod.",
        "confidence": 0.8,
        "uncertainty": 0.2,
        "policy_compliance": 0.9,
        "reversibility": 0.7,
        "blast_radius": 0.1,
    }


def mock_ollama_response(proposal):
    response_body = {
        "message": {
            "content": json.dumps(proposal)
        }
    }
    return io.BytesIO(json.dumps(response_body).encode("utf-8"))


class TestProposalValidation(unittest.TestCase):

    def test_valid_proposal_is_accepted(self):
        proposal = _validate_proposal(
            valid_proposal(), "pod_failure"
        )
        self.assertEqual(proposal["action"], "restart_pod")

    def test_unsupported_action_is_rejected(self):
        proposal = valid_proposal()
        proposal["action"] = "delete_namespace"

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_mismatched_incident_is_rejected(self):
        proposal = valid_proposal()
        proposal["incident"] = "deployment_failure"

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_missing_field_is_rejected(self):
        proposal = valid_proposal()
        del proposal["confidence"]

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_unexpected_field_is_rejected(self):
        proposal = valid_proposal()
        proposal["extra_command"] = "unsafe"

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_out_of_range_score_is_rejected(self):
        proposal = valid_proposal()
        proposal["confidence"] = 1.5

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_negative_score_is_rejected(self):
        proposal = valid_proposal()
        proposal["uncertainty"] = -0.1

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_boolean_score_is_rejected(self):
        proposal = valid_proposal()
        proposal["confidence"] = True

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_nan_score_is_rejected(self):
        proposal = valid_proposal()
        proposal["confidence"] = float("nan")

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")

    def test_empty_description_is_rejected(self):
        proposal = valid_proposal()
        proposal["description"] = "   "

        with self.assertRaises(ProposalError):
            _validate_proposal(proposal, "pod_failure")


class TestOllamaIntegration(unittest.TestCase):

    @patch("llm_proposal.urllib.request.urlopen")
    def test_successful_ollama_response(self, mock_urlopen):
        mock_urlopen.return_value = mock_ollama_response(
            valid_proposal()
        )

        proposal = generate_remediation("pod_failure")

        self.assertEqual(proposal["action"], "restart_pod")
        self.assertEqual(proposal["incident"], "pod_failure")
        mock_urlopen.assert_called_once()

    @patch("llm_proposal.urllib.request.urlopen")
    def test_dict_incident_input(self, mock_urlopen):
        mock_urlopen.return_value = mock_ollama_response(
            valid_proposal()
        )

        proposal = generate_remediation({
            "incident_type": "pod_failure",
            "resource_name": "demo-app",
        })

        self.assertEqual(proposal["incident"], "pod_failure")

    def test_unsupported_incident_is_rejected_before_api_call(self):
        with patch(
            "llm_proposal.urllib.request.urlopen"
        ) as mock_urlopen:
            with self.assertRaises(ProposalError):
                generate_remediation("deployment_failure")

            mock_urlopen.assert_not_called()

    @patch("llm_proposal.urllib.request.urlopen")
    def test_ollama_connection_error(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")

        with self.assertRaises(ProposalError):
            generate_remediation("pod_failure")

    @patch("llm_proposal.urllib.request.urlopen")
    def test_invalid_ollama_json_response(self, mock_urlopen):
        mock_urlopen.return_value = io.BytesIO(
            b'{"message": {"content": "not valid json"}}'
        )

        with self.assertRaises(ProposalError):
            generate_remediation("pod_failure")


if __name__ == "__main__":
    unittest.main()
