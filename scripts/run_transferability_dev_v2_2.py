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
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

import pandas as pd

from evflex.pilot import evaluate_pilot_work_unit
from evflex.runner import (
    atomic_write_json,
    run_work_unit,
    validate_completed_payload,
)
from evflex.transferability_dev_v2_2 import (
    load_development_design,
    owned_paths,
)


STATUS_PATH = Path("results/transferability_dev_v2_2/run_status.json")
MAX_ATTEMPTS = 3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_commit(repo_root: str | Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(Path(repo_root)), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    commit = completed.stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("current Git commit is not a full lowercase SHA-1")
    return commit


def _compute_payload(
    repo_root: Path,
    work_unit: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    evaluations = evaluate_pilot_work_unit(
        repo_root,
        work_unit,
        config=config,
    )
    return {
        "resource_policy": {
            "workers": 1,
            "numeric_threads": 1,
            "environment": dict(THREAD_ENVIRONMENT),
        },
        "run_provenance": {
            "code_commit": _git_commit(repo_root),
            "config_sha256": str(config["_config_sha256"]),
            "source_manifest_sha256": str(config["source_manifest_sha256"]),
            "holdout_access": "prohibited",
            "output_namespace": "results/transferability_dev_v2_2",
        },
        "evaluations": evaluations,
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        unit = {
            key: (None if pd.isna(value) else value)
            for key, value in raw.items()
        }
        unit["scenario_seed"] = int(unit["scenario_seed"])
        records.append(unit)
    return records


def _run_child(
    root: Path,
    unit: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    resume: bool,
) -> dict[str, Any]:
    paths = owned_paths(root, str(unit["work_unit_id"]))

    def compute(current: Mapping[str, Any], attempt_count: int) -> dict[str, Any]:
        del attempt_count
        return _compute_payload(root, current, config)

    outcome = run_work_unit(
        unit,
        paths.result,
        paths.lock,
        compute,
        resume=resume,
        max_attempts=MAX_ATTEMPTS,
        attempt_state_path=paths.attempt,
    )
    validate_completed_payload(outcome, unit)
    return outcome


def _read_completed(path: Path, unit: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"completed result is not a JSON object: {path}")
    validate_completed_payload(payload, unit)
    return payload


def _write_status(
    root: Path,
    *,
    started_at_utc: str,
    selected: int,
    total: int,
    completed: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    resume: bool,
) -> None:
    counts: dict[str, int] = {}
    for item in completed:
        status = str(item.get("status", "UNKNOWN"))
        counts[status] = counts.get(status, 0) + 1
    atomic_write_json(
        root / STATUS_PATH,
        {
            "protocol_version": "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-DEV",
            "started_at_utc": started_at_utc,
            "updated_at_utc": _utc_now(),
            "work_units_total": total,
            "work_units_selected": selected,
            "work_units_terminal": len(completed),
            "status_counts": counts,
            "runner_errors": errors,
            "resume": bool(resume),
            "resource_policy": {
                "workers": 1,
                "numeric_threads": 1,
                "environment": dict(THREAD_ENVIRONMENT),
            },
            "formal_holdout_opened": False,
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen 32-unit V2.2 fixed-schedule transferability "
            "development experiment."
        )
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-units", type=int)
    parser.add_argument("--unit-id")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: str | Path | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.workers != 1:
        raise SystemExit("--workers must be exactly 1")
    if args.max_units is not None and args.max_units < 1:
        raise SystemExit("--max-units must be positive")

    root = (
        Path(repo_root).resolve(strict=False)
        if repo_root is not None
        else Path(__file__).resolve().parents[1]
    )
    config, frame = load_development_design(root)
    units = _records(frame)

    if args.unit_id is not None:
        matches = [
            unit for unit in units if str(unit["work_unit_id"]) == args.unit_id
        ]
        if len(matches) != 1:
            raise SystemExit(f"unknown V2.2 development unit: {args.unit_id}")
        outcome = _run_child(
            root,
            matches[0],
            config,
            resume=bool(args.resume),
        )
        print(
            json.dumps(
                {
                    "work_unit_id": args.unit_id,
                    "status": outcome.get("status"),
                    "runner_status": outcome.get("runner_status"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return 1 if outcome.get("status") == "UNHANDLED_FAILURE" else 0

    selected_units = units[: args.max_units] if args.max_units else units
    started = _utc_now()
    completed_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, unit in enumerate(selected_units, start=1):
        unit_id = str(unit["work_unit_id"])
        print(f"[{index:02d}/{len(selected_units):02d}] {unit_id}", flush=True)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--workers",
            "1",
            "--unit-id",
            unit_id,
        ]
        if args.resume:
            command.append("--resume")
        child = subprocess.run(
            command,
            cwd=root,
            env={**os.environ, **THREAD_ENVIRONMENT},
            check=False,
        )
        paths = owned_paths(root, unit_id)
        try:
            if child.returncode != 0:
                raise RuntimeError(f"child exit code {child.returncode}")
            result = _read_completed(paths.result, unit)
            completed_results.append(result)
            print(f"  {result.get('status')}", flush=True)
        except Exception as exc:
            errors.append(
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
            _write_status(
                root,
                started_at_utc=started,
                selected=len(selected_units),
                total=len(units),
                completed=completed_results,
                errors=errors,
                resume=bool(args.resume),
            )
            return 1
        _write_status(
            root,
            started_at_utc=started,
            selected=len(selected_units),
            total=len(units),
            completed=completed_results,
            errors=errors,
            resume=bool(args.resume),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
