import unittest

import pandas as pd

from evflex.manifests import build_ablation_manifest, validate_core_manifests


class ManifestTest(unittest.TestCase):
    def test_core_counts_and_roles(self):
        evaluations = pd.read_csv("manifests/core_evaluations_v2_0.csv")
        work = pd.read_csv("manifests/core_work_units_v2_0.csv")
        validate_core_manifests(evaluations, work)
        self.assertEqual(len(evaluations), 1536)
        self.assertEqual((evaluations.data_role == "development").sum(), 1152)
        self.assertEqual((evaluations.data_role == "holdout").sum(), 384)
        self.assertEqual(len(work), 512)
        self.assertEqual((work.data_role == "development").sum(), 384)
        self.assertEqual((work.data_role == "holdout").sum(), 128)

    def test_compact_ablation_count(self):
        frame = build_ablation_manifest()
        self.assertEqual(len(frame), 336)
        self.assertEqual(frame.ablation_id.nunique(), 336)
        self.assertEqual(frame.seed.nunique(), 336)
        self.assertTrue((frame.data_role == "development_ablation").all())
        self.assertTrue((frame.holdout_access == "prohibited").all())
        self.assertEqual(
            frame.block.value_counts().to_dict(),
            {"A1_phase": 72, "A2_location": 72, "A3_load": 72, "A4_urgency": 72, "A5_v2g": 48},
        )
        self.assertEqual(set(frame.call_time), {"19:00", "02:00"})
        self.assertEqual(set(frame.duration_min), {15})
        self.assertEqual(int(frame.seed.min()), 2026072001)
        self.assertEqual(int(frame.seed.max()), 2026072336)

    def test_inherited_split_and_seed_are_preserved(self):
        inherited = pd.read_csv("data/inherited/core_run_manifest_v1_2.csv")
        generated = pd.read_csv("manifests/core_evaluations_v2_0.csv")
        joined = generated.merge(
            inherited[["run_id", "data_split", "scenario_seed"]],
            left_on="inherited_run_id",
            right_on="run_id",
            validate="one_to_one",
        )
        self.assertTrue((joined.data_role == joined.data_split).all())
        self.assertTrue((joined.scenario_seed_x == joined.scenario_seed_y).all())


if __name__ == "__main__":
    unittest.main()
