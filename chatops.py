import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

NOTIFICATION_LOG = Path("evidence/chatops_notifications.jsonl")


def format_slack_card(
    incident: Dict[str, Any],
    proposal: Dict[str, Any],
    risk_score: float,
    decision: str,
    commit_sha: Optional[str] = None
) -> Dict[str, Any]:
    """Formats an incident alert payload for Slack incoming webhooks."""
    res_type = incident.get("resource_type", "Resource")
    res_name = incident.get("resource_name", "unknown")
    inc_type = incident.get("incident_type", "unknown")
    ev = incident.get("evidence", {}) or {}
    reason = ev.get("failure_reason", "N/A")

    severity_color = "#36a64f" if risk_score < 0.30 else ("#ecb22e" if risk_score < 0.60 else "#e01e5a")

    return {
        "text": f"KubeGuard AI Alert: {inc_type} detected on {res_type}/{res_name}",
        "attachments": [
            {
                "color": severity_color,
                "title": f"🚨 Incident: {inc_type} ({res_type}/{res_name})",
                "fields": [
                    {"title": "Failure Reason", "value": str(reason), "short": True},
                    {"title": "Risk Score / Tier", "value": f"{risk_score:.2f} ({decision})", "short": True},
                    {"title": "Proposed Action", "value": proposal.get("action", "N/A"), "short": True},
                    {"title": "Git Commit", "value": (commit_sha[:7] if commit_sha else "PENDING"), "short": True},
                    {"title": "Ollama Root Cause Analysis", "value": proposal.get("description", "N/A"), "short": False},
                ],
                "footer": "KubeGuard AI Enterprise Guardian",
                "ts": int(datetime.now(timezone.utc).timestamp())
            }
        ]
    }


def send_chatops_notification(
    incident: Dict[str, Any],
    proposal: Dict[str, Any],
    risk_score: float,
    decision: str,
    commit_sha: Optional[str] = None,
    webhook_url: Optional[str] = None
) -> bool:
    """
    Dispatches a structured alert card to configured Slack, Teams, or Discord webhooks.
    Gracefully logs locally if no webhook URL is defined.
    """
    url = webhook_url or os.getenv("KUBEGUARD_SLACK_WEBHOOK") or os.getenv("KUBEGUARD_CHATOPS_WEBHOOK")
    payload = format_slack_card(incident, proposal, risk_score, decision, commit_sha)

    # Persist notification locally for auditability
    try:
        NOTIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with NOTIFICATION_LOG.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": payload
            }) + "\n")
    except Exception:
        pass

    if not url:
        print("[ChatOps] Notification logged locally (KUBEGUARD_SLACK_WEBHOOK not set).")
        return True

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status in (200, 204)
    except Exception as err:
        print(f"[ChatOps Warning] Failed to dispatch webhook alert: {err}")
        return False


if __name__ == "__main__":
    test_inc = {
        "incident_type": "pod_failure",
        "resource_type": "Pod",
        "resource_name": "demo-app-test",
        "evidence": {"failure_reason": "CrashLoopBackOff"}
    }
    test_prop = {
        "action": "restart_pod",
        "description": "Restart pod to recover from entrypoint failure."
    }
    success = send_chatops_notification(test_inc, test_prop, 0.15, "AUTO_EXECUTE")
    print(f"ChatOps Result: {'SUCCESS' if success else 'FAILED'}")
