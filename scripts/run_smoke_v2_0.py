from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from evflex.engine import compare_all_durations, validate_result_bundle
from evflex.network import write_json_atomic


PREFERRED_SMOKE_UNITS = (
    ("ieee13_1900_17", "inc"),
    ("lv906_1900_18", "dec"),
    ("ieee13_1900_17", "dec"),
    ("lv906_1900_18", "inc"),
)


def select_work_units(frame: pd.DataFrame, count: int) -> pd.DataFrame:
    development = frame.loc[frame["data_role"] == "development"].copy()
    selected_indices: list[int] = []
    for scenario_id, direction in PREFERRED_SMOKE_UNITS:
        match = development.loc[
            (development["scenario_id"] == scenario_id)
            & (development["direction"] == direction)
        ]
        if not match.empty:
            selected_indices.append(int(match.index[0]))
        if len(selected_indices) == count:
            break
    if len(selected_indices) < count:
        for index in development.index:
            if int(index) not in selected_indices:
                selected_indices.append(int(index))
            if len(selected_indices) == count:
                break
    if len(selected_indices) != count:
        raise ValueError(f"Requested {count} smoke work units, found {len(selected_indices)}")
    return development.loc[selected_indices].reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.scenarios < 2:
        raise SystemExit("Smoke validation requires at least two work units")
    if args.workers != 1:
        raise SystemExit("Smoke validation is intentionally sequential: use --workers 1")

    repo = Path(__file__).resolve().parents[1]
    work_units = pd.read_csv(repo / "manifests" / "core_work_units_v2_0.csv")
    selected = select_work_units(work_units, args.scenarios)
    all_rows = []
    timings = []
    for ordinal, work_unit in enumerate(selected.to_dict("records"), start=1):
        started = time.perf_counter()
        print(
            f"[{ordinal}/{len(selected)}] {work_unit['work_unit_id']} "
            f"(workers=1, numeric_threads=1)",
            flush=True,
        )
        rows = compare_all_durations(repo, work_unit)
        validate_result_bundle(rows, work_unit)
        elapsed = time.perf_counter() - started
        timings.append(
            {"work_unit_id": work_unit["work_unit_id"], "runtime_s": elapsed}
        )
        all_rows.extend(rows)
        print(f"completed in {elapsed:.2f}s", flush=True)

    feeders = sorted({row["feeder"] for row in all_rows})
    directions = sorted({row["direction"] for row in all_rows})
    gate = bool(feeders == ["ieee13", "lv906"] and directions == ["dec", "inc"])
    report = {
        "gate": "PASS" if gate else "FAIL",
        "protocol_version": "EV-FLEX-BIAS-V2.0",
        "resource_policy": {
            "numeric_threads": 1,
            "workers": 1,
            "execution": "sequential",
        },
        "work_units": len(selected),
        "evaluations": len(all_rows),
        "feeders": feeders,
        "directions": directions,
        "durations_min": sorted({row["duration_min"] for row in all_rows}),
        "physical_failures": sum(not row["physical_feasible"] for row in all_rows),
        "reserve_violation_max_kwh": max(
            row["max_reserve_violation_kwh"] for row in all_rows
        ),
        "simultaneous_slots_total": sum(row["simultaneous_slots"] for row in all_rows),
        "timings": timings,
        "results": all_rows,
    }
    output = args.output if args.output.is_absolute() else repo / args.output
    write_json_atomic(output, report)
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    if not gate:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
