import unittest
from unittest.mock import patch, MagicMock
from kubernetes.client.exceptions import ApiException
from validator import validate_remediation


class TestValidator(unittest.TestCase):

    def _create_mock_argo_app(
        self,
        sync_status="Synced",
        health_status="Healthy",
        revision="abc1234567890abcdef1234567890abcdef12",
        target_revision="implementation-baseline"
    ):
        return {
            "spec": {
                "source": {
                    "targetRevision": target_revision,
                    "repoURL": "https://github.com/AIJAY-G/ai-remediation-gitops.git"
                }
            },
            "status": {
                "sync": {
                    "status": sync_status,
                    "revision": revision
                },
                "health": {
                    "status": health_status
                }
            }
        }

    def _create_mock_deployment(self, replicas=1, ready=1, updated=1, available=1):
        deployment = MagicMock()
        deployment.spec.replicas = replicas
        deployment.status.ready_replicas = ready
        deployment.status.updated_replicas = updated
        deployment.status.available_replicas = available
        return deployment

    @patch("validator.config.load_kube_config")
    @patch("validator.client.CustomObjectsApi")
    @patch("validator.client.AppsV1Api")
    def test_existing_successful_gitops_validation_passes(self, mock_apps_api_cls, mock_custom_api_cls, mock_load_config):
        # Successful GitOps validation: Synced, Healthy, exact 40-char SHA match, matching branch, ready replicas
        mock_custom = mock_custom_api_cls.return_value
        mock_apps = mock_apps_api_cls.return_value

        full_commit_sha = "abcdef1234567890abcdef1234567890abcdef12"
        mock_custom.get_namespaced_custom_object.return_value = self._create_mock_argo_app(
            sync_status="Synced",
            health_status="Healthy",
            revision=full_commit_sha,
            target_revision="implementation-baseline"
        )
        mock_apps.read_namespaced_deployment.return_value = self._create_mock_deployment()

        success = validate_remediation(
            expected_commit=full_commit_sha,
            expected_branch="implementation-baseline",
            timeout=2,
            interval=0.05
        )
        self.assertTrue(success)

    @patch("validator.config.load_kube_config")
    @patch("validator.client.CustomObjectsApi")
    @patch("validator.client.AppsV1Api")
    def test_branch_mismatch_fails_validation(self, mock_apps_api_cls, mock_custom_api_cls, mock_load_config):
        # Branch mismatch: Argo CD has targetRevision="main", but expected_branch is "implementation-baseline"
        mock_custom = mock_custom_api_cls.return_value
        mock_apps = mock_apps_api_cls.return_value

        full_commit_sha = "abcdef1234567890abcdef1234567890abcdef12"
        mock_custom.get_namespaced_custom_object.return_value = self._create_mock_argo_app(
            sync_status="Synced",
            health_status="Healthy",
            revision=full_commit_sha,
            target_revision="main"
        )
        mock_apps.read_namespaced_deployment.return_value = self._create_mock_deployment()

        success = validate_remediation(
            expected_commit=full_commit_sha,
            expected_branch="implementation-baseline",
            timeout=0.2,
            interval=0.05
        )
        # Branch mismatch must fail validation
        self.assertFalse(success)

    @patch("validator.config.load_kube_config")
    @patch("validator.client.CustomObjectsApi")
    @patch("validator.client.AppsV1Api")
    def test_incorrect_or_older_commit_revision_fails_validation(self, mock_apps_api_cls, mock_custom_api_cls, mock_load_config):
        mock_custom = mock_custom_api_cls.return_value
        mock_apps = mock_apps_api_cls.return_value

        old_commit = "1111111111111111111111111111111111111111"
        expected_commit = "2222222222222222222222222222222222222222"

        # Argo CD is Synced and Healthy, but with an older / incorrect revision
        mock_custom.get_namespaced_custom_object.return_value = self._create_mock_argo_app(
            sync_status="Synced",
            health_status="Healthy",
            revision=old_commit,
            target_revision="implementation-baseline"
        )
        mock_apps.read_namespaced_deployment.return_value = self._create_mock_deployment()

        success = validate_remediation(
            expected_commit=expected_commit,
            expected_branch="implementation-baseline",
            timeout=0.2,
            interval=0.05
        )
        # Must fail because Argo CD has not synchronized the expected commit
        self.assertFalse(success)

    @patch("validator.config.load_kube_config")
    @patch("validator.client.CustomObjectsApi")
    @patch("validator.client.AppsV1Api")
    def test_validation_fails_when_argocd_out_of_sync(self, mock_apps_api_cls, mock_custom_api_cls, mock_load_config):
        mock_custom = mock_custom_api_cls.return_value
        mock_apps = mock_apps_api_cls.return_value

        commit_sha = "abcdef1234567890abcdef1234567890abcdef12"
        mock_custom.get_namespaced_custom_object.return_value = self._create_mock_argo_app(
            sync_status="OutOfSync",
            health_status="Healthy",
            revision=commit_sha,
            target_revision="implementation-baseline"
        )
        mock_apps.read_namespaced_deployment.return_value = self._create_mock_deployment()

        success = validate_remediation(
            expected_commit=commit_sha,
            expected_branch="implementation-baseline",
            timeout=0.2,
            interval=0.05
        )
        self.assertFalse(success)

    @patch("validator.config.load_kube_config")
    @patch("validator.client.CustomObjectsApi")
    @patch("validator.client.AppsV1Api")
    def test_validation_fails_when_deployment_unready(self, mock_apps_api_cls, mock_custom_api_cls, mock_load_config):
        mock_custom = mock_custom_api_cls.return_value
        mock_apps = mock_apps_api_cls.return_value

        commit_sha = "abcdef1234567890abcdef1234567890abcdef12"
        mock_custom.get_namespaced_custom_object.return_value = self._create_mock_argo_app(
            sync_status="Synced",
            health_status="Healthy",
            revision=commit_sha,
            target_revision="implementation-baseline"
        )
        mock_apps.read_namespaced_deployment.return_value = self._create_mock_deployment(
            replicas=1, ready=0, updated=1, available=0
        )

        success = validate_remediation(
            expected_commit=commit_sha,
            expected_branch="implementation-baseline",
            timeout=0.2,
            interval=0.05
        )
        self.assertFalse(success)

    @patch("validator.config.load_kube_config")
    @patch("validator.client.CustomObjectsApi")
    @patch("validator.client.AppsV1Api")
    def test_handles_missing_argocd_resource_gracefully(self, mock_apps_api_cls, mock_custom_api_cls, mock_load_config):
        mock_custom = mock_custom_api_cls.return_value
        mock_apps = mock_apps_api_cls.return_value

        mock_custom.get_namespaced_custom_object.side_effect = ApiException(status=404, reason="Not Found")
        mock_apps.read_namespaced_deployment.return_value = self._create_mock_deployment()

        success = validate_remediation(timeout=0.2, interval=0.05)
        self.assertFalse(success)

    @patch("validator.config.load_kube_config")
    @patch("validator.client.CustomObjectsApi")
    @patch("validator.client.AppsV1Api")
    def test_handles_missing_deployment_gracefully(self, mock_apps_api_cls, mock_custom_api_cls, mock_load_config):
        mock_custom = mock_custom_api_cls.return_value
        mock_apps = mock_apps_api_cls.return_value

        mock_custom.get_namespaced_custom_object.return_value = self._create_mock_argo_app()
        mock_apps.read_namespaced_deployment.side_effect = ApiException(status=404, reason="Not Found")

        success = validate_remediation(timeout=0.2, interval=0.05)
        self.assertFalse(success)

    @patch("validator.config.load_kube_config")
    def test_handles_kubeconfig_failure_gracefully(self, mock_load_config):
        mock_load_config.side_effect = Exception("kubeconfig not found")
        success = validate_remediation(timeout=0.2, interval=0.05)
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
