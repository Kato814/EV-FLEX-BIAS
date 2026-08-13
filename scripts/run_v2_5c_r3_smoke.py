from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, csr_matrix

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
DT = 0.25
TOL = 1e-9

SMOKE_IDS = (
    # IEEE13: transformer-limited, inc.
    "v25b_replication_ieee13_1900_28__inc__15m",
    # IEEE13: VUF-limited, inc.
    "v25b_replication_ieee13_0600_27__inc__15m",
    # LV906: low-voltage, inc.
    "v25b_replication_lv906_1900_28__inc__15m",
    # LV906: high-voltage, dec.
    "v25b_replication_lv906_1900_26__dec__15m",
)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        row = {key: (None if pd.isna(value) else value) for key, value in raw.items()}
        row["scenario_seed"] = int(row["scenario_seed"])
        row["prior_holdout_open_acknowledged"] = bool(
            row["prior_holdout_open_acknowledged"]
        )
        out.append(row)
    return out


def _load_boundary(path: Path) -> dict[str, dict[str, Any]]:
    frame = pd.read_csv(path)
    if len(frame) != 56:
        raise ValueError(f"boundary witness must contain 56 rows, got {len(frame)}")
    by_id = {
        str(row.evaluation_id): row._asdict()
        for row in frame.itertuples(index=False)
    }
    missing = [name for name in SMOKE_IDS if name not in by_id]
    if missing:
        raise KeyError(f"smoke ids absent from boundary witness: {missing}")
    return by_id


def _mode(direction: str) -> str:
    if direction == "inc":
        return "v1g"
    if direction == "dec":
        return "v2g"
    raise ValueError(f"unsupported direction {direction!r}")


def _pairs(
    fleet: Sequence[Any],
) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    pairs = [
        (i, t)
        for i, ev in enumerate(fleet)
        for t in range(int(ev.arrival), int(ev.departure))
    ]
    return pairs, {pair: index for index, pair in enumerate(pairs)}


def _group_to_evs(
    fleet: Sequence[Any],
    groups: Sequence[Any],
) -> list[list[int]]:
    result: list[list[int]] = []
    for group in groups:
        if not (
            isinstance(group, (tuple, list))
            and len(group) == 2
        ):
            raise ValueError("R3 spatial targets require three-phase (bus, phase) groups")
        bus, phase = str(group[0]), int(group[1])
        result.append(
            [
                i
                for i, ev in enumerate(fleet)
                if str(ev.bus) == bus and int(ev.phase) == phase
            ]
        )
    return result


def _build_repair_lp(
    fleet: Sequence[Any],
    fixed_ray: np.ndarray,
    *,
    mode: str,
    groups: Sequence[Any],
    spatial_targets: Mapping[int, np.ndarray],
) -> dict[str, Any]:
    """Feeder-trajectory-preserving trajectory LP with fixed spatial targets.

    This implements the preregistered preservation rule:
      * all 96 feeder-time aggregate EV powers equal the fixed ray;
      * selected failure slots additionally match a frozen, nonlinear-verified
        three-phase bus/phase target;
      * all EV trajectory constraints remain active.

    No network sensitivity inequalities are inserted into this trajectory LP.
    """
    pairs, pmap = _pairs(fleet)
    n = len(pairs)
    z0 = 2 * n
    nvar = 3 * n

    objective = np.zeros(nvar, dtype=float)
    objective[: 2 * n] = 1e-5
    objective[z0:] = 1.0

    bounds: list[tuple[float | None, float | None]] = []
    for i, _ in pairs:
        bounds.append((0.0, float(fleet[i].pch)))
    for i, _ in pairs:
        ev = fleet[i]
        upper = float(ev.pdis) if mode == "v2g" and bool(ev.v2g) else 0.0
        bounds.append((0.0, upper))
    bounds.extend([(0.0, None)] * n)

    ub_rows: list[dict[int, float]] = []
    ub_rhs: list[float] = []
    eq_rows: list[dict[int, float]] = []
    eq_rhs: list[float] = []

    # Vehicle energy, reserve/capacity, departure-energy and V2G-budget constraints.
    for i, ev in enumerate(fleet):
        indices = [
            pmap[(i, t)]
            for t in range(int(ev.arrival), int(ev.departure))
        ]
        for k in range(len(indices)):
            upper_row: dict[int, float] = {}
            lower_row: dict[int, float] = {}
            for j in indices[: k + 1]:
                upper_row[j] = float(ev.eta_c) * DT
                upper_row[n + j] = -DT / float(ev.eta_d)
                lower_row[j] = -float(ev.eta_c) * DT
                lower_row[n + j] = DT / float(ev.eta_d)
            ub_rows.append(upper_row)
            ub_rhs.append(float(ev.capacity) - float(ev.initial))
            ub_rows.append(lower_row)
            ub_rhs.append(float(ev.initial) - float(ev.reserve))

        terminal: dict[int, float] = {}
        for j in indices:
            terminal[j] = float(ev.eta_c) * DT
            terminal[n + j] = -DT / float(ev.eta_d)
        eq_rows.append(terminal)
        eq_rhs.append(float(ev.target) - float(ev.initial))

        if mode == "v2g" and bool(ev.v2g):
            ub_rows.append({n + j: DT for j in indices})
            ub_rhs.append(float(ev.max_discharge))

    # Deterministic tie-break: remain as close as possible to the exact fixed ray.
    for j, (i, t) in enumerate(pairs):
        target = float(fixed_ray[i, t])
        ub_rows.append({j: 1.0, n + j: -1.0, z0 + j: -1.0})
        ub_rhs.append(target)
        ub_rows.append({j: -1.0, n + j: 1.0, z0 + j: -1.0})
        ub_rhs.append(-target)

    # Exact feeder-time aggregate trajectory for all 96 slots.
    feeder_target = np.asarray(fixed_ray, dtype=float).sum(axis=0)
    for t in range(T):
        row: dict[int, float] = {}
        for i, _ev in enumerate(fleet):
            j = pmap.get((i, t))
            if j is None:
                continue
            row[j] = 1.0
            row[n + j] = -1.0
        eq_rows.append(row)
        eq_rhs.append(float(feeder_target[t]))

    # Preregistered fixed bus-phase equality targets for already-diagnosed slots.
    group_evs = _group_to_evs(fleet, groups)
    for slot, raw_target in sorted(spatial_targets.items()):
        target = np.asarray(raw_target, dtype=float)
        if target.shape != (len(groups),) or not np.isfinite(target).all():
            raise ValueError(f"invalid spatial target at slot {slot}")
        if abs(float(target.sum()) - float(feeder_target[slot])) > 1e-6:
            raise ValueError(
                f"spatial target at slot {slot} changes feeder aggregate commitment"
            )
        for g, evs in enumerate(group_evs):
            row: dict[int, float] = {}
            for i in evs:
                j = pmap.get((i, int(slot)))
                if j is None:
                    continue
                row[j] = 1.0
                row[n + j] = -1.0
            eq_rows.append(row)
            eq_rhs.append(float(target[g]))

    def sparse(rows: Sequence[Mapping[int, float]]) -> csr_matrix:
        rr: list[int] = []
        cc: list[int] = []
        vv: list[float] = []
        for r, row in enumerate(rows):
            for c, value in row.items():
                value = float(value)
                if abs(value) <= 1e-18:
                    continue
                rr.append(r)
                cc.append(int(c))
                vv.append(value)
        return coo_matrix(
            (vv, (rr, cc)),
            shape=(len(rows), nvar),
        ).tocsr()

    return {
        "objective": objective,
        "bounds": bounds,
        "A_ub": sparse(ub_rows),
        "b_ub": np.asarray(ub_rhs, dtype=float),
        "A_eq": sparse(eq_rows),
        "b_eq": np.asarray(eq_rhs, dtype=float),
        "pairs": pairs,
        "n": n,
        "feeder_target": feeder_target,
    }


def _solve_repair_lp(
    fleet: Sequence[Any],
    fixed_ray: np.ndarray,
    *,
    mode: str,
    groups: Sequence[Any],
    spatial_targets: Mapping[int, np.ndarray],
) -> dict[str, Any]:
    lp = _build_repair_lp(
        fleet,
        fixed_ray,
        mode=mode,
        groups=groups,
        spatial_targets=spatial_targets,
    )
    result = linprog(
        lp["objective"],
        A_ub=lp["A_ub"],
        b_ub=lp["b_ub"],
        A_eq=lp["A_eq"],
        b_eq=lp["b_eq"],
        bounds=lp["bounds"],
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-9,
            "dual_feasibility_tolerance": 1e-9,
        },
    )
    if not result.success:
        return {
            "success": False,
            "status": "TRAJECTORY_LP_INFEASIBLE",
            "message": str(result.message),
        }

    n = int(lp["n"])
    schedule = np.zeros((len(fleet), T), dtype=float)
    charge = np.zeros_like(schedule)
    discharge = np.zeros_like(schedule)
    for j, (i, t) in enumerate(lp["pairs"]):
        charge[i, t] = float(result.x[j])
        discharge[i, t] = float(result.x[n + j])
        schedule[i, t] = charge[i, t] - discharge[i, t]

    invariants = _trajectory_invariants(
        fleet,
        schedule,
        charge,
        discharge,
        mode,
    )
    aggregate_error = float(
        np.max(
            np.abs(
                schedule.sum(axis=0)
                - np.asarray(lp["feeder_target"], dtype=float)
            ),
            initial=0.0,
        )
    )
    valid = bool(
        aggregate_error <= 1e-6
        and invariants["max_ev_invariant_error"] <= 1e-6
        and invariants["simultaneous_slots"] == 0
    )
    return {
        "success": valid,
        "status": "SUCCESS" if valid else "INVARIANT_FAILURE",
        "message": str(result.message),
        "schedule": schedule,
        "charge": charge,
        "discharge": discharge,
        "aggregate_error_kw": aggregate_error,
        "invariants": invariants,
    }


def _audit(
    runtime: Any,
    schedule: np.ndarray,
    truth_cache: Any,
    baseline_slots: Any,
    *,
    full: bool,
) -> dict[str, Any]:
    return runtime.audit_corrected(
        schedule,
        truth_cache,
        baseline_slot_results=baseline_slots,
        stop_on_violation=not full,
        retain_slot_results=False,
    )


def _first_physical_failure(
    raw: Mapping[str, Any],
) -> tuple[int | None, list[Any]]:
    violations = raw.get("violations", [])
    if not isinstance(violations, list):
        return None, []
    physical: list[tuple[int, list[Any]]] = []
    for item in violations:
        if not isinstance(item, Mapping):
            continue
        if item.get("failure_class") != "PHYSICAL_CONSTRAINT":
            continue
        try:
            slot = int(item["slot"])
        except (KeyError, TypeError, ValueError):
            continue
        witness = item.get("violations", [])
        physical.append(
            (slot, list(witness) if isinstance(witness, list) else [])
        )
    if not physical:
        return None, []
    slot = min(value[0] for value in physical)
    witnesses: list[Any] = []
    for observed_slot, observed in physical:
        if observed_slot == slot:
            witnesses.extend(observed)
    return slot, witnesses


def _pointwise_spatial_target(
    runtime: Any,
    baseline: np.ndarray,
    fixed_ray: np.ndarray,
    truth_cache: Any,
    slot: int,
) -> dict[str, Any]:
    """Construct the preregistered nonlinear-feasible point target.

    1. Start from the baseline three-phase EV group injection at the failure slot.
    2. Use the existing finite-difference sensitivity + point optimizer.
    3. The point optimizer performs a nonlinear evaluation and, if needed,
       backtracks toward baseline.
    4. Interpolate the verified pointwise-feasible injection to exactly match
       the fixed-ray feeder aggregate at this slot.
    5. Nonlinearly evaluate the interpolated target before it is frozen.
    """
    scale = float(runtime.load_scales[slot])
    if scale not in truth_cache:
        raise KeyError(f"truth cache has no network for load scale {scale}")
    network = truth_cache[scale]
    groups = list(network.groups)

    # Reuse the archived instantaneous vehicle-bound construction with the
    # actual R2 baseline schedule.
    frame = runtime.corrected_core.fleet_frame(
        runtime.fleet,
        baseline,
        int(slot),
    )
    if len(frame) != len(runtime.fleet):
        raise ValueError("instantaneous fleet frame row count differs")

    if runtime.direction == "inc":
        lower_values = np.asarray(frame["v1_lo"], dtype=float)
        upper_values = np.asarray(frame["v1_hi"], dtype=float)
        sense = "max"
    elif runtime.direction == "dec":
        lower_values = np.asarray(frame["v2_lo"], dtype=float)
        upper_values = np.asarray(frame["v2_hi"], dtype=float)
        sense = "min"
    else:
        raise ValueError(runtime.direction)

    base_values = np.asarray(frame["base"], dtype=float)
    p0 = np.asarray(
        runtime.archived_engine.group_vector(
            runtime.fleet,
            base_values,
            groups,
            "3ph",
        ),
        dtype=float,
    )
    lower = np.asarray(
        runtime.archived_engine.group_vector(
            runtime.fleet,
            lower_values,
            groups,
            "3ph",
        ),
        dtype=float,
    )
    upper = np.asarray(
        runtime.archived_engine.group_vector(
            runtime.fleet,
            upper_values,
            groups,
            "3ph",
        ),
        dtype=float,
    )

    baseline_eval = network.evaluate(p0)
    if baseline_eval.get("feasible") is not True:
        return {
            "success": False,
            "status": "POINT_BASELINE_INVALID",
        }

    sensitivity = network.sensitivity(p0)
    optimized = network.optimize(
        p0,
        lower,
        upper,
        sense,
        sensitivity,
    )
    if optimized.get("success") is not True:
        return {
            "success": False,
            "status": "POINT_OPTIMIZER_FAILED",
        }

    p_opt = np.asarray(optimized["p"], dtype=float)
    if p_opt.shape != p0.shape or not np.isfinite(p_opt).all():
        return {
            "success": False,
            "status": "POINT_OPTIMIZER_INVALID_VECTOR",
        }
    opt_eval = network.evaluate(p_opt)
    if opt_eval.get("feasible") is not True:
        return {
            "success": False,
            "status": "POINT_OPTIMIZER_NONLINEAR_INVALID",
        }

    required_total = float(np.asarray(fixed_ray[:, slot], dtype=float).sum())
    base_total = float(p0.sum())
    opt_total = float(p_opt.sum())
    denominator = opt_total - base_total

    if runtime.direction == "inc":
        if required_total > opt_total + 1e-6:
            return {
                "success": False,
                "status": "POINTWISE_HEADROOM_INSUFFICIENT",
                "base_total_kw": base_total,
                "point_opt_total_kw": opt_total,
                "required_total_kw": required_total,
            }
    else:
        if required_total < opt_total - 1e-6:
            return {
                "success": False,
                "status": "POINTWISE_HEADROOM_INSUFFICIENT",
                "base_total_kw": base_total,
                "point_opt_total_kw": opt_total,
                "required_total_kw": required_total,
            }

    if abs(required_total - base_total) <= 1e-8:
        lam = 0.0
        target = p0.copy()
    else:
        if abs(denominator) <= 1e-12:
            return {
                "success": False,
                "status": "POINTWISE_ZERO_HEADROOM",
                "base_total_kw": base_total,
                "point_opt_total_kw": opt_total,
                "required_total_kw": required_total,
            }
        lam = (required_total - base_total) / denominator
        if lam < -1e-7 or lam > 1.0 + 1e-7:
            return {
                "success": False,
                "status": "POINTWISE_INTERPOLATION_OUT_OF_RANGE",
                "lambda": float(lam),
                "base_total_kw": base_total,
                "point_opt_total_kw": opt_total,
                "required_total_kw": required_total,
            }
        lam = min(max(float(lam), 0.0), 1.0)
        target = p0 + lam * (p_opt - p0)

    aggregate_error = abs(float(target.sum()) - required_total)
    if aggregate_error > 1e-6:
        return {
            "success": False,
            "status": "POINT_TARGET_AGGREGATE_MISMATCH",
            "aggregate_error_kw": aggregate_error,
        }

    target_eval = network.evaluate(target)
    if target_eval.get("feasible") is not True:
        return {
            "success": False,
            "status": "INTERPOLATED_TARGET_NONLINEAR_INVALID",
            "lambda": float(lam),
            "base_total_kw": base_total,
            "point_opt_total_kw": opt_total,
            "required_total_kw": required_total,
        }

    return {
        "success": True,
        "status": "SUCCESS",
        "groups": groups,
        "target": target,
        "lambda": float(lam),
        "base_total_kw": base_total,
        "point_opt_total_kw": opt_total,
        "required_total_kw": required_total,
        "aggregate_error_kw": aggregate_error,
    }


def _repair_at_alpha(
    runtime: Any,
    baseline: np.ndarray,
    original: np.ndarray,
    *,
    alpha: float,
    truth_cache: Any,
    baseline_slots: Any,
) -> dict[str, Any]:
    fixed_ray = baseline + float(alpha) * (original - baseline)
    mode = _mode(runtime.direction)

    # All truth-cache networks for a work unit use the same EV bus/phase groups.
    first_network = next(iter(truth_cache.values()))
    groups = list(first_network.groups)

    spatial_targets: dict[int, np.ndarray] = {}
    seen_slots: set[int] = set()
    trace: list[dict[str, Any]] = []
    point_optimizer_calls = 0

    for iteration in range(T + 1):
        solved = _solve_repair_lp(
            runtime.fleet,
            fixed_ray,
            mode=mode,
            groups=groups,
            spatial_targets=spatial_targets,
        )
        if not solved["success"]:
            return {
                "verified_feasible": False,
                "status": solved["status"],
                "iterations": iteration,
                "spatial_target_slots": sorted(seen_slots),
                "point_optimizer_calls": point_optimizer_calls,
                "trace": trace,
            }

        schedule = solved["schedule"]
        raw = _audit(
            runtime,
            schedule,
            truth_cache,
            baseline_slots,
            full=False,
        )
        numerical = int(raw.get("numerical_failure_checks", 0))
        nonconverged = int(raw.get("nonconverged_checks", 0))
        if numerical or nonconverged:
            return {
                "verified_feasible": False,
                "status": "NUMERICAL_INVALID",
                "iterations": iteration,
                "spatial_target_slots": sorted(seen_slots),
                "point_optimizer_calls": point_optimizer_calls,
                "trace": trace,
            }

        if (
            raw.get("feasible") is True
            and int(raw.get("checked_intervals", 0)) == T
        ):
            final = _audit(
                runtime,
                schedule,
                truth_cache,
                baseline_slots,
                full=True,
            )
            verified = bool(
                final.get("feasible") is True
                and int(final.get("checked_intervals", 0)) == T
                and int(final.get("numerical_failure_checks", 0)) == 0
                and int(final.get("nonconverged_checks", 0)) == 0
            )
            return {
                "verified_feasible": verified,
                "status": (
                    "VERIFIED_FEASIBLE"
                    if verified
                    else "FULL_AUDIT_FAILED"
                ),
                "iterations": iteration,
                "spatial_target_slots": sorted(seen_slots),
                "point_optimizer_calls": point_optimizer_calls,
                "aggregate_error_kw": solved["aggregate_error_kw"],
                "invariants": solved["invariants"],
                "trace": trace,
            }

        slot, witnesses = _first_physical_failure(raw)
        trace_entry: dict[str, Any] = {
            "iteration": iteration,
            "first_failure_slot": slot,
            "witnesses": witnesses,
            "aggregate_error_kw": solved["aggregate_error_kw"],
        }
        trace.append(trace_entry)

        if slot is None:
            return {
                "verified_feasible": False,
                "status": "UNCLASSIFIED_INVALID",
                "iterations": iteration,
                "spatial_target_slots": sorted(seen_slots),
                "point_optimizer_calls": point_optimizer_calls,
                "trace": trace,
            }
        if slot in seen_slots:
            return {
                "verified_feasible": False,
                "status": "TARGETED_SLOT_STILL_FAILS",
                "iterations": iteration,
                "spatial_target_slots": sorted(seen_slots),
                "point_optimizer_calls": point_optimizer_calls,
                "trace": trace,
            }

        point = _pointwise_spatial_target(
            runtime,
            baseline,
            fixed_ray,
            truth_cache,
            int(slot),
        )
        point_optimizer_calls += 1
        trace_entry["point_target_status"] = point["status"]
        for name in (
            "lambda",
            "base_total_kw",
            "point_opt_total_kw",
            "required_total_kw",
            "aggregate_error_kw",
        ):
            if name in point:
                trace_entry[name] = point[name]

        if not point["success"]:
            return {
                "verified_feasible": False,
                "status": point["status"],
                "iterations": iteration,
                "spatial_target_slots": sorted(seen_slots),
                "point_optimizer_calls": point_optimizer_calls,
                "trace": trace,
            }

        if list(point["groups"]) != groups:
            raise ValueError("truth-cache group ordering changed across load scales")
        spatial_targets[int(slot)] = np.asarray(point["target"], dtype=float)
        seen_slots.add(int(slot))

    return {
        "verified_feasible": False,
        "status": "ITERATION_LIMIT",
        "iterations": T + 1,
        "spatial_target_slots": sorted(seen_slots),
        "point_optimizer_calls": point_optimizer_calls,
        "trace": trace,
    }


def _reconstruct_schedule(
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
    selected = select_nested_candidate(raw_by_duration, 15)
    schedule = _validated_schedule(
        selected["schedule"],
        len(runtime.fleet),
        "selected balanced schedule",
    )
    return baseline, schedule, selected


def smoke(
    repo_root: Path,
    *,
    boundary_csv: Path,
) -> dict[str, Any]:
    boundary = _load_boundary(boundary_csv)
    config, frame = load_replication_design(repo_root)
    units = {
        str(row["work_unit_id"]): row
        for row in _records(frame)
    }
    cases: list[dict[str, Any]] = []

    for evaluation_id in SMOKE_IDS:
        archived = boundary[evaluation_id]
        work_unit_id = str(archived["work_unit_id"])
        if work_unit_id not in units:
            raise KeyError(work_unit_id)
        unit = units[work_unit_id]

        runtime = _create_real_pilot_runtime(repo_root, unit, config)
        baseline, original, _selected = _reconstruct_schedule(
            runtime,
            config,
            unit,
        )
        observed_hash = canonical_schedule_sha256(
            runtime.fleet,
            original,
        )
        expected_hash = str(archived["schedule_sha256"])
        if observed_hash != expected_hash:
            raise AssertionError(
                f"{evaluation_id}: schedule hash differs"
            )

        truth_cache = runtime.create_corrected_truth_cache()
        baseline_raw = runtime.audit_corrected(
            baseline,
            truth_cache,
            baseline_slot_results=None,
            stop_on_violation=False,
            retain_slot_results=True,
        )
        if not (
            baseline_raw.get("feasible") is True
            and int(baseline_raw.get("checked_intervals", 0)) == T
        ):
            raise AssertionError(
                f"{evaluation_id}: baseline not feasible"
            )
        baseline_slots = baseline_raw.get("slot_results")

        alpha_fixed = float(archived["alpha_transfer"])
        probe_alpha = float(archived["probe_alpha"])

        fixed_schedule = (
            baseline + alpha_fixed * (original - baseline)
        )
        fixed_audit = _audit(
            runtime,
            fixed_schedule,
            truth_cache,
            baseline_slots,
            full=True,
        )
        if not (
            fixed_audit.get("feasible") is True
            and int(fixed_audit.get("checked_intervals", 0)) == T
        ):
            raise AssertionError(
                f"{evaluation_id}: alpha_fixed did not reproduce as feasible"
            )

        probe_schedule = (
            baseline + probe_alpha * (original - baseline)
        )
        probe_audit = _audit(
            runtime,
            probe_schedule,
            truth_cache,
            baseline_slots,
            full=False,
        )
        observed_probe_slot, probe_witnesses = (
            _first_physical_failure(probe_audit)
        )
        expected_probe_slot = int(
            archived["observed_first_failure_slot"]
        )
        if (
            probe_audit.get("feasible") is True
            or observed_probe_slot != expected_probe_slot
        ):
            raise AssertionError(
                f"{evaluation_id}: archived failing probe did not reproduce"
            )

        repair = _repair_at_alpha(
            runtime,
            baseline,
            original,
            alpha=probe_alpha,
            truth_cache=truth_cache,
            baseline_slots=baseline_slots,
        )
        if repair["status"] == "NUMERICAL_INVALID":
            raise AssertionError(
                f"{evaluation_id}: repair generated numerical invalidity"
            )
        # Every failing probe must actually exercise the preregistered
        # point-optimizer branch at least once.
        if int(repair["point_optimizer_calls"]) < 1:
            raise AssertionError(
                f"{evaluation_id}: point optimizer was not exercised"
            )
        if repair["verified_feasible"]:
            if float(
                repair.get("aggregate_error_kw", math.inf)
            ) > 1e-6:
                raise AssertionError(
                    f"{evaluation_id}: aggregate commitment changed"
                )
            inv = repair["invariants"]
            if (
                float(inv["max_ev_invariant_error"]) > 1e-6
                or int(inv["simultaneous_slots"]) != 0
            ):
                raise AssertionError(
                    f"{evaluation_id}: EV invariants failed"
                )

        cases.append(
            {
                "evaluation_id": evaluation_id,
                "feeder": str(archived["feeder"]),
                "direction": str(archived["direction"]),
                "constraint_classes": str(
                    archived["constraint_classes"]
                ),
                "alpha_fixed": alpha_fixed,
                "probe_alpha": probe_alpha,
                "probe_failure_slot": observed_probe_slot,
                "probe_witnesses": probe_witnesses,
                "repair_status_at_probe": repair["status"],
                "repair_verified_at_probe": bool(
                    repair["verified_feasible"]
                ),
                "repair_iterations": int(
                    repair["iterations"]
                ),
                "spatial_target_slots": list(
                    repair["spatial_target_slots"]
                ),
                "point_optimizer_calls": int(
                    repair["point_optimizer_calls"]
                ),
                "schedule_sha256": observed_hash,
            }
        )
        print(
            f"{evaluation_id}: fixed={alpha_fixed:.3f} "
            f"probe={probe_alpha:.3f} "
            f"repair={repair['status']} "
            f"point_calls={repair['point_optimizer_calls']}",
            flush=True,
        )

    return {
        "analysis": (
            "V2.5C-R3 preregistration-consistent "
            "spatial-repair implementation smoke"
        ),
        "role": (
            "implementation validation only; "
            "not manuscript evidence"
        ),
        "method_identity": (
            "point optimizer -> nonlinear-feasible spatial target -> "
            "fixed bus-phase equality in feeder-trajectory-preserving "
            "trajectory LP"
        ),
        "smoke_case_n": len(cases),
        "all_schedule_hashes_reproduced": True,
        "all_archived_fixed_boundaries_reproduced": True,
        "all_point_optimizer_branches_exercised": all(
            case["point_optimizer_calls"] >= 1
            for case in cases
        ),
        "numerical_invalid_n": sum(
            case["repair_status_at_probe"] == "NUMERICAL_INVALID"
            for case in cases
        ),
        "verified_probe_repairs_n": sum(
            case["repair_verified_at_probe"]
            for case in cases
        ),
        "cases": cases,
        "claim_boundary": (
            "Smoke outcomes are implementation evidence only. "
            "They are not used to select R3 cases, tune thresholds, "
            "or support manuscript efficacy claims."
        ),
    }


def _write_markdown(
    result: Mapping[str, Any],
    path: Path,
) -> None:
    lines = [
        "# V2.5C-R3 preregistration-consistent spatial-repair smoke",
        "",
        f"- Cases: **{result['smoke_case_n']}**",
        "- Exact balanced-schedule hashes reproduced: **yes**",
        "- Archived fixed/probe boundary behavior reproduced: **yes**",
        "- Preregistered point-optimizer branch exercised in every case: **yes**",
        f"- Numerical-invalid repair paths: **{result['numerical_invalid_n']}**",
        (
            "- Probe points repaired and nonlinearly verified: "
            f"**{result['verified_probe_repairs_n']}**"
        ),
        "",
        (
            "> Smoke outcomes are implementation evidence only "
            "and are not manuscript results."
        ),
        "",
        "## Method identity",
        "",
        result["method_identity"],
        "",
        "## Cases",
        "",
        (
            "| case | feeder | dir | boundary | alpha_fixed | "
            "probe | repair status | point calls |"
        ),
        "|---|---|---|---|---:|---:|---|---:|",
    ]
    for row in result["cases"]:
        lines.append(
            f"| `{row['evaluation_id']}` | {row['feeder']} | "
            f"{row['direction']} | {row['constraint_classes']} | "
            f"{row['alpha_fixed']:.3f} | {row['probe_alpha']:.3f} | "
            f"{row['repair_status_at_probe']} | "
            f"{row['point_optimizer_calls']} |"
        )
    path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--boundary-csv", required=True)
    parser.add_argument(
        "--output-json",
        default="reports/v2_5c_r3_smoke.json",
    )
    parser.add_argument(
        "--output-md",
        default="reports/v2_5c_r3_smoke.md",
    )
    args = parser.parse_args()

    root = Path(args.repo_root).resolve(strict=True)
    result = smoke(
        root,
        boundary_csv=Path(args.boundary_csv).resolve(strict=True),
    )
    output_json = root / args.output_json
    output_md = root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_markdown(result, output_md)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output_json": str(
                    output_json.relative_to(root)
                ),
                "output_md": str(
                    output_md.relative_to(root)
                ),
                "verified_probe_repairs_n": result[
                    "verified_probe_repairs_n"
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
