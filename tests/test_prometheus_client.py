import io
import json
import unittest
from urllib.error import URLError
from unittest.mock import patch, MagicMock

from prometheus_client import (
    PrometheusClient,
    PrometheusClientError,
    query_prometheus_safely,
)


def _mock_http_response(body_dict, status=200):
    raw_bytes = json.dumps(body_dict).encode("utf-8")
    resp = io.BytesIO(raw_bytes)
    resp.status = status
    return resp


class TestPrometheusClient(unittest.TestCase):

    def setUp(self):
        self.client = PrometheusClient(base_url="http://mock-prometheus:9090", timeout=2.0)

    @patch("prometheus_client.urllib.request.urlopen")
    def test_check_health_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        self.assertTrue(self.client.check_health())

    @patch("prometheus_client.urllib.request.urlopen")
    def test_check_health_connection_error(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("Connection refused")
        self.assertFalse(self.client.check_health())

    def test_empty_query_raises_error(self):
        with self.assertRaises(PrometheusClientError):
            self.client.query("")
        with self.assertRaises(PrometheusClientError):
            self.client.query("   ")
        with self.assertRaises(PrometheusClientError):
            self.client.query(None)

    @patch("prometheus_client.urllib.request.urlopen")
    def test_query_success_parses_vector_results(self, mock_urlopen):
        sample_payload = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"container": "nginx", "pod": "demo-app-123"},
                        "value": [1700000000.0, "3"]
                    }
                ]
            }
        }
        mock_urlopen.return_value.__enter__.return_value = _mock_http_response(sample_payload)

        results = self.client.query("kube_pod_container_status_restarts_total")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metric"]["container"], "nginx")
        self.assertEqual(results[0]["value"][1], "3")

    @patch("prometheus_client.urllib.request.urlopen")
    def test_query_handles_server_error_status(self, mock_urlopen):
        error_payload = {
            "status": "error",
            "error": "execution timed out"
        }
        mock_urlopen.return_value.__enter__.return_value = _mock_http_response(error_payload)

        with self.assertRaises(PrometheusClientError) as ctx:
            self.client.query("up")
        self.assertIn("execution timed out", str(ctx.exception))

    @patch("prometheus_client.urllib.request.urlopen")
    def test_query_handles_malformed_json(self, mock_urlopen):
        bad_resp = io.BytesIO(b"Not valid JSON response")
        bad_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = bad_resp

        with self.assertRaises(PrometheusClientError):
            self.client.query("up")

    @patch("prometheus_client.urllib.request.urlopen")
    def test_query_handles_connection_failure(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("Network is unreachable")

        with self.assertRaises(PrometheusClientError) as ctx:
            self.client.query("up")
        self.assertIn("Failed to connect", str(ctx.exception))

    @patch("prometheus_client.urllib.request.urlopen")
    def test_query_handles_timeout_error(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError("Timed out")

        with self.assertRaises(PrometheusClientError):
            self.client.query("up")

    @patch.object(PrometheusClient, "query")
    def test_get_container_restart_count_success(self, mock_query):
        mock_query.return_value = [
            {
                "metric": {"container": "nginx"},
                "value": [1700000000.0, "5"]
            }
        ]
        count = self.client.get_container_restart_count("ai-remediation", "nginx")
        self.assertEqual(count, 5)

    @patch.object(PrometheusClient, "query")
    def test_get_container_restart_count_with_pod_name(self, mock_query):
        mock_query.return_value = [
            {
                "metric": {"container": "nginx", "pod": "demo-app-xyz"},
                "value": [1700000000.0, "2"]
            }
        ]
        count = self.client.get_container_restart_count("ai-remediation", "nginx", pod="demo-app-xyz")
        self.assertEqual(count, 2)
        mock_query.assert_called_once()
        self.assertIn('pod="demo-app-xyz"', mock_query.call_args[0][0])

    @patch.object(PrometheusClient, "query")
    def test_get_container_restart_count_empty_result(self, mock_query):
        mock_query.return_value = []
        count = self.client.get_container_restart_count("ai-remediation", "nginx")
        self.assertIsNone(count)

    @patch.object(PrometheusClient, "query")
    def test_get_container_restart_count_handles_exception(self, mock_query):
        mock_query.side_effect = PrometheusClientError("connection refused")
        count = self.client.get_container_restart_count("ai-remediation", "nginx")
        self.assertIsNone(count)

    @patch.object(PrometheusClient, "query")
    def test_get_deployment_metrics_success(self, mock_query):
        def side_effect(query_str):
            if "replicas_available" in query_str:
                return [{"value": [1700000000.0, "1"]}]
            if "spec_replicas" in query_str:
                return [{"value": [1700000000.0, "1"]}]
            return []

        mock_query.side_effect = side_effect
        metrics = self.client.get_deployment_metrics("ai-remediation", "demo-app")
        self.assertEqual(metrics.get("available_replicas"), 1)
        self.assertEqual(metrics.get("desired_replicas"), 1)

    @patch.object(PrometheusClient, "query")
    def test_query_prometheus_safely_success(self, mock_query):
        mock_query.return_value = [{"value": [1, "1"]}]
        res = query_prometheus_safely("up")
        self.assertIsNotNone(res)

    @patch.object(PrometheusClient, "query")
    def test_query_prometheus_safely_handles_error(self, mock_query):
        mock_query.side_effect = PrometheusClientError("failed")
        res = query_prometheus_safely("up")
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
