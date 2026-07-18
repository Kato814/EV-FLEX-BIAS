import importlib.metadata
import os
import sys
import unittest

import evflex


EXPECTED = {
    "numpy": "2.3.5",
    "pandas": "2.2.3",
    "scipy": "1.17.0",
    "scikit-learn": "1.7.2",
    "opendssdirect.py": "0.9.4",
    "matplotlib": "3.10.7",
    "seaborn": "0.13.2",
}


class EnvironmentTest(unittest.TestCase):
    def test_python_minor(self):
        self.assertEqual(sys.version_info[:2], (3, 12))

    def test_locked_packages(self):
        actual = {name: importlib.metadata.version(name) for name in EXPECTED}
        self.assertEqual(actual, EXPECTED)

    def test_numeric_thread_caps(self):
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            self.assertEqual(os.environ.get(name), "1")


if __name__ == "__main__":
    unittest.main()
