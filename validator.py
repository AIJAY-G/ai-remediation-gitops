from kubernetes import client, config
import time


def validate_remediation(
    namespace="ai-remediation",
    deployment_name="demo-app",
    argocd_namespace="argocd",
    application_name="ai-remediation",
    timeout=120,
    interval=5
):
    config.load_kube_config()

    apps_v1 = client.AppsV1Api()
    custom_api = client.CustomObjectsApi()

    print("Checking GitOps and Kubernetes remediation status...")

    start_time = time.time()

    while time.time() - start_time < timeout:

        # Check Argo CD application
        try:
            app = custom_api.get_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace=argocd_namespace,
                plural="applications",
                name=application_name
            )

            sync_status = (
                app.get("status", {})
                .get("sync", {})
                .get("status", "Unknown")
            )

            health_status = (
                app.get("status", {})
                .get("health", {})
                .get("status", "Unknown")
            )

        except Exception as error:
            print(f"Argo CD check error: {error}")
            sync_status = "Unknown"
            health_status = "Unknown"

        # Check Kubernetes Deployment
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace
        )

        desired = deployment.spec.replicas or 1
        ready = deployment.status.ready_replicas or 0
        updated = deployment.status.updated_replicas or 0
        available = deployment.status.available_replicas or 0

        print(
            f"Argo CD: sync={sync_status}, health={health_status} | "
            f"Deployment: ready={ready}/{desired}, "
            f"updated={updated}/{desired}, "
            f"available={available}/{desired}"
        )

        # Successful remediation
        if (
            sync_status == "Synced"
            and health_status == "Healthy"
            and ready >= desired
            and updated >= desired
            and available >= desired
        ):
            print()
            print("Validation: SUCCESS")
            print("GitOps and Kubernetes remediation completed successfully.")
            return True

        time.sleep(interval)

    print()
    print("Validation: FAILED")
    print("Remediation did not become healthy within timeout.")
    return False


if __name__ == "__main__":
    validate_remediation()