"""
KubeGuard AI — Failure Scenario Evaluation Tool
Compares Low, Medium, and High Risk failure modes and outputs the exact
5-factor mathematical formula breakdown and RBAC decision.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from risk_engine import calculate_risk, evaluate_policy_compliance
from rbac import authorize_approval

# Ensure UTF-8 output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_scenario(title, incident, action, conf, uncert, policy_score, policy_msg, rev, blast, role_test):
    print("=" * 76)
    print(f"{BOLD}{title}{RESET}")
    print("=" * 76)
    print(f"  Incident Type:    {incident}")
    print(f"  Proposed Action:  {action}")
    print(f"  Policy Check:     {policy_msg}")
    print("-" * 76)
    print(f"  5 Risk Factors:")
    print(f"    1. Confidence:        {conf:.2f}  (Weight: 25%)")
    print(f"    2. Uncertainty:       {uncert:.2f}  (Weight: 20%)")
    print(f"    3. Policy Compliance: {policy_score:.2f}  (Weight: 25%)")
    print(f"    4. Reversibility:     {rev:.2f}  (Weight: 15%)")
    print(f"    5. Blast Radius:      {blast:.2f}  (Weight: 15%)")
    
    score, decision = calculate_risk(conf, uncert, policy_score, rev, blast)
    
    badge_color = GREEN if decision == "AUTO_EXECUTE" else (YELLOW if decision == "HUMAN_APPROVAL" else RED)
    print("-" * 76)
    print(f"  {BOLD}Calculated Risk Score:{RESET} {score:.3f}")
    print(f"  {BOLD}Risk Decision:{RESET}         {badge_color}{BOLD}{decision}{RESET}")
    
    # Test RBAC
    is_auth, auth_msg = authorize_approval(role_test, decision)
    auth_color = GREEN if is_auth else RED
    print(f"  {BOLD}RBAC Test ({role_test}):{RESET} {auth_color}{auth_msg}{RESET}")
    print()


def main():
    print(f"\n{CYAN}{BOLD}============================================================================{RESET}")
    print(f"{CYAN}{BOLD}       KUBEGUARD AI — RISK SPECTRUM COMPARISON (LOW / MED / HIGH)          {RESET}")
    print(f"{CYAN}{BOLD}============================================================================{RESET}\n")

    # 1. LOW RISK
    print_scenario(
        title="SCENARIO 1: LOW RISK (Transient Pod Crash / CrashLoopBackOff)",
        incident="CrashLoopBackOff (exit code 1)",
        action="restart_pod",
        conf=0.95,
        uncert=0.05,
        policy_score=1.0,
        policy_msg="Policy compliant: Safe pod restart annotation.",
        rev=0.95,
        blast=0.05,
        role_test="Developer"
    )

    # 2. MEDIUM RISK (Image Pull Error / Rollback)
    print_scenario(
        title="SCENARIO 2A: MEDIUM RISK (ImagePullBackOff / Rollback Image)",
        incident="ImagePullBackOff (Faulty container release tag)",
        action="rollback_image",
        conf=0.65,
        uncert=0.35,
        policy_score=1.0,
        policy_msg="Policy compliant: Reverting image tag to previous stable commit.",
        rev=0.55,
        blast=0.50,
        role_test="Developer"
    )

    # 2B. MEDIUM RISK (OOMKilled) tested with SRE-Lead
    print_scenario(
        title="SCENARIO 2B: MEDIUM RISK (OOMKilled 137 / Scale Memory Limit)",
        incident="OOMKilled (Exit Code 137 - Container Out of Memory)",
        action="update_memory_limit",
        conf=0.60,
        uncert=0.40,
        policy_score=1.0,
        policy_msg="Policy compliant: Scale memory allocation from 64Mi to 256Mi.",
        rev=0.60,
        blast=0.55,
        role_test="SRE-Lead"
    )

    # 3. HIGH RISK
    print_scenario(
        title="SCENARIO 3: HIGH RISK (Security Escalation / Privileged Container)",
        incident="Privilege Escalation Request",
        action="modify_security_context",
        conf=0.30,
        uncert=0.70,
        policy_score=0.0,
        policy_msg="Policy VIOLATION: Privileged execution and hostPID are prohibited by OPA.",
        rev=0.10,
        blast=0.85,
        role_test="Platform-Admin"
    )


if __name__ == "__main__":
    main()
