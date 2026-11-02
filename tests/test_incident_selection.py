import unittest
from k8s_monitor import select_primary_incident


class TestIncidentSelection(unittest.TestCase):

    def test_empty_list_returns_none(self):
        self.assertIsNone(select_primary_incident([]))
        self.assertIsNone(select_primary_incident(None))

    def test_single_pod_failure_selected(self):
        incidents = [
            {
                "incident_id": "INC-pod-1",
                "incident_type": "pod_failure",
                "resource_name": "demo-app-1"
            }
        ]
        selected = select_primary_incident(incidents)
        self.assertEqual(selected["incident_id"], "INC-pod-1")
        self.assertEqual(selected["incident_type"], "pod_failure")

    def test_pod_failure_prioritized_over_others(self):
        incidents = [
            {
                "incident_id": "INC-dep-1",
                "incident_type": "deployment_failure",
                "resource_name": "demo-app"
            },
            {
                "incident_id": "INC-pod-1",
                "incident_type": "pod_failure",
                "resource_name": "demo-app-pod-1"
            },
            {
                "incident_id": "INC-pod-restart-1",
                "incident_type": "pod_restart",
                "resource_name": "demo-app-pod-2"
            }
        ]
        selected = select_primary_incident(incidents)
        self.assertEqual(selected["incident_id"], "INC-pod-1")
        self.assertEqual(selected["incident_type"], "pod_failure")

    def test_first_incident_selected_when_no_pod_failure(self):
        incidents = [
            {
                "incident_id": "INC-dep-1",
                "incident_type": "deployment_failure",
                "resource_name": "demo-app"
            },
            {
                "incident_id": "INC-pod-restart-1",
                "incident_type": "pod_restart",
                "resource_name": "demo-app-pod-2"
            }
        ]
        selected = select_primary_incident(incidents)
        self.assertEqual(selected["incident_id"], "INC-dep-1")
        self.assertEqual(selected["incident_type"], "deployment_failure")

    def test_handles_non_dict_elements_defensively(self):
        incidents = ["invalid_element", {"incident_type": "pod_failure", "id": "valid"}]
        selected = select_primary_incident(incidents)
        self.assertEqual(selected.get("id"), "valid")


if __name__ == "__main__":
    unittest.main()
