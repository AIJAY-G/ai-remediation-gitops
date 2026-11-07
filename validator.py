import time
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

try:
    from prometheus_client import PrometheusClient
except ImportError:
    PrometheusClient = None


def get_current_git_commit():
    """Helper to get current git commit if validator is run standalone."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return None


def get_current_git_branch():
    """Helper to get current git branch if validator is run standalone."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return None


def validate_remediation(
    namespace="ai-remediation",
    deployment_name="demo-app",
    argocd_namespace="argocd",
    application_name="ai-remediation",
    expected_commit=None,
    expected_branch=None,
    timeout=120,
    interval=5
):
    try:
        config.load_kube_config()
    except Exception as err:
        print(f"Failed to load Kubernetes configuration: {err}")
        return False

    apps_v1 = client.AppsV1Api()
    custom_api = client.CustomObjectsApi()

    print("Checking GitOps and Kubernetes remediation status...")
    if expected_commit:
        print(f"Expected remediation commit: {expected_commit[:7] if len(expected_commit) > 7 else expected_commit}")
    if expected_branch:
        print(f"Expected target branch: {expected_branch}")

    start_time = time.time()

    while time.time() - start_time < timeout:

        # 1. Check Argo CD application
        app = None
        sync_status = "Unknown"
        sync_revision = ""
        health_status = "Unknown"
        app_target_revision = ""

        try:
            app = custom_api.get_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace=argocd_namespace,
                plural="applications",
                name=application_name
            )

            status = (app.get("status") if isinstance(app, dict) else None) or {}
            sync_info = status.get("sync") or {}
            sync_status = sync_info.get("status", "Unknown")
            sync_revision = sync_info.get("revision", "")

            health_info = status.get("health") or {}
            health_status = health_info.get("status", "Unknown")

            spec = (app.get("spec") if isinstance(app, dict) else None) or {}
            source = spec.get("source") or {}
            app_target_revision = source.get("targetRevision", "")

        except ApiException as error:
            if error.status == 404:
                print(
                    f"Argo CD Application '{application_name}' not found "
                    f"in namespace '{argocd_namespace}'."
                )
            else:
                print(f"Argo CD API error ({error.status}): {error.reason}")
        except Exception as error:
            print(f"Argo CD check error: {error}")

        # Strict branch validation: if expected_branch is supplied, targetRevision must match
        if expected_branch:
            if app_target_revision and app_target_revision != expected_branch:
                print(
                    f"Validation: FAILED - Branch mismatch: Argo CD configured targetRevision is "
                    f"'{app_target_revision}', but expected branch is '{expected_branch}'."
                )
                return False
            if not app_target_revision:
                branch_matched = False
            else:
                branch_matched = (app_target_revision == expected_branch)
        else:
            branch_matched = True

        # 2. Check Kubernetes Deployment
        deployment = None
        desired = 1
        ready = 0
        updated = 0
        available = 0

        try:
            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=namespace
            )
            spec = deployment.spec or client.V1DeploymentSpec()
            status = deployment.status or client.V1DeploymentStatus()

            desired = spec.replicas or 1
            ready = status.ready_replicas or 0
            updated = status.updated_replicas or 0
            available = status.available_replicas or 0

        except ApiException as error:
            if error.status == 404:
                print(f"Deployment '{deployment_name}' not found in namespace '{namespace}'.")
            else:
                print(f"Kubernetes API error querying deployment ({error.status}): {error.reason}")
        except Exception as error:
            print(f"Kubernetes Deployment check error: {error}")

        # 3. Verify commit synchronization
        commit_matched = True
        if expected_commit:
            clean_expected = expected_commit.strip()
            clean_actual = sync_revision.strip()

            if not clean_actual:
                commit_matched = False
            elif len(clean_expected) == 40:
                # Full 40-character commit SHA: require exact match
                commit_matched = (clean_actual == clean_expected)
            else:
                # Short commit prefix: require startswith match
                commit_matched = clean_actual.startswith(clean_expected)

        revision_display = f", rev={sync_revision[:7]}" if sync_revision else ""
        commit_check_display = ""
        if expected_commit:
            commit_check_display = f" (matches expected={commit_matched})"

        print(
            f"Argo CD: sync={sync_status}{revision_display}{commit_check_display}, "
            f"health={health_status} | "
            f"Deployment: ready={ready}/{desired}, "
            f"updated={updated}/{desired}, "
            f"available={available}/{desired}"
        )

        # 4. Check all success conditions
        if (
            branch_matched
            and commit_matched
            and sync_status == "Synced"
            and health_status == "Healthy"
            and deployment is not None
            and ready >= desired
            and updated >= desired
            and available >= desired
        ):
            print()
            print("Validation: SUCCESS")
            print("GitOps and Kubernetes remediation completed successfully.")
            if expected_commit:
                print(f"Verified synchronized commit: {sync_revision}")

            if PrometheusClient is not None:
                try:
                    p_client = PrometheusClient()
                    p_restarts = p_client.get_container_restart_count(namespace, "nginx")
                    if p_restarts is not None:
                        print(f"Prometheus Telemetry: Verified container restart count = {p_restarts}")
                except Exception:
                    pass

            return True

        time.sleep(interval)

    print()
    print("Validation: FAILED")
    print("Remediation did not become healthy and synchronized within timeout.")
    return False


if __name__ == "__main__":
    current_commit = get_current_git_commit()
    current_branch = get_current_git_branch()
    validate_remediation(
        expected_commit=current_commit,
        expected_branch=current_branch
    )
