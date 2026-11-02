import unittest
from risk_engine import calculate_risk
from llm_proposal import generate_remediation


class TestRiskEngine(unittest.TestCase):

    def test_minimum_risk_vector(self):
        # Best possible inputs: confidence=1.0, uncertainty=0.0, policy=1.0, reversibility=1.0, blast=0.0
        risk, decision = calculate_risk(
            confidence=1.0,
            uncertainty=0.0,
            policy_compliance=1.0,
            reversibility=1.0,
            blast_radius=0.0
        )
        self.assertAlmostEqual(risk, 0.0, places=4)
        self.assertEqual(decision, "AUTO_EXECUTE")

    def test_maximum_risk_vector(self):
        # Worst possible inputs: confidence=0.0, uncertainty=1.0, policy=0.0, reversibility=0.0, blast=1.0
        risk, decision = calculate_risk(
            confidence=0.0,
            uncertainty=1.0,
            policy_compliance=0.0,
            reversibility=0.0,
            blast_radius=1.0
        )
        self.assertAlmostEqual(risk, 1.0, places=4)
        self.assertEqual(decision, "REJECT")

    def test_threshold_auto_execute_boundary(self):
        # Just below 0.30
        # If confidence=1, uncertainty=0, policy=1, reversibility=1, blast=0.29 / 0.15 ...
        # Formula: (1-c)*0.25 + u*0.20 + (1-p)*0.25 + (1-r)*0.15 + b*0.15
        # Let's set blast_radius = 0.29 / 0.15 -> risk = 0.29
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.29 / 0.15)
        self.assertAlmostEqual(risk, 0.29, places=4)
        self.assertEqual(decision, "AUTO_EXECUTE")

    def test_threshold_human_approval_lower_boundary(self):
        # Exactly 0.30 -> HUMAN_APPROVAL
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.30 / 0.15)
        self.assertAlmostEqual(risk, 0.30, places=4)
        self.assertEqual(decision, "HUMAN_APPROVAL")

    def test_threshold_human_approval_upper_boundary(self):
        # Just below 0.60 -> HUMAN_APPROVAL
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.59 / 0.15)
        self.assertAlmostEqual(risk, 0.59, places=4)
        self.assertEqual(decision, "HUMAN_APPROVAL")

    def test_threshold_reject_boundary(self):
        # Exactly 0.60 -> REJECT
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.60 / 0.15)
        self.assertAlmostEqual(risk, 0.60, places=4)
        self.assertEqual(decision, "REJECT")

    def test_pod_failure_proposal_risk(self):
        proposal = generate_remediation("pod_failure")
        self.assertEqual(proposal["action"], "restart_pod")
        risk, decision = calculate_risk(
            proposal["confidence"],
            proposal["uncertainty"],
            proposal["policy_compliance"],
            proposal["reversibility"],
            proposal["blast_radius"]
        )
        # (1 - 0.90)*0.25 + 0.10*0.20 + (1 - 1.00)*0.25 + (1 - 0.90)*0.15 + 0.10*0.15
        # = 0.025 + 0.020 + 0.000 + 0.015 + 0.015 = 0.075
        self.assertAlmostEqual(risk, 0.075, places=4)
        self.assertEqual(decision, "AUTO_EXECUTE")

    def test_deployment_failure_proposal_risk(self):
        proposal = generate_remediation("deployment_failure")
        self.assertEqual(proposal["action"], "rollback_deployment")
        risk, decision = calculate_risk(
            proposal["confidence"],
            proposal["uncertainty"],
            proposal["policy_compliance"],
            proposal["reversibility"],
            proposal["blast_radius"]
        )
        # (1 - 0.70)*0.25 + 0.40*0.20 + (1 - 0.80)*0.25 + (1 - 0.60)*0.15 + 0.50*0.15
        # = 0.075 + 0.080 + 0.050 + 0.060 + 0.075 = 0.340
        self.assertAlmostEqual(risk, 0.340, places=4)
        self.assertEqual(decision, "HUMAN_APPROVAL")

    def test_unknown_incident_proposal_risk(self):
        proposal = generate_remediation("unknown_type")
        self.assertEqual(proposal["action"], "unknown")
        risk, decision = calculate_risk(
            proposal["confidence"],
            proposal["uncertainty"],
            proposal["policy_compliance"],
            proposal["reversibility"],
            proposal["blast_radius"]
        )
        # (1 - 0.40)*0.25 + 0.80*0.20 + (1 - 0.40)*0.25 + (1 - 0.20)*0.15 + 0.90*0.15
        # = 0.150 + 0.160 + 0.150 + 0.120 + 0.135 = 0.715
        self.assertAlmostEqual(risk, 0.715, places=4)
        self.assertEqual(decision, "REJECT")

    def test_proposal_accepts_dict_input(self):
        incident_dict = {
            "incident_type": "pod_failure",
            "resource_name": "demo-app-xxx"
        }
        proposal = generate_remediation(incident_dict)
        self.assertEqual(proposal["action"], "restart_pod")
        self.assertEqual(proposal["incident"], "pod_failure")


if __name__ == "__main__":
    unittest.main()
