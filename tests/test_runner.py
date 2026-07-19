import json
import os
from pathlib import Path
import tempfile
import unittest

from evflex import runner
from evflex.runner import atomic_write_json, exclusive_lock, run_work_unit


def current_process_id():
    return os.getpid()


def sample_work_unit():
    return {
        "work_unit_id": "v20_work_test__inc",
        "protocol_version": "EV-FLEX-BIAS-V2.0",
        "scenario_id": "test_01",
        "feeder": "ieee13",
        "call_time": "19:00",
        "direction": "inc",
        "scenario_seed": 123,
        "data_role": "development",
        "evaluation_ids": json.dumps(
            [
                "v20_core_test__inc__15m",
                "v20_core_test__inc__30m",
                "v20_core_test__inc__60m",
            ]
        ),
    }


def success_rows(work_unit):
    return [
        {"evaluation_id": evaluation_id, "duration_min": duration, "status": "SUCCESS"}
        for evaluation_id, duration in zip(
            json.loads(work_unit["evaluation_ids"]), (15, 30, 60)
        )
    ]


class RunnerTest(unittest.TestCase):
    def test_pool_recycles_process_after_each_work_unit(self):
        with runner.isolated_process_pool(1) as pool:
            first_pid = pool.submit(current_process_id).result(timeout=30)
            second_pid = pool.submit(current_process_id).result(timeout=30)
        self.assertNotEqual(first_pid, second_pid)

    def test_lock_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "work.lock"
            with exclusive_lock(lock_path):
                self.assertTrue(lock_path.exists())
            self.assertFalse(lock_path.exists())

            result_path = root / "result.json"
            atomic_write_json(result_path, {"status": "SUCCESS"})
            self.assertEqual(json.loads(result_path.read_text())["status"], "SUCCESS")

    def test_existing_lock_is_not_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "work.lock"
            lock_path.write_text("occupied", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                with exclusive_lock(lock_path):
                    pass
            self.assertTrue(lock_path.exists())

    def test_completed_result_is_skipped_without_engine_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work_unit = sample_work_unit()
            output = root / "result.json"
            atomic_write_json(
                output,
                {
                    "status": "SUCCESS",
                    "work_unit_id": work_unit["work_unit_id"],
                    "scenario_seed": work_unit["scenario_seed"],
                    "attempt_count": 1,
                    "evaluations": success_rows(work_unit),
                },
            )

            def must_not_run(_work_unit, _attempt):
                raise AssertionError("engine was called")

            result = run_work_unit(
                work_unit,
                output,
                root / "work.lock",
                must_not_run,
                resume=True,
            )
            self.assertEqual(result["runner_status"], "SKIPPED_COMPLETED")

    def test_infrastructure_retry_reuses_id_seed_and_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work_unit = sample_work_unit()
            output = root / "result.json"
            seen = []

            def flaky(unit, attempt):
                seen.append((unit["work_unit_id"], unit["scenario_seed"], attempt))
                if attempt == 1:
                    raise OSError("transient test failure")
                return success_rows(unit)

            result = run_work_unit(
                work_unit,
                output,
                root / "work.lock",
                flaky,
                resume=True,
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["attempt_count"], 2)
            self.assertEqual(
                seen,
                [
                    (work_unit["work_unit_id"], work_unit["scenario_seed"], 1),
                    (work_unit["work_unit_id"], work_unit["scenario_seed"], 2),
                ],
            )
            self.assertEqual([path.name for path in root.glob("*.json")], ["result.json"])

    def test_scientific_terminal_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work_unit = sample_work_unit()
            calls = []

            def infeasible(_unit, attempt):
                calls.append(attempt)
                raise RuntimeError("3ph baseline infeasible at slot 28")

            result = run_work_unit(
                work_unit,
                root / "result.json",
                root / "work.lock",
                infeasible,
                resume=True,
            )
            self.assertEqual(calls, [1])
            self.assertEqual(result["status"], "SCIENTIFIC_TERMINAL")
            self.assertEqual(
                {row["status"] for row in result["evaluations"]},
                {"THREE_PHASE_BASELINE_INFEASIBLE"},
            )


if __name__ == "__main__":
    unittest.main()
