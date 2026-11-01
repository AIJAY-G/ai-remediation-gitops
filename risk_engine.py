from llm_proposal import generate_remediation
from k8s_monitor import detect_incident


def calculate_risk(confidence, uncertainty, policy_compliance,
                   reversibility, blast_radius):

    risk = (
        (1 - confidence) * 0.25
        + uncertainty * 0.20
        + (1 - policy_compliance) * 0.25
        + (1 - reversibility) * 0.15
        + blast_radius * 0.15
    )

    if risk < 0.30:
        decision = "AUTO_EXECUTE"
    elif risk < 0.60:
        decision = "HUMAN_APPROVAL"
    else:
        decision = "REJECT"

    return risk, decision


if __name__ == "__main__":

    # Detect real incident from Kubernetes
    incident = detect_incident()

    if not incident:
        print("No incident detected")
        exit()

    print(f"Incident detected: {incident}")

    # Generate remediation proposal
    proposal = generate_remediation(incident)

    # Calculate risk
    risk, decision = calculate_risk(
        proposal["confidence"],
        proposal["uncertainty"],
        proposal["policy_compliance"],
        proposal["reversibility"],
        proposal["blast_radius"]
    )

    print()
    print("Remediation Authorization")
    print("-------------------------")
    print(f"Action: {proposal['action']}")
    print(f"Description: {proposal['description']}")
    print(f"Risk Score: {risk:.2f}")
    print(f"Authorization Decision: {decision}")