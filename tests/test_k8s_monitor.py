import unittest
from unittest.mock import patch, MagicMock
from kubernetes.client.exceptions import ApiException

from k8s_monitor import detect_incident, select_primary_incident


def _create_mock_pod(
    name="demo-app-123",
    phase="Running",
    container_name="nginx",
    ready=True,
    restart_count=0,
    waiting_reason=None,
    terminated_reason=None,
    exit_code=0
):
    pod = MagicMock()
    pod.metadata.name = name
    pod.status.phase = phase

    container = MagicMock()
    container.name = container_name
    container.ready = ready
    container.restart_count = restart_count

    if waiting_reason:
        container.state.waiting.reason = waiting_reason
    else:
        container.state.waiting = None

    if terminated_reason or exit_code != 0:
        container.state.terminated.reason = terminated_reason
        container.state.terminated.exit_code = exit_code
    else:
        container.state.terminated = None

    pod.status.container_statuses = [container]
    return pod


def _create_mock_deployment(name="demo-app", desired=1, available=1, ready=1):
    dep = MagicMock()
    dep.metadata.name = name
    dep.spec.replicas = desired
    dep.status.available_replicas = available
    dep.status.ready_replicas = ready
    return dep


class TestK8sMonitor(unittest.TestCase):

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    @patch("k8s_monitor.client.AppsV1Api")
    def test_detect_crashloop_backoff(self, mock_apps_cls, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_apps = mock_apps_cls.return_value

        pod = _create_mock_pod(
            name="crash-pod",
            ready=False,
            restart_count=3,
            waiting_reason="CrashLoopBackOff"
        )
        mock_core.list_namespaced_pod.return_value.items = [pod]
        mock_apps.list_namespaced_deployment.return_value.items = []

        incidents = detect_incident()
        self.assertGreaterEqual(len(incidents), 1)

        primary = select_primary_incident(incidents)
        self.assertEqual(primary["incident_type"], "pod_failure")
        self.assertEqual(primary["resource_name"], "crash-pod")
        self.assertEqual(primary["evidence"]["failure_reason"], "CrashLoopBackOff")

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    @patch("k8s_monitor.client.AppsV1Api")
    def test_detect_image_pull_failure(self, mock_apps_cls, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_apps = mock_apps_cls.return_value

        pod = _create_mock_pod(
            name="image-pod",
            ready=False,
            waiting_reason="ImagePullBackOff"
        )
        mock_core.list_namespaced_pod.return_value.items = [pod]
        mock_apps.list_namespaced_deployment.return_value.items = []

        incidents = detect_incident()
        primary = select_primary_incident(incidents)
        self.assertEqual(primary["incident_type"], "pod_failure")
        self.assertEqual(primary["evidence"]["failure_reason"], "ImagePullBackOff")

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    @patch("k8s_monitor.client.AppsV1Api")
    def test_detect_oom_killed(self, mock_apps_cls, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_apps = mock_apps_cls.return_value

        pod = _create_mock_pod(
            name="oom-pod",
            ready=False,
            restart_count=1,
            terminated_reason="OOMKilled",
            exit_code=137
        )
        mock_core.list_namespaced_pod.return_value.items = [pod]
        mock_apps.list_namespaced_deployment.return_value.items = []

        incidents = detect_incident()
        primary = select_primary_incident(incidents)
        self.assertEqual(primary["incident_type"], "pod_failure")
        self.assertEqual(primary["evidence"]["failure_reason"], "OOMKilled")

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    @patch("k8s_monitor.client.AppsV1Api")
    def test_detect_excessive_restarts_while_ready(self, mock_apps_cls, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_apps = mock_apps_cls.return_value

        # Pod with 6 restarts but currently marked ready
        pod = _create_mock_pod(
            name="flapping-pod",
            ready=True,
            restart_count=6
        )
        mock_core.list_namespaced_pod.return_value.items = [pod]
        mock_apps.list_namespaced_deployment.return_value.items = []

        incidents = detect_incident()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["incident_type"], "pod_restart")
        self.assertEqual(incidents[0]["resource_name"], "flapping-pod")

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    @patch("k8s_monitor.client.AppsV1Api")
    def test_detect_deployment_replica_deficit(self, mock_apps_cls, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_apps = mock_apps_cls.return_value

        mock_core.list_namespaced_pod.return_value.items = []
        dep = _create_mock_deployment(name="demo-app", desired=3, available=1, ready=1)
        mock_apps.list_namespaced_deployment.return_value.items = [dep]

        incidents = detect_incident()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["incident_type"], "deployment_failure")
        self.assertEqual(incidents[0]["evidence"]["desired_replicas"], 3)
        self.assertEqual(incidents[0]["evidence"]["available_replicas"], 1)

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    @patch("k8s_monitor.client.AppsV1Api")
    def test_healthy_cluster_detects_no_incidents(self, mock_apps_cls, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_apps = mock_apps_cls.return_value

        pod = _create_mock_pod(name="healthy-pod", ready=True, restart_count=0)
        dep = _create_mock_deployment(name="demo-app", desired=1, available=1, ready=1)
        mock_core.list_namespaced_pod.return_value.items = [pod]
        mock_apps.list_namespaced_deployment.return_value.items = [dep]

        incidents = detect_incident()
        self.assertEqual(len(incidents), 0)

    @patch("k8s_monitor.config.load_kube_config", side_effect=Exception("No kubeconfig"))
    def test_kubeconfig_failure_returns_empty_list(self, mock_load):
        incidents = detect_incident()
        self.assertEqual(incidents, [])

    @patch("k8s_monitor.config.load_kube_config")
    @patch("k8s_monitor.client.CoreV1Api")
    def test_api_exception_returns_empty_list(self, mock_core_cls, mock_load):
        mock_core = mock_core_cls.return_value
        mock_core.list_namespaced_pod.side_effect = ApiException(status=500, reason="API error")

        incidents = detect_incident()
        self.assertEqual(incidents, [])


if __name__ == "__main__":
    unittest.main()
