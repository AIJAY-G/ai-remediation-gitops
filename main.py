from k8s_monitor import detect_incident, select_primary_incident
from llm_proposal import generate_remediation
from risk_engine import calculate_risk
from gitops_remediation import apply_gitops_remediation
from validator import validate_remediation


def main():
    print("=== AI Kubernetes Remediation Authorization ===")
    print()

    # 1. Detect incidents
    incidents = detect_incident()

    if not incidents:
        print("No incident detected.")
        return

    print(f"Detected {len(incidents)} incident(s)")

    # Select the primary incident for remediation analysis
    primary_incident = select_primary_incident(incidents)

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
    print(
        f"Failure Reason: "
        f"{evidence.get('failure_reason', 'N/A')}"
    )

    # 2. Generate remediation proposal
    proposal = generate_remediation(
        primary_incident.get("incident_type", "")
    )

    print()
    print("Remediation Proposal")
    print("--------------------")
    print(f"Action: {proposal['action']}")
    print(f"Description: {proposal['description']}")

    # 3. Calculate risk
    risk, decision = calculate_risk(
        proposal["confidence"],
        proposal["uncertainty"],
        proposal["policy_compliance"],
        proposal["reversibility"],
        proposal["blast_radius"]
    )

    print()
    print("Risk Assessment")
    print("----------------")
    print(f"Risk Score: {risk:.2f}")
    print(f"Authorization Decision: {decision}")

    # 4. Authorization
    if decision == "REJECT":
        print()
        print("Remediation rejected.")
        return

    if decision == "HUMAN_APPROVAL":
        print()
        approval = input(
            "Approve remediation? (yes/no): "
        ).strip().lower()

        if approval != "yes":
            print("Human approval denied.")
            return

        print("Human approval granted.")

    # 5. GitOps execution
    print()
    print("Executing authorized GitOps remediation...")

    result = apply_gitops_remediation(
        proposal["action"]
    )

    if not result:
        print(f"GitOps remediation failed: {getattr(result, 'message', 'unknown error')}")
        return

    # 6. Post-remediation validation
    print()
    print("Waiting for Kubernetes reconciliation...")

    print()
    print("Post-Remediation Validation")
    print("---------------------------")

    validation_success = validate_remediation(
        namespace="ai-remediation",
        deployment_name="demo-app",
        expected_commit=getattr(result, "commit", None),
        expected_branch=getattr(result, "branch", None),
        timeout=300,
        interval=5
    )

    if validation_success:
        print()
        print("Remediation completed successfully.")
    else:
        print()
        print("Remediation validation failed.")


if __name__ == "__main__":
    main()
