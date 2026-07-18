from __future__ import annotations

import gc
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from evflex.engine import compare_all_durations
from evflex.provenance import sha256_file


CAPACITY_FIELDS = ("f_bal_kw", "f_3ph_kw")
BOOLEAN_FIELDS = (
    "raw_balanced_schedule_feasible",
    "balanced_network_feasible",
    "three_phase_network_feasible",
    "mapped_network_feasible",
)
CANONICAL_FIELDS = (
    "scenario_id",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    *CAPACITY_FIELDS,
    "alpha_map",
    *BOOLEAN_FIELDS,
    "max_departure_error_kwh",
    "max_reserve_violation_kwh",
    "max_capacity_violation_kwh",
    "simultaneous_slots",
    "status",
)


def close_capacity(expected: float, actual: float) -> bool:
    absolute = abs(expected - actual)
    relative = absolute / max(abs(expected), 1e-12)
    return absolute <= 1e-5 or relative <= 1e-8


def close_scalar(expected: float, actual: float, tolerance: float) -> bool:
    return abs(expected - actual) <= tolerance


def run_regression_gate(
    repo_root: Path,
    golden_path: Path,
    repeats: int,
    workers: int,
) -> dict[str, Any]:
    if repeats < 2:
        raise ValueError("G1 requires at least two sequential repeats")
    if workers != 1:
        raise ValueError("G1 is frozen to one numerical worker by the resource policy")

    repo = repo_root.resolve(strict=True)
    golden_file = golden_path.resolve(strict=True)
    golden = pd.read_csv(golden_file)
    if len(golden) != 24:
        raise ValueError(f"Expected 24 D5 golden rows, found {len(golden)}")
    key_fields = ["scenario_id", "direction", "duration_min"]
    if golden.duplicated(key_fields).any():
        raise ValueError("Duplicate keys in D5 golden rows")

    manifests = pd.read_csv(repo / "manifests" / "core_work_units_v2_0.csv")
    work_units = []
    for scenario_id, direction in (
        golden[["scenario_id", "direction"]].drop_duplicates().itertuples(index=False)
    ):
        match = manifests.loc[
            (manifests["scenario_id"] == scenario_id)
            & (manifests["direction"] == direction)
            & (manifests["data_role"] == "development")
        ]
        if len(match) != 1:
            raise ValueError(
                f"Expected one development work unit for {scenario_id}/{direction}, found {len(match)}"
            )
        work_units.append(match.iloc[0].to_dict())

    repeated_rows: list[list[dict[str, Any]]] = []
    for repeat in range(1, repeats + 1):
        rows: list[dict[str, Any]] = []
        for ordinal, work_unit in enumerate(work_units, start=1):
            print(
                f"repeat {repeat}/{repeats} work {ordinal}/{len(work_units)} "
                f"{work_unit['work_unit_id']} (workers=1, numeric_threads=1)",
                flush=True,
            )
            rows.extend(
                compare_all_durations(
                    repo,
                    work_unit,
                    network_voltage_max_pu=1.05,
                )
            )
            gc.collect()
        repeated_rows.append(sorted(rows, key=_row_key))

    comparisons, mismatch_counts = _compare_golden(golden, repeated_rows[0])
    repeat_summary = _compare_repeats(repeated_rows)
    physical = _physical_summary(repeated_rows[0])
    hashes = [_canonical_hash(rows) for rows in repeated_rows]
    pass_gate = bool(
        len(repeated_rows[0]) == 24
        and all(count == 0 for count in mismatch_counts.values())
        and repeat_summary["pass"]
        and physical["pass"]
    )
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.0",
        "gate": "G1_ENGINE_REGRESSION",
        "gate_status": "PASS" if pass_gate else "FAIL",
        "resource_policy": {
            "numeric_threads": 1,
            "workers": 1,
            "execution": "sequential",
            "two_worker_check": "NOT_RUN_STRICTER_REGRESSION_WORKER_LIMIT",
        },
        "golden": {
            "path": str(golden_file.relative_to(repo)).replace("\\", "/"),
            "sha256": sha256_file(golden_file),
            "expected_rows": 24,
        },
        "repeats": repeats,
        "rows_per_repeat": [len(rows) for rows in repeated_rows],
        "status_matches": 24 - mismatch_counts["status"],
        "mismatch_counts": mismatch_counts,
        "physical": physical,
        "repeatability": repeat_summary,
        "canonical_result_sha256": hashes,
        "tolerances": {
            "capacity_absolute_kw": 1e-5,
            "capacity_relative": 1e-8,
            "alpha_map_absolute": 1e-8,
            "departure_error_max_kwh": 1e-8,
            "reserve_violation_max_kwh": 1e-9,
            "simultaneous_slots": 0,
        },
        "comparisons": comparisons,
    }


def render_regression_markdown(report: dict[str, Any]) -> str:
    physical = report["physical"]
    repeatability = report["repeatability"]
    mismatches = report["mismatch_counts"]
    return f"""# EV-FLEX-BIAS-V2.0 G1 engine regression

**Gate status: {report['gate_status']}**

- Golden comparisons: {report['status_matches']}/24 status matches
- Repeats: {report['repeats']} sequential runs with one numerical worker
- Capacity mismatches: {mismatches['capacity']}
- `alpha_map` mismatches: {mismatches['alpha_map']}
- Boolean/status mismatches: {mismatches['boolean'] + mismatches['status']}
- Maximum departure-energy error: {physical['max_departure_error_kwh']:.3e} kWh
- Maximum reserve violation: {physical['max_reserve_violation_kwh']:.3e} kWh
- Simultaneous charge/discharge intervals: {physical['simultaneous_slots_total']}
- Repeatability maximum capacity difference: {repeatability['max_capacity_abs_difference_kw']:.3e} kW
- Repeatability maximum `alpha_map` difference: {repeatability['max_alpha_map_abs_difference']:.3e}

The optional two-worker comparison was not run because the frozen low-resource policy limits G1 regression to one numerical worker. Sequential process/context reconstruction is covered by the repeated runs.
"""


def write_text_atomic(path: Path, text: str) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _compare_golden(
    golden: pd.DataFrame, actual_rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    actual = {_row_key(row): row for row in actual_rows}
    comparisons = []
    counts = {"missing": 0, "capacity": 0, "alpha_map": 0, "boolean": 0, "status": 0}
    for expected in golden.to_dict("records"):
        key = _row_key(expected)
        row = actual.get(key)
        if row is None:
            counts["missing"] += 1
            comparisons.append({"key": list(key), "pass": False, "reason": "missing"})
            continue
        capacity_ok = all(
            close_capacity(float(expected[field]), float(row[field]))
            for field in CAPACITY_FIELDS
        )
        alpha_ok = close_scalar(
            float(expected["alpha_map"]), float(row["alpha_map"]), 1e-8
        )
        boolean_ok = all(
            bool(expected[field]) == bool(row[field]) for field in BOOLEAN_FIELDS
        ) and int(expected["simultaneous_slots"]) == int(row["simultaneous_slots"])
        expected_success = bool(
            expected["balanced_network_feasible"]
            and expected["three_phase_network_feasible"]
            and expected["mapped_network_feasible"]
            and float(expected["max_departure_error_kwh"]) <= 1e-8
            and float(expected["max_reserve_violation_kwh"]) <= 1e-9
            and int(expected["simultaneous_slots"]) == 0
        )
        status_ok = (row["status"] == "SUCCESS") == expected_success
        counts["capacity"] += int(not capacity_ok)
        counts["alpha_map"] += int(not alpha_ok)
        counts["boolean"] += int(not boolean_ok)
        counts["status"] += int(not status_ok)
        comparisons.append(
            {
                "scenario_id": key[0],
                "direction": key[1],
                "duration_min": key[2],
                "capacity_pass": capacity_ok,
                "alpha_map_pass": alpha_ok,
                "boolean_pass": boolean_ok,
                "status_pass": status_ok,
                "pass": capacity_ok and alpha_ok and boolean_ok and status_ok,
            }
        )
    if len(actual) != len(golden):
        counts["missing"] += abs(len(actual) - len(golden))
    return comparisons, counts


def _compare_repeats(repeats: list[list[dict[str, Any]]]) -> dict[str, Any]:
    reference = {_row_key(row): row for row in repeats[0]}
    max_capacity = 0.0
    max_alpha = 0.0
    status_mismatches = 0
    for rows in repeats[1:]:
        current = {_row_key(row): row for row in rows}
        if set(current) != set(reference):
            status_mismatches += len(set(current) ^ set(reference))
            continue
        for key, expected in reference.items():
            actual = current[key]
            max_capacity = max(
                max_capacity,
                *(abs(float(expected[field]) - float(actual[field])) for field in CAPACITY_FIELDS),
            )
            max_alpha = max(
                max_alpha, abs(float(expected["alpha_map"]) - float(actual["alpha_map"]))
            )
            status_mismatches += int(expected["status"] != actual["status"])
    return {
        "pass": bool(max_capacity <= 1e-5 and max_alpha <= 1e-8 and status_mismatches == 0),
        "max_capacity_abs_difference_kw": max_capacity,
        "max_alpha_map_abs_difference": max_alpha,
        "status_mismatches": status_mismatches,
    }


def _physical_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    departure = max(float(row["max_departure_error_kwh"]) for row in rows)
    reserve = max(float(row["max_reserve_violation_kwh"]) for row in rows)
    capacity = max(float(row["max_capacity_violation_kwh"]) for row in rows)
    simultaneous = sum(int(row["simultaneous_slots"]) for row in rows)
    all_networks = all(
        row["balanced_network_feasible"]
        and row["three_phase_network_feasible"]
        and row["mapped_network_feasible"]
        for row in rows
    )
    return {
        "pass": bool(
            departure <= 1e-8
            and reserve <= 1e-9
            and capacity <= 1e-8
            and simultaneous == 0
            and all_networks
        ),
        "max_departure_error_kwh": departure,
        "max_reserve_violation_kwh": reserve,
        "max_capacity_violation_kwh": capacity,
        "simultaneous_slots_total": simultaneous,
        "all_network_checks_feasible": all_networks,
    }


def _canonical_hash(rows: list[dict[str, Any]]) -> str:
    canonical = [
        {field: row[field] for field in CANONICAL_FIELDS}
        for row in sorted(rows, key=_row_key)
    ]
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return str(row["scenario_id"]), str(row["direction"]), int(row["duration_min"])
