"""Reviewer verification V3 (temporary; does not modify the Git repository).

Run under the installed EV-FLEX-BIAS Python 3.12 environment:
    python reviewer_alpha_grid_v3.py --mode selftest
    python reviewer_alpha_grid_v3.py --mode stress
    python reviewer_alpha_grid_v3.py --mode full

The source is the frozen 46-case V2.5B INC/V1G evidence. Each recreated
15-minute vehicle-level schedule must match its archived canonical SHA-256
before a grid point is evaluated.
"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path
from statistics import median
from typing import Any, Mapping

# The original frozen experiment used one numerical thread and one worker.
for _variable in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS",
):
    os.environ[_variable] = "1"

SCRIPT_VERSION = "reviewer-alpha-grid-v3.0"
DEFAULT_REPO = Path("E:/EV-FLEX-BIAS")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "reviewer_alpha_v3_results"
FROZEN_DIR = Path("manuscript_freeze_20260813/manuscript_freeze_20260813")
FROZEN_CASES = FROZEN_DIR / "v2_5b_inc_only_cases.csv"
FROZEN_RAW = FROZEN_DIR / "v2_5b_inc_only_raw_evaluations.json"
STRESS_CASES = ("ieee13_1900_28", "lv906_1900_28")
N_GRID = 501
STEP = 0.002
GRID_FIELDS = (
    "evaluation_id", "scenario_id", "feeder", "alpha_index", "alpha", "feasible",
    "failure_class", "first_failure_slot", "first_constraint_metrics",
    "checked_intervals", "complete_coverage", "converged_checks",
    "nonconverged_checks", "numerical_failure_checks", "physical_violation_checks",
    "power_flow_evaluations", "reused_baseline_intervals", "runtime_s",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as f:
        f.write(value)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def atomic_csv(path: Path, records: list[dict[str, Any]]) -> None:
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=GRID_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    atomic_text(path, buffer.getvalue())


def analyze_flags(flags: list[bool]) -> dict[str, Any]:
    """Report discrete grid connectivity, without assuming continuous monotonicity."""
    if not flags:
        raise ValueError("Empty feasibility grid")
    intervals: list[list[int]] = []
    beginnings: list[int] = []
    recoveries = 0
    seen_failure = False
    for idx, feasible in enumerate(flags):
        if not feasible:
            seen_failure = True
        else:
            if idx == 0 or not flags[idx - 1]:
                beginnings.append(idx)
                intervals.append([idx, idx])
                if seen_failure:
                    recoveries += 1
            else:
                intervals[-1][1] = idx
    return {
        "sampled_feasible_interval_count": len(intervals),
        "sampled_feasible_intervals_alpha": [[round(i / 500, 6), round(j / 500, 6)] for i, j in intervals],
        "infeasible_to_feasible_transition_count": recoveries,
        "nonmonotone_observed": recoveries > 0,
        "grid_prefix_alpha": (round((next((i for i, f in enumerate(flags) if not f), len(flags)) - 1) / 500, 6)
                              if flags[0] else None),
        "grid_max_feasible_alpha": (round(max(i for i, f in enumerate(flags) if f) / 500, 6)
                                    if any(flags) else None),
        "first_infeasible_alpha": (round(next(i for i, f in enumerate(flags) if not f) / 500, 6)
                                   if not all(flags) else None),
    }


def read_sources(repo: Path):
    """Read and cross-check paper cases and archived, vehicle-level evidence."""
    with (repo / FROZEN_CASES).open(newline="", encoding="utf-8-sig") as f:
        cases = list(csv.DictReader(f))
    raw = json.loads((repo / FROZEN_RAW).read_text(encoding="utf-8"))
    if len(cases) != 46 or len(raw) != 46:
        raise ValueError(f"Expected exactly 46 frozen cases and raw rows, got {len(cases)} / {len(raw)}")
    by_id = {r["evaluation_id"]: r for r in raw}
    if len(by_id) != 46:
        raise ValueError("Duplicate frozen evaluation IDs")
    if {r["evaluation_id"] for r in cases} != set(by_id):
        raise ValueError("The compact and raw frozen evaluation ID sets differ")
    if sum(r["feeder"] == "ieee13" for r in cases) != 22 or sum(r["feeder"] == "lv906" for r in cases) != 24:
        raise ValueError("Frozen feeder case counts differ from manuscript")
    for r in cases:
        o = by_id[r["evaluation_id"]]
        for key in ("scenario_id", "feeder", "call_time", "direction"):
            if r[key] != o[key]:
                raise ValueError(f"Frozen case mismatch: {key} for {r['evaluation_id']}")
        if (r["direction"] != "inc" or int(o["duration_min"]) != 15 or
                int(o["source_duration_min"]) != 15 or o["status"] != "SUCCESS" or
                not o.get("schedule_sha256") or not o.get("baseline_schedule_sha256")):
            raise ValueError(f"Frozen 15-minute INC case is not eligible: {r['evaluation_id']}")
        if abs(float(r["alpha_transfer"]) - float(o["alpha_transfer"])) > 1e-9:
            raise ValueError(f"Frozen alpha disagreement: {r['evaluation_id']}")
    return cases, by_id


def collect_constraint_metrics(raw: Mapping[str, Any]) -> str:
    failures = raw.get("violations", [])
    if not isinstance(failures, list) or not failures:
        return ""
    item = failures[0]
    details = item.get("violations", []) if isinstance(item, dict) else []
    metrics = sorted({
        str(x.get("metric") or x.get("label") or x.get("kind"))
        for x in details if isinstance(x, dict) and (x.get("metric") or x.get("label") or x.get("kind"))
    })
    return ";".join(metrics)


def provenance(repo: Path, config_path: Path) -> dict[str, Any]:
    def version(p: str) -> str | None:
        from importlib.metadata import PackageNotFoundError, version as installed_version
        try:
            return installed_version(p)
        except PackageNotFoundError:
            return None
    head = None
    try:
        p = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=True)
        head = p.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return {
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(Path(__file__)),
        "repo_root": str(repo),
        "git_head": head,
        "frozen_cases_sha256": sha256_file(repo / FROZEN_CASES),
        "frozen_raw_sha256": sha256_file(repo / FROZEN_RAW),
        "replication_config_sha256": sha256_file(config_path),
        "python_version": sys.version.split(" ")[0],
        "platform": platform.platform(),
        "numpy_version": version("numpy"),
        "scipy_version": version("scipy"),
        "opendssdirect_version": version("opendssdirect.py"),
        "dss_python_version": version("dss-python"),
        "n_grid": N_GRID,
        "grid_step": STEP,
        "workers": 1,
        "numerical_threads": 1,
        "validation_audit": "96-slot full coverage, no early stop, reusable verified baseline slots",
    }


def is_valid_cached_case(out: Path, case: dict[str, str], prov: dict[str, Any]) -> bool:
    stem = case["scenario_id"]
    meta_path = out / f"{stem}.json"
    grid_path = out / f"{stem}.csv"
    if not meta_path.exists() or not grid_path.exists():
        return False
    try:
        record = json.loads(meta_path.read_text(encoding="utf-8"))
        return (
            record.get("status") in {"PASS", "REVIEW_REQUIRED"} and
            record.get("evaluation_id") == case["evaluation_id"] and
            record.get("provenance") == prov and
            record.get("points") == N_GRID and
            record.get("grid_csv_sha256") == sha256_file(grid_path)
        )
    except (ValueError, KeyError, OSError):
        return False


def create_summary(out: Path, cases: list[dict[str, str]], prov: dict[str, Any]) -> dict[str, Any]:
    completed = []
    for case in cases:
        if is_valid_cached_case(out, case, prov):
            completed.append(json.loads((out / (case["scenario_id"] + ".json")).read_text(encoding="utf-8")))
    result = {
        "protocol": SCRIPT_VERSION,
        "expected_frozen_cases": 46,
        "completed_case_count": len(completed),
        "missing_case_count": 46 - len(completed),
        "completed_ieee13": sum(x["feeder"] == "ieee13" for x in completed),
        "completed_lv906": sum(x["feeder"] == "lv906" for x in completed),
        "sampled_nonmonotone_cases": sum(x["grid"]["nonmonotone_observed"] for x in completed),
        "review_required_case_count": sum(x["status"] == "REVIEW_REQUIRED" for x in completed),
        "sampled_disconnected_cases": sum(x["grid"]["sampled_feasible_interval_count"] != 1 for x in completed),
        "maximum_abs_grid_vs_frozen_alpha_difference": (
            max(abs(x["grid"]["grid_max_feasible_alpha"] - x["frozen_alpha"]) for x in completed)
            if completed else None
        ),
        "complete_46_case_result": len(completed) == 46,
        "cases": [x["scenario_id"] for x in completed],
        "provenance": prov,
    }
    atomic_json(out / "summary.json", result)
    return result


def run_one(repo: Path, out: Path, case: dict[str, str], frozen: dict[str, Any], config: Mapping[str, Any],
            source_units: Mapping[tuple[str, str], Mapping[str, Any]], prov: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    from evflex.pilot import (
        _create_real_pilot_runtime, _normalize_raw_balanced_result,
        _compact_audit_summary, _evaluate_corrected_schedule_path,
        canonical_schedule_sha256,
    )

    scenario = case["scenario_id"]
    original_cwd = Path.cwd()
    begun = time.perf_counter()
    runtime = None
    cache = None
    try:
        key = (scenario, case["direction"])
        if key not in source_units:
            raise ValueError(f"Missing work unit in verified V2.5B design: {key}")
        unit = dict(source_units[key])
        if unit["feeder"] != case["feeder"] or unit["call_time"] != case["call_time"]:
            raise ValueError(f"V2.5B work unit / frozen case mismatch for {scenario}")
        target_id = f"v25b_replication_{scenario}__inc__15m"
        if case["evaluation_id"] != target_id:
            raise ValueError(f"Unexpected evaluation ID for {scenario}")
        t0 = time.perf_counter()
        runtime = _create_real_pilot_runtime(repo, unit, config)
        runtime_construction_s = time.perf_counter() - t0
        baseline = np.asarray(runtime.baseline, dtype=float)
        baseline_hash = canonical_schedule_sha256(runtime.fleet, baseline)
        if baseline_hash != frozen["baseline_schedule_sha256"]:
            raise ValueError(f"FROZEN_BASELINE_SHA256_MISMATCH: {scenario}: {baseline_hash} != {frozen['baseline_schedule_sha256']}")
        t0 = time.perf_counter()
        raw = runtime.generate_balanced_raw(15, "balanced")
        normalized = _normalize_raw_balanced_result(raw, 15, runtime.fleet, baseline, direction="inc")
        if normalized["physical_feasible"] is not True:
            raise ValueError(f"Balanced target is vehicle-infeasible: {scenario}")
        target = normalized["schedule"]
        target_hash = canonical_schedule_sha256(runtime.fleet, target)
        if target_hash != frozen["schedule_sha256"]:
            raise ValueError(f"FROZEN_TARGET_SHA256_MISMATCH: {scenario}: {target_hash} != {frozen['schedule_sha256']}")
        if abs(float(normalized["flex_kw"]) - float(case["f_bal_kw"])) > 1e-5:
            raise ValueError(f"Balanced scheduled offer differs from frozen result: {scenario}")
        target_generation_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        cache = runtime.create_corrected_truth_cache()
        baseline_raw = runtime.audit_corrected(baseline, cache,
                                               baseline_slot_results=None,
                                               stop_on_violation=False,
                                               retain_slot_results=True)
        baseline_info = _compact_audit_summary(baseline_raw)
        baseline_audit_s = time.perf_counter() - t0
        if (not baseline_info["feasible"] or not baseline_info["complete_coverage"] or
                baseline_info["checked_intervals"] != 96 or baseline_info["failure_class"] != "NONE" or
                baseline_info["nonconverged_checks"] or baseline_info["numerical_failure_checks"]):
            raise ValueError(f"Baseline is not a valid 96-slot network-feasible reference: {scenario} / {baseline_info['failure_class']}")
        baseline_slots = baseline_raw.get("slot_results")
        if not isinstance(baseline_slots, list) or len(baseline_slots) != 96:
            raise ValueError(f"No reusable 96-slot baseline audit records: {scenario}")

        # Benchmark the ACTUAL original 0.02 + local 0.002 search separately.
        t0 = time.perf_counter()
        original = _evaluate_corrected_schedule_path(
            runtime, cache, target, baseline, baseline_slots,
            coarse_step=0.02, refine_tolerance=STEP,
        )
        original_search_s = time.perf_counter() - t0
        if original["status"] != "VALID" or original["scientific_valid"] is not True:
            raise ValueError(f"Original alpha path is numerically invalid for {scenario}")
        if original["audit_summary"]["numerical_failure_audits"]:
            raise ValueError(f"Original alpha path contains numerical failure for {scenario}")
        original_delta = float(original["alpha_prefix"]) - float(frozen["alpha_transfer"])

        # Dense grid: all 96 time slots audited at every alpha; never early-stop.
        records: list[dict[str, Any]] = []
        flags: list[bool] = []
        t0 = time.perf_counter()
        for idx in range(N_GRID):
            alpha = idx / 500
            schedule = baseline + alpha * (target - baseline)
            started = time.perf_counter()
            audit = runtime.audit_corrected(
                schedule, cache, baseline_slot_results=baseline_slots,
                stop_on_violation=False, retain_slot_results=False,
            )
            elapsed = time.perf_counter() - started
            info = _compact_audit_summary(audit)
            if (info["checked_intervals"] != 96 or not info["complete_coverage"] or
                    info["numerical_failure_checks"] or info["nonconverged_checks"] or
                    info["failure_class"] not in {"NONE", "PHYSICAL_CONSTRAINT"}):
                raise RuntimeError(f"UNCLASSIFIED_OR_NUMERICAL_GRID_AUDIT: {scenario} alpha={alpha:.3f}: {info['failure_class']}; checked={info['checked_intervals']}")
            feasible = info["feasible"]
            if (feasible and info["failure_class"] != "NONE") or (
                not feasible and (info["failure_class"] != "PHYSICAL_CONSTRAINT" or not info["explicit_physical_witness"])
            ):
                raise RuntimeError(f"Inconsistent physical feasibility witness: {scenario} alpha={alpha:.3f}")
            records.append({
                "evaluation_id": case["evaluation_id"],
                "scenario_id": scenario,
                "feeder": case["feeder"],
                "alpha_index": idx,
                "alpha": f"{alpha:.3f}",
                "feasible": bool(feasible),
                "failure_class": info["failure_class"],
                "first_failure_slot": info["first_failure_slot"],
                "first_constraint_metrics": collect_constraint_metrics(audit),
                "checked_intervals": info["checked_intervals"],
                "complete_coverage": info["complete_coverage"],
                "converged_checks": info["converged_checks"],
                "nonconverged_checks": info["nonconverged_checks"],
                "numerical_failure_checks": info["numerical_failure_checks"],
                "physical_violation_checks": info["physical_violation_checks"],
                "power_flow_evaluations": info["power_flow_evaluations"],
                "reused_baseline_intervals": info["reused_baseline_intervals"],
                "runtime_s": round(elapsed, 9),
            })
            flags.append(bool(feasible))
            if (idx + 1) % 100 == 0 or idx == N_GRID - 1:
                print(f"    {scenario}: {idx + 1}/{N_GRID} alpha points, grid elapsed {time.perf_counter() - t0:.1f}s", flush=True)
        full_grid_s = time.perf_counter() - t0
        grid = analyze_flags(flags)
        if not flags[0]:
            raise ValueError(f"Alpha=0 unexpectedly infeasible: {scenario}")
        delta = float(grid["grid_max_feasible_alpha"]) - float(frozen["alpha_transfer"])
        # Preserve genuine nonmonotonicity and disagreements for reviewer scrutiny.
        requires_review = bool(
            abs(delta) > 1e-9 or abs(original_delta) > 1e-9
            or grid["nonmonotone_observed"]
            or grid["sampled_feasible_interval_count"] != 1
        )
        out.mkdir(parents=True, exist_ok=True)
        csv_file = out / f"{scenario}.csv"
        atomic_csv(csv_file, records)
        time_list = [float(x["runtime_s"]) for x in records]
        meta = {
            "status": "REVIEW_REQUIRED" if requires_review else "PASS",
            "evaluation_id": case["evaluation_id"],
            "scenario_id": scenario,
            "feeder": case["feeder"],
            "call_time": case["call_time"],
            "points": N_GRID,
            "frozen_alpha": float(frozen["alpha_transfer"]),
            "frozen_schedule_sha256": frozen["schedule_sha256"],
            "regenerated_schedule_sha256": target_hash,
            "frozen_baseline_sha256": frozen["baseline_schedule_sha256"],
            "regenerated_baseline_sha256": baseline_hash,
            "frozen_scheduled_offer_kw": float(case["f_bal_kw"]),
            "new_scheduled_offer_kw": float(normalized["flex_kw"]),
            "original_search_alpha_prefix": original["alpha_prefix"],
            "original_search_vs_frozen_alpha_difference": original_delta,
            "original_search_alpha_sup": original["alpha_sup"],
            "original_search_nonmonotone_observed": original["nonmonotone"],
            "original_search_alpha_audit_calls": original["audit_calls"],
            "original_search_power_flow_evaluations": original["audit_summary"]["power_flow_evaluations"],
            "grid": grid,
            "grid_vs_frozen_alpha_difference": delta,
            "time_s": {
                "runtime_construction": runtime_construction_s,
                "balanced_target_generation": target_generation_s,
                "network_cache_and_baseline": baseline_audit_s,
                "original_search_only": original_search_s,
                "original_pre_dispatch_total": runtime_construction_s + target_generation_s + baseline_audit_s + original_search_s,
                "full_grid_only": full_grid_s,
                "full_case_with_validation": time.perf_counter() - begun,
                "full_grid_per_alpha_median": median(time_list),
            },
            "grid_power_flow_evaluations": sum(int(x["power_flow_evaluations"]) for x in records),
            "grid_reused_baseline_intervals": sum(int(x["reused_baseline_intervals"]) for x in records),
            "grid_numerical_failure_checks": sum(int(x["numerical_failure_checks"]) for x in records),
            "grid_nonconverged_checks": sum(int(x["nonconverged_checks"]) for x in records),
            "grid_invalid_coverage_points": sum(int(x["checked_intervals"]) != 96 for x in records),
            "grid_csv_sha256": sha256_file(csv_file),
            "provenance": prov,
        }
        atomic_json(out / f"{scenario}.json", meta)
        print(f"  {meta['status']} {scenario}: grid_alpha={grid['grid_max_feasible_alpha']}, recovery={grid['infeasible_to_feasible_transition_count']}, original={original_search_s:.2f}s, full_grid={full_grid_s:.2f}s", flush=True)
        return meta
    finally:
        os.chdir(original_cwd)
        cache = None
        runtime = None
        gc.collect()


def run_selftest() -> None:
    assert analyze_flags([True, True, True])["sampled_feasible_interval_count"] == 1
    x = analyze_flags([True, False, True, False, True])
    assert x["sampled_feasible_interval_count"] == 3 and x["infeasible_to_feasible_transition_count"] == 2
    assert analyze_flags([True, True, False, False])["grid_prefix_alpha"] == 0.002
    assert analyze_flags([True] * 501)["grid_max_feasible_alpha"] == 1.0
    assert analyze_flags([True] * 499 + [False, False])["grid_max_feasible_alpha"] == 0.996
    print("Self-test PASS: sampled interval/recovery/prefix calculations")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("selftest", "list", "stress", "full", "single"), default="stress")
    parser.add_argument("--case", default=None, help="Internal single-case execution, isolated in a child process")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="Rerun completed cases instead of skipping verified results")
    args = parser.parse_args()
    if args.mode == "selftest":
        run_selftest()
        return 0

    repo = args.repo.resolve(strict=True)
    out = args.output.resolve()
    all_cases, raw_by_id = read_sources(repo)
    if args.mode == "list":
        print("Frozen INC/V1G cases: 46 = IEEE13 (22) + LV906 (24)")
        print("Stress test cases:", ", ".join(STRESS_CASES))
        return 0

    # Use the V2.5B design to verify source-manifest hashes, scenario seeds,
    # work units, and *the actual constraints used in the accepted paper*.
    from evflex.transferability_replication_v2_5b import load_replication_design
    config, unit_frame = load_replication_design(repo)
    source_units = {
        (str(row["scenario_id"]), str(row["direction"])): row
        for row in unit_frame.to_dict(orient="records")
    }
    prov = provenance(repo, repo / "config/transferability_replication_v2_5b.json")
    atomic_json(out / "provenance.json", prov)
    if args.mode == "single":
        if not args.case:
            parser.error("--mode single requires --case")
        target_cases = [r for r in all_cases if r["scenario_id"] == args.case]
        if len(target_cases) != 1:
            raise ValueError(f"Case not found in frozen 46: {args.case}")
    elif args.mode == "full":
        target_cases = all_cases
    else:
        target_cases = [r for r in all_cases if r["scenario_id"] in STRESS_CASES]
        if len(target_cases) != 2:
            raise RuntimeError("Stress cases not found among frozen 46 evaluations")
    print(f"Mode={args.mode}; selected={len(target_cases)}; output={out}; step={STEP}; workers=1", flush=True)
    started = time.perf_counter()
    for i, case in enumerate(target_cases, start=1):
        scenario = case["scenario_id"]
        if not args.force and args.mode != "single" and is_valid_cached_case(out, case, prov):
            print(f"[{i}/{len(target_cases)}] SKIP completed {scenario}", flush=True)
            continue
        print(f"[{i}/{len(target_cases)}] RUN {scenario}: frozen alpha={case['alpha_transfer']}", flush=True)
        if args.mode != "single":
            # Fresh Python/OpenDSS process per case to avoid DSS-C-API state
            # leakage or native-memory accumulation during a long 46-case run.
            command = [
                sys.executable, str(Path(__file__).resolve()),
                "--mode", "single", "--case", scenario,
                "--repo", str(repo), "--output", str(out),
            ]
            try:
                child = subprocess.run(command, cwd=str(Path(__file__).resolve().parent), check=False)
            except OSError as exc:
                print(f"Unable to start child process for {scenario}: {exc}", file=sys.stderr)
                return 2
            if child.returncode:
                print(f"Case {scenario} failed in isolated child process (exit code {child.returncode}); stopped.",
                      file=sys.stderr, flush=True)
                create_summary(out, all_cases, prov)
                return 2
        else:
            try:
                run_one(repo, out, case, raw_by_id[case["evaluation_id"]], config, source_units, prov)
            except Exception as e:
                detail = {"status": "FAILED", "scenario_id": scenario, "exception": str(e),
                          "traceback": traceback.format_exc(), "script_version": SCRIPT_VERSION}
                atomic_json(out / f"{scenario}.error.json", detail)
                print(f"FAILED {scenario}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                create_summary(out, all_cases, prov)
                return 2
        create_summary(out, all_cases, prov)
    result = create_summary(out, all_cases, prov)
    if args.mode != "single":
        print(json.dumps({
            "selected": len(target_cases),
            "completed_of_46": result["completed_case_count"],
            "sampled_nonmonotone_cases": result["sampled_nonmonotone_cases"],
            "sampled_disconnected_cases": result["sampled_disconnected_cases"],
            "review_required_case_count": result["review_required_case_count"],
            "full_46_complete": result["complete_46_case_result"],
            "elapsed_wall_s": round(time.perf_counter() - started, 2),
        }, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
