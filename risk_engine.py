import math
from llm_proposal import generate_remediation
from k8s_monitor import detect_incident, select_primary_incident


def calculate_risk(confidence, uncertainty, policy_compliance,
                   reversibility, blast_radius):
    """
    Computes the 5-factor risk score:
      Risk = 0.25 * (1 - confidence)
           + 0.20 * uncertainty
           + 0.25 * (1 - policy_compliance)
           + 0.15 * (1 - reversibility)
           + 0.15 * blast_radius

    Thresholds:
      Risk < 0.30: AUTO_EXECUTE
      0.30 <= Risk < 0.60: HUMAN_APPROVAL
      Risk >= 0.60: REJECT
    """
    factors = (
        ("confidence", confidence),
        ("uncertainty", uncertainty),
        ("policy_compliance", policy_compliance),
        ("reversibility", reversibility),
        ("blast_radius", blast_radius),
    )

    for name, val in factors:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError(f"Risk factor '{name}' must be numeric, got {type(val).__name__}.")
        if not math.isfinite(val):
            raise ValueError(f"Risk factor '{name}' must be a finite number.")

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
    incidents = detect_incident()

    if not incidents:
        print("No incident detected")
        exit(0)

    primary_incident = select_primary_incident(incidents)
    incident_type = (
        primary_incident.get("incident_type")
        if isinstance(primary_incident, dict)
        else primary_incident
    )

    resource_name = (
        primary_incident.get("resource_name", "unknown")
        if isinstance(primary_incident, dict)
        else "unknown"
    )

    print(f"Incident detected: {incident_type} (Resource: {resource_name})")

    # Generate remediation proposal
    proposal = generate_remediation(incident_type)

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
