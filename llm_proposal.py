
import json
import math
import os
import urllib.error
import urllib.request


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT", "180"))

SUPPORTED_INCIDENTS = {
    "pod_failure",
    "pod_crash",
    "pod_restart",
}

ALLOWED_ACTIONS = {"restart_pod"}

RISK_FIELDS = (
    "confidence",
    "uncertainty",
    "policy_compliance",
    "reversibility",
    "blast_radius",
)


class ProposalError(Exception):
    """Raised when a safe remediation proposal cannot be generated."""


def _validate_proposal(proposal, incident_type):
    if not isinstance(proposal, dict):
        raise ProposalError("LLM response must be a JSON object.")

    required = {
        "incident",
        "action",
        "description",
        *RISK_FIELDS,
    }

    if set(proposal.keys()) != required:
        raise ProposalError("LLM response has missing or unexpected fields.")

    if proposal["incident"] != incident_type:
        raise ProposalError("LLM returned a mismatched incident type.")

    if proposal["action"] not in ALLOWED_ACTIONS:
        raise ProposalError(
            f"Unsupported remediation action: {proposal['action']}"
        )

    description = proposal["description"]

    if not isinstance(description, str) or not description.strip():
        raise ProposalError("Proposal description is invalid.")

    for field in RISK_FIELDS:
        value = proposal[field]

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProposalError(f"{field} must be a numeric value.")

        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ProposalError(f"{field} must be between 0 and 1.")

        proposal[field] = float(value)

    return proposal


def generate_remediation(incident):
    if isinstance(incident, dict):
        incident_type = incident.get("incident_type", "")
    else:
        incident_type = incident

    if not isinstance(incident_type, str):
        raise ProposalError("Incident type must be a string.")

    incident_type = incident_type.strip()

    if incident_type not in SUPPORTED_INCIDENTS:
        raise ProposalError(
            f"Unsupported incident type: {incident_type}"
        )

    context_lines = [f"Incident type: {incident_type}"]
    if isinstance(incident, dict):
        res_name = incident.get("resource_name")
        if res_name:
            context_lines.append(f"Resource: {incident.get('resource_type', 'Resource')}/{res_name}")
        ev = incident.get("evidence") or {}
        if ev.get("failure_reason"):
            context_lines.append(f"Failure reason: {ev.get('failure_reason')}")
        if ev.get("restart_count") is not None:
            context_lines.append(f"Container restart count: {ev.get('restart_count')}")
        if ev.get("prometheus_restarts") is not None:
            context_lines.append(f"Prometheus restart telemetry: {ev.get('prometheus_restarts')}")
        if ev.get("events"):
            context_lines.append("Recent warning events: " + "; ".join(ev["events"][:3]))
        if ev.get("pod_logs"):
            log_snippet = ev["pod_logs"][-500:]
            context_lines.append(f"Container logs (tail):\n{log_snippet}")

    incident_context = "\n".join(context_lines)

    prompt = f"""
You are an expert Kubernetes AIOps remediation generator.

Analyze this incident, understand the failure, and determine root cause:
{incident_context}

Return ONLY one JSON object with exactly these fields:
{{
  "incident": "{incident_type}",
  "action": "restart_pod",
  "description": "Root Cause Analysis (RCA) and explanation of why this action is safe and appropriate",
  "confidence": 0.0,
  "uncertainty": 0.0,
  "policy_compliance": 0.0,
  "reversibility": 0.0,
  "blast_radius": 0.0
}}

All five numerical values must be between 0.0 and 1.0.

Only propose restart_pod.
Do not include shell commands, Kubernetes commands,
additional fields, markdown, or text outside the JSON.
These numerical values are estimates, not verified facts.
"""

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return valid JSON only. "
                    "Follow the requested schema exactly."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "format": "json",
        "stream": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.1,
            "num_predict": 160,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_exc = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT_SECONDS,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))

            content = result["message"]["content"]
            proposal = json.loads(content)
            return _validate_proposal(proposal, incident_type)

        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt == 0:
                print("Ollama connection timed out or is warming up; retrying request...")
                continue
            raise ProposalError(
                f"Ollama connection failed: {exc}"
            ) from exc

        except (KeyError, TypeError, ValueError) as exc:
            raise ProposalError(
                f"Invalid Ollama response: {exc}"
            ) from exc


if __name__ == "__main__":
    try:
        proposal = generate_remediation("pod_failure")

        print("Ollama LLM Remediation Proposal")
        print("--------------------------------")

        for key, value in proposal.items():
            print(f"{key}: {value}")

    except ProposalError as exc:
        print(f"PROPOSAL REJECTED: {exc}")
