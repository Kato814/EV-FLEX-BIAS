"""Audit and summarize Reviewer-1/Reviewer-2 alpha-grid V3 evidence.

Run from the Downloads folder after a stress or full validation:
    python analyze_reviewer_alpha_v3.py

Read-only to the EV-FLEX-BIAS repository. Reports are written alongside the
per-case CSV and JSON under Downloads/reviewer_alpha_v3_results.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any

from reviewer_alpha_grid_v3 import (
    DEFAULT_OUTPUT, DEFAULT_REPO, N_GRID, SCRIPT_VERSION,
    analyze_flags, atomic_json, atomic_text, provenance, read_sources,
    sha256_file,
)


def safe_num(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite numeric value: {value}")
    return result


def csv_output(path: Path, records: list[dict[str, Any]], columns: list[str]) -> None:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    atomic_text(path, buf.getvalue())


def percentile_nearest_rank(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def analyze_one(meta: dict[str, Any], grid_rows: list[dict[str, str]], frozen: dict[str, str]) -> dict[str, Any]:
    scenario = frozen["scenario_id"]
    if len(grid_rows) != N_GRID:
        raise ValueError(f"{scenario}: expected 501 grid rows, found {len(grid_rows)}")
    flags = []
    first_failed_slots = []
    point_times = []
    total_power_flows = 0
    for idx, row in enumerate(grid_rows):
        if row["scenario_id"] != scenario or row["evaluation_id"] != frozen["evaluation_id"]:
            raise ValueError(f"{scenario}: grid row identity mismatch at {idx}")
        if int(row["alpha_index"]) != idx or abs(float(row["alpha"]) - idx / 500) > 1e-12:
            raise ValueError(f"{scenario}: missing/out-of-order alpha grid point {idx}")
        if row["feasible"] not in ("True", "False"):
            raise ValueError(f"{scenario}: unrecognized feasible flag at {idx}")
        flag = row["feasible"] == "True"
        flags.append(flag)
        if (int(row["checked_intervals"]) != 96 or row["complete_coverage"] != "True" or
                int(row["nonconverged_checks"]) != 0 or int(row["numerical_failure_checks"]) != 0 or
                int(row["converged_checks"]) != 96):
            raise ValueError(f"{scenario}: invalid numerical/coverage evidence at alpha index {idx}")
        cls = row["failure_class"]
        if flag and cls != "NONE":
            raise ValueError(f"{scenario}: a feasible alpha has failure class {cls}")
        if not flag:
            if cls != "PHYSICAL_CONSTRAINT" or not row["first_failure_slot"]:
                raise ValueError(f"{scenario}: missing physical witness at alpha index {idx}")
            first_failed_slots.append(int(row["first_failure_slot"]))
        point_times.append(safe_num(row["runtime_s"]))
        total_power_flows += int(row["power_flow_evaluations"])
    analysis = analyze_flags(flags)
    for key, val in analysis.items():
        if meta["grid"].get(key) != val:
            raise ValueError(f"{scenario}: saved grid statistics differ from recomputed {key}")
    alpha_grid = analysis["grid_max_feasible_alpha"]
    alpha_frozen = safe_num(frozen["alpha_transfer"])
    boundary_disagreement = (abs(alpha_grid - alpha_frozen) > 1e-9 or
                             abs(meta["original_search_alpha_prefix"] - alpha_frozen) > 1e-9)
    expected_review = (boundary_disagreement or analysis["nonmonotone_observed"] or
                       analysis["sampled_feasible_interval_count"] != 1)
    if (meta["status"] == "REVIEW_REQUIRED") != bool(expected_review):
        raise ValueError(f"{scenario}: inconsistent REVIEW_REQUIRED status")
    if meta["regenerated_schedule_sha256"] != meta["frozen_schedule_sha256"]:
        raise ValueError(f"{scenario}: vehicle schedule SHA mismatch")
    if meta["regenerated_baseline_sha256"] != meta["frozen_baseline_sha256"]:
        raise ValueError(f"{scenario}: baseline schedule SHA mismatch")
    if meta["grid_power_flow_evaluations"] != total_power_flows:
        raise ValueError(f"{scenario}: accumulated power-flow count differs")
    return {
        "scenario_id": scenario,
        "case_status": meta["status"],
        "evaluation_id": frozen["evaluation_id"],
        "feeder": frozen["feeder"],
        "frozen_alpha": alpha_frozen,
        "grid_alpha_prefix": analysis["grid_prefix_alpha"],
        "grid_alpha_max": alpha_grid,
        "grid_vs_frozen_delta": round(alpha_grid - alpha_frozen, 12),
        "feasible_interval_count": analysis["sampled_feasible_interval_count"],
        "nonmonotonic_recovery_transitions": analysis["infeasible_to_feasible_transition_count"],
        "first_infeasible_alpha": analysis["first_infeasible_alpha"],
        "first_failure_slot_min": min(first_failed_slots) if first_failed_slots else None,
        "target_hash_match": True,
        "baseline_hash_match": True,
        "complete_audit_points": N_GRID,
        "nonconverged_checks": 0,
        "numerical_failure_checks": 0,
        "original_search_evaluations": int(meta["original_search_alpha_audit_calls"]),
        "original_search_s": safe_num(meta["time_s"]["original_search_only"]),
        "end_to_end_pre_dispatch_s": safe_num(meta["time_s"]["original_pre_dispatch_total"]),
        "full_grid_s": safe_num(meta["time_s"]["full_grid_only"]),
        "grid_point_median_s": median(point_times),
        "grid_point_p95_s": percentile_nearest_rank(point_times, 0.95),
        "grid_power_flow_evaluations": total_power_flows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    out = args.output.resolve()
    if not out.is_dir():
        raise FileNotFoundError(f"No validation result directory: {out}")
    cases, _ = read_sources(repo)
    prov = provenance(repo, repo / "config/transferability_replication_v2_5b.json")
    completed: list[dict[str, Any]] = []
    missing = []
    all_grids = []
    for case in cases:
        scenario = case["scenario_id"]
        meta_file = out / f"{scenario}.json"
        grid_file = out / f"{scenario}.csv"
        if not meta_file.is_file() or not grid_file.is_file():
            missing.append(scenario)
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta.get("status") not in {"PASS", "REVIEW_REQUIRED"} or meta.get("provenance") != prov:
            raise ValueError(f"{scenario}: outdated/invalid case metadata; please rerun")
        if sha256_file(grid_file) != meta["grid_csv_sha256"]:
            raise ValueError(f"{scenario}: CSV SHA256 differs from saved checksum")
        with grid_file.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        completed.append(analyze_one(meta, rows, case))
        all_grids.extend(rows)
    finished = len(completed) == 46
    by_feeder = []
    for feeder in ("ieee13", "lv906"):
        z = [r for r in completed if r["feeder"] == feeder]
        if not z:
            continue
        record = {"feeder": feeder, "cases": len(z)}
        for key in ("original_search_s", "end_to_end_pre_dispatch_s", "full_grid_s", "grid_point_median_s"):
            values = [safe_num(x[key]) for x in z]
            record[key + "_median"] = median(values)
            record[key + "_mean"] = mean(values)
            record[key + "_min"] = min(values)
            record[key + "_max"] = max(values)
            record[key + "_p95"] = percentile_nearest_rank(values, 0.95)
        by_feeder.append(record)
    summary = {
        "protocol": SCRIPT_VERSION,
        "covered_cases": len(completed),
        "expected_cases": 46,
        "complete_46_case_evidence": finished,
        "missing_scenarios": missing,
        "grid_points_checked": N_GRID * len(completed),
        "grid_audits_all_full_96_slots": bool(completed),
        "nonmonotonic_cases_observed": sum(r["nonmonotonic_recovery_transitions"] > 0 for r in completed),
        "disconnected_cases_observed": sum(r["feasible_interval_count"] > 1 for r in completed),
        "review_required_cases": sum(r["case_status"] == "REVIEW_REQUIRED" for r in completed),
        "maximum_abs_alpha_difference": max((abs(r["grid_vs_frozen_delta"]) for r in completed), default=None),
        "schedule_hash_matches": sum(r["target_hash_match"] for r in completed),
        "baseline_hash_matches": sum(r["baseline_hash_match"] for r in completed),
        "numerical_failure_checks": sum(r["numerical_failure_checks"] for r in completed),
        "nonconverged_checks": sum(r["nonconverged_checks"] for r in completed),
        "per_feeder_runtime": by_feeder,
        "evidence_interpretation": (
            "Finite-grid verification at delta-alpha=0.002 only; not a proof of monotonicity over the continuous interval. "
            "Original search times are single measurements with baseline/cache prepared; end-to-end includes "
            "runtime initialization, balanced target generation, cache/baseline preparation, and original alpha search."
        ),
        "provenance": prov,
    }
    atomic_json(out / "analysis_summary.json", summary)
    if completed:
        columns = list(completed[0])
        csv_output(out / "case_table.csv", completed, columns)
        boundary_keys = ["scenario_id", "feeder", "frozen_alpha", "grid_alpha_prefix", "grid_alpha_max",
                         "grid_vs_frozen_delta", "feasible_interval_count", "nonmonotonic_recovery_transitions",
                         "first_infeasible_alpha", "target_hash_match"]
        csv_output(out / "boundary_comparison.csv", completed, boundary_keys)
        csv_output(out / "feeder_runtime_summary.csv", by_feeder, list(by_feeder[0]))
        csv_output(out / "all_alpha_grid_rows.csv", all_grids, list(all_grids[0]))
    print(json.dumps({
        "covered_cases": len(completed), "expected_cases": 46,
        "complete_46_case_evidence": finished,
        "nonmonotonic_cases_observed": summary["nonmonotonic_cases_observed"],
        "disconnected_cases_observed": summary["disconnected_cases_observed"],
        "review_required_cases": summary["review_required_cases"],
        "maximum_abs_alpha_difference": summary["maximum_abs_alpha_difference"],
        "numerical_failure_checks": summary["numerical_failure_checks"],
        "per_feeder_runtime": by_feeder,
        "reports": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
