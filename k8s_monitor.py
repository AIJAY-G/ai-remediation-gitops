from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


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


def detect_incident():
    try:
        config.load_kube_config()
    except Exception as err:
        print(f"Failed to load Kubernetes configuration: {err}")
        return []

    try:
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        pods = v1.list_namespaced_pod(NAMESPACE)
    except ApiException as err:
        print(f"Kubernetes API error querying pods in namespace '{NAMESPACE}': {err}")
        return []
    except Exception as err:
        print(f"Error connecting to Kubernetes cluster: {err}")
        return []

    incidents = []

    for pod in pods.items:
        pod_name = pod.metadata.name if pod.metadata else "unknown"
        pod_status = (pod.status.phase if pod.status else None) or "Unknown"

        restart_count = 0
        container_ready = True

        container_statuses = (pod.status.container_statuses if pod.status else None) or []
        for container in container_statuses:
            restart_count += container.restart_count or 0

            if not container.ready:
                container_ready = False

            waiting = container.state.waiting if (container.state and container.state.waiting) else None

            if waiting:
                reason = waiting.reason or ""

                if reason in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"]:
                    incidents.append({
                        "incident_id": f"INC-{pod_name}",
                        "incident_type": "pod_failure",
                        "severity": "medium",
                        "namespace": NAMESPACE,
                        "resource_type": "Pod",
                        "resource_name": pod_name,
                        "status": "detected",
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                        "evidence": {
                            "pod_phase": pod_status,
                            "container_ready": container_ready,
                            "restart_count": restart_count,
                            "failure_reason": reason
                        }
                    })

        if restart_count > 2 and container_ready is False:
            incidents.append({
                "incident_id": f"INC-{pod_name}-restart",
                "incident_type": "pod_restart",
                "severity": "medium",
                "namespace": NAMESPACE,
                "resource_type": "Pod",
                "resource_name": pod_name,
                "status": "detected",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "evidence": {
                    "pod_phase": pod_status,
                    "container_ready": container_ready,
                    "restart_count": restart_count
                }
            })

    # Check deployments
    try:
        deployments = apps_v1.list_namespaced_deployment(NAMESPACE)
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
                    "namespace": NAMESPACE,
                    "resource_type": "Deployment",
                    "resource_name": dep_name,
                    "status": "detected",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "evidence": {
                        "desired_replicas": desired,
                        "available_replicas": available,
                        "ready_replicas": ready
                    }
                })
    except ApiException as err:
        print(f"Kubernetes API error querying deployments in namespace '{NAMESPACE}': {err}")
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
