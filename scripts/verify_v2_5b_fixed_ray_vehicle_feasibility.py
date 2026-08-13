from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from evflex.engine import select_nested_candidate
from evflex.pilot import (
    _create_real_pilot_runtime,
    _normalize_raw_balanced_result,
    _trajectory_invariants,
    _validated_schedule,
    canonical_schedule_sha256,
)
from evflex.transferability_replication_v2_5b import load_replication_design

T = 96
TOL = 1e-6
PRIMARY_DURATION_MIN = 15
EXPECTED_PRIMARY_PLANNED_N = 96
EXPECTED_PRIMARY_ACTIVE_ELIGIBLE_N = 89


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        row = {key: (None if pd.isna(value) else value) for key, value in raw.items()}
        row["scenario_seed"] = int(row["scenario_seed"])
        row["prior_holdout_open_acknowledged"] = bool(
            row["prior_holdout_open_acknowledged"]
        )
        records.append(row)
    return records


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _active_primary_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    evaluations = summary.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != 288:
        raise ValueError("completed R2 summary must contain exactly 288 evaluations")

    primary = [
        dict(row)
        for row in evaluations
        if int(row.get("requested_duration_min", -1)) == PRIMARY_DURATION_MIN
    ]
    if len(primary) != EXPECTED_PRIMARY_PLANNED_N:
        raise ValueError(
            f"completed R2 summary must contain {EXPECTED_PRIMARY_PLANNED_N} primary rows"
        )

    active = [
        row
        for row in primary
        if row.get("status") == "SUCCESS"
        and row.get("scientific_status") == "VALID"
        and row.get("active_offer") is True
        and row.get("eligible_for_scientific_denominator") is True
        and isinstance(row.get("alpha_transfer"), (int, float))
        and not isinstance(row.get("alpha_transfer"), bool)
    ]
    if len(active) != EXPECTED_PRIMARY_ACTIVE_ELIGIBLE_N:
        raise ValueError(
            "completed R2 summary must contain exactly "
            f"{EXPECTED_PRIMARY_ACTIVE_ELIGIBLE_N} active eligible 15-min rows; "
            f"observed {len(active)}"
        )
    return sorted(active, key=lambda row: str(row["evaluation_id"]))


def _reconstruct_selected_schedule(
    runtime: Any,
    config: Mapping[str, Any],
    unit: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, Mapping[str, Any]]:
    baseline = _validated_schedule(
        runtime.baseline,
        len(runtime.fleet),
        "runtime baseline",
    )
    raw_by_duration: dict[int, dict[str, Any]] = {}
    for duration in config["durations_min"]:
        raw = runtime.generate_balanced_raw(int(duration), "balanced")
        raw_by_duration[int(duration)] = _normalize_raw_balanced_result(
            raw,
            int(duration),
            runtime.fleet,
            baseline,
            direction=str(unit["direction"]),
        )
    selected = select_nested_candidate(raw_by_duration, PRIMARY_DURATION_MIN)
    schedule = _validated_schedule(
        selected["schedule"],
        len(runtime.fleet),
        "selected balanced schedule",
    )
    return baseline, schedule, selected


def _mode(direction: str) -> str:
    if direction == "inc":
        return "v1g"
    if direction == "dec":
        return "v2g"
    raise ValueError(f"unsupported direction {direction!r}")


def _sign_decomposed_invariants(
    fleet: Sequence[Any],
    schedule: np.ndarray,
    direction: str,
) -> dict[str, Any]:
    charge = np.maximum(schedule, 0.0)
    discharge = np.maximum(-schedule, 0.0)
    return _trajectory_invariants(
        fleet,
        schedule,
        charge,
        discharge,
        _mode(direction),
    )


def _convex_witness_invariants(
    fleet: Sequence[Any],
    baseline: np.ndarray,
    balanced_schedule: np.ndarray,
    alpha: float,
    direction: str,
) -> dict[str, Any]:
    balanced_charge = np.maximum(balanced_schedule, 0.0)
    balanced_discharge = np.maximum(-balanced_schedule, 0.0)
    charge = baseline + float(alpha) * (balanced_charge - baseline)
    discharge = float(alpha) * balanced_discharge
    schedule = charge - discharge
    expected = baseline + float(alpha) * (balanced_schedule - baseline)
    identity_error = float(np.max(np.abs(schedule - expected), initial=0.0))
    if identity_error > 1e-9:
        raise AssertionError("convex charge/discharge witness does not reproduce the fixed ray")
    result = _trajectory_invariants(
        fleet,
        schedule,
        charge,
        discharge,
        _mode(direction),
    )
    result = dict(result)
    result["ray_identity_error_kw"] = identity_error
    return result


def _vehicle_feasible(invariants: Mapping[str, Any]) -> bool:
    return bool(
        float(invariants["max_ev_invariant_error"]) <= TOL
        and int(invariants["simultaneous_slots"]) == 0
    )


def _prefix_alpha_samples(row: Mapping[str, Any]) -> list[float]:
    audit = row.get("alpha_path_audit")
    if not isinstance(audit, Mapping):
        raise ValueError(f"{row['evaluation_id']}: missing alpha_path_audit")
    trace = audit.get("alpha_trace")
    if not isinstance(trace, list) or not trace:
        raise ValueError(f"{row['evaluation_id']}: missing alpha trace")
    alpha_fixed = float(row["alpha_transfer"])
    values = {
        float(item["alpha"])
        for item in trace
        if isinstance(item, Mapping)
        and isinstance(item.get("alpha"), (int, float))
        and not isinstance(item.get("alpha"), bool)
        and float(item["alpha"]) <= alpha_fixed + 1e-12
    }
    values.add(0.0)
    values.add(alpha_fixed)
    return sorted(values)


def _case_result(
    row: Mapping[str, Any],
    *,
    runtime: Any,
    config: Mapping[str, Any],
    unit: Mapping[str, Any],
) -> dict[str, Any]:
    baseline, schedule, selected = _reconstruct_selected_schedule(runtime, config, unit)

    observed_schedule_hash = canonical_schedule_sha256(runtime.fleet, schedule)
    observed_baseline_hash = canonical_schedule_sha256(runtime.fleet, baseline)
    expected_schedule_hash = str(row["schedule_sha256"])
    expected_baseline_hash = str(row["baseline_schedule_sha256"])
    if observed_schedule_hash != expected_schedule_hash:
        raise AssertionError(f"{row['evaluation_id']}: balanced schedule SHA differs from R2")
    if observed_baseline_hash != expected_baseline_hash:
        raise AssertionError(f"{row['evaluation_id']}: baseline schedule SHA differs from R2")
    if int(selected["source_duration_min"]) != int(row["source_duration_min"]):
        raise AssertionError(f"{row['evaluation_id']}: nested source duration differs from R2")
    if abs(float(selected["flex_kw"]) - float(row["f_bal_kw"])) > 1e-6:
        raise AssertionError(f"{row['evaluation_id']}: balanced offer differs from R2")
    if float(selected["max_ev_invariant_error"]) > TOL or int(selected["simultaneous_slots"]) != 0:
        raise AssertionError(f"{row['evaluation_id']}: reconstructed balanced endpoint is not vehicle-feasible")

    alpha_fixed = float(row["alpha_transfer"])
    fixed_ray = baseline + alpha_fixed * (schedule - baseline)
    sign_inv = _sign_decomposed_invariants(
        runtime.fleet,
        fixed_ray,
        str(row["direction"]),
    )
    convex_inv = _convex_witness_invariants(
        runtime.fleet,
        baseline,
        schedule,
        alpha_fixed,
        str(row["direction"]),
    )

    cross_mask = (baseline > 1e-7) & (schedule < -1e-7)
    sign_cross_slots = int(np.count_nonzero(cross_mask))
    sign_cross_vehicles = int(np.count_nonzero(np.any(cross_mask, axis=1)))

    prefix_samples = _prefix_alpha_samples(row)
    invalid_prefix: list[dict[str, Any]] = []
    valid_prefix_n = 0
    worst_prefix_error = 0.0
    for alpha in prefix_samples:
        candidate = baseline + float(alpha) * (schedule - baseline)
        inv = _sign_decomposed_invariants(
            runtime.fleet,
            candidate,
            str(row["direction"]),
        )
        worst_prefix_error = max(worst_prefix_error, float(inv["max_ev_invariant_error"]))
        if _vehicle_feasible(inv):
            valid_prefix_n += 1
        else:
            invalid_prefix.append(
                {
                    "alpha": float(alpha),
                    "max_ev_invariant_error": float(inv["max_ev_invariant_error"]),
                    "max_departure_error_kwh": float(inv["max_departure_error_kwh"]),
                    "max_reserve_violation_kwh": float(inv["max_reserve_violation_kwh"]),
                    "max_capacity_violation_kwh": float(inv["max_capacity_violation_kwh"]),
                    "max_discharge_budget_violation_kwh": float(
                        inv["max_discharge_budget_violation_kwh"]
                    ),
                }
            )

    return {
        "evaluation_id": str(row["evaluation_id"]),
        "work_unit_id": str(row["work_unit_id"]),
        "scenario_id": str(row["scenario_id"]),
        "feeder": str(row["feeder"]),
        "call_time": str(row["call_time"]),
        "direction": str(row["direction"]),
        "alpha_fixed": alpha_fixed,
        "f_bal_kw": float(row["f_bal_kw"]),
        "source_duration_min": int(row["source_duration_min"]),
        "schedule_sha256": observed_schedule_hash,
        "baseline_schedule_sha256": observed_baseline_hash,
        "sign_cross_vehicle_slots": sign_cross_slots,
        "sign_cross_vehicles": sign_cross_vehicles,
        "alpha_fixed_vehicle_feasible_sign_interpretation": _vehicle_feasible(sign_inv),
        "alpha_fixed_sign_max_ev_invariant_error": float(sign_inv["max_ev_invariant_error"]),
        "alpha_fixed_sign_max_departure_error_kwh": float(sign_inv["max_departure_error_kwh"]),
        "alpha_fixed_sign_max_reserve_violation_kwh": float(sign_inv["max_reserve_violation_kwh"]),
        "alpha_fixed_sign_max_capacity_violation_kwh": float(sign_inv["max_capacity_violation_kwh"]),
        "alpha_fixed_sign_max_discharge_budget_violation_kwh": float(
            sign_inv["max_discharge_budget_violation_kwh"]
        ),
        "alpha_fixed_sign_max_availability_violation_kw": float(
            sign_inv["max_availability_violation_kw"]
        ),
        "alpha_fixed_sign_max_charge_limit_violation_kw": float(
            sign_inv["max_charge_limit_violation_kw"]
        ),
        "alpha_fixed_sign_max_discharge_limit_violation_kw": float(
            sign_inv["max_discharge_limit_violation_kw"]
        ),
        "alpha_fixed_sign_simultaneous_slots": int(sign_inv["simultaneous_slots"]),
        "alpha_fixed_convex_witness_max_ev_invariant_error": float(
            convex_inv["max_ev_invariant_error"]
        ),
        "alpha_fixed_convex_witness_simultaneous_slots": int(
            convex_inv["simultaneous_slots"]
        ),
        "alpha_fixed_convex_witness_ray_identity_error_kw": float(
            convex_inv["ray_identity_error_kw"]
        ),
        "archived_prefix_sample_n": len(prefix_samples),
        "archived_prefix_vehicle_valid_sample_n": valid_prefix_n,
        "archived_prefix_vehicle_invalid_sample_n": len(invalid_prefix),
        "first_archived_prefix_vehicle_invalid_alpha": (
            float(invalid_prefix[0]["alpha"]) if invalid_prefix else None
        ),
        "worst_archived_prefix_max_ev_invariant_error": float(worst_prefix_error),
        "invalid_prefix_examples": invalid_prefix[:5],
    }


def _write_markdown(result: Mapping[str, Any], path: Path) -> None:
    s = result["summary"]
    lines = [
        "# V2.5B fixed-ray vehicle-feasibility verification",
        "",
        "**Role:** verification-only. No three-phase network result is recomputed, no alpha is changed, and no case is dropped.",
        "",
        f"- Active eligible primary 15-min cases checked: **{s['case_n']}**",
        f"- Exact balanced schedule SHA matches: **{s['schedule_hash_match_n']}/{s['case_n']}**",
        f"- Exact baseline schedule SHA matches: **{s['baseline_hash_match_n']}/{s['case_n']}**",
        f"- `alpha_fixed` vehicle-feasible under signed-net physical interpretation: **{s['alpha_fixed_vehicle_feasible_n']}/{s['case_n']}**",
        f"- Cases with at least one invalid archived prefix alpha sample: **{s['prefix_invalid_case_n']}/{s['case_n']}**",
        f"- INC alpha-fixed vehicle-feasible: **{s['by_direction']['inc']['alpha_fixed_vehicle_feasible_n']}/{s['by_direction']['inc']['n']}**",
        f"- DEC alpha-fixed vehicle-feasible: **{s['by_direction']['dec']['alpha_fixed_vehicle_feasible_n']}/{s['by_direction']['dec']['n']}**",
        "",
        "The signed-net interpretation sets charge=max(u,0) and discharge=max(-u,0), so no simultaneous charging/discharging is possible by construction. Vehicle feasibility then requires the original reserve/capacity/departure-energy/power/budget invariants to remain within 1e-6.",
        "",
        "## Cases failing vehicle feasibility at archived alpha_fixed",
        "",
        "| evaluation | feeder | dir | alpha_fixed | sign-cross slots | max EV error | departure error |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    failures = [
        row
        for row in result["cases"]
        if not row["alpha_fixed_vehicle_feasible_sign_interpretation"]
    ]
    if not failures:
        lines.append("| _none_ | | | | | | |")
    else:
        for row in failures:
            lines.append(
                f"| `{row['evaluation_id']}` | {row['feeder']} | {row['direction']} | "
                f"{row['alpha_fixed']:.6f} | {row['sign_cross_vehicle_slots']} | "
                f"{row['alpha_fixed_sign_max_ev_invariant_error']:.6g} | "
                f"{row['alpha_fixed_sign_max_departure_error_kwh']:.6g} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify(
    repo_root: Path,
    summary_path: Path,
    *,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = _active_primary_rows(summary)
    config, design = load_replication_design(repo_root)
    units = {str(row["work_unit_id"]): row for row in _records(design)}

    cases: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        work_unit_id = str(row["work_unit_id"])
        unit = units.get(work_unit_id)
        if unit is None:
            raise KeyError(f"R2 work unit absent from frozen design: {work_unit_id}")
        runtime = _create_real_pilot_runtime(repo_root, unit, config)
        case = _case_result(row, runtime=runtime, config=config, unit=unit)
        cases.append(case)
        if progress_path is not None:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            with progress_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_json_safe(case), sort_keys=True, allow_nan=False) + "\n")
        print(
            f"[{index:02d}/{len(rows)}] {case['evaluation_id']}: "
            f"alpha={case['alpha_fixed']:.3f} "
            f"vehicle={'PASS' if case['alpha_fixed_vehicle_feasible_sign_interpretation'] else 'FAIL'} "
            f"prefix_invalid={case['archived_prefix_vehicle_invalid_sample_n']} "
            f"cross_slots={case['sign_cross_vehicle_slots']}",
            flush=True,
        )

    by_direction: dict[str, dict[str, int]] = {}
    for direction in ("inc", "dec"):
        subset = [row for row in cases if row["direction"] == direction]
        by_direction[direction] = {
            "n": len(subset),
            "alpha_fixed_vehicle_feasible_n": sum(
                row["alpha_fixed_vehicle_feasible_sign_interpretation"] for row in subset
            ),
            "prefix_invalid_case_n": sum(
                row["archived_prefix_vehicle_invalid_sample_n"] > 0 for row in subset
            ),
            "sign_cross_case_n": sum(row["sign_cross_vehicle_slots"] > 0 for row in subset),
        }

    verification_summary = {
        "case_n": len(cases),
        "schedule_hash_match_n": len(cases),
        "baseline_hash_match_n": len(cases),
        "alpha_fixed_vehicle_feasible_n": sum(
            row["alpha_fixed_vehicle_feasible_sign_interpretation"] for row in cases
        ),
        "alpha_fixed_vehicle_infeasible_n": sum(
            not row["alpha_fixed_vehicle_feasible_sign_interpretation"] for row in cases
        ),
        "prefix_invalid_case_n": sum(
            row["archived_prefix_vehicle_invalid_sample_n"] > 0 for row in cases
        ),
        "sign_cross_case_n": sum(row["sign_cross_vehicle_slots"] > 0 for row in cases),
        "by_direction": by_direction,
    }

    return {
        "analysis": "V2.5B fixed-ray vehicle-feasibility verification",
        "analysis_role": "verification-only; no network result recomputation and no alpha modification",
        "r2_summary_sha256": _sha256(summary_path),
        "r2_config_sha256": str(config["_config_sha256"]),
        "primary_duration_min": PRIMARY_DURATION_MIN,
        "vehicle_invariant_tolerance": TOL,
        "signed_net_physical_interpretation": {
            "charge": "max(u, 0)",
            "discharge": "max(-u, 0)",
            "simultaneous_charge_discharge": "impossible by construction",
        },
        "summary": verification_summary,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--summary", required=True)
    parser.add_argument(
        "--output-json",
        default="reports/v2_5b_fixed_ray_vehicle_verification.json",
    )
    parser.add_argument(
        "--output-csv",
        default="reports/v2_5b_fixed_ray_vehicle_verification.csv",
    )
    parser.add_argument(
        "--output-md",
        default="reports/v2_5b_fixed_ray_vehicle_verification.md",
    )
    args = parser.parse_args()

    root = Path(args.repo_root).resolve(strict=True)
    summary_path = Path(args.summary).resolve(strict=True)
    progress_path = root / "reports/v2_5b_fixed_ray_vehicle_verification_partial.jsonl"
    if progress_path.exists():
        progress_path.unlink()
    result = verify(root, summary_path, progress_path=progress_path)

    output_json = root / args.output_json
    output_csv = root / args.output_csv
    output_md = root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(_json_safe(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(result["cases"]).drop(columns=["invalid_prefix_examples"]).to_csv(
        output_csv,
        index=False,
    )
    _write_markdown(result, output_md)

    print(
        json.dumps(
            {
                "status": "COMPLETED",
                "case_n": result["summary"]["case_n"],
                "alpha_fixed_vehicle_feasible_n": result["summary"][
                    "alpha_fixed_vehicle_feasible_n"
                ],
                "prefix_invalid_case_n": result["summary"]["prefix_invalid_case_n"],
                "output_json": str(output_json.relative_to(root)),
                "output_csv": str(output_csv.relative_to(root)),
                "output_md": str(output_md.relative_to(root)),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    # This is a diagnostic gate, not a CI pass/fail based on scientific outcome.
    # Exit nonzero only for execution/integrity errors; scientific vehicle-infeasible
    # cases are preserved in the report and still exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
