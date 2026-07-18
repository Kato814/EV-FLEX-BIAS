import unittest

from evflex.engine import select_nested_candidate


class EngineTest(unittest.TestCase):
    def test_longer_feasible_candidate_promotes_shorter_duration(self):
        raw = {
            15: {"flex_kw": 8.0, "physical_feasible": True},
            30: {"flex_kw": 9.0, "physical_feasible": True},
            60: {"flex_kw": 7.0, "physical_feasible": True},
        }
        selected = select_nested_candidate(raw, 15)
        self.assertEqual(selected["source_duration_min"], 30)
        self.assertEqual(selected["flex_kw"], 9.0)

    def test_infeasible_candidate_is_rejected(self):
        raw = {
            15: {"flex_kw": 8.0, "physical_feasible": True},
            30: {"flex_kw": 20.0, "physical_feasible": False},
            60: {"flex_kw": 7.0, "physical_feasible": True},
        }
        selected = select_nested_candidate(raw, 15)
        self.assertEqual(selected["source_duration_min"], 15)


if __name__ == "__main__":
    unittest.main()
