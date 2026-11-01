from datetime import datetime, timezone

from kubernetes import client, config


NAMESPACE = "ai-remediation"


def detect_incident():
    config.load_kube_config()

    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    pods = v1.list_namespaced_pod(NAMESPACE)

    incidents = []

    for pod in pods.items:
        pod_name = pod.metadata.name
        pod_status = pod.status.phase or "Unknown"

        restart_count = 0
        container_ready = True

        for container in pod.status.container_statuses or []:
            restart_count += container.restart_count or 0

            if not container.ready:
                container_ready = False

            waiting = container.state.waiting

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
    deployments = apps_v1.list_namespaced_deployment(NAMESPACE)

    for deployment in deployments.items:
        desired = deployment.spec.replicas or 0
        available = deployment.status.available_replicas or 0
        ready = deployment.status.ready_replicas or 0

        if desired > 0 and available < desired:
            incidents.append({
                "incident_id": f"INC-{deployment.metadata.name}-deployment",
                "incident_type": "deployment_failure",
                "severity": "high",
                "namespace": NAMESPACE,
                "resource_type": "Deployment",
                "resource_name": deployment.metadata.name,
                "status": "detected",
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "evidence": {
                    "desired_replicas": desired,
                    "available_replicas": available,
                    "ready_replicas": ready
                }
            })

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