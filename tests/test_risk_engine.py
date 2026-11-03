import math
import unittest
from risk_engine import calculate_risk


class TestRiskEngine(unittest.TestCase):

    def test_minimum_risk_vector(self):
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.0)
        self.assertAlmostEqual(risk, 0.0, places=4)
        self.assertEqual(decision, "AUTO_EXECUTE")

    def test_maximum_risk_vector(self):
        risk, decision = calculate_risk(0.0, 1.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(risk, 1.0, places=4)
        self.assertEqual(decision, "REJECT")

    def test_threshold_auto_execute_boundary(self):
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.29 / 0.15)
        self.assertAlmostEqual(risk, 0.29, places=4)
        self.assertEqual(decision, "AUTO_EXECUTE")

    def test_threshold_human_approval_lower_boundary(self):
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.30 / 0.15)
        self.assertAlmostEqual(risk, 0.30, places=4)
        self.assertEqual(decision, "HUMAN_APPROVAL")

    def test_threshold_human_approval_upper_boundary(self):
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.59 / 0.15)
        self.assertAlmostEqual(risk, 0.59, places=4)
        self.assertEqual(decision, "HUMAN_APPROVAL")

    def test_threshold_reject_boundary(self):
        risk, decision = calculate_risk(1.0, 0.0, 1.0, 1.0, 0.60 / 0.15)
        self.assertAlmostEqual(risk, 0.60, places=4)
        self.assertEqual(decision, "REJECT")

    def test_pod_failure_risk_vector(self):
        # Controlled test values; not a live LLM response.
        risk, decision = calculate_risk(0.90, 0.10, 1.00, 0.90, 0.10)
        self.assertAlmostEqual(risk, 0.075, places=4)
        self.assertEqual(decision, "AUTO_EXECUTE")

    def test_deployment_failure_risk_vector(self):
        # Controlled test values; not a live LLM response.
        risk, decision = calculate_risk(0.70, 0.40, 0.80, 0.60, 0.50)
        self.assertAlmostEqual(risk, 0.340, places=4)
        self.assertEqual(decision, "HUMAN_APPROVAL")

    def test_unknown_incident_risk_vector(self):
        # High-risk controlled vector; proposal generation is tested separately.
        risk, decision = calculate_risk(0.40, 0.80, 0.40, 0.20, 0.90)
        self.assertAlmostEqual(risk, 0.715, places=4)
        self.assertEqual(decision, "REJECT")

    def test_boolean_input_rejected_with_type_error(self):
        with self.assertRaises(TypeError):
            calculate_risk(True, 0.10, 1.00, 0.90, 0.10)
        with self.assertRaises(TypeError):
            calculate_risk(0.90, False, 1.00, 0.90, 0.10)

    def test_string_input_rejected_with_type_error(self):
        with self.assertRaises(TypeError):
            calculate_risk("0.90", 0.10, 1.00, 0.90, 0.10)

    def test_nan_input_rejected_with_value_error(self):
        with self.assertRaises(ValueError):
            calculate_risk(float("nan"), 0.10, 1.00, 0.90, 0.10)

    def test_infinite_input_rejected_with_value_error(self):
        with self.assertRaises(ValueError):
            calculate_risk(float("inf"), 0.10, 1.00, 0.90, 0.10)
        with self.assertRaises(ValueError):
            calculate_risk(0.90, float("-inf"), 1.00, 0.90, 0.10)


if __name__ == "__main__":
    unittest.main()
