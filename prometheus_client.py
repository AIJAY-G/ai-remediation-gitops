"""
Prometheus Client Module for KubeGuard AI.

Provides safe, optional querying of Prometheus telemetry in Kubernetes clusters.
Designed to fail gracefully: if Prometheus is unreachable or metrics are absent,
returns None or empty collections without interrupting core Kubernetes operations.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("PROMETHEUS_TIMEOUT", "5.0"))


class PrometheusClientError(Exception):
    """Raised when a fatal or malformed response occurs during a query."""
    pass


class PrometheusClient:
    """
    Lightweight, robust client for querying Prometheus Instant Query API.
    Supports standard HTTP endpoints and optional Kubernetes API service proxy fallback.
    """

    def __init__(self, base_url=None, timeout=None):
        self.base_url = (base_url or DEFAULT_PROMETHEUS_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS

    def check_health(self) -> bool:
        """
        Checks whether the Prometheus endpoint is reachable.
        Returns True if reachable and healthy, False otherwise.
        """
        health_url = f"{self.base_url}/-/healthy"
        req = urllib.request.Request(health_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def query(self, promql: str) -> list[dict]:
        """
        Executes an instant query against /api/v1/query.
        Returns the parsed 'result' list of metrics, or empty list on missing/empty results.
        Raises PrometheusClientError on HTTP errors, timeouts, or malformed responses.
        """
        if not promql or not isinstance(promql, str) or not promql.strip():
            raise PrometheusClientError("PromQL query string must be non-empty.")

        params = urllib.parse.urlencode({"query": promql.strip()})
        query_url = f"{self.base_url}/api/v1/query?{params}"
        req = urllib.request.Request(
            query_url,
            headers={"Accept": "application/json"},
            method="GET"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise PrometheusClientError(f"Prometheus returned HTTP status {resp.status}")
                raw_data = resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError) as err:
            raise PrometheusClientError(f"Failed to connect to Prometheus at {self.base_url}: {err}") from err
        except Exception as err:
            raise PrometheusClientError(f"Unexpected error communicating with Prometheus: {err}") from err

        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError as err:
            raise PrometheusClientError(f"Malformed JSON response from Prometheus: {err}") from err

        if not isinstance(payload, dict):
            raise PrometheusClientError("Prometheus response root must be a JSON object.")

        status = payload.get("status")
        if status != "success":
            error_msg = payload.get("error", "Unknown Prometheus server error")
            raise PrometheusClientError(f"Prometheus query failed: {error_msg}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise PrometheusClientError("Prometheus 'data' field missing or invalid.")

        results = data.get("result", [])
        if not isinstance(results, list):
            raise PrometheusClientError("Prometheus 'result' field must be a list.")

        return results

    def get_container_restart_count(
        self,
        namespace: str = "ai-remediation",
        container: str = "nginx",
        pod: str = None
    ) -> int | None:
        """
        Queries kube_pod_container_status_restarts_total for the given namespace and container.
        Returns the integer restart count if available, or None if unavailable.
        """
        if pod:
            query_str = (
                f'kube_pod_container_status_restarts_total{{'
                f'namespace="{namespace}",container="{container}",pod="{pod}"}}'
            )
        else:
            query_str = (
                f'kube_pod_container_status_restarts_total{{'
                f'namespace="{namespace}",container="{container}"}}'
            )

        try:
            results = self.query(query_str)
            if not results:
                return None

            # Look for the latest value in the result vector
            sample = results[0]
            val_pair = sample.get("value")
            if isinstance(val_pair, (list, tuple)) and len(val_pair) >= 2:
                return int(float(val_pair[1]))
            return None
        except Exception:
            return None

    def get_deployment_metrics(
        self,
        namespace: str = "ai-remediation",
        deployment: str = "demo-app"
    ) -> dict:
        """
        Collects available replica and ready replica metrics for a deployment.
        Returns a dict with 'available', 'desired', or empty dict on failure.
        """
        metrics = {}
        avail_query = (
            f'kube_deployment_status_replicas_available{{'
            f'namespace="{namespace}",deployment="{deployment}"}}'
        )
        desired_query = (
            f'kube_deployment_spec_replicas{{'
            f'namespace="{namespace}",deployment="{deployment}"}}'
        )

        try:
            res_avail = self.query(avail_query)
            if res_avail:
                val = res_avail[0].get("value")
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    metrics["available_replicas"] = int(float(val[1]))
        except Exception:
            pass

        try:
            res_desired = self.query(desired_query)
            if res_desired:
                val = res_desired[0].get("value")
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    metrics["desired_replicas"] = int(float(val[1]))
        except Exception:
            pass

        return metrics


def query_prometheus_safely(promql: str, url: str = None) -> list[dict] | None:
    """
    Convenience function that queries Prometheus and returns results,
    or None if Prometheus is unavailable or returns an error.
    Guaranteed not to raise an exception.
    """
    client = PrometheusClient(base_url=url)
    try:
        return client.query(promql)
    except Exception:
        return None


if __name__ == "__main__":
    client = PrometheusClient()
    print(f"Checking Prometheus at {client.base_url}...")
    is_healthy = client.check_health()
    print(f"Prometheus healthy: {is_healthy}")

    restarts = client.get_container_restart_count("ai-remediation", "nginx")
    print(f"Observed restarts for nginx in ai-remediation: {restarts}")

    deployment_data = client.get_deployment_metrics("ai-remediation", "demo-app")
    print(f"Observed deployment metrics for demo-app: {deployment_data}")
