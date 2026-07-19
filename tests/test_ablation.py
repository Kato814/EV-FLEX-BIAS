from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from evflex.ablation import (
    BOOTSTRAP_SEED,
    analyze_ablation_contrasts,
    bootstrap_contrast,
    merge_manifest_fields,
    stratified_bootstrap_indices,
    validate_ablation_manifest,
)


class AblationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(__file__).resolve().parents[1]
        cls.manifest = pd.read_csv(cls.repo / "manifests" / "compact_ablation_v2_0.csv")

    def test_fixed_design(self):
        summary = validate_ablation_manifest(self.manifest)
        self.assertEqual(
            summary["block_counts"],
            {
                "A1_phase": 72,
                "A2_location": 72,
                "A3_load": 72,
                "A4_urgency": 72,
                "A5_v2g": 48,
            },
        )
        self.assertEqual(summary["duration_min"], [15])
        self.assertEqual(summary["call_times"], ["02:00", "19:00"])
        self.assertEqual(summary["unique_seeds"], 336)
        self.assertTrue(summary["holdout_prohibited"])

    def test_holdout_access_is_rejected(self):
        invalid = self.manifest.copy()
        invalid.loc[0, "holdout_access"] = "allowed"
        with self.assertRaisesRegex(ValueError, "holdout"):
            validate_ablation_manifest(invalid)

    def test_manifest_pending_status_does_not_overwrite_result(self):
        merged = merge_manifest_fields(
            {"evaluation_id": "v20_abl_0001", "status": "SUCCESS"},
            pd.Series(
                {
                    "ablation_id": "v20_abl_0001",
                    "status": "PENDING",
                    "seed": 2026072001,
                }
            ),
        )
        self.assertEqual(merged["status"], "SUCCESS")
        self.assertEqual(merged["manifest_status"], "PENDING")

    def test_bootstrap_is_deterministic(self):
        frame = pd.DataFrame(
            {
                "feeder": ["ieee13"] * 6 + ["lv906"] * 6,
                "call_time": ["19:00"] * 12,
                "direction": ["inc"] * 12,
                "replicate": [0, 0, 0, 1, 1, 1] * 2,
            }
        )
        strata = ["feeder", "call_time", "direction", "replicate"]
        first = stratified_bootstrap_indices(frame, strata, 20, BOOTSTRAP_SEED)
        second = stratified_bootstrap_indices(frame, strata, 20, BOOTSTRAP_SEED)
        changed = stratified_bootstrap_indices(frame, strata, 20, BOOTSTRAP_SEED + 1)
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(first, second)))
        self.assertTrue(any(not np.array_equal(a, b) for a, b in zip(first, changed)))

    def test_bootstrap_contrast_is_deterministic(self):
        level = np.array([0.70, 0.75, 0.80, 0.82, 0.84, 0.86])
        reference = np.array([0.75, 0.76, 0.78, 0.80, 0.81, 0.83])
        first = bootstrap_contrast(level, reference, 1000, BOOTSTRAP_SEED)
        second = bootstrap_contrast(level, reference, 1000, BOOTSTRAP_SEED)
        self.assertEqual(first, second)
        self.assertIn("median_contrast", first)
        self.assertIn("ci_low", first)
        self.assertIn("ci_high", first)

    def test_fixed_analysis_produces_112_rows(self):
        results = self.manifest.copy()
        results["status"] = "SUCCESS"
        results["alpha_map"] = 0.80 + (results["replicate"] * 0.02)
        results["bias_pct"] = 10.0 + results["replicate"]
        first = analyze_ablation_contrasts(results, n_resamples=100, seed=BOOTSTRAP_SEED)
        second = analyze_ablation_contrasts(results, n_resamples=100, seed=BOOTSTRAP_SEED)
        self.assertEqual(len(first), 112)
        pd.testing.assert_frame_equal(first, second)
        references = first.loc[first["factor_level"].eq(first["reference_level"])]
        self.assertTrue(references["alpha_contrast"].eq(0.0).all())


if __name__ == "__main__":
    unittest.main()
