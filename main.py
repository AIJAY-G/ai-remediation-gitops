
from k8s_monitor import detect_incident, select_primary_incident
from llm_proposal import generate_remediation, ProposalError
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

    # 2. Generate LLM remediation proposal
    try:
        proposal = generate_remediation(
            primary_incident.get("incident_type", "")
        )
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
    print(f"Risk Engine Decision: {decision}")

    # 4. Authorization safeguard
    if decision == "REJECT":
        print()
        print("Remediation rejected by risk assessment.")
        return

    # LLM self-reported scores are not independently calibrated.
    # Therefore, AUTO_EXECUTE is downgraded to HUMAN_APPROVAL.
    effective_decision = "HUMAN_APPROVAL"

    print()
    print("Authorization Safeguard")
    print("-----------------------")
    print("LLM-generated risk scores require human verification.")
    print(f"Effective Decision: {effective_decision}")

    approval = input(
        "Approve this GitOps remediation? (yes/no): "
    ).strip().lower()

    if approval != "yes":
        print("Human approval denied. No remediation executed.")
        return

    print("Human approval granted.")

    # 5. GitOps execution
    print()
    print("Executing authorized GitOps remediation...")

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
