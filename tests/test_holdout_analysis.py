import hashlib
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from evflex.holdout_analysis import (
    build_holdout_feature_frame,
    directional_summary,
    evaluate_frozen_applicability,
    wilson_interval,
)


REPO = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO / "results" / "modeling_v2_0" / "applicability_models_v2_0.json"


class HoldoutAnalysisTest(unittest.TestCase):
    def test_wilson_intervals_cover_zero_one_and_all_failures(self):
        zero = wilson_interval(0, 20)
        one = wilson_interval(1, 20)
        all_failed = wilson_interval(20, 20)

        self.assertAlmostEqual(zero[0], 0.0)
        self.assertAlmostEqual(zero[1], 0.16112515805281938)
        self.assertAlmostEqual(one[0], 0.008881448800795402)
        self.assertAlmostEqual(one[1], 0.23613119344674205)
        self.assertAlmostEqual(all_failed[0], 0.8388748419471806)
        self.assertAlmostEqual(all_failed[1], 1.0)
        self.assertEqual(wilson_interval(0, 0), (None, None))

    def test_frozen_model_scoring_does_not_mutate_model_or_thresholds(self):
        before_bytes = MODEL_PATH.read_bytes()
        before_file_hash = hashlib.sha256(before_bytes).hexdigest()
        payload = json.loads(before_bytes)
        before_payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        fixture_rows = []
        for record in payload["models"]:
            model = record["final_model"]
            row = {
                "evaluation_id": f"fixture_{record['cell_id']}",
                "scenario_id": f"scenario_{record['cell_id']}",
                "data_role": "holdout",
                "feeder": record["feeder"],
                "direction": record["direction"],
                "duration_min": record["duration_min"],
                "alpha_map": 1.0,
                "false_safe": False,
                "dominant_phase": model["dominant_phase_reference"],
            }
            row.update(dict(zip(model["numeric_features"], model["numeric_mean"])))
            fixture_rows.append(row)

        validation = evaluate_frozen_applicability(
            payload,
            pd.DataFrame(fixture_rows),
            model_sha256=before_file_hash,
        )

        after_bytes = MODEL_PATH.read_bytes()
        after_payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(len(validation), 12)
        self.assertEqual(hashlib.sha256(after_bytes).hexdigest(), before_file_hash)
        self.assertEqual(after_payload_hash, before_payload_hash)
        self.assertTrue(validation["model_sha256"].eq(before_file_hash).all())

    def test_holdout_feature_contract_rejects_split_crossing(self):
        evaluations = pd.DataFrame(
            {
                "evaluation_id": ["e1"],
                "scenario_id": ["s1"],
                "data_role": ["holdout"],
                "feeder": ["ieee13"],
                "call_time": ["19:00"],
                "direction": ["dec"],
                "duration_min": [15],
                "status": ["SUCCESS"],
                "alpha_map": [0.9],
            }
        )
        scenarios = pd.DataFrame(
            {
                "scenario_id": ["s1"],
                "data_split": ["holdout"],
                "native_load_multiplier": [1.0],
                "phase_ratio": ["4:1:1"],
                "dominant_phase": ["b"],
                "far_zone_probability": [0.5],
            }
        )
        populations = pd.DataFrame(
            {
                "scenario_id": ["s1"],
                "data_split": ["holdout"],
                "actual_nameplate_to_transformer_ratio": [0.4],
                "median_natural_urgency": [0.1],
                "v2g_actual_rate": [0.6],
            }
        )

        features = build_holdout_feature_frame(evaluations, scenarios, populations)
        self.assertEqual(features.loc[0, "data_role"], "holdout")
        self.assertTrue(bool(features.loc[0, "false_safe"]))
        self.assertAlmostEqual(features.loc[0, "phase_imbalance_index"], 0.5)

        scenarios.loc[0, "data_split"] = "development"
        with self.assertRaisesRegex(ValueError, "sealed split"):
            build_holdout_feature_frame(evaluations, scenarios, populations)

    def test_directional_bootstrap_is_deterministic_and_pairs_scenarios(self):
        rows = []
        for index in range(6):
            for direction, alpha, bias, capacity in (
                ("inc", 0.80 + index / 100, 20.0 + index, 100.0 + index),
                ("dec", 0.95 + index / 100, 5.0 + index, 80.0 + index),
            ):
                rows.append(
                    {
                        "evaluation_id": f"e{index}_{direction}",
                        "scenario_id": f"s{index}",
                        "data_role": "holdout",
                        "feeder": "ieee13",
                        "call_time": "19:00",
                        "direction": direction,
                        "duration_min": 15,
                        "status": "SUCCESS",
                        "alpha_map": alpha,
                        "bias_pct": bias,
                        "f_3ph_kw": capacity,
                    }
                )
        frame = pd.DataFrame(rows)

        first, first_audit = directional_summary(
            frame, bootstrap_resamples=200, bootstrap_seed=2026072002
        )
        second, second_audit = directional_summary(
            frame, bootstrap_resamples=200, bootstrap_seed=2026072002
        )

        pd.testing.assert_frame_equal(first, second)
        self.assertEqual(first_audit, second_audit)
        self.assertEqual(len(first), 1)
        self.assertEqual(first.loc[0, "paired_n"], 6)
        self.assertAlmostEqual(first.loc[0, "median_alpha_difference_inc_minus_dec"], -0.15)
        self.assertAlmostEqual(first.loc[0, "median_bias_difference_inc_minus_dec"], 15.0)
        self.assertAlmostEqual(
            first.loc[0, "median_capacity_difference_inc_minus_dec_kw"], 20.0
        )
        self.assertEqual(first_audit["unpaired_evaluation_ids"], [])


if __name__ == "__main__":
    unittest.main()
