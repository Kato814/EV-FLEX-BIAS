from pathlib import Path
import tempfile
import unittest

from evflex.provenance import sha256_file, verify_rows


class ProvenanceTest(unittest.TestCase):
    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.bin"
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_verify_rows_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.bin"
            path.write_bytes(b"abc")
            rows = [{"path": str(path), "sha256": "0" * 64}]
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_rows(rows)


if __name__ == "__main__":
    unittest.main()
