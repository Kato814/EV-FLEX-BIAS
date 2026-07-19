import json
from pathlib import Path
import tempfile
import unittest

from evflex.holdout import (
    GATE_NAMES,
    assert_holdout_sealed,
    validate_gate_payloads,
    verify_file_records,
)


class HoldoutSealTest(unittest.TestCase):
    def passing_gates(self):
        return {
            path: {"gate": gate, "gate_status": "PASS"}
            for path, gate in GATE_NAMES.items()
        }

    def test_rejects_any_failed_preholdout_gate(self):
        payloads = self.passing_gates()
        payloads["reports/modeling_gate_v2_0.json"] = {
            "gate": "G3_MODEL_THRESHOLD_FREEZE",
            "gate_status": "FAIL",
        }
        with self.assertRaisesRegex(ValueError, "G3"):
            validate_gate_payloads(payloads)

    def test_rejects_required_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "artifact.txt"
            target.write_text("changed", encoding="utf-8")
            records = [
                {
                    "path": "artifact.txt",
                    "bytes": 8,
                    "sha256": "0" * 64,
                }
            ]
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_file_records(root, records)

    def test_rejects_existing_holdout_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "results" / "work_units" / "holdout" / "unit.json"
            result.parent.mkdir(parents=True)
            result.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "holdout result"):
                assert_holdout_sealed(root)

    def test_rejects_prior_unlock_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unlock = root / "state" / "holdout_unlock_v2_0.json"
            unlock.parent.mkdir(parents=True)
            unlock.write_text(
                json.dumps({"status": "UNLOCKED", "holdout_open_count": 1}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "already opened"):
                assert_holdout_sealed(root)


if __name__ == "__main__":
    unittest.main()
