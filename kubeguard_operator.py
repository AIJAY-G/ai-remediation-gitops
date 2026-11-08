import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Set

from k8s_monitor import detect_incident, select_primary_incident
from main import main as run_pipeline
from audit_logger import log_audit_event, verify_audit_log_integrity
from rbac import get_current_operator


class KubeGuardOperator:
    """
    24/7 Autonomous Kubernetes Controller / Operator Daemon.
    Continuously monitors cluster workloads, detects incidents, dispatches ChatOps alerts,
    enforces RBAC & risk gates, and drives GitOps self-healing without manual intervention.
    """

    def __init__(
        self,
        namespace: str = "ai-remediation",
        deployment: str = "demo-app",
        manifest_path: str = "gitops/demo-app.yaml",
        application_name: str = "ai-remediation",
        interval: int = 15,
        auto_execute: bool = False,
        max_retries: int = 1
    ):
        self.namespace = namespace
        self.deployment = deployment
        self.manifest_path = Path(manifest_path)
        self.application_name = application_name
        self.interval = max(5, int(interval))
        self.auto_execute = auto_execute
        self.max_retries = max_retries
        self.running = True
        self.handled_incidents: Dict[str, float] = {}  # incident_id -> timestamp
        self.cooldown_seconds = 180  # Cooldown before re-processing same incident

        # Setup graceful signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        print()
        print("[KubeGuard Operator] Received termination signal. Shutting down gracefully...")
        self.running = False

    def _clean_cooldowns(self):
        """Purges expired incident cooldowns from memory cache."""
        now = time.time()
        self.handled_incidents = {
            inc_id: ts
            for inc_id, ts in self.handled_incidents.items()
            if now - ts < self.cooldown_seconds
        }

    def run_tick(self) -> bool:
        """
        Executes a single monitoring tick.
        Returns True if an incident was processed, False otherwise.
        """
        self._clean_cooldowns()

        incidents = detect_incident(namespace=self.namespace)
        if not incidents:
            return False

        primary = select_primary_incident(incidents)
        if not primary:
            return False

        inc_id = primary.get("incident_id") or primary.get("resource_name", "unknown")

        # Skip recently handled incidents within cooldown window
        if inc_id in self.handled_incidents:
            return False

        print()
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] [KubeGuard Operator] Alert: Incident detected on {self.namespace}/{self.deployment}")
        self.handled_incidents[inc_id] = time.time()

        success = run_pipeline(
            namespace=self.namespace,
            deployment_name=self.deployment,
            manifest_path=self.manifest_path,
            application_name=self.application_name,
            auto_execute=self.auto_execute,
            max_retries=self.max_retries
        )
        return True

    def start(self):
        """Starts the 24/7 continuous autonomous monitoring loop."""
        user, role = get_current_operator()
        print("=" * 68)
        print("     KubeGuard AI — Autonomous Kubernetes Controller / Daemon")
        print("=" * 68)
        print(f"Target Namespace:    {self.namespace}")
        print(f"Target Deployment:   {self.deployment}")
        print(f"Argo CD Application: {self.application_name}")
        print(f"Polling Interval:    {self.interval}s")
        print(f"Auto-Execute Mode:   {'ENABLED (Low Risk)' if self.auto_execute else 'HUMAN SAFEGUARD'}")
        print(f"Operator Identity:   {user} ({role})")
        print("Status:              RUNNING (Press Ctrl+C to terminate)")
        print("=" * 68)

        # Integrity check on startup
        valid, msg, count = verify_audit_log_integrity()
        print(f"[Audit Engine] {msg}")
        print()

        while self.running:
            try:
                self.run_tick()
            except Exception as err:
                print(f"[Operator Warning] Tick error: {err}")

            # Sleep in 1-second chunks for responsive Ctrl+C handling
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

        print("[KubeGuard Operator] Stopped.")


def main():
    parser = argparse.ArgumentParser(description="KubeGuard AI 24/7 Autonomous Operator")
    parser.add_argument("--namespace", default="ai-remediation", help="Namespace to monitor")
    parser.add_argument("--deployment", default="demo-app", help="Deployment to monitor")
    parser.add_argument("--manifest", default="gitops/demo-app.yaml", help="GitOps manifest path")
    parser.add_argument("--app", default="ai-remediation", help="Argo CD application name")
    parser.add_argument("--interval", type=int, default=15, help="Polling interval in seconds (default: 15)")
    parser.add_argument("--auto-execute", action="store_true", help="Autonomous execution for low-risk proposals (<0.30)")
    parser.add_argument("--max-retries", type=int, default=1, help="Max retry attempts per incident")
    parser.add_argument("--once", action="store_true", help="Run a single monitoring tick and exit")
    args = parser.parse_args()

    operator = KubeGuardOperator(
        namespace=args.namespace,
        deployment=args.deployment,
        manifest_path=args.manifest,
        application_name=args.app,
        interval=args.interval,
        auto_execute=args.auto_execute,
        max_retries=args.max_retries
    )

    if args.once:
        processed = operator.run_tick()
        print(f"Single tick finished. Incident processed: {processed}")
    else:
        operator.start()


if __name__ == "__main__":
    main()
