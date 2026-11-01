from kubernetes import client, config


def execute_remediation(action, decision):

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

    config.load_kube_config()

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

        print("Remediation executed: restart_pod")
        return True

    print("Remediation not executed:", action)
    return False


if __name__ == "__main__":
    execute_remediation("restart_pod", "HUMAN_APPROVAL")