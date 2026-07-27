import hashlib
import json
from pathlib import Path
import unittest

from PIL import Image

from paper.validate_manuscript_numbers_v2_0 import validate_marked_text


REPO = Path(__file__).resolve().parents[1]
PAPER = REPO / "paper"
ALLOWED_LEDGER_ROOTS = (
    "results/development_v2_0/",
    "results/ablation_v2_0/",
    "results/final_analysis_v2_0/",
    "results/holdout_v2_0/",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PaperAssetsTest(unittest.TestCase):
    def test_every_asset_metadata_declares_source_csv_and_hashes(self):
        metadata_paths = sorted((PAPER / "data").glob("*_metadata.json"))
        self.assertEqual(len(metadata_paths), 9)
        for metadata_path in metadata_paths:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["protocol_id"], "EV-FLEX-BIAS-V2.0")
            if metadata["asset_id"] == "fig1_framework_v2_0":
                self.assertIsNone(metadata["source_data_csv"])
                self.assertEqual(metadata["source_artifacts"], [])
                self.assertFalse(metadata["contains_experimental_values"])
                continue

            source_csv = REPO / metadata["source_data_csv"]
            self.assertTrue(source_csv.is_file(), metadata_path.name)
            self.assertEqual(sha256(source_csv), metadata["source_data_sha256"])
            self.assertTrue(metadata["source_artifacts"])
            for source in metadata["source_artifacts"]:
                source_path = REPO / source["path"]
                self.assertTrue(source_path.is_file(), source["path"])
                self.assertEqual(sha256(source_path), source["sha256"])

    def test_value_ledger_uses_only_v2_result_sources(self):
        ledger = json.loads(
            (PAPER / "generated_values_v2_0.json").read_text(encoding="utf-8")
        )
        self.assertEqual(ledger["protocol_id"], "EV-FLEX-BIAS-V2.0")
        self.assertGreater(len(ledger["values"]), 100)
        for key, record in ledger["values"].items():
            self.assertTrue(key.startswith("v2."), key)
            source_path = record["source_path"]
            self.assertTrue(source_path.startswith(ALLOWED_LEDGER_ROOTS), source_path)
            self.assertEqual(sha256(REPO / source_path), record["source_sha256"])
            self.assertIn("display", record)
            self.assertNotEqual(record["display"], "")

    def test_figure_export_bundle_is_complete_and_high_resolution(self):
        figure_directory = PAPER / "figures"
        stems = [
            "fig1_framework_v2_0",
            "fig2_alpha_map_v2_0",
            "fig3_false_safe_v2_0",
            "fig4_applicability_v2_0",
            "fig5_ablation_v2_0",
            "fig6_holdout_v2_0",
        ]
        for stem in stems:
            for suffix in (".png", ".tiff", ".svg", ".pdf"):
                path = figure_directory / f"{stem}{suffix}"
                self.assertTrue(path.is_file(), path.name)
                self.assertGreater(path.stat().st_size, 1000, path.name)
            with Image.open(figure_directory / f"{stem}.png") as image:
                dpi = image.info.get("dpi", (0, 0))
                self.assertGreaterEqual(min(dpi), 590)

    def test_manuscript_marker_validation_detects_exact_and_mismatched_values(self):
        ledger = {
            "v2.holdout.evaluations": {"display": "384"},
            "v2.holdout.false_safe_rate": {"display": "3.3%"},
        }
        valid = validate_marked_text(
            "The holdout contained 384 [[V2:v2.holdout.evaluations]] evaluations "
            "and a rate of 3.3% [[V2:v2.holdout.false_safe_rate]].",
            ledger,
        )
        invalid = validate_marked_text(
            "The holdout contained 383 [[V2:v2.holdout.evaluations]].",
            ledger,
        )
        self.assertEqual(valid["mismatches"], [])
        self.assertEqual(valid["unknown_keys"], [])
        self.assertEqual(valid["marker_count"], 2)
        self.assertEqual(len(invalid["mismatches"]), 1)


if __name__ == "__main__":
    unittest.main()
