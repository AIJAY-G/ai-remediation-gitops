
from pathlib import Path
import subprocess
import time
import yaml

MANIFEST = Path("gitops/demo-app.yaml")
EXPECTED_DEPLOYMENT = "demo-app"
EXPECTED_CONTAINER = "nginx"


def run_command(command):
    subprocess.run(command, check=True)


def get_current_branch():
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()


def apply_gitops_remediation(action):
    if action != "restart_pod":
        print(f"Unsupported remediation: {action}")
        return False

    if not MANIFEST.exists():
        print(f"GitOps manifest not found: {MANIFEST}")
        return False

    branch = get_current_branch()

    # Never allow this development workflow to push to main.
    if not branch or branch == "main":
        print("Refusing execution: use a development branch.")
        return False

    # Protect unrelated staged changes from being included.
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"]
    )

    if staged.returncode != 0:
        print("Unrelated staged changes detected. Commit or unstage them first.")
        return False

    documents = list(
        yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8"))
    )

    deployment_found = False
    container_found = False

    for doc in documents:
        if not doc:
            continue

        if (
            doc.get("kind") == "Deployment"
            and doc.get("metadata", {}).get("name") == EXPECTED_DEPLOYMENT
        ):
            deployment_found = True

            template = doc.setdefault("spec", {}).setdefault("template", {})
            metadata = template.setdefault("metadata", {})
            annotations = metadata.setdefault("annotations", {})

            containers = template.setdefault("spec", {}).setdefault(
                "containers", []
            )

            for container in containers:
                if container.get("name") == EXPECTED_CONTAINER:
                    container_found = True

                    # Restore the expected NGINX startup command.
                    container["command"] = [
                        "nginx",
                        "-g",
                        "daemon off;"
                    ]

                    annotations["ai-remediation/restarted-at"] = str(
                        int(time.time())
                    )

    if not deployment_found or not container_found:
        print("Expected Deployment or NGINX container not found.")
        return False

    # Write the updated desired state.
    with MANIFEST.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump_all(
            documents,
            file,
            sort_keys=False
        )

    print(f"GitOps manifest updated on branch: {branch}")

    # Validate manifest syntax and Kubernetes schema.
    run_command([
        "kubectl",
        "apply",
        "--dry-run=client",
        "-f",
        str(MANIFEST)
    ])

    # Stage only the intended manifest.
    run_command([
        "git",
        "add",
        "--",
        str(MANIFEST)
    ])

    # Confirm that only the intended file is staged.
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True
    )

    staged_files = result.stdout.splitlines()

    if staged_files != [MANIFEST.as_posix()]:
        print("Unexpected staged files detected. Aborting commit.")
        return False

    # Check whether a manifest change exists.
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"]
    )

    if result.returncode == 0:
        print("No GitOps manifest change required.")
        return True

    # Commit and push only to the current development branch.
    run_command([
        "git",
        "commit",
        "-m",
        "Apply authorized remediation"
    ])

    run_command([
        "git",
        "push",
        "origin",
        branch
    ])

    print(f"GitOps remediation pushed to {branch}.")
    return True


if __name__ == "__main__":
    apply_gitops_remediation("restart_pod")
