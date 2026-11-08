
import os
from k8s_monitor import detect_incident, select_primary_incident
from llm_proposal import generate_remediation, ProposalError
from risk_engine import calculate_risk, evaluate_policy_compliance
from gitops_remediation import apply_gitops_remediation, apply_gitops_rollback
from validator import validate_remediation
from audit_logger import log_audit_event
from rbac import get_current_operator, authorize_approval
from chatops import send_chatops_notification


def main(
    namespace=None,
    deployment_name=None,
    manifest_path=None,
    container_name=None,
    application_name=None,
    auto_execute=False,
    max_retries=1
):
    print("=== AI Kubernetes Remediation Authorization ===")
    print()

    target_namespace = namespace or "ai-remediation"
    target_deployment = deployment_name or "demo-app"
    target_app = application_name or "ai-remediation"
    retries_limit = max(1, int(max_retries or 1))

    for attempt in range(1, retries_limit + 1):
        if attempt > 1:
            print()
            print(f"=== Remediation Feedback Loop (Attempt {attempt}/{retries_limit}) ===")
            print()

        # 1. Detect incidents
        if namespace is not None:
            incidents = detect_incident(namespace=namespace)
        else:
            incidents = detect_incident()

        if not incidents:
            print("No incident detected.")
            return

        print(f"Detected {len(incidents)} incident(s)")

        primary_incident = select_primary_incident(incidents)

        if not primary_incident:
            print("No valid primary incident could be selected.")
            return

        print()
        print("Primary Incident")
        print("----------------")
        print(f"Type: {primary_incident.get('incident_type', 'unknown')}")
        print(f"Severity: {primary_incident.get('severity', 'unknown')}")
        print(
            f"Resource: "
            f"{primary_incident.get('resource_type', 'unknown')}/"
            f"{primary_incident.get('resource_name', 'unknown')}"
        )

        evidence = primary_incident.get("evidence", {})
        print(f"Failure Reason: {evidence.get('failure_reason', 'N/A')}")
        if evidence.get("pod_logs"):
            print("Container Logs Captured: Yes")
        if evidence.get("events"):
            print(f"Warning Events Captured: {len(evidence['events'])}")

        # 2. Generate LLM remediation proposal
        print()
        print("Querying Ollama (llama3.1:8b) for remediation proposal...")
        try:
            proposal = generate_remediation(primary_incident)
        except ProposalError as exc:
            print()
            print(f"Remediation proposal rejected: {exc}")
            print("No remediation will be executed.")
            return

        print()
        print("LLM Remediation Proposal")
        print("------------------------")
        print(f"Action: {proposal['action']}")
        print(f"Description: {proposal['description']}")

        # 3. Policy-as-Code check & Risk calculation
        policy_score, policy_message = evaluate_policy_compliance(
            proposal["action"],
            namespace=target_namespace
        )
        effective_compliance = min(proposal["policy_compliance"], policy_score)
        if policy_score < 1.0:
            print(f"Policy Guardrail Notice: {policy_message}")

        risk, decision = calculate_risk(
            proposal["confidence"],
            proposal["uncertainty"],
            effective_compliance,
            proposal["reversibility"],
            proposal["blast_radius"]
        )

        print()
        print("Risk Assessment")
        print("----------------")
        print(f"Risk Score: {risk:.2f}")
        print(f"Risk Engine Decision: {decision}")

        # 4. Authorization Decision Engine
        operator_user, operator_role = get_current_operator()

        # Send Enterprise ChatOps alert
        send_chatops_notification(
            primary_incident,
            proposal,
            risk,
            decision
        )

        if decision == "REJECT":
            print()
            print("Remediation rejected by risk assessment.")
            log_audit_event(
                incident_id=primary_incident.get("incident_id", "unknown"),
                resource=f"{target_namespace}/{primary_incident.get('resource_name', 'unknown')}",
                failure_reason=evidence.get("failure_reason", "unknown"),
                action=proposal["action"],
                risk_score=risk,
                risk_vector={
                    "confidence": proposal["confidence"],
                    "uncertainty": proposal["uncertainty"],
                    "policy_compliance": effective_compliance,
                    "reversibility": proposal["reversibility"],
                    "blast_radius": proposal["blast_radius"],
                },
                policy_status=policy_message,
                decision="REJECTED_BY_ENGINE",
                authorized_by=operator_user,
                authorizer_role=operator_role,
                container_logs=evidence.get("pod_logs"),
                description=proposal.get("description"),
            )
            return

        # Check Enterprise RBAC clearance
        rbac_ok, rbac_msg = authorize_approval(operator_role, decision)
        if not rbac_ok:
            print()
            print(f"RBAC Authorization Failure: {rbac_msg}")
            log_audit_event(
                incident_id=primary_incident.get("incident_id", "unknown"),
                resource=f"{target_namespace}/{primary_incident.get('resource_name', 'unknown')}",
                failure_reason=evidence.get("failure_reason", "unknown"),
                action=proposal["action"],
                risk_score=risk,
                risk_vector={
                    "confidence": proposal["confidence"],
                    "uncertainty": proposal["uncertainty"],
                    "policy_compliance": effective_compliance,
                    "reversibility": proposal["reversibility"],
                    "blast_radius": proposal["blast_radius"],
                },
                policy_status=policy_message,
                decision=f"DENIED_BY_RBAC: {rbac_msg}",
                authorized_by=operator_user,
                authorizer_role=operator_role,
                container_logs=evidence.get("pod_logs"),
                description=proposal.get("description"),
            )
            return False

        can_auto_execute = auto_execute or os.getenv("KUBEGUARD_AUTO_EXECUTE", "").strip().lower() in ("true", "1", "yes")

        if decision == "AUTO_EXECUTE" and can_auto_execute:
            print()
            print("Authorization Decision: AUTO_EXECUTE (Low Risk, High Confidence)")
            print("Autonomous execution authorized by operational policy.")
        else:
            effective_decision = "HUMAN_APPROVAL"

            print()
            print("Authorization Safeguard")
            print("-----------------------")
            print("LLM-generated risk scores require human verification.")
            print(f"Effective Decision: {effective_decision}")
            print(f"Authorized Operator: {operator_user} (Role: {operator_role})")

            env_approval = os.getenv("KUBEGUARD_APPROVAL")
            if env_approval:
                print(f"Approve this GitOps remediation? (yes/no): {env_approval}")
                approval = env_approval.strip().lower()
            else:
                approval = input(
                    "Approve this GitOps remediation? (yes/no): "
                ).strip().lower()

            if approval != "yes":
                print("Human approval denied. No remediation executed.")
                log_audit_event(
                    incident_id=primary_incident.get("incident_id", "unknown"),
                    resource=f"{target_namespace}/{primary_incident.get('resource_name', 'unknown')}",
                    failure_reason=evidence.get("failure_reason", "unknown"),
                    action=proposal["action"],
                    risk_score=risk,
                    risk_vector={
                        "confidence": proposal["confidence"],
                        "uncertainty": proposal["uncertainty"],
                        "policy_compliance": effective_compliance,
                        "reversibility": proposal["reversibility"],
                        "blast_radius": proposal["blast_radius"],
                    },
                    policy_status=policy_message,
                    decision="DENIED_BY_HUMAN",
                    authorized_by=operator_user,
                    authorizer_role=operator_role,
                    container_logs=evidence.get("pod_logs"),
                    description=proposal.get("description"),
                )
                return

            print("Human approval granted.")

        # 5. GitOps execution
        print()
        print("Executing authorized GitOps remediation...")

        if manifest_path is not None or deployment_name is not None or container_name is not None:
            result = apply_gitops_remediation(
                proposal["action"],
                manifest_path=manifest_path,
                deployment_name=deployment_name,
                container_name=container_name
            )
        else:
            result = apply_gitops_remediation(proposal["action"])

        if not result:
            print(
                "GitOps remediation failed: "
                f"{getattr(result, 'message', 'unknown error')}"
            )
            return

        # 6. Post-remediation validation
        print()
        print("Waiting for Kubernetes reconciliation...")
        print()
        print("Post-Remediation Validation")
        print("---------------------------")

        validate_kwargs = {
            "namespace": target_namespace,
            "deployment_name": target_deployment,
            "expected_commit": getattr(result, "commit", None),
            "expected_branch": getattr(result, "branch", None),
            "timeout": 300,
            "interval": 5,
        }
        if application_name is not None:
            validate_kwargs["application_name"] = application_name

        validation_success = validate_remediation(**validate_kwargs)

        # Record event in immutable compliance audit ledger
        log_audit_event(
            incident_id=primary_incident.get("incident_id", "unknown"),
            resource=f"{target_namespace}/{target_deployment}",
            failure_reason=evidence.get("failure_reason", "unknown"),
            action=proposal["action"],
            risk_score=risk,
            risk_vector={
                "confidence": proposal["confidence"],
                "uncertainty": proposal["uncertainty"],
                "policy_compliance": effective_compliance,
                "reversibility": proposal["reversibility"],
                "blast_radius": proposal["blast_radius"],
            },
            policy_status=policy_message,
            decision="AUTHORIZED_AND_EXECUTED",
            authorized_by=operator_user,
            authorizer_role=operator_role,
            git_commit=getattr(result, "commit", None),
            validation_status="SUCCESS" if validation_success else "FAILED",
            container_logs=evidence.get("pod_logs"),
            description=proposal.get("description"),
        )

        if validation_success:
            print()
            print("Remediation completed successfully.")
            return True
        else:
            print()
            print("Remediation validation failed.")
            print("Initiating automated GitOps rollback...")
            rollback_res = apply_gitops_rollback(
                target_commit=getattr(result, "commit", None),
                branch=getattr(result, "branch", None),
                manifest_path=manifest_path
            )
            if rollback_res and rollback_res.success:
                print(f"Rollback status: {rollback_res.message}")
            else:
                print(f"Rollback notice: {getattr(rollback_res, 'message', 'manual review recommended')}")

            if attempt < retries_limit:
                print()
                print("Feedback Loop: Propagating validation failure to AI diagnostic agent for re-analysis...")
            else:
                print()
                print("Remediation escalation: Maximum retry attempts reached. Action rejected/escalated.")
                return False


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="KubeGuard AI Remediation")
    parser.add_argument("--namespace", default=None, help="Kubernetes namespace (default: ai-remediation)")
    parser.add_argument("--deployment", default=None, help="Target deployment name (default: demo-app)")
    parser.add_argument("--manifest", default=None, help="Path to GitOps manifest (default: gitops/demo-app.yaml)")
    parser.add_argument("--container", default=None, help="Target container name (default: nginx)")
    parser.add_argument("--app", default=None, help="Argo CD application name (default: ai-remediation)")
    parser.add_argument("--auto-execute", action="store_true", help="Allow autonomous execution for low-risk proposals (<0.30)")
    parser.add_argument("--max-retries", type=int, default=1, help="Maximum remediation attempts before escalating (default: 1)")
    args = parser.parse_args()

    main(
        namespace=args.namespace,
        deployment_name=args.deployment,
        manifest_path=Path(args.manifest) if args.manifest else None,
        container_name=args.container,
        application_name=args.app,
        auto_execute=args.auto_execute,
        max_retries=args.max_retries
    )
