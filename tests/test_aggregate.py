import unittest

from evflex.aggregate import assess_evaluations


def valid_rows():
    rows = []
    for duration in (15, 30, 60):
        rows.append(
            {
                "evaluation_id": f"eval_{duration}",
                "work_unit_id": "work_1",
                "scenario_id": "scenario_1",
                "feeder": "ieee13",
                "direction": "inc",
                "duration_min": duration,
                "status": "SUCCESS",
                "physical_feasible": True,
                "max_departure_error_kwh": 0.0,
                "max_reserve_violation_kwh": 0.0,
                "max_capacity_violation_kwh": 0.0,
                "min_soc_margin_kwh": 0.0,
                "simultaneous_slots": 0,
            }
        )
    return rows


class AggregateTest(unittest.TestCase):
    def test_valid_bundle_passes(self):
        report = assess_evaluations(valid_rows(), expected_evaluations=3)
        self.assertEqual(report["gate_status"], "PASS")

    def test_duplicate_evaluation_id_fails(self):
        rows = valid_rows()
        rows.append(dict(rows[0]))
        report = assess_evaluations(rows, expected_evaluations=4)
        self.assertEqual(report["gate_status"], "FAIL")
        self.assertTrue(report["violations"]["duplicate_evaluation_ids"])

    def test_missing_duration_fails(self):
        report = assess_evaluations(valid_rows()[:2], expected_evaluations=2)
        self.assertEqual(report["gate_status"], "FAIL")
        self.assertTrue(report["violations"]["incomplete_duration_bundles"])

    def test_unhandled_failure_fails(self):
        rows = valid_rows()
        rows[0]["status"] = "UNHANDLED_FAILURE"
        report = assess_evaluations(rows, expected_evaluations=3)
        self.assertEqual(report["gate_status"], "FAIL")
        self.assertEqual(report["unhandled_failure_count"], 1)

    def test_simultaneous_charge_discharge_fails(self):
        rows = valid_rows()
        rows[1]["simultaneous_slots"] = 1
        report = assess_evaluations(rows, expected_evaluations=3)
        self.assertEqual(report["gate_status"], "FAIL")

    def test_negative_soc_margin_fails(self):
        rows = valid_rows()
        rows[2]["min_soc_margin_kwh"] = -1e-4
        report = assess_evaluations(rows, expected_evaluations=3)
        self.assertEqual(report["gate_status"], "FAIL")

    def test_scientific_infeasibility_is_terminal_not_crash(self):
        rows = valid_rows()
        rows[0]["status"] = "THREE_PHASE_BASELINE_INFEASIBLE"
        rows[0]["physical_feasible"] = None
        report = assess_evaluations(rows, expected_evaluations=3)
        self.assertEqual(report["gate_status"], "PASS")
        self.assertEqual(report["scientific_terminal_count"], 1)
        self.assertEqual(report["unhandled_failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
