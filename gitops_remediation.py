from datetime import datetime, timezone
from pathlib import Path
import subprocess
import time
import uuid
import yaml

MANIFEST = Path("gitops/demo-app.yaml")
EXPECTED_DEPLOYMENT = "demo-app"
EXPECTED_CONTAINER = "nginx"


class RemediationResult:
    """Represents the outcome of a GitOps remediation attempt."""

    def __init__(
        self,
        success: bool,
        commit: str = None,
        branch: str = None,
        message: str = "",
        unpushed_commit: str = None
    ):
        self.success = success
        self.commit = commit
        self.branch = branch
        self.message = message
        self.unpushed_commit = unpushed_commit

    def __bool__(self):
        return bool(self.success)

    def __repr__(self):
        return (
            f"RemediationResult(success={self.success}, commit={self.commit}, "
            f"branch={self.branch}, message='{self.message}', unpushed_commit={self.unpushed_commit})"
        )


def run_command(command):
    """Executes a command and returns the completed process or raises CalledProcessError with diagnostics."""
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr
        )
    return result


def get_current_branch():
    """Returns the current Git branch name, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        print(f"Failed to determine current Git branch: {err}")
        return ""


def get_head_commit():
    """Returns the current Git HEAD commit SHA, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        print(f"Failed to get Git HEAD commit: {err}")
        return ""


def is_valid_branch_name(branch):
    """
    Validates that branch is a syntactically valid Git branch name using
    'git check-ref-format --branch'. Rejects invalid syntax and arbitrary ref paths.
    """
    if not branch or not isinstance(branch, str) or not branch.strip():
        return False
    branch = branch.strip()
    try:
        result = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def is_commit_pushed(commit_sha, branch):
    """
    Verifies that commit_sha exists on the remote branch origin/<branch>.
    1. Validates inputs and branch name using git check-ref-format --branch.
    2. Refreshes remote tracking info via explicit refspec:
       git fetch origin +refs/heads/<branch>:refs/remotes/origin/<branch>
       If fetching fails, immediately returns False (fail-closed, never uses stale data).
    3. Verifies that origin/<branch> exists and points to a valid commit object.
    4. Verifies that commit_sha is reachable from origin/<branch> via
       git merge-base --is-ancestor commit_sha origin/<branch>.
    """
    if not commit_sha or not isinstance(commit_sha, str) or not commit_sha.strip():
        return False
    if not branch or not isinstance(branch, str) or not branch.strip():
        return False

    commit_sha = commit_sha.strip()
    branch = branch.strip()

    # 1. Validate branch name syntax before constructing refspec
    if not is_valid_branch_name(branch):
        print(f"Invalid Git branch name rejected: '{branch}'")
        return False

    refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"

    # 2. Refresh remote tracking information using explicit refspec
    try:
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", refspec],
            capture_output=True,
            text=True,
            check=False
        )
        if fetch_result.returncode != 0:
            err_msg = fetch_result.stderr.strip() if fetch_result.stderr else "fetch returned non-zero exit code"
            print(f"Git fetch failed for {refspec}: {err_msg}")
            return False
    except Exception as err:
        print(f"Exception during git fetch origin {refspec}: {err}")
        return False

    expected_ref = f"origin/{branch}"

    # 3. Verify remote tracking branch exists and points to a valid commit
    try:
        rev_check = subprocess.run(
            ["git", "rev-parse", "--verify", f"{expected_ref}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False
        )
        if rev_check.returncode != 0:
            print(f"Remote tracking ref '{expected_ref}' not found or invalid.")
            return False
    except Exception as err:
        print(f"Error verifying ref '{expected_ref}': {err}")
        return False

    # 4. Verify exact commit_sha is reachable from the exact remote branch
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit_sha, expected_ref],
            capture_output=True,
            check=False
        )
        if merge_base.returncode == 0:
            return True
        print(f"Commit {commit_sha[:7]} is not an ancestor of {expected_ref}.")
        return False
    except Exception as err:
        print(f"Error checking ancestry of {commit_sha[:7]} against {expected_ref}: {err}")
        return False


def get_unpushed_commits(branch):
    """Returns a list of local commit SHAs that have not been pushed to origin/<branch>."""
    if not branch or not isinstance(branch, str) or not branch.strip():
        return []
    branch = branch.strip()
    try:
        result = subprocess.run(
            ["git", "rev-list", f"origin/{branch}..HEAD"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return []
    except Exception:
        return []


def generate_restart_annotation():
    """
    Generates a unique timestamp/identifier for pod-template annotations.
    Combines ISO-8601 UTC timestamp and a high-entropy UUID suffix to guarantee uniqueness
    across back-to-back invocations.
    """
    now_utc = datetime.now(timezone.utc).isoformat()
    unique_suffix = uuid.uuid4().hex[:12]
    return f"{now_utc}-{unique_suffix}"


def parse_manifest_documents(manifest_path=MANIFEST):
    """Loads and returns all YAML documents from the specified manifest file."""
    p = Path(manifest_path)
    return list(yaml.safe_load_all(p.read_text(encoding="utf-8")))


def update_manifest_for_restart(
    manifest_path=MANIFEST,
    restart_id=None,
    deployment_name=None,
    container_name=None
):
    """
    Updates the Deployment in the manifest with a unique restart annotation and restores NGINX command.
    Returns (documents, old_annotation, new_annotation).
    """
    target_deployment = deployment_name or EXPECTED_DEPLOYMENT
    target_container = container_name or EXPECTED_CONTAINER

    if restart_id is None:
        restart_id = generate_restart_annotation()

    documents = list(
        yaml.safe_load_all(manifest_path.read_text(encoding="utf-8"))
    )

    deployment_found = False
    container_found = False
    old_annotation = None

    for doc in documents:
        if not doc:
            continue

        if (
            doc.get("kind") == "Deployment"
            and doc.get("metadata", {}).get("name") == target_deployment
        ):
            deployment_found = True

            template = doc.setdefault("spec", {}).setdefault("template", {})
            metadata = template.setdefault("metadata", {})
            annotations = metadata.setdefault("annotations", {})

            old_annotation = annotations.get("ai-remediation/restarted-at")
            annotations["ai-remediation/restarted-at"] = str(restart_id)

            containers = template.setdefault("spec", {}).setdefault(
                "containers", []
            )

            for container in containers:
                if container.get("name") == target_container:
                    container_found = True

                    # Restore the expected NGINX startup command.
                    container["command"] = [
                        "nginx",
                        "-g",
                        "daemon off;"
                    ]

    if not deployment_found or not container_found:
        raise ValueError(
            f"Expected Deployment '{target_deployment}' or container '{target_container}' not found in manifest."
        )

    return documents, old_annotation, str(restart_id)


def write_manifest_documents(documents, manifest_path=MANIFEST):
    """Writes YAML documents to the manifest file."""
    with manifest_path.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump_all(
            documents,
            file,
            sort_keys=False
        )


SUPPORTED_GITOPS_ACTIONS = {
    "restart_pod",
    "rollback_image",
    "scale_replicas",
    "update_memory_limit",
}


def update_manifest_action(
    manifest_path=MANIFEST,
    action="restart_pod",
    deployment_name=EXPECTED_DEPLOYMENT,
    container_name=EXPECTED_CONTAINER,
    restart_id=None
):
    """
    Applies the specified enterprise remediation action to the GitOps manifest document.
    Supports restart_pod, rollback_image, scale_replicas, and update_memory_limit.
    """
    if action == "restart_pod":
        return update_manifest_for_restart(
            manifest_path=manifest_path,
            deployment_name=deployment_name,
            container_name=container_name,
            restart_id=restart_id
        )

    restart_id = restart_id or generate_restart_annotation()
    documents = parse_manifest_documents(manifest_path)
    deployment_found = False
    container_found = False
    old_val = None

    for doc in documents:
        if (
            isinstance(doc, dict)
            and doc.get("kind") == "Deployment"
            and doc.get("metadata", {}).get("name") == deployment_name
        ):
            deployment_found = True
            template = doc.setdefault("spec", {}).setdefault("template", {})
            metadata = template.setdefault("metadata", {})
            annotations = metadata.setdefault("annotations", {})
            annotations["ai-remediation/restarted-at"] = str(restart_id)

            if action == "scale_replicas":
                current_replicas = doc.get("spec", {}).get("replicas", 1)
                old_val = current_replicas
                doc["spec"]["replicas"] = max(1, current_replicas + 1)
                container_found = True
                continue

            containers = template.setdefault("spec", {}).setdefault("containers", [])
            for container in containers:
                if isinstance(container, dict) and container.get("name") == container_name:
                    container_found = True
                    if action == "rollback_image":
                        old_val = container.get("image")
                        container["image"] = "nginx:latest"
                        container["command"] = ["nginx", "-g", "daemon off;"]
                    elif action == "update_memory_limit":
                        resources = container.setdefault("resources", {})
                        limits = resources.setdefault("limits", {})
                        old_val = limits.get("memory")
                        limits["memory"] = "256Mi"
                        requests = resources.setdefault("requests", {})
                        requests["memory"] = "128Mi"

    if not deployment_found or not container_found:
        raise ValueError(
            f"Expected Deployment '{deployment_name}' or container '{container_name}' not found in manifest."
        )

    return documents, old_val, str(restart_id)


def apply_gitops_remediation(
    action,
    manifest_path=None,
    deployment_name=None,
    container_name=None
):
    if action not in SUPPORTED_GITOPS_ACTIONS:
        print(f"Unsupported remediation: {action}")
        return RemediationResult(success=False, message=f"Unsupported action: {action}")

    target_manifest = Path(manifest_path) if manifest_path else MANIFEST
    target_deployment = deployment_name or EXPECTED_DEPLOYMENT
    target_container = container_name or EXPECTED_CONTAINER

    if not target_manifest.exists():
        print(f"GitOps manifest not found: {target_manifest}")
        return RemediationResult(success=False, message=f"Manifest not found: {target_manifest}")

    branch = get_current_branch()

    # Never allow this development workflow to push to main.
    if not branch or branch == "main":
        print("Refusing execution: active branch must be a development branch (not main or detached).")
        return RemediationResult(success=False, branch=branch, message="Refusing execution on main or detached HEAD")

    # Protect unrelated staged changes from being included.
    try:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"]
        )
        if staged.returncode != 0:
            print("Unrelated staged changes detected. Commit or unstage them first.")
            return RemediationResult(success=False, branch=branch, message="Unrelated staged changes detected")
    except Exception as err:
        print(f"Error checking git staging status: {err}")
        return RemediationResult(success=False, branch=branch, message=str(err))

    # Update the manifest according to the authorized action
    try:
        documents, old_annotation, new_annotation = update_manifest_action(
            target_manifest,
            action=action,
            deployment_name=target_deployment,
            container_name=target_container
        )
    except Exception as err:
        print(f"Failed to update manifest documents: {err}")
        return RemediationResult(success=False, branch=branch, message=str(err))

    # Write the updated desired state to file.
    try:
        write_manifest_documents(documents, target_manifest)
    except Exception as err:
        print(f"Failed to write updated manifest: {err}")
        return RemediationResult(success=False, branch=branch, message=str(err))

    print(f"GitOps manifest updated on branch: {branch} (annotation: {new_annotation})")

    # Validate manifest syntax and Kubernetes schema via client-side dry-run.
    try:
        run_command([
            "kubectl",
            "apply",
            "--dry-run=client",
            "-f",
            str(target_manifest)
        ])
    except subprocess.CalledProcessError as err:
        print(f"Manifest schema validation failed: {err.stderr or err}")
        return RemediationResult(success=False, branch=branch, message="Manifest dry-run validation failed")
    except FileNotFoundError:
        print("Warning: kubectl not found for dry-run validation, skipping dry-run check.")

    # Stage only the intended manifest.
    try:
        run_command([
            "git",
            "add",
            "--",
            str(target_manifest)
        ])

        # Confirm that only the intended file is staged.
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True
        )

        staged_files = result.stdout.splitlines()

        if staged_files != [target_manifest.as_posix()]:
            print(f"Unexpected staged files detected ({staged_files}). Aborting commit.")
            return RemediationResult(success=False, branch=branch, message="Unexpected staged files")

        # Check whether a genuine manifest change was created.
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"]
        )

        if result.returncode == 0:
            # Idempotency requirement: do not report success if no desired-state change was created
            print("No desired-state change was created for restart_pod remediation.")
            head_commit = get_head_commit()
            unpushed = get_unpushed_commits(branch)
            return RemediationResult(
                success=False,
                commit=head_commit,
                branch=branch,
                message="No desired-state change was created",
                unpushed_commit=head_commit if head_commit in unpushed else None
            )

        # Commit only to the current development branch.
        run_command([
            "git",
            "commit",
            "-m",
            "Apply authorized remediation"
        ])

        new_commit = get_head_commit()

    except subprocess.CalledProcessError as err:
        err_detail = err.stderr.strip() if err.stderr else str(err)
        print(f"Git staging or commit failed: {err_detail}")
        return RemediationResult(success=False, branch=branch, message=f"Git commit failed: {err_detail}")
    except Exception as err:
        print(f"Unexpected error staging or committing remediation: {err}")
        return RemediationResult(success=False, branch=branch, message=str(err))

    # Push to remote branch with verification
    try:
        run_command([
            "git",
            "push",
            "origin",
            branch
        ])
    except subprocess.CalledProcessError as err:
        err_detail = err.stderr.strip() if err.stderr else str(err)
        print(f"Git push failed to branch '{branch}': {err_detail}")
        return RemediationResult(
            success=False,
            commit=new_commit,
            branch=branch,
            message=f"Git push failed: {err_detail}",
            unpushed_commit=new_commit
        )
    except Exception as err:
        print(f"Unexpected error during Git push: {err}")
        return RemediationResult(
            success=False,
            commit=new_commit,
            branch=branch,
            message=f"Git push error: {err}",
            unpushed_commit=new_commit
        )

    # Verify push confirmation on remote tracking branch
    if not is_commit_pushed(new_commit, branch):
        print(f"Git push could not be confirmed on origin/{branch} for commit {new_commit[:7]}.")
        return RemediationResult(
            success=False,
            commit=new_commit,
            branch=branch,
            message=f"Commit {new_commit[:7]} not confirmed on remote branch origin/{branch}",
            unpushed_commit=new_commit
        )

    print(f"GitOps remediation committed ({new_commit[:7]}) and confirmed pushed to {branch}.")
    return RemediationResult(
        success=True,
        commit=new_commit,
        branch=branch,
        message=f"Remediation committed and pushed to {branch}"
    )


def apply_gitops_rollback(target_commit=None, branch=None, manifest_path=None):
    """
    Rolls back a GitOps remediation by reverting the target commit (or HEAD)
    and pushing to origin, triggering Argo CD to reconcile to the prior state.
    Returns RemediationResult.
    """
    target_branch = branch or get_current_branch()
    if not target_branch or target_branch == "main":
        print("Refusing rollback: active branch must be a development branch (not main or detached).")
        return RemediationResult(
            success=False,
            branch=target_branch,
            message="Refusing rollback on main or detached HEAD"
        )

    commit_to_revert = target_commit or get_head_commit()
    if not commit_to_revert:
        return RemediationResult(
            success=False,
            branch=target_branch,
            message="No commit available to revert."
        )

    print(f"Initiating GitOps rollback for commit {commit_to_revert[:7]} on branch '{target_branch}'...")

    try:
        run_command([
            "git",
            "revert",
            "--no-edit",
            commit_to_revert
        ])
        rollback_commit = get_head_commit()
    except subprocess.CalledProcessError as err:
        try:
            run_command(["git", "revert", "--abort"])
        except Exception:
            pass
        err_msg = err.stderr.strip() if err.stderr else str(err)
        print(f"Git revert failed during rollback: {err_msg}")
        return RemediationResult(
            success=False,
            branch=target_branch,
            message=f"Git revert failed: {err_msg}"
        )

    if manifest_path:
        t_manifest = Path(manifest_path)
        if t_manifest.exists():
            try:
                run_command(["kubectl", "apply", "--dry-run=client", "-f", str(t_manifest)])
            except Exception:
                pass

    try:
        run_command([
            "git",
            "push",
            "origin",
            target_branch
        ])
    except subprocess.CalledProcessError as err:
        err_msg = err.stderr.strip() if err.stderr else str(err)
        print(f"Git push failed for rollback commit '{rollback_commit[:7]}': {err_msg}")
        return RemediationResult(
            success=False,
            commit=rollback_commit,
            branch=target_branch,
            message=f"Git push failed: {err_msg}",
            unpushed_commit=rollback_commit
        )

    if not is_commit_pushed(rollback_commit, target_branch):
        print(f"Rollback push could not be confirmed on origin/{target_branch}.")
        return RemediationResult(
            success=False,
            commit=rollback_commit,
            branch=target_branch,
            message=f"Commit {rollback_commit[:7]} not confirmed on origin/{target_branch}",
            unpushed_commit=rollback_commit
        )

    print(f"GitOps rollback successfully pushed ({rollback_commit[:7]}) to {target_branch}.")
    return RemediationResult(
        success=True,
        commit=rollback_commit,
        branch=target_branch,
        message=f"Rollback committed and pushed to {target_branch}"
    )


if __name__ == "__main__":
    apply_gitops_remediation("restart_pod")
