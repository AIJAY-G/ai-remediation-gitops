def generate_remediation(incident):
    if isinstance(incident, dict):
        incident_type = incident.get("incident_type", "")
    else:
        incident_type = incident

    # Pod failure / restart incidents
    if incident_type in [
        "pod_crash",
        "pod_failure",
        "pod_restart"
    ]:
        return {
            "incident": incident_type,
            "action": "restart_pod",
            "description": "Restart the affected Kubernetes pod",
            "confidence": 0.90,
            "uncertainty": 0.10,
            "policy_compliance": 1.00,
            "reversibility": 0.90,
            "blast_radius": 0.10
        }

    # Deployment failure
    if incident_type == "deployment_failure":
        return {
            "incident": incident_type,
            "action": "rollback_deployment",
            "description": "Rollback the affected deployment",
            "confidence": 0.70,
            "uncertainty": 0.40,
            "policy_compliance": 0.80,
            "reversibility": 0.60,
            "blast_radius": 0.50
        }

    # Unknown incident
    return {
        "incident": incident_type,
        "action": "unknown",
        "description": "No safe remediation identified",
        "confidence": 0.40,
        "uncertainty": 0.80,
        "policy_compliance": 0.40,
        "reversibility": 0.20,
        "blast_radius": 0.90
    }


if __name__ == "__main__":
    proposal = generate_remediation("pod_failure")

    print("LLM Remediation Proposal")
    print("------------------------")

    for key, value in proposal.items():
        print(f"{key}: {value}")
