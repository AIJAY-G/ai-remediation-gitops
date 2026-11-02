import unittest
from unittest.mock import patch, MagicMock
from kubernetes.client.exceptions import ApiException
from executor import execute_direct_remediation, execute_remediation


class TestLegacyExecutor(unittest.TestCase):

    def test_reject_decision_blocks_execution(self):
        result = execute_direct_remediation("restart_pod", "REJECT")
        self.assertFalse(result)

    @patch("builtins.input", return_value="no")
    def test_human_approval_denied_blocks_execution(self, mock_input):
        result = execute_direct_remediation("restart_pod", "HUMAN_APPROVAL")
        self.assertFalse(result)

    @patch("builtins.input", return_value="yes")
    @patch("executor.config.load_kube_config")
    @patch("executor.client.AppsV1Api")
    def test_direct_remediation_success(self, mock_apps_api_cls, mock_config, mock_input):
        mock_apps = mock_apps_api_cls.return_value
        result = execute_direct_remediation("restart_pod", "HUMAN_APPROVAL")
        self.assertTrue(result)
        mock_apps.patch_namespaced_deployment.assert_called_once()

    @patch("builtins.input", return_value="yes")
    @patch("executor.config.load_kube_config")
    @patch("executor.client.AppsV1Api")
    def test_direct_remediation_handles_api_exception(self, mock_apps_api_cls, mock_config, mock_input):
        mock_apps = mock_apps_api_cls.return_value
        mock_apps.patch_namespaced_deployment.side_effect = ApiException(status=500, reason="Server Error")
        result = execute_direct_remediation("restart_pod", "HUMAN_APPROVAL")
        self.assertFalse(result)

    def test_backward_compatibility_alias(self):
        self.assertIs(execute_remediation, execute_direct_remediation)


if __name__ == "__main__":
    unittest.main()
