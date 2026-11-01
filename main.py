from k8s_monitor import detect_incident
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
    primary_incident = next(
        (
            item
            for item in incidents
            if item["incident_type"] == "pod_failure"
        ),
        incidents[0]
    )

    print()
    print("Primary Incident")
    print("----------------")
    print(f"Type: {primary_incident['incident_type']}")
    print(f"Severity: {primary_incident['severity']}")
    print(
        f"Resource: "
        f"{primary_incident['resource_type']}/"
        f"{primary_incident['resource_name']}"
    )
    print(
        f"Failure Reason: "
        f"{primary_incident['evidence'].get('failure_reason', 'N/A')}"
    )

    # 2. Generate remediation proposal
    proposal = generate_remediation(
        primary_incident["incident_type"]
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

    success = apply_gitops_remediation(
        proposal["action"]
    )

    if not success:
        print("GitOps remediation failed.")
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