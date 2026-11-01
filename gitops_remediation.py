from pathlib import Path
import subprocess
import time
import yaml

MANIFEST = Path("gitops/demo-app.yaml")


def run_command(command):
    subprocess.run(command, check=True)


def apply_gitops_remediation(action):
    if action != "restart_pod":
        print(f"Unsupported remediation: {action}")
        return False

    if not MANIFEST.exists():
        print(f"GitOps manifest not found: {MANIFEST}")
        return False

    content = MANIFEST.read_text()

    documents = list(yaml.safe_load_all(content))

    deployment_found = False

    for doc in documents:

        if not doc:
            continue

        if (
            doc.get("kind") == "Deployment"
            and doc.get("metadata", {}).get("name") == "demo-app"
        ):

            deployment_found = True

            template = doc.setdefault(
                "spec", {}
            ).setdefault(
                "template", {}
            )

            metadata = template.setdefault(
                "metadata", {}
            )

            annotations = metadata.setdefault(
                "annotations", {}
            )

            # -------------------------------------------------
            # Explicitly define the normal NGINX startup command
            # -------------------------------------------------
            containers = template.setdefault(
                "spec", {}
            ).setdefault(
                "containers", []
            )

            for container in containers:

                if container.get("name") == "nginx":

                    # Remove any failure command and explicitly
                    # define the normal nginx startup command.
                    container["command"] = [
                        "nginx",
                        "-g",
                        "daemon off;"
                    ]

                    # Unique annotation forces a new pod.
                    annotations[
                        "ai-remediation/restarted-at"
                    ] = str(int(time.time()))

    if not deployment_found:
        print("Deployment demo-app not found in GitOps manifest.")
        return False

    # ---------------------------------------------------------
    # Write desired state
    # ---------------------------------------------------------
    with MANIFEST.open("w") as file:
        yaml.safe_dump_all(
            documents,
            file,
            sort_keys=False
        )

    print("GitOps manifest updated.")

    # ---------------------------------------------------------
    # Validate Kubernetes YAML
    # ---------------------------------------------------------
    print("Validating GitOps manifest...")

    run_command([
        "kubectl",
        "apply",
        "--dry-run=client",
        "-f",
        str(MANIFEST)
    ])

    # ---------------------------------------------------------
    # Stage
    # ---------------------------------------------------------
    run_command([
        "git",
        "add",
        str(MANIFEST)
    ])

    # ---------------------------------------------------------
    # Check for Git change
    # ---------------------------------------------------------
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"]
    )

    if result.returncode == 0:
        print("No GitOps manifest change required.")
        return True

    # ---------------------------------------------------------
    # Commit
    # ---------------------------------------------------------
    run_command([
        "git",
        "commit",
        "-m",
        "Apply authorized remediation"
    ])

    # ---------------------------------------------------------
    # Push
    # ---------------------------------------------------------
    run_command([
        "git",
        "push",
        "origin",
        "main"
    ])

    print("GitOps remediation committed and pushed.")

    return True


if __name__ == "__main__":
    apply_gitops_remediation("restart_pod")