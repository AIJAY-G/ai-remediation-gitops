from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

try:
    from prometheus_client import PrometheusClient
except ImportError:
    PrometheusClient = None


NAMESPACE = "ai-remediation"


def select_primary_incident(incidents):
    """
    Selects the primary incident for remediation analysis.
    Prioritizes 'pod_failure' over other detected incidents.
    Returns None if the list is empty or invalid.
    """
    if not incidents:
        return None

    for item in incidents:
        if isinstance(item, dict) and item.get("incident_type") == "pod_failure":
            return item

    return incidents[0] if incidents else None


def detect_incident(namespace=NAMESPACE):
    """
    Scans the specified Kubernetes namespace for incidents:
      1. Pod failures: waiting reasons (CrashLoopBackOff, ImagePullBackOff, ErrImagePull),
         or terminated reasons (OOMKilled, Error).
      2. Pod restarts: excessive restart counts (>2 unready, or >=5 total).
      3. Deployment deficits: desired > 0 and available < desired.
    Optionally enriches evidence with Prometheus telemetry if accessible.
    """
    target_namespace = namespace or NAMESPACE

    try:
        config.load_kube_config()
    except Exception as err:
        print(f"Failed to load Kubernetes configuration: {err}")
        return []

    try:
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        pods = v1.list_namespaced_pod(target_namespace)
    except ApiException as err:
        print(f"Kubernetes API error querying pods in namespace '{target_namespace}': {err}")
        return []
    except Exception as err:
        print(f"Error connecting to Kubernetes cluster: {err}")
        return []

    incidents = []

    # Optional Prometheus helper
    prom_client = None
    if PrometheusClient is not None:
        try:
            prom_client = PrometheusClient()
        except Exception:
            prom_client = None

    for pod in pods.items:
        pod_name = pod.metadata.name if pod.metadata else "unknown"
        pod_status = (pod.status.phase if pod.status else None) or "Unknown"

        restart_count = 0
        container_ready = True
        pod_failure_reason = None
        failing_container_name = "unknown"

        container_statuses = (pod.status.container_statuses if pod.status else None) or []
        for container in container_statuses:
            c_name = container.name or "unknown"
            c_restarts = container.restart_count or 0
            restart_count += c_restarts

            if not container.ready:
                container_ready = False

            # Check waiting state
            waiting = container.state.waiting if (container.state and container.state.waiting) else None
            if waiting and waiting.reason:
                if waiting.reason in [
                    "CrashLoopBackOff",
                    "ImagePullBackOff",
                    "ErrImagePull",
                    "CreateContainerConfigError",
                ]:
                    pod_failure_reason = waiting.reason
                    failing_container_name = c_name

            # Check terminated state (e.g. OOMKilled or abnormal crash)
            terminated = container.state.terminated if (container.state and container.state.terminated) else None
            if not pod_failure_reason and terminated:
                term_reason = terminated.reason or ""
                exit_code = terminated.exit_code
                if term_reason in ["OOMKilled", "Error", "ContainerCannotRun"]:
                    pod_failure_reason = term_reason
                    failing_container_name = c_name
                elif exit_code not in (0, None) and not container.ready:
                    pod_failure_reason = f"TerminatedExitCode{exit_code}"
                    failing_container_name = c_name

        # If a failure was identified on this pod, record pod_failure
        if pod_failure_reason:
            evidence = {
                "pod_phase": pod_status,
                "container_ready": container_ready,
                "restart_count": restart_count,
                "failure_reason": pod_failure_reason,
                "container_name": failing_container_name,
            }

            # Optional telemetry enrichment
            if prom_client is not None:
                try:
                    p_restarts = prom_client.get_container_restart_count(
                        target_namespace, failing_container_name, pod=pod_name
                    )
                    if p_restarts is not None:
                        evidence["prometheus_restarts"] = p_restarts
                except Exception:
                    pass

            incidents.append({
                "incident_id": f"INC-{pod_name}",
                "incident_type": "pod_failure",
                "severity": "medium",
                "namespace": target_namespace,
                "resource_type": "Pod",
                "resource_name": pod_name,
                "status": "detected",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "evidence": evidence,
            })

        # Excessive restarts check
        if (restart_count > 2 and container_ready is False) or (restart_count >= 5):
            evidence = {
                "pod_phase": pod_status,
                "container_ready": container_ready,
                "restart_count": restart_count,
            }
            incidents.append({
                "incident_id": f"INC-{pod_name}-restart",
                "incident_type": "pod_restart",
                "severity": "medium",
                "namespace": target_namespace,
                "resource_type": "Pod",
                "resource_name": pod_name,
                "status": "detected",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "evidence": evidence,
            })

    # Check deployments
    try:
        deployments = apps_v1.list_namespaced_deployment(target_namespace)
        for deployment in deployments.items:
            spec = deployment.spec or client.V1DeploymentSpec()
            status = deployment.status or client.V1DeploymentStatus()
            desired = spec.replicas or 0
            available = status.available_replicas or 0
            ready = status.ready_replicas or 0

            if desired > 0 and available < desired:
                dep_name = deployment.metadata.name if deployment.metadata else "unknown"
                incidents.append({
                    "incident_id": f"INC-{dep_name}-deployment",
                    "incident_type": "deployment_failure",
                    "severity": "high",
                    "namespace": target_namespace,
                    "resource_type": "Deployment",
                    "resource_name": dep_name,
                    "status": "detected",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "evidence": {
                        "desired_replicas": desired,
                        "available_replicas": available,
                        "ready_replicas": ready,
                    },
                })
    except ApiException as err:
        print(f"Kubernetes API error querying deployments in namespace '{target_namespace}': {err}")
    except Exception as err:
        print(f"Error querying deployments: {err}")

    return incidents


if __name__ == "__main__":
    incidents = detect_incident()

    if not incidents:
        print("No incident detected.")
    else:
        print(f"Detected {len(incidents)} incident(s)")
        print()

        for incident in incidents:
            print("Incident")
            print("--------")
            print(f"ID: {incident['incident_id']}")
            print(f"Type: {incident['incident_type']}")
            print(f"Severity: {incident['severity']}")
            print(f"Resource: {incident['resource_type']}/{incident['resource_name']}")
            print(f"Status: {incident['status']}")
            print(f"Detected: {incident['detected_at']}")
            print("Evidence:")

            for key, value in incident["evidence"].items():
                print(f"  {key}: {value}")

            print()
