from __future__ import annotations

import argparse
from concurrent.futures import as_completed
import json
from pathlib import Path
from typing import Any

import pandas as pd

from evflex.engine import compare_all_durations
from evflex.runner import isolated_process_pool, run_work_unit


def _run_core_unit(
    repo_text: str, work_unit: dict[str, Any], role: str, resume: bool
) -> dict[str, Any]:
    repo = Path(repo_text)
    unit_id = str(work_unit["work_unit_id"])
    result_path = repo / "results" / "work_units" / role / f"{unit_id}.json"
    lock_path = repo / "state" / "runtime" / "locks" / role / f"{unit_id}.lock"

    def compute(unit, _attempt):
        return compare_all_durations(repo, unit)

    return run_work_unit(
        work_unit,
        result_path,
        lock_path,
        compute,
        resume=resume,
        max_attempts=3,
    )


def _verify_prerequisites(repo: Path, role: str) -> None:
    gate_path = repo / "reports" / "engine_regression_gate_v2_0.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("gate_status") != "PASS":
        raise RuntimeError("G1 engine regression has not passed")
    if role == "holdout":
        unlock_path = repo / "state" / "holdout_unlock_v2_0.json"
        if not unlock_path.is_file():
            raise RuntimeError("Holdout is sealed: verified unlock record is absent")
        unlock = json.loads(unlock_path.read_text(encoding="utf-8"))
        if unlock.get("status") != "UNLOCKED" or unlock.get("protocol_version") != "EV-FLEX-BIAS-V2.0":
            raise RuntimeError("Holdout unlock record is invalid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--role", choices=("development", "development_ablation", "holdout"), required=True
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-work-units", type=int)
    args = parser.parse_args()
    if not 1 <= args.workers <= 2:
        raise SystemExit("--workers must be 1 or 2 under the frozen resource policy")
    if args.max_work_units is not None and args.max_work_units < 1:
        raise SystemExit("--max-work-units must be positive")

    repo = Path(__file__).resolve().parents[1]
    _verify_prerequisites(repo, args.role)
    manifest_path = args.manifest if args.manifest.is_absolute() else repo / args.manifest
    frame = pd.read_csv(manifest_path)
    selected = frame.loc[frame["data_role"] == args.role].copy()
    if args.max_work_units is not None:
        selected = selected.head(args.max_work_units)
    if selected.empty:
        raise SystemExit(f"No work units for role {args.role}")
    if args.role == "development_ablation":
        raise SystemExit("The ablation numerical adapter is frozen in Task 10; no runs were started")

    units = selected.to_dict("records")
    print(
        f"role={args.role} work_units={len(units)} workers={args.workers} "
        "numeric_threads=1",
        flush=True,
    )
    outcomes = []
    with isolated_process_pool(args.workers) as executor:
        futures = {
            executor.submit(_run_core_unit, str(repo), unit, args.role, args.resume): unit
            for unit in units
        }
        completed = 0
        for future in as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            completed += 1
            print(
                f"[{completed}/{len(units)}] {outcome['work_unit_id']} "
                f"{outcome['runner_status']}",
                flush=True,
            )

    summary = {
        "role": args.role,
        "work_units": len(outcomes),
        "success": sum(outcome["status"] == "SUCCESS" for outcome in outcomes),
        "scientific_terminal": sum(
            outcome["status"] == "SCIENTIFIC_TERMINAL" for outcome in outcomes
        ),
        "unhandled_failure": sum(
            outcome["status"] == "UNHANDLED_FAILURE" for outcome in outcomes
        ),
        "skipped_completed": sum(
            outcome["runner_status"] == "SKIPPED_COMPLETED" for outcome in outcomes
        ),
        "workers": args.workers,
        "numeric_threads": 1,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["unhandled_failure"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
