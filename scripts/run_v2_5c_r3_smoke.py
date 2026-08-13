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


def _pairs(fleet: Sequence[Any]) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    pairs = [
        (i, t)
        for i, ev in enumerate(fleet)
        for t in range(int(ev.arrival), int(ev.departure))
    ]
    return pairs, {pair: index for index, pair in enumerate(pairs)}


def _build_repair_lp(
    fleet: Sequence[Any],
    fixed_ray: np.ndarray,
    *,
    mode: str,
    linearizations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a feeder-trajectory-preserving EV LP with frozen linearized 3ph cuts.

    The LP keeps the exact 96-slot feeder aggregate trajectory of ``fixed_ray``.
    Spatial/vehicle allocation is free subject to the original EV trajectory
    constraints. Network cuts are only a proposal mechanism; final truth is
    always a nonlinear OpenDSS audit.
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

    # Vehicle energy, reserve/capacity and V2G budget constraints.
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

    # Absolute deviation from the fixed ray; this only selects a deterministic
    # nearby realization and does not relax the aggregate commitment.
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

    # Successive linearized 3ph cuts. Each stored cut set comes from one
    # nonlinear-evaluated failing slot.
    for cut in linearizations:
        slot = int(cut["slot"])
        groups = list(cut["groups"])
        sensitivity = np.asarray(cut["sensitivity"], dtype=float)
        m0 = np.asarray(cut["m0_vector"], dtype=float)
        p0 = np.asarray(cut["p0"], dtype=float)
        lower = np.asarray(cut["lower"], dtype=float)
        upper = np.asarray(cut["upper"], dtype=float)
        if sensitivity.shape != (len(m0), len(groups)):
            raise ValueError("network sensitivity dimensions differ")
        if not np.isfinite(sensitivity).all() or not np.isfinite(m0).all():
            raise ValueError("network linearization contains non-finite values")

        group_evs: list[list[int]] = []
        for group in groups:
            if not (
                isinstance(group, (tuple, list))
                and len(group) == 2
            ):
                raise ValueError("R3 requires three-phase (bus, phase) groups")
            bus, phase = str(group[0]), int(group[1])
            group_evs.append(
                [
                    i for i, ev in enumerate(fleet)
                    if str(ev.bus) == bus and int(ev.phase) == phase
                ]
            )

        sp0 = sensitivity @ p0
        for metric in range(len(m0)):
            srow = sensitivity[metric]
            if math.isfinite(float(upper[metric])):
                row: dict[int, float] = {}
                for g, evs in enumerate(group_evs):
                    coeff = float(srow[g])
                    if abs(coeff) <= 1e-15:
                        continue
                    for i in evs:
                        j = pmap.get((i, slot))
                        if j is None:
                            continue
                        row[j] = row.get(j, 0.0) + coeff
                        row[n + j] = row.get(n + j, 0.0) - coeff
                ub_rows.append(row)
                ub_rhs.append(float(upper[metric] - m0[metric] + sp0[metric]))
            if math.isfinite(float(lower[metric])):
                row = {}
                for g, evs in enumerate(group_evs):
                    coeff = -float(srow[g])
                    if abs(coeff) <= 1e-15:
                        continue
                    for i in evs:
                        j = pmap.get((i, slot))
                        if j is None:
                            continue
                        row[j] = row.get(j, 0.0) + coeff
                        row[n + j] = row.get(n + j, 0.0) - coeff
                ub_rows.append(row)
                ub_rhs.append(float(m0[metric] - lower[metric] - sp0[metric]))

    def sparse(rows: Sequence[Mapping[int, float]]) -> csr_matrix:
        rr: list[int] = []
        cc: list[int] = []
        vv: list[float] = []
        for r, row in enumerate(rows):
            for c, value in row.items():
                if abs(float(value)) <= 1e-18:
                    continue
                rr.append(r)
                cc.append(int(c))
                vv.append(float(value))
        return coo_matrix((vv, (rr, cc)), shape=(len(rows), nvar)).tocsr()

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
    linearizations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    lp = _build_repair_lp(
        fleet,
        fixed_ray,
        mode=mode,
        linearizations=linearizations,
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
            np.abs(schedule.sum(axis=0) - np.asarray(lp["feeder_target"])),
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


def _first_physical_failure(raw: Mapping[str, Any]) -> tuple[int | None, list[Any]]:
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
        physical.append((slot, list(witness) if isinstance(witness, list) else []))
    if not physical:
        return None, []
    slot = min(value[0] for value in physical)
    witnesses: list[Any] = []
    for observed_slot, observed in physical:
        if observed_slot == slot:
            witnesses.extend(observed)
    return slot, witnesses


def _make_linearization(
    runtime: Any,
    truth_cache: Any,
    schedule: np.ndarray,
    slot: int,
) -> dict[str, Any]:
    scale = float(runtime.load_scales[slot])
    if scale not in truth_cache:
        raise KeyError(f"truth cache has no network for load scale {scale}")
    network = truth_cache[scale]
    groups = list(network.groups)
    p0 = np.asarray(
        runtime.archived_engine.group_vector(
            runtime.fleet,
            schedule[:, slot],
            groups,
            "3ph",
        ),
        dtype=float,
    )
    linear = network.sensitivity(p0)
    if not (
        isinstance(linear, tuple)
        and len(linear) == 2
        and isinstance(linear[0], Mapping)
    ):
        raise TypeError("network.sensitivity must return (evaluation, matrix)")
    m0, sensitivity = linear
    vector = np.asarray(m0["vector"], dtype=float)
    sensitivity = np.asarray(sensitivity, dtype=float)
    lower, upper = network.bounds()
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if vector.shape != lower.shape or vector.shape != upper.shape:
        raise ValueError("network metric/bound dimensions differ")
    if sensitivity.shape != (len(vector), len(groups)):
        raise ValueError("network sensitivity shape differs")
    return {
        "slot": int(slot),
        "groups": [
            [str(group[0]), int(group[1])]
            for group in groups
        ],
        "p0": p0.tolist(),
        "m0_vector": vector.tolist(),
        "sensitivity": sensitivity.tolist(),
        "lower": lower.tolist(),
        "upper": upper.tolist(),
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
    linearizations: list[dict[str, Any]] = []
    seen_slots: set[int] = set()
    trace: list[dict[str, Any]] = []

    for iteration in range(T + 1):
        solved = _solve_repair_lp(
            runtime.fleet,
            fixed_ray,
            mode=mode,
            linearizations=linearizations,
        )
        if not solved["success"]:
            return {
                "verified_feasible": False,
                "status": solved["status"],
                "iterations": iteration,
                "linearized_slots": sorted(seen_slots),
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
                "linearized_slots": sorted(seen_slots),
                "trace": trace,
            }
        if raw.get("feasible") is True and int(raw.get("checked_intervals", 0)) == T:
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
                "status": "VERIFIED_FEASIBLE" if verified else "FULL_AUDIT_FAILED",
                "iterations": iteration,
                "linearized_slots": sorted(seen_slots),
                "aggregate_error_kw": solved["aggregate_error_kw"],
                "invariants": solved["invariants"],
                "trace": trace,
            }

        slot, witnesses = _first_physical_failure(raw)
        trace.append(
            {
                "iteration": iteration,
                "first_failure_slot": slot,
                "witnesses": witnesses,
                "aggregate_error_kw": solved["aggregate_error_kw"],
            }
        )
        if slot is None:
            return {
                "verified_feasible": False,
                "status": "UNCLASSIFIED_INVALID",
                "iterations": iteration,
                "linearized_slots": sorted(seen_slots),
                "trace": trace,
            }
        if slot in seen_slots:
            return {
                "verified_feasible": False,
                "status": "SAME_SLOT_LINEARIZATION_EXHAUSTED",
                "iterations": iteration,
                "linearized_slots": sorted(seen_slots),
                "trace": trace,
            }
        linearizations.append(
            _make_linearization(runtime, truth_cache, schedule, slot)
        )
        seen_slots.add(slot)

    return {
        "verified_feasible": False,
        "status": "ITERATION_LIMIT",
        "iterations": T + 1,
        "linearized_slots": sorted(seen_slots),
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
        observed_hash = canonical_schedule_sha256(runtime.fleet, original)
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
            raise AssertionError(f"{evaluation_id}: baseline not feasible")
        baseline_slots = baseline_raw.get("slot_results")

        alpha_fixed = float(archived["alpha_transfer"])
        probe_alpha = float(archived["probe_alpha"])
        fixed_schedule = baseline + alpha_fixed * (original - baseline)
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
                f"{evaluation_id}: archived alpha_fixed did not reproduce as feasible"
            )

        probe_schedule = baseline + probe_alpha * (original - baseline)
        probe_audit = _audit(
            runtime,
            probe_schedule,
            truth_cache,
            baseline_slots,
            full=False,
        )
        observed_probe_slot, probe_witnesses = _first_physical_failure(probe_audit)
        expected_probe_slot = int(archived["observed_first_failure_slot"])
        if probe_audit.get("feasible") is True or observed_probe_slot != expected_probe_slot:
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
            raise AssertionError(f"{evaluation_id}: repair generated numerical invalidity")
        if repair["verified_feasible"]:
            if float(repair.get("aggregate_error_kw", math.inf)) > 1e-6:
                raise AssertionError(f"{evaluation_id}: aggregate commitment changed")
            inv = repair["invariants"]
            if (
                float(inv["max_ev_invariant_error"]) > 1e-6
                or int(inv["simultaneous_slots"]) != 0
            ):
                raise AssertionError(f"{evaluation_id}: EV invariants failed")

        cases.append(
            {
                "evaluation_id": evaluation_id,
                "feeder": str(archived["feeder"]),
                "direction": str(archived["direction"]),
                "constraint_classes": str(archived["constraint_classes"]),
                "alpha_fixed": alpha_fixed,
                "probe_alpha": probe_alpha,
                "probe_failure_slot": observed_probe_slot,
                "probe_witnesses": probe_witnesses,
                "repair_status_at_probe": repair["status"],
                "repair_verified_at_probe": bool(repair["verified_feasible"]),
                "repair_iterations": int(repair["iterations"]),
                "linearized_slots": list(repair["linearized_slots"]),
                "schedule_sha256": observed_hash,
            }
        )
        print(
            f"{evaluation_id}: fixed={alpha_fixed:.3f} "
            f"probe={probe_alpha:.3f} repair={repair['status']}",
            flush=True,
        )

    return {
        "analysis": "V2.5C-R3 spatial-repair implementation smoke",
        "role": "implementation validation only; not manuscript evidence",
        "scientific_input_commit": config.get("_config_sha256"),
        "smoke_case_n": len(cases),
        "all_schedule_hashes_reproduced": True,
        "all_archived_fixed_boundaries_reproduced": True,
        "numerical_invalid_n": sum(
            case["repair_status_at_probe"] == "NUMERICAL_INVALID"
            for case in cases
        ),
        "verified_probe_repairs_n": sum(
            case["repair_verified_at_probe"] for case in cases
        ),
        "cases": cases,
        "claim_boundary": (
            "Smoke outcomes are used only to validate code paths, invariants, "
            "aggregate-commitment preservation, and nonlinear audit integration. "
            "They are not used to select R3 cases or tune scientific thresholds."
        ),
    }


def _write_markdown(result: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# V2.5C-R3 spatial-repair smoke",
        "",
        f"- Cases: **{result['smoke_case_n']}**",
        "- Exact balanced-schedule hashes reproduced: **yes**",
        "- Archived fixed/probe boundary behavior reproduced: **yes**",
        f"- Numerical-invalid repair paths: **{result['numerical_invalid_n']}**",
        f"- Probe points repaired and nonlinearly verified: **{result['verified_probe_repairs_n']}**",
        "",
        "> Smoke outcomes are implementation evidence only and are not manuscript results.",
        "",
        "## Cases",
        "",
        "| case | feeder | dir | boundary | alpha_fixed | probe | repair status |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for row in result["cases"]:
        lines.append(
            f"| `{row['evaluation_id']}` | {row['feeder']} | {row['direction']} | "
            f"{row['constraint_classes']} | {row['alpha_fixed']:.3f} | "
            f"{row['probe_alpha']:.3f} | {row['repair_status_at_probe']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--boundary-csv",
        required=True,
    )
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
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_markdown(result, output_md)
    print(json.dumps({
        "status": "PASS",
        "output_json": str(output_json.relative_to(root)),
        "output_md": str(output_md.relative_to(root)),
        "verified_probe_repairs_n": result["verified_probe_repairs_n"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
