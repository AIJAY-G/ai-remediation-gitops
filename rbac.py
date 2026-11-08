import os
from typing import Dict, Set, Tuple

# Role hierarchy definition
ROLES: Dict[str, Set[str]] = {
    "Platform-Admin": {"AUTO_EXECUTE", "LOW", "MEDIUM"},
    "SRE-Lead": {"AUTO_EXECUTE", "LOW", "MEDIUM"},
    "Developer": {"AUTO_EXECUTE", "LOW"},
    "Auditor": set(),
    "Viewer": set(),
}

VALID_ROLE_NAMES = set(ROLES.keys())


class RBACError(Exception):
    """Raised when an authorization violation occurs."""


def get_current_operator() -> Tuple[str, str]:
    """
    Resolves the current operator identity and role from system environment.
    Falls back safely to local user identity.
    """
    username = (
        os.getenv("KUBEGUARD_USER")
        or os.getenv("USERNAME")
        or os.getenv("USER")
        or "system-operator"
    ).strip()

    role = (
        os.getenv("KUBEGUARD_ROLE")
        or "SRE-Lead"
    ).strip()

    # Normalize role alias
    role_map = {
        "admin": "Platform-Admin",
        "platform-admin": "Platform-Admin",
        "sre": "SRE-Lead",
        "sre-lead": "SRE-Lead",
        "dev": "Developer",
        "developer": "Developer",
        "auditor": "Auditor",
        "viewer": "Viewer",
    }
    normalized_role = role_map.get(role.lower(), role)
    if normalized_role not in VALID_ROLE_NAMES:
        normalized_role = "Developer"

    return username, normalized_role


def authorize_approval(role: str, risk_decision: str) -> Tuple[bool, str]:
    """
    Evaluates whether the specified role is authorized to approve changes at the given risk decision tier.
    Enforces that HIGH risk / REJECT actions cannot be overridden by any human role.
    """
    decision = (risk_decision or "").strip().upper()
    role_name = (role or "").strip()

    if decision == "REJECT":
        return False, "Authorization Denied: Actions classified as REJECT (High Risk >= 0.60) cannot be authorized by any role."

    allowed_tiers = ROLES.get(role_name, set())

    # Map engine decisions to tier labels
    if decision == "AUTO_EXECUTE":
        target_tier = "LOW"
    elif decision == "HUMAN_APPROVAL":
        target_tier = "MEDIUM"
    else:
        target_tier = decision

    if target_tier not in allowed_tiers:
        return False, f"Authorization Denied: Role '{role_name}' lacks privilege to authorize '{decision}' actions. Requires 'SRE-Lead' or 'Platform-Admin'."

    return True, f"Authorized: Role '{role_name}' has verified clearance for '{decision}' remediation."


if __name__ == "__main__":
    user, r = get_current_operator()
    print(f"Current Operator: {user} (Role: {r})")
    allowed, msg = authorize_approval(r, "HUMAN_APPROVAL")
    print(f"Approval Check: {'ALLOWED' if allowed else 'DENIED'} - {msg}")
