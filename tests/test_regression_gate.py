import unittest

from evflex.regression import close_capacity, close_scalar


class RegressionGateTest(unittest.TestCase):
    def test_capacity_tolerance(self):
        self.assertTrue(close_capacity(100.0, 100.000001))
        self.assertFalse(close_capacity(100.0, 100.1))

    def test_alpha_tolerance(self):
        self.assertTrue(close_scalar(0.95, 0.950000001, 1e-8))
        self.assertFalse(close_scalar(0.95, 0.951, 1e-8))


if __name__ == "__main__":
    unittest.main()
