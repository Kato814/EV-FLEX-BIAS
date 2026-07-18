from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

import pandas as pd

from evflex.provenance import sha256_file


SCIENTIFIC_TERMINAL_STATUSES = {
    "THREE_PHASE_BASELINE_INFEASIBLE",
    "BALANCED_BASELINE_INFEASIBLE",
    "NETWORK_BASE_INFEASIBLE",
    "TRAJECTORY_INFEASIBLE",
    "POINT_OPTIMIZATION_INFEASIBLE",
}
KNOWN_STATUSES = {"SUCCESS", "UNHANDLED_FAILURE", *SCIENTIFIC_TERMINAL_STATUSES}
PHYSICAL_TOLERANCE_KWH = 1e-6


def load_work_unit_evaluations(input_directory: Path) -> tuple[list[dict[str, Any]], list[str]]:
    root = input_directory.resolve(strict=True)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        evaluations = payload.get("evaluations")
        if not isinstance(evaluations, list):
            errors.append(f"{path.name}: missing evaluations list")
            continue
        for evaluation in evaluations:
            row = dict(evaluation)
            row.setdefault("work_unit_id", payload.get("work_unit_id"))
            row["work_unit_status"] = payload.get("status")
            row["attempt_count"] = payload.get("attempt_count")
            row["source_result_file"] = path.name
            rows.append(row)
    return rows, errors


def assess_evaluations(
    evaluations: Iterable[Mapping[str, Any]],
    expected_evaluations: int,
    *,
    input_errors: Iterable[str] = (),
) -> dict[str, Any]:
    rows = [dict(row) for row in evaluations]
    input_error_list = list(input_errors)
    ids = [str(row.get("evaluation_id")) for row in rows]
    duplicates = sorted({evaluation_id for evaluation_id in ids if ids.count(evaluation_id) > 1})

    incomplete = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("work_unit_id")), []).append(row)
    for work_unit_id, group in grouped.items():
        durations = {int(row["duration_min"]) for row in group if row.get("duration_min") is not None}
        if len(group) == 3 and durations != {15, 30, 60}:
            incomplete.append({"work_unit_id": work_unit_id, "durations": sorted(durations)})
        elif len(group) not in {1, 3}:
            incomplete.append({"work_unit_id": work_unit_id, "durations": sorted(durations)})

    statuses = [str(row.get("status")) for row in rows]
    unknown_statuses = sorted(set(statuses) - KNOWN_STATUSES)
    unhandled_ids = [
        str(row.get("evaluation_id"))
        for row in rows
        if row.get("status") == "UNHANDLED_FAILURE"
    ]
    scientific_ids = [
        str(row.get("evaluation_id"))
        for row in rows
        if row.get("status") in SCIENTIFIC_TERMINAL_STATUSES
    ]

    simultaneous_ids = []
    negative_soc_ids = []
    physical_ids = []
    for row in rows:
        if row.get("status") != "SUCCESS":
            continue
        evaluation_id = str(row.get("evaluation_id"))
        simultaneous = int(row.get("simultaneous_slots", 0))
        reserve_violation = float(row.get("max_reserve_violation_kwh", 0.0))
        soc_margin = float(row.get("min_soc_margin_kwh", -reserve_violation))
        departure_error = float(row.get("max_departure_error_kwh", 0.0))
        capacity_violation = float(row.get("max_capacity_violation_kwh", 0.0))
        if simultaneous != 0:
            simultaneous_ids.append(evaluation_id)
        if soc_margin < -1e-9:
            negative_soc_ids.append(evaluation_id)
        physical_feasible = row.get("physical_feasible", True)
        if (
            physical_feasible is not True
            or departure_error > PHYSICAL_TOLERANCE_KWH
            or reserve_violation > PHYSICAL_TOLERANCE_KWH
            or capacity_violation > PHYSICAL_TOLERANCE_KWH
        ):
            physical_ids.append(evaluation_id)

    cell_counts: dict[str, int] = {}
    for row in rows:
        if row.get("status") != "SUCCESS":
            continue
        if not all(key in row for key in ("feeder", "direction", "duration_min")):
            continue
        key = f"{row['feeder']}|{row['direction']}|{int(row['duration_min'])}"
        cell_counts[key] = cell_counts.get(key, 0) + 1
    cell_min_required = 80 if expected_evaluations >= 1152 else 0
    underfilled_cells = {
        key: count for key, count in cell_counts.items() if count < cell_min_required
    }
    if cell_min_required:
        expected_cells = {
            f"{feeder}|{direction}|{duration}"
            for feeder in ("ieee13", "lv906")
            for direction in ("inc", "dec")
            for duration in (15, 30, 60)
        }
        for missing_cell in sorted(expected_cells - set(cell_counts)):
            underfilled_cells[missing_cell] = 0

    violations = {
        "input_errors": input_error_list,
        "count_mismatch": len(rows) != expected_evaluations,
        "duplicate_evaluation_ids": duplicates,
        "incomplete_duration_bundles": incomplete,
        "unknown_statuses": unknown_statuses,
        "unhandled_failure_ids": unhandled_ids,
        "simultaneous_charge_discharge_ids": simultaneous_ids,
        "negative_soc_margin_ids": negative_soc_ids,
        "physical_invariant_ids": physical_ids,
        "underfilled_cells": underfilled_cells,
    }
    failed = bool(
        input_error_list
        or len(rows) != expected_evaluations
        or duplicates
        or incomplete
        or unknown_statuses
        or unhandled_ids
        or simultaneous_ids
        or negative_soc_ids
        or physical_ids
        or underfilled_cells
    )
    status_counts = {status: statuses.count(status) for status in sorted(set(statuses))}
    return {
        "gate": "G2_DEVELOPMENT" if expected_evaluations >= 1152 else "DEVELOPMENT_SMOKE",
        "gate_status": "FAIL" if failed else "PASS",
        "expected_evaluations": expected_evaluations,
        "actual_evaluations": len(rows),
        "unique_evaluation_ids": len(set(ids)),
        "work_units": len(grouped),
        "status_counts": status_counts,
        "scientific_terminal_count": len(scientific_ids),
        "scientific_terminal_ids": scientific_ids,
        "unhandled_failure_count": len(unhandled_ids),
        "paired_eligible_cell_counts": cell_counts,
        "paired_eligible_cell_min_required": cell_min_required,
        "violations": violations,
    }


def sort_and_normalize_rows(
    rows: list[dict[str, Any]], evaluation_order: Mapping[str, int]
) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            evaluation_order.get(str(row.get("evaluation_id")), 10**12),
            str(row.get("evaluation_id")),
        ),
    )
    normalized = []
    for row in ordered:
        normalized.append(
            {
                key: (
                    json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    if isinstance(value, (dict, list))
                    else value
                )
                for key, value in row.items()
            }
        )
    return normalized


def write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> str:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        pd.DataFrame(rows).to_csv(temporary, index=False, encoding="utf-8", lineterminator="\n")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(target)


def render_gate_markdown(report: Mapping[str, Any]) -> str:
    return f"""# EV-FLEX-BIAS-V2.0 development gate

**Gate status: {report['gate_status']}**

- Evaluations: {report['actual_evaluations']} / {report['expected_evaluations']}
- Unique evaluation IDs: {report['unique_evaluation_ids']}
- Work units: {report['work_units']}
- Scientific terminal evaluations: {report['scientific_terminal_count']}
- Unhandled failures: {report['unhandled_failure_count']}
- Minimum eligible observations required per feeder-direction-duration cell: {report['paired_eligible_cell_min_required']}
- Aggregated CSV SHA-256: {report.get('output_sha256') or 'not written'}
"""
