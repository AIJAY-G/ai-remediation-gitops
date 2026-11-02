"""
Legacy Direct Kubernetes Remediation Executor (DEPRECATED FOR GITOPS)
--------------------------------------------------------------------
WARNING: This module directly modifies live Kubernetes resources via the
Kubernetes API (AppsV1Api).

In a GitOps-managed environment (e.g., using Argo CD), direct imperative
mutations cause configuration drift. Argo CD's self-healing reconciliation
loop detects cluster-side drift and will overwrite manual patches with the
desired state declared in Git.

PRIMARY WORKFLOW:
    Use `gitops_remediation.apply_gitops_remediation()` instead. The GitOps
    workflow commits manifest changes to the Git repository, allowing Argo CD
    to declaratively reconcile and synchronize the cluster state safely.

LEGACY WORKFLOW:
    `execute_direct_remediation()` (or legacy alias `execute_remediation()`)
    is retained strictly for emergency direct execution or non-GitOps fallback
    environments. DO NOT delete this module without explicit approval.
"""

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


def execute_direct_remediation(action, decision):
    """
    Directly patches the Kubernetes deployment via AppsV1Api.
    LEGACY: Bypasses GitOps workflow and causes drift if Argo CD selfHeal is active.
    """
    if decision == "REJECT":
        print("Remediation blocked.")
        print("Authorization Decision: REJECT")
        return False

    if decision == "HUMAN_APPROVAL":
        print("Human approval required.")
        approval = input("Approve remediation? (yes/no): ").strip().lower()

        if approval != "yes":
            print("Remediation not executed.")
            print("Human approval: DENIED")
            return False

    print("[LEGACY WARNING] Executing direct Kubernetes mutation (bypassing GitOps)...")

    try:
        config.load_kube_config()
    except Exception as err:
        print(f"Error loading Kubernetes configuration for direct execution: {err}")
        return False

    try:
        apps_v1 = client.AppsV1Api()

        if action == "restart_pod":
            apps_v1.patch_namespaced_deployment(
                name="demo-app",
                namespace="ai-remediation",
                body={
                    "spec": {
                        "template": {
                            "metadata": {
                                "annotations": {
                                    "ai-remediation/restarted-at": "risk-authorized"
                                }
                            }
                        }
                    }
                }
            )

            print("Remediation executed (direct Kubernetes patch): restart_pod")
            return True

        print(f"Remediation not executed: unsupported action '{action}'")
        return False

    except ApiException as err:
        print(f"Kubernetes API error during direct remediation: {err}")
        return False
    except Exception as err:
        print(f"Unexpected error during direct remediation: {err}")
        return False


# Backward compatibility alias
execute_remediation = execute_direct_remediation


if __name__ == "__main__":
    execute_remediation("restart_pod", "HUMAN_APPROVAL")
