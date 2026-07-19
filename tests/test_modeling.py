import unittest

import numpy as np
import pandas as pd

from evflex.modeling import (
    C_GRID,
    CV_SEED,
    build_feature_frame,
    choose_threshold,
    fit_cell_model,
    predict_risk_scores,
    select_threshold_candidate,
)


class ModelingTest(unittest.TestCase):
    def test_threshold_maximizes_qualifying_coverage(self):
        scores = np.array([0.10] * 20 + [0.20] + [0.90] * 4)
        labels = np.array([1] + [0] * 20 + [1] + [0] * 3)

        selected = choose_threshold(scores, labels)

        self.assertEqual(selected["selected_n"], 21)
        self.assertAlmostEqual(selected["risk_threshold"], 0.20)
        self.assertLessEqual(selected["false_safe_rate"], 0.05)
        self.assertGreaterEqual(selected["selected_n"], 20)

    def test_equal_coverage_tie_selects_lower_risk_threshold(self):
        candidates = [
            {"risk_threshold": 0.25, "selected_n": 20, "false_safe_rate": 0.05},
            {"risk_threshold": 0.20, "selected_n": 20, "false_safe_rate": 0.05},
        ]
        self.assertEqual(
            select_threshold_candidate(candidates)["risk_threshold"], 0.20
        )

    def test_no_qualifying_threshold_returns_none(self):
        scores = np.linspace(0.01, 0.30, 30)
        labels = np.ones(30, dtype=int)
        self.assertIsNone(choose_threshold(scores, labels))

    def test_feature_contract_uses_frozen_inputs(self):
        evaluations = pd.DataFrame(
            {
                "evaluation_id": ["v20_core_s1__dec__15m"],
                "scenario_id": ["s1"],
                "data_role": ["development"],
                "feeder": ["ieee13"],
                "call_time": ["19:00"],
                "direction": ["dec"],
                "duration_min": [15],
                "status": ["SUCCESS"],
                "alpha_map": [1.0],
            }
        )
        scenarios = pd.DataFrame(
            {
                "scenario_id": ["s1"],
                "data_split": ["development"],
                "native_load_multiplier": [1.02],
                "phase_ratio": ["4:1:1"],
                "dominant_phase": ["b"],
                "far_zone_probability": [0.6],
            }
        )
        populations = pd.DataFrame(
            {
                "scenario_id": ["s1"],
                "data_split": ["development"],
                "actual_nameplate_to_transformer_ratio": [0.45],
                "median_natural_urgency": [0.12],
                "v2g_actual_rate": [0.7],
            }
        )

        features = build_feature_frame(evaluations, scenarios, populations)

        self.assertAlmostEqual(features.loc[0, "phase_imbalance_index"], 0.5)
        self.assertAlmostEqual(features.loc[0, "call_time_sin"], -0.9659258263)
        self.assertAlmostEqual(features.loc[0, "call_time_cos"], 0.2588190451)
        self.assertAlmostEqual(features.loc[0, "realized_v2g_participation"], 0.7)
        self.assertEqual(features.loc[0, "dominant_phase"], "b")
        self.assertTrue(features.loc[0, "false_safe"] == False)

    def test_cell_fit_is_deterministic_and_uses_frozen_cv(self):
        n = 40
        frame = pd.DataFrame(
            {
                "evaluation_id": [f"eval_{i:02d}" for i in range(n)],
                "scenario_id": [f"scenario_{i:02d}" for i in range(n)],
                "data_role": ["development"] * n,
                "feeder": ["ieee13"] * n,
                "direction": ["inc"] * n,
                "duration_min": [15] * n,
                "alpha_map": [0.8 if i % 4 == 0 else 1.0 for i in range(n)],
                "false_safe": [i % 4 == 0 for i in range(n)],
                "actual_nameplate_to_transformer_ratio": np.linspace(0.2, 0.8, n),
                "native_load_multiplier": np.linspace(0.8, 1.2, n),
                "phase_imbalance_index": [0.0, 0.25, 0.5, 0.25] * 10,
                "far_zone_probability": np.linspace(0.1, 0.9, n),
                "median_natural_urgency": np.linspace(0.01, 0.3, n),
                "call_time_sin": [0.0, 0.5, -0.5, 1.0] * 10,
                "call_time_cos": [1.0, -0.5, 0.5, 0.0] * 10,
                "dominant_phase": ["a", "b", "c", "a"] * 10,
            }
        )

        first_record, first_oof = fit_cell_model(frame)
        second_record, second_oof = fit_cell_model(frame)

        self.assertEqual(first_record["cv_seed"], CV_SEED)
        self.assertIn(first_record["selected_c"], C_GRID)
        self.assertEqual(first_record, second_record)
        np.testing.assert_allclose(first_oof["oof_risk_score"], second_oof["oof_risk_score"])
        self.assertEqual(first_record["final_model"]["dominant_phase_reference"], "a")
        frozen_scores = predict_risk_scores(first_record, frame)
        self.assertEqual(frozen_scores.shape, (n,))
        self.assertTrue(np.isfinite(frozen_scores).all())


if __name__ == "__main__":
    unittest.main()
