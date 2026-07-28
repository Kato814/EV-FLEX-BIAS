from __future__ import annotations

import os


_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)
THREAD_ENVIRONMENT = {name: "1" for name in _THREAD_VARIABLES}
for _name, _value in THREAD_ENVIRONMENT.items():
    os.environ[_name] = _value


import argparse
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import ctypes
import errno
import json
import multiprocessing
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence

import pandas as pd

from evflex.pilot import (
    evaluate_pilot_work_unit,
    load_pilot_config,
    validate_pilot_manifest,
)
from evflex.runner import run_work_unit, validate_completed_payload


RESULT_DIRECTORY = "results/pilot_v2_1/work_units"
LOCK_DIRECTORY = "state/runtime/locks/pilot_v2_1"
ATTEMPT_DIRECTORY = "state/runtime/attempts/pilot_v2_1"
MAX_ATTEMPTS = 3
MAX_POOL_RESTARTS_WITHOUT_TERMINAL_RESULT = 3


class UnitPaths(NamedTuple):
    result: Path
    lock: Path
    attempt: Path


def _unit_paths(repo_root: str | Path, work_unit_id: str) -> UnitPaths:
    root = Path(repo_root).resolve(strict=False)
    name = str(work_unit_id)
    return UnitPaths(
        result=root / RESULT_DIRECTORY / f"{name}.json",
        lock=root / LOCK_DIRECTORY / f"{name}.lock",
        attempt=root / ATTEMPT_DIRECTORY / f"{name}.json",
    )


def _unit_id(work_unit: Mapping[str, Any]) -> str:
    value = str(work_unit.get("work_unit_id", ""))
    if not value:
        raise ValueError("work unit has no stable ID")
    return value


def _seed(work_unit: Mapping[str, Any]) -> int:
    try:
        value = int(work_unit["scenario_seed"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("work unit has no valid frozen seed") from exc
    return value


def _read_json_mapping(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must contain a JSON object: {path}")
    return payload


def _validate_completed(
    payload: Mapping[str, Any], work_unit: Mapping[str, Any]
) -> None:
    validate_completed_payload(payload, work_unit)
    for field in ("protocol_version", "data_role"):
        if str(payload.get(field)) != str(work_unit.get(field)):
            raise ValueError(f"Completed result {field} mismatch")


def _validate_attempt(
    payload: Mapping[str, Any], work_unit: Mapping[str, Any]
) -> None:
    if str(payload.get("work_unit_id")) != _unit_id(work_unit):
        raise ValueError("Attempt state work-unit ID mismatch")
    try:
        observed_seed = int(payload.get("scenario_seed"))
        attempt_count = int(payload.get("attempt_count"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Attempt state has an invalid seed or count") from exc
    if observed_seed != _seed(work_unit):
        raise ValueError("Attempt state seed mismatch")
    if attempt_count < 0 or attempt_count > MAX_ATTEMPTS:
        raise ValueError("Attempt state count is outside the allowed range")
    errors = payload.get("errors")
    if not isinstance(errors, list):
        raise ValueError("Attempt state errors must be a list")


def _read_lock_pid(path: Path) -> int:
    try:
        raw = path.read_bytes()
        text = raw.decode("ascii")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"malformed runtime lock: {path}") from exc
    if not text or not text.isascii() or not text.isdecimal():
        raise RuntimeError(f"malformed runtime lock: {path}")
    pid = int(text)
    if pid <= 0:
        raise RuntimeError(f"malformed runtime lock: {path}")
    return pid


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno == errno.EPERM
        return True

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        process_query_limited_information, False, int(pid)
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == 5:
            return True
        if error == 87:
            return False
        return True
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _reclaim_dead_lock(path: Path) -> None:
    pid = _read_lock_pid(path)
    if _pid_is_alive(pid):
        raise RuntimeError(f"active lock belongs to PID {pid}: {path}")
    path.unlink()


def _prepare_unit_artifacts(
    work_unit: Mapping[str, Any],
    paths: UnitPaths,
    *,
    resume: bool,
) -> dict[str, Any] | None:
    existing = [path for path in paths if path.exists()]
    if not resume:
        if existing:
            joined = ", ".join(str(path) for path in existing)
            raise FileExistsError(
                f"Owned runtime artifacts already exist; use --resume: {joined}"
            )
        return None

    completed: dict[str, Any] | None = None
    if paths.result.exists():
        try:
            completed = _read_json_mapping(paths.result, "Existing result")
            _validate_completed(completed, work_unit)
        except ValueError as exc:
            if "unreadable" in str(exc):
                raise
            raise ValueError(
                f"Existing result is invalid and will not be overwritten: "
                f"{paths.result}: {exc}"
            ) from exc

    attempt: dict[str, Any] | None = None
    if paths.attempt.exists():
        attempt = _read_json_mapping(paths.attempt, "Attempt state")
        _validate_attempt(attempt, work_unit)

    if paths.lock.exists():
        _reclaim_dead_lock(paths.lock)

    if completed is not None:
        if attempt is not None:
            paths.attempt.unlink()
        return {**completed, "runner_status": "SKIPPED_COMPLETED"}
    return None


def _prepare_repository(
    repo_root: str | Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    root = Path(repo_root).resolve(strict=False)
    config = load_pilot_config(root)
    manifest_path = root / str(config["pilot_manifest"])
    frame = pd.read_csv(manifest_path)
    validate_pilot_manifest(frame, config)
    return config, frame


def _new_executor() -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
        max_tasks_per_child=1,
    )


def _run_pilot_unit(
    repo_root: str,
    work_unit: Mapping[str, Any],
    resume: bool,
) -> dict[str, Any]:
    unit = dict(work_unit)
    paths = _unit_paths(repo_root, _unit_id(unit))

    def compute(current: Mapping[str, Any], attempt_count: int) -> dict[str, Any]:
        del attempt_count
        evaluations = evaluate_pilot_work_unit(Path(repo_root), current)
        return {
            "resource_policy": {
                "workers": 1,
                "numeric_threads": 1,
                "environment": dict(THREAD_ENVIRONMENT),
            },
            "evaluations": evaluations,
        }

    return run_work_unit(
        unit,
        paths.result,
        paths.lock,
        compute,
        resume=resume,
        max_attempts=MAX_ATTEMPTS,
        attempt_state_path=paths.attempt,
    )


def _manifest_units(frame: pd.DataFrame) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        unit = {
            key: (None if pd.isna(value) else value)
            for key, value in raw.items()
        }
        unit["scenario_seed"] = int(unit["scenario_seed"])
        units.append(unit)
    return units


def _execute_one(
    repo_root: Path,
    work_unit: Mapping[str, Any],
    *,
    resume: bool,
) -> dict[str, Any]:
    paths = _unit_paths(repo_root, _unit_id(work_unit))
    prepared = _prepare_unit_artifacts(work_unit, paths, resume=resume)
    if prepared is not None:
        return prepared

    restarts = 0
    while True:
        try:
            with _new_executor() as executor:
                future = executor.submit(
                    _run_pilot_unit,
                    str(repo_root),
                    dict(work_unit),
                    resume,
                )
                return future.result()
        except BrokenProcessPool:
            restarts += 1
            if restarts > MAX_POOL_RESTARTS_WITHOUT_TERMINAL_RESULT:
                raise RuntimeError(
                    f"worker pool repeatedly failed for {_unit_id(work_unit)}"
                )
            prepared = _prepare_unit_artifacts(
                work_unit, paths, resume=True
            )
            if prepared is not None:
                return prepared
            resume = True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen 16-unit V2.1 development pilot."
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: str | Path | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.workers != 1:
        raise SystemExit("--workers must be exactly 1")

    root = (
        Path(repo_root).resolve(strict=False)
        if repo_root is not None
        else Path(__file__).resolve().parents[1]
    )
    _, frame = _prepare_repository(root)
    units = _manifest_units(frame)

    outcomes: list[dict[str, Any]] = []
    execution_errors: list[dict[str, str]] = []
    for index, unit in enumerate(units, start=1):
        unit_id = _unit_id(unit)
        print(f"[{index:02d}/{len(units):02d}] {unit_id}", flush=True)
        try:
            outcome = _execute_one(root, unit, resume=bool(args.resume))
            outcomes.append(outcome)
            print(
                f"  {outcome.get('status')} "
                f"({outcome.get('runner_status')})",
                flush=True,
            )
        except Exception as exc:
            execution_errors.append(
                {
                    "work_unit_id": unit_id,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            print(
                f"  RUNNER_ERROR {type(exc).__name__}: {exc}",
                flush=True,
            )

    status_counts: dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome.get("status", "UNKNOWN"))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "work_units_expected": len(units),
        "work_units_terminal": len(outcomes),
        "status_counts": status_counts,
        "runner_errors": execution_errors,
        "resource_policy": {
            "workers": 1,
            "numeric_threads": 1,
            "environment": dict(THREAD_ENVIRONMENT),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    unhandled = status_counts.get("UNHANDLED_FAILURE", 0)
    return 0 if not execution_errors and unhandled == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
