import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

AUDIT_LOG_FILE = Path("evidence/compliance_audit.jsonl")
GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


def _compute_sha256(data: str) -> str:
    """Computes a SHA256 hexadecimal hash string for arbitrary text."""
    return hashlib.sha256((data or "").encode("utf-8")).hexdigest()


def _get_last_record_hash(log_path: Path = AUDIT_LOG_FILE) -> str:
    """Retrieves the record_hash of the most recent log entry to maintain cryptographic chain integrity."""
    if not log_path.exists():
        return GENESIS_HASH

    last_line = ""
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
        if last_line:
            record = json.loads(last_line)
            return record.get("record_hash", GENESIS_HASH)
    except Exception:
        pass
    return GENESIS_HASH


def log_audit_event(
    incident_id: str,
    resource: str,
    failure_reason: str,
    action: str,
    risk_score: float,
    risk_vector: Dict[str, float],
    policy_status: str,
    decision: str,
    authorized_by: str,
    authorizer_role: str,
    git_commit: Optional[str] = None,
    validation_status: Optional[str] = None,
    container_logs: Optional[str] = None,
    description: Optional[str] = None,
    log_path: Path = AUDIT_LOG_FILE
) -> Dict[str, Any]:
    """
    Appends an immutable, cryptographically chained audit record complying with SOC2 & ISO 27001 standards.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prev_hash = _get_last_record_hash(log_path)
    now_utc = datetime.now(timezone.utc).isoformat()
    logs_hash = _compute_sha256(container_logs) if container_logs else "NONE"

    entry: Dict[str, Any] = {
        "timestamp_utc": now_utc,
        "incident_id": incident_id,
        "resource": resource,
        "failure_reason": failure_reason,
        "evidence_logs_sha256": logs_hash,
        "proposed_action": action,
        "action_description": description or "",
        "risk_score": round(float(risk_score), 4),
        "risk_vector": {k: round(float(v), 4) for k, v in risk_vector.items()},
        "policy_compliance_status": policy_status,
        "authorization_decision": decision,
        "authorized_by": authorized_by,
        "authorizer_role": authorizer_role,
        "git_commit_sha": git_commit or "NONE",
        "validation_status": validation_status or "PENDING",
        "previous_record_hash": prev_hash,
    }

    # Cryptographic hash over all payload fields + previous link
    serialized_payload = json.dumps(entry, sort_keys=True)
    entry["record_hash"] = _compute_sha256(serialized_payload)

    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def verify_audit_log_integrity(log_path: Path = AUDIT_LOG_FILE) -> Tuple[bool, str, int]:
    """
    Validates the entire audit log file against cryptographic hash chain tampering.
    Returns (is_valid, report_message, record_count).
    """
    if not log_path.exists():
        return True, "Audit log does not exist yet (clean slate).", 0

    records_read = 0
    expected_prev_hash = GENESIS_HASH

    with log_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                return False, f"Corruption detected at line {line_num}: invalid JSON", records_read

            actual_record_hash = record.get("record_hash")
            actual_prev_hash = record.get("previous_record_hash")

            if actual_prev_hash != expected_prev_hash:
                return (
                    False,
                    f"Chain break at record {line_num}: expected previous hash '{expected_prev_hash[:12]}...', "
                    f"got '{actual_prev_hash[:12] if actual_prev_hash else 'None'}...'",
                    records_read
                )

            # Recompute hash
            copy_to_check = {k: v for k, v in record.items() if k != "record_hash"}
            recomputed = _compute_sha256(json.dumps(copy_to_check, sort_keys=True))

            if recomputed != actual_record_hash:
                return (
                    False,
                    f"Tamper detected at record {line_num}: hash mismatch. Record has been altered.",
                    records_read
                )

            expected_prev_hash = actual_record_hash
            records_read += 1

    return True, f"Audit log verified: {records_read} records validated with 100% cryptographic integrity.", records_read


if __name__ == "__main__":
    valid, message, count = verify_audit_log_integrity()
    print(f"Status: {'VALID' if valid else 'COMPROMISED'}")
    print(f"Details: {message}")
