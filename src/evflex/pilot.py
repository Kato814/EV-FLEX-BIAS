from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Mapping, Sequence
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from numbers import Number
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, csr_matrix, hstack, issparse, vstack


_DURATION_SUFFIX = re.compile(r"__(\d+)m$")
_PILOT_ADAPTER_SCHEMA = "evflex.pilot.network-audit"
_PILOT_ADAPTER_VERSION = 2
_REQUIRED_COLUMNS = (
    "work_unit_id",
    "protocol_version",
    "scenario_id",
    "feeder",
    "call_time",
    "direction",
    "scenario_seed",
    "data_role",
    "evaluation_ids",
    "holdout_access",
    "status",
)


def load_pilot_config(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    path = root / "config" / "pilot_gate_v2_1.json"
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    source_path = root / config["source_manifest"]
    source = pd.read_csv(source_path)
    scenario_ids = tuple(config["scenario_ids"])
    directions = set(config["directions"])
    source = source[source["scenario_id"].isin(scenario_ids)].copy()
    if len(source) != len(scenario_ids) * len(directions):
        _fail("V2 source manifest does not contain the frozen pilot rows")
    if set(source["scenario_id"]) != set(scenario_ids):
        _fail("V2 source manifest scenario set differs from the pilot config")
    if set(source["protocol_version"]) != {config["source_protocol_version"]}:
        _fail("V2 source manifest protocol version differs from the pilot config")

    source_design: dict[str, dict[str, object]] = {}
    source_rows: dict[tuple[str, str], dict[str, object]] = {}
    for scenario_id, group in source.groupby("scenario_id", sort=False):
        if set(group["direction"]) != directions:
            _fail(f"V2 source scenario {scenario_id} does not have paired directions")
        for column in ("feeder", "call_time", "scenario_seed"):
            if group[column].nunique(dropna=False) != 1:
                _fail(f"V2 source scenario {scenario_id} varies in {column}")
        first = group.iloc[0]
        source_design[scenario_id] = {
            "feeder": first["feeder"],
            "call_time": first["call_time"],
            "scenario_seed": _strict_int(
                first["scenario_seed"], f"V2 source scenario {scenario_id} seed"
            ),
        }
        for row in group.itertuples(index=False):
            key = (row.scenario_id, row.direction)
            if key in source_rows:
                _fail(f"V2 source manifest duplicates row {key}")
            try:
                evaluation_ids = _evaluation_ids(row.evaluation_ids)
            except (json.JSONDecodeError, TypeError) as exc:
                _fail(f"invalid V2 source evaluation_ids for {key}: {exc}")
            source_rows[key] = {
                "work_unit_id": row.work_unit_id,
                "scenario_id": row.scenario_id,
                "feeder": row.feeder,
                "call_time": row.call_time,
                "direction": row.direction,
                "scenario_seed": _strict_int(
                    row.scenario_seed, f"V2 source row {key} seed"
                ),
                "evaluation_ids": evaluation_ids,
            }

    if source_design != config["scenario_design"]:
        _fail("pilot config scenario design differs from the V2 source manifest")
    config["_source_scenario_design"] = source_design
    config["_source_rows"] = source_rows
    return config


def _evaluation_ids(value: object) -> list[str]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise TypeError("evaluation_ids must decode to a list")
    return [str(item) for item in parsed]


def _fail(detail: str) -> None:
    raise ValueError(f"pilot design: {detail}")


def _strict_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, Number)):
        _fail(f"{label} must be a finite, lossless integer")
    try:
        text = value.strip() if isinstance(value, str) else str(value)
        parsed = Decimal(text)
        if not parsed.is_finite() or parsed != parsed.to_integral_value():
            raise ValueError("value is non-finite or fractional")
        return int(parsed)
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        _fail(f"{label} must be a finite, lossless integer: {exc}")


def evaluate_alpha_path(
    audit: Any,
    *,
    coarse_step: float = 0.02,
    refine_tolerance: float = 0.002,
) -> dict[str, Any]:
    step = Decimal(str(coarse_step))
    tolerance = Decimal(str(refine_tolerance))
    if not step.is_finite() or step <= 0 or step > 1:
        raise ValueError("coarse_step must be finite and in (0, 1]")
    if not tolerance.is_finite() or tolerance <= 0:
        raise ValueError("refine_tolerance must be finite and positive")

    coarse_alphas: list[Decimal] = []
    alpha = Decimal(0)
    while alpha < 1:
        coarse_alphas.append(alpha)
        alpha += step
    if not coarse_alphas or coarse_alphas[-1] != 1:
        coarse_alphas.append(Decimal(1))

    audit_calls = 0

    def run(candidate: float) -> bool:
        nonlocal audit_calls
        result = audit(candidate)
        audit_calls += 1
        if isinstance(result, Mapping):
            if "feasible" not in result:
                raise ValueError("audit result dictionary must contain feasible")
            result = result["feasible"]
        if not isinstance(result, (bool, np.bool_)):
            raise TypeError("audit feasibility must be boolean")
        return bool(result)

    coarse_results = []
    for candidate in coarse_alphas:
        value = float(candidate)
        coarse_results.append({"alpha": value, "feasible": run(value)})

    valid_baseline = bool(coarse_results[0]["feasible"])
    refinement_results: list[dict[str, Any]] = []

    if not valid_baseline:
        alpha_prefix = None
        prefix_resolution = None
    else:
        first_failure = next(
            (
                index
                for index, item in enumerate(coarse_results)
                if not item["feasible"]
            ),
            None,
        )
        if first_failure is None:
            alpha_prefix = 1.0
            prefix_resolution = 0.0
        else:
            lower = Decimal(str(coarse_results[first_failure - 1]["alpha"]))
            upper = Decimal(str(coarse_results[first_failure]["alpha"]))
            segments = int(
                ((upper - lower) / tolerance).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
            increment = (upper - lower) / max(segments, 1)
            for index in range(1, segments):
                candidate = lower + increment * index
                candidate_float = float(candidate)
                feasible = run(candidate_float)
                refinement_results.append(
                    {"alpha": candidate_float, "feasible": feasible}
                )
            boundary_results = [
                coarse_results[first_failure - 1],
                *refinement_results,
                coarse_results[first_failure],
            ]
            boundary_failure = next(
                index
                for index, item in enumerate(boundary_results)
                if not item["feasible"]
            )
            alpha_prefix = boundary_results[boundary_failure - 1]["alpha"]
            prefix_resolution = float(increment)

    ordered_results = sorted(
        [*coarse_results, *refinement_results], key=lambda item: item["alpha"]
    )
    alpha_sup = max(
        (
            item["alpha"]
            for item in ordered_results
            if item["feasible"]
        ),
        default=None,
    )
    failure_seen = False
    nonmonotone = False
    for item in ordered_results:
        if not item["feasible"]:
            failure_seen = True
        elif failure_seen:
            nonmonotone = True
            break

    return {
        "valid_baseline": valid_baseline,
        "alpha_prefix": alpha_prefix,
        "scientific_alpha": alpha_prefix,
        "alpha_sup": alpha_sup,
        "nonmonotone": nonmonotone,
        "coarse_results": coarse_results,
        "refinement_results": refinement_results,
        "audit_calls": audit_calls,
        "prefix_resolution": prefix_resolution,
    }


def canonical_schedule_sha256(fleet: Sequence[Any], schedule: Any) -> str:
    """Hash a fleet-aligned schedule without rounding floating-point values."""
    order, identity_tokens = _canonical_fleet_order(fleet)
    values = _validated_schedule(schedule, len(fleet), "schedule")[order]
    return _hash_labeled_float64_matrix(
        "evflex.pilot.vehicle-schedule.v1",
        identity_tokens,
        values,
    )


def phase_balanced_tie_break(
    engine: Any,
    fleet: Sequence[Any],
    baseline: Any,
    original_schedule: Any,
    *,
    direction: str | None = None,
    mode: str | None = None,
    call_slots: Sequence[int] | None = None,
    offer_kw: float | None = None,
) -> dict[str, Any]:
    """Lexicographically rebalance phase deltas without changing bus schedules."""
    if not callable(getattr(engine, "build_trajectory_lp", None)):
        raise TypeError("engine must provide archived build_trajectory_lp")
    if mode is None:
        if direction == "inc":
            mode = "v1g"
        elif direction == "dec":
            mode = "v2g"
        elif direction is None:
            raise ValueError("direction or mode is required")
        else:
            raise ValueError("direction must be 'inc' or 'dec'")
    if mode not in {"v1g", "v2g"}:
        raise ValueError("mode must be 'v1g' or 'v2g'")
    if direction is None:
        direction = "inc" if mode == "v1g" else "dec"
    if direction is not None and direction not in {"inc", "dec"}:
        raise ValueError("direction must be 'inc' or 'dec'")
    expected_mode = {"inc": "v1g", "dec": "v2g"}.get(direction)
    if expected_mode is not None and mode != expected_mode:
        raise ValueError(
            f"direction/mode conflict: {direction!r} requires {expected_mode!r}"
        )

    order, identity_tokens = _canonical_fleet_order(fleet)
    sorted_fleet = [fleet[int(index)] for index in order]
    base_input = _validated_schedule(baseline, len(fleet), "baseline")
    original_input = _validated_schedule(
        original_schedule, len(fleet), "original_schedule"
    )
    sorted_base = base_input[order]
    sorted_original = original_input[order]
    buses = sorted({str(ev.bus) for ev in sorted_fleet})
    groups = list(buses)
    original_bus_time = _bus_time_schedule(sorted_fleet, sorted_original, buses)
    targets = {
        slot: original_bus_time[:, slot].copy() for slot in range(96)
    }

    original_schedule_hash = canonical_schedule_sha256(fleet, original_input)
    vehicle_hash = _vehicle_identity_sha256(sorted_fleet, identity_tokens)
    original_phase_matrix, phase_labels = _bus_phase_time_schedule(
        sorted_fleet, sorted_original
    )
    original_phase_hash = _hash_labeled_float64_matrix(
        "evflex.pilot.bus-phase-time.v1",
        phase_labels,
        original_phase_matrix,
    )
    original_phase_objective = _phase_delta_l1(
        sorted_fleet, sorted_original, sorted_base
    )
    common = {
        "success": False,
        "comparator_valid": False,
        "schedule": None,
        "charge": None,
        "discharge": None,
        "mode": mode,
        "direction": direction,
        "vehicle_identity_sha256": vehicle_hash,
        "original_schedule_sha256": original_schedule_hash,
        "tied_schedule_sha256": None,
        "original_bus_phase_time_sha256": original_phase_hash,
        "tied_bus_phase_time_sha256": None,
        "bus_phase_time_sha256": None,
        "original_phase_imbalance_objective": original_phase_objective,
        "original_bus_time_schedule": original_bus_time,
        "bus_time_schedule": None,
        "max_bus_time_error_kw": None,
        "bus_labels": buses,
        "declared_offer_kw": None,
        "declared_offer_absolute_gap_kw": None,
        "declared_offer_relative_gap": None,
        "declared_offer_identity": None,
        "primary_objective_original_absolute_gap": None,
        "primary_objective_original_relative_gap": None,
        "primary_objective_tied_absolute_gap": None,
        "primary_objective_tied_relative_gap": None,
    }

    try:
        lp = engine.build_trajectory_lp(
            sorted_fleet,
            sorted_base,
            groups,
            targets,
            "balanced",
            mode,
            1.0,
        )
        _validate_archived_fixed_alpha_lp(lp)
    except Exception as exc:
        return {
            **common,
            "status": "LP_BUILD_FAILED",
            "message": f"{type(exc).__name__}: {exc}",
        }

    primary_result = linprog(
        np.asarray(lp["objective"], dtype=float),
        A_ub=csr_matrix(lp["A_ub"]),
        b_ub=np.asarray(lp["b_ub"], dtype=float),
        A_eq=csr_matrix(lp["A_eq"]),
        b_eq=np.asarray(lp["b_eq"], dtype=float),
        bounds=list(lp["bounds"]),
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-9,
            "dual_feasibility_tolerance": 1e-9,
        },
    )
    if not primary_result.success:
        return {
            **common,
            "status": "PRIMARY_INFEASIBLE",
            "message": str(primary_result.message),
        }

    primary_objective = float(primary_result.fun)
    primary_tolerance = 1e-6 * max(1.0, abs(primary_objective))
    stage_two = _build_phase_tie_lp(
        lp,
        sorted_fleet,
        sorted_base,
        buses,
        primary_objective + primary_tolerance,
    )
    tie_result = linprog(
        stage_two["objective"],
        A_ub=stage_two["A_ub"],
        b_ub=stage_two["b_ub"],
        A_eq=stage_two["A_eq"],
        b_eq=stage_two["b_eq"],
        bounds=stage_two["bounds"],
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-9,
            "dual_feasibility_tolerance": 1e-9,
        },
    )
    if not tie_result.success:
        return {
            **common,
            "status": "TIE_BREAK_INFEASIBLE",
            "message": str(tie_result.message),
            "primary_objective_optimum": primary_objective,
            "primary_objective_tolerance": primary_tolerance,
        }

    sorted_schedule, sorted_charge, sorted_discharge = _decode_lp_schedule(
        lp, sorted_fleet, tie_result.x
    )
    inverse = np.argsort(order)
    schedule = sorted_schedule[inverse]
    charge = sorted_charge[inverse]
    discharge = sorted_discharge[inverse]
    tied_bus_time = _bus_time_schedule(sorted_fleet, sorted_schedule, buses)
    max_bus_time_error = float(
        np.max(np.abs(tied_bus_time - original_bus_time), initial=0.0)
    )
    tied_primary = _trajectory_primary_objective(
        lp,
        sorted_base,
        sorted_schedule,
        sorted_charge,
        sorted_discharge,
    )
    primary_absolute_gap = abs(tied_primary - primary_objective)
    primary_relative_gap = (
        primary_absolute_gap / max(1.0, abs(primary_objective))
    )
    original_primary = _schedule_primary_objective(
        lp, sorted_base, sorted_original
    )
    original_primary_absolute_gap = abs(original_primary - primary_objective)
    original_primary_relative_gap = (
        original_primary_absolute_gap / max(1.0, abs(primary_objective))
    )
    tied_phase_objective = _phase_delta_l1(
        sorted_fleet, sorted_schedule, sorted_base
    )
    ev_invariants = _trajectory_invariants(
        sorted_fleet,
        sorted_schedule,
        sorted_charge,
        sorted_discharge,
        mode,
    )
    original_charge = np.maximum(sorted_original, 0.0)
    original_discharge = np.maximum(-sorted_original, 0.0)
    original_ev_invariants = _trajectory_invariants(
        sorted_fleet,
        sorted_original,
        original_charge,
        original_discharge,
        mode,
    )
    original_offer, tied_offer = _comparable_offers(
        sorted_base,
        sorted_original,
        sorted_schedule,
        direction=direction,
        call_slots=call_slots,
    )
    if offer_kw is None:
        declared_offer = None
        declared_offer_absolute_gap = None
        declared_offer_relative_gap = None
        declared_offer_identity = True
    else:
        declared_offer = float(offer_kw)
        if not math.isfinite(declared_offer) or declared_offer < 0:
            raise ValueError("offer_kw must be finite and nonnegative")
        declared_offer_absolute_gap = abs(declared_offer - original_offer)
        declared_offer_relative_gap = declared_offer_absolute_gap / max(
            1.0, abs(original_offer)
        )
        declared_offer_identity = bool(declared_offer_relative_gap <= 1e-6)
    offer_relative_difference = abs(tied_offer - original_offer) / max(
        abs(original_offer), 1e-12
    )
    offer_retention = (
        tied_offer / original_offer if abs(original_offer) > 1e-12 else 1.0
    )
    tied_schedule_hash = canonical_schedule_sha256(fleet, schedule)
    tied_phase_matrix, tied_phase_labels = _bus_phase_time_schedule(
        sorted_fleet, sorted_schedule
    )
    tied_phase_hash = _hash_labeled_float64_matrix(
        "evflex.pilot.bus-phase-time.v1",
        tied_phase_labels,
        tied_phase_matrix,
    )
    comparator_valid = bool(
        max_bus_time_error <= 1e-7
        and declared_offer_identity
        and original_primary_relative_gap <= 1e-6
        and primary_relative_gap <= 1e-6
        and offer_relative_difference <= 0.005
        and ev_invariants["max_ev_invariant_error"] <= 1e-6
        and ev_invariants["simultaneous_slots"] == 0
        and original_ev_invariants["max_ev_invariant_error"] <= 1e-6
        and original_ev_invariants["simultaneous_slots"] == 0
        and tied_phase_objective <= original_phase_objective + 1e-7
    )
    status = (
        "NO_OP"
        if comparator_valid and tied_schedule_hash == original_schedule_hash
        else "SUCCESS"
        if comparator_valid
        else "COMPARATOR_INVALID"
    )
    return {
        **common,
        "success": True,
        "comparator_valid": comparator_valid,
        "status": status,
        "message": str(tie_result.message),
        "schedule": schedule,
        "charge": charge,
        "discharge": discharge,
        "bus_time_schedule": tied_bus_time,
        "bus_phase_time_schedule": tied_phase_matrix,
        "tied_schedule_sha256": tied_schedule_hash,
        "tied_bus_phase_time_sha256": tied_phase_hash,
        "bus_phase_time_sha256": tied_phase_hash,
        "max_bus_time_error_kw": max_bus_time_error,
        "original_offer_kw": float(original_offer),
        "tied_offer_kw": float(tied_offer),
        "declared_offer_kw": declared_offer,
        "declared_offer_absolute_gap_kw": declared_offer_absolute_gap,
        "declared_offer_relative_gap": declared_offer_relative_gap,
        "declared_offer_identity": declared_offer_identity,
        "offer_relative_difference": float(offer_relative_difference),
        "offer_retention": float(offer_retention),
        "primary_objective_original": float(original_primary),
        "primary_objective_optimum": primary_objective,
        "primary_objective_tied": tied_primary,
        "primary_objective_tolerance": primary_tolerance,
        "primary_objective_original_absolute_gap": float(
            original_primary_absolute_gap
        ),
        "primary_objective_original_relative_gap": float(
            original_primary_relative_gap
        ),
        "primary_objective_tied_absolute_gap": float(primary_absolute_gap),
        "primary_objective_tied_relative_gap": float(primary_relative_gap),
        "primary_objective_relative_gap": float(primary_relative_gap),
        "phase_imbalance_objective": float(tied_phase_objective),
        "phase_imbalance_improvement": float(
            original_phase_objective - tied_phase_objective
        ),
        "original_ev_invariants": original_ev_invariants,
        **ev_invariants,
    }


def _canonical_fleet_order(
    fleet: Sequence[Any],
) -> tuple[np.ndarray, list[str]]:
    if not isinstance(fleet, Sequence) or isinstance(fleet, (str, bytes)):
        raise TypeError("fleet must be a sequence")
    if not fleet:
        raise ValueError("fleet must not be empty")
    tokens: list[str] = []
    for ev in fleet:
        if not hasattr(ev, "ev_id"):
            raise ValueError("every vehicle must have an ev_id")
        value = ev.ev_id
        if isinstance(value, (bool, np.bool_)):
            raise ValueError("ev_id values must not be boolean")
        if isinstance(value, (Number, Decimal)):
            try:
                parsed = Decimal(str(value))
            except (InvalidOperation, ValueError):
                parsed = Decimal("NaN")
            if not parsed.is_finite() or parsed != parsed.to_integral_value():
                raise ValueError("numeric ev_id values must be finite integers")
            token = f"number:{int(parsed)}"
        elif isinstance(value, str) and value:
            token = f"string:{value}"
        else:
            raise ValueError("ev_id values must be non-empty strings or integers")
        tokens.append(token)
    if len(tokens) != len(set(tokens)):
        raise ValueError("ev_id values must be unique")
    order = np.asarray(
        sorted(range(len(tokens)), key=lambda index: tokens[index]),
        dtype=int,
    )
    return order, [tokens[int(index)] for index in order]


def _validated_schedule(value: Any, rows: int, label: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape != (rows, 96):
        raise ValueError(f"{label} must have shape ({rows}, 96)")
    if not np.isfinite(array).all():
        raise ValueError(f"{label} must contain only finite values")
    return array.copy()


def _normalized_little_endian_float64(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64).copy(order="C")
    array[array == 0.0] = 0.0
    return np.ascontiguousarray(array, dtype="<f8")


def _hash_labeled_float64_matrix(
    domain: str,
    labels: Sequence[Any],
    values: Any,
) -> str:
    array = _normalized_little_endian_float64(values)
    label_bytes = json.dumps(
        list(labels),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    shape_bytes = json.dumps(list(array.shape), separators=(",", ":")).encode(
        "ascii"
    )
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\0")
    digest.update(shape_bytes)
    digest.update(b"\0")
    digest.update(label_bytes)
    digest.update(b"\0")
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _vehicle_identity_sha256(
    sorted_fleet: Sequence[Any], identity_tokens: Sequence[str]
) -> str:
    fields = (
        "capacity",
        "initial",
        "target",
        "reserve",
        "arrival",
        "departure",
        "pch",
        "pdis",
        "eta_c",
        "eta_d",
        "v2g",
        "max_discharge",
        "bus",
        "phase",
        "kv_ln",
    )
    records = []
    for token, ev in zip(identity_tokens, sorted_fleet, strict=True):
        record: dict[str, Any] = {"ev_id": token}
        for field in fields:
            if not hasattr(ev, field):
                raise ValueError(f"vehicle {ev.ev_id} is missing {field}")
            value = getattr(ev, field)
            if isinstance(value, (bool, np.bool_)):
                record[field] = bool(value)
            elif isinstance(value, Number):
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError(
                        f"vehicle {ev.ev_id} has non-finite {field}"
                    )
                if number == 0.0:
                    number = 0.0
                record[field] = number.hex()
            else:
                record[field] = str(value)
        records.append(record)
    payload = json.dumps(
        records,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(b"evflex.pilot.vehicle-identity.v1\0" + payload).hexdigest()


def _bus_time_schedule(
    fleet: Sequence[Any], schedule: np.ndarray, buses: Sequence[str] | None = None
) -> np.ndarray:
    bus_order = (
        list(buses)
        if buses is not None
        else sorted({str(ev.bus) for ev in fleet})
    )
    index = {bus: position for position, bus in enumerate(bus_order)}
    aggregate = np.zeros((len(bus_order), 96), dtype=float)
    for row, ev in enumerate(fleet):
        aggregate[index[str(ev.bus)]] += schedule[row]
    return aggregate


def _bus_phase_time_schedule(
    fleet: Sequence[Any], schedule: np.ndarray
) -> tuple[np.ndarray, list[str]]:
    buses = sorted({str(ev.bus) for ev in fleet})
    labels = [f"{bus}|{phase}" for bus in buses for phase in (1, 2, 3)]
    index = {
        (bus, phase): position
        for position, (bus, phase) in enumerate(
            (pair for bus in buses for pair in ((bus, 1), (bus, 2), (bus, 3)))
        )
    }
    aggregate = np.zeros((len(labels), 96), dtype=float)
    for row, ev in enumerate(fleet):
        phase = int(ev.phase)
        if phase not in {1, 2, 3}:
            raise ValueError("vehicle phases must be 1, 2, or 3")
        aggregate[index[(str(ev.bus), phase)]] += schedule[row]
    return aggregate, labels


def _phase_delta_l1(
    fleet: Sequence[Any], schedule: np.ndarray, baseline: np.ndarray
) -> float:
    delta, _ = _bus_phase_time_schedule(fleet, schedule - baseline)
    objective = 0.0
    for offset in range(0, delta.shape[0], 3):
        phase = delta[offset : offset + 3]
        objective += float(np.abs(phase[0] - phase[1]).sum())
        objective += float(np.abs(phase[0] - phase[2]).sum())
        objective += float(np.abs(phase[1] - phase[2]).sum())
    return objective


def _validate_archived_fixed_alpha_lp(lp: Any) -> None:
    required = {
        "objective",
        "bounds",
        "A_ub",
        "b_ub",
        "A_eq",
        "b_eq",
        "pairs",
        "n",
    }
    if not isinstance(lp, Mapping) or not required.issubset(lp):
        raise ValueError("archived fixed-alpha LP is incomplete")
    n = int(lp["n"])
    if n < 0 or len(lp["pairs"]) != n:
        raise ValueError("archived LP pair map is inconsistent")
    if len(lp["objective"]) != 3 * n or len(lp["bounds"]) != 3 * n:
        raise ValueError("archived LP is not the fixed-alpha trajectory form")
    if not issparse(lp["A_ub"]) or not issparse(lp["A_eq"]):
        raise ValueError("archived trajectory LP matrices must be sparse")


def _build_phase_tie_lp(
    lp: Mapping[str, Any],
    fleet: Sequence[Any],
    baseline: np.ndarray,
    buses: Sequence[str],
    primary_upper_bound: float,
) -> dict[str, Any]:
    base_objective = np.asarray(lp["objective"], dtype=float)
    base_variables = len(base_objective)
    n = int(lp["n"])
    pairs = list(lp["pairs"])
    pair_map = {pair: index for index, pair in enumerate(pairs)}
    phase_pairs = [
        (bus, slot, phase_a, phase_b)
        for bus in buses
        for slot in range(96)
        for phase_a, phase_b in ((1, 2), (1, 3), (2, 3))
    ]
    auxiliaries = len(phase_pairs)
    objective = np.concatenate(
        [np.zeros(base_variables, dtype=float), np.ones(auxiliaries, dtype=float)]
    )

    phase_evs: dict[tuple[str, int], list[int]] = {
        (bus, phase): [
            index
            for index, ev in enumerate(fleet)
            if str(ev.bus) == bus and int(ev.phase) == phase
        ]
        for bus in buses
        for phase in (1, 2, 3)
    }
    base_phase, phase_labels = _bus_phase_time_schedule(fleet, baseline)
    phase_index = {
        tuple(label.rsplit("|", 1)[0:1] + [int(label.rsplit("|", 1)[1])]): index
        for index, label in enumerate(phase_labels)
    }
    rows: list[int] = []
    columns: list[int] = []
    data: list[float] = []
    rhs = np.empty(2 * auxiliaries, dtype=float)
    for auxiliary, (bus, slot, phase_a, phase_b) in enumerate(phase_pairs):
        coefficients: dict[int, float] = {}
        for phase, sign in ((phase_a, 1.0), (phase_b, -1.0)):
            for vehicle in phase_evs[(bus, phase)]:
                pair = (vehicle, slot)
                if pair not in pair_map:
                    continue
                variable = pair_map[pair]
                coefficients[variable] = coefficients.get(variable, 0.0) + sign
                coefficients[n + variable] = (
                    coefficients.get(n + variable, 0.0) - sign
                )
        row_positive = 2 * auxiliary
        row_negative = row_positive + 1
        for variable, coefficient in coefficients.items():
            rows.extend((row_positive, row_negative))
            columns.extend((variable, variable))
            data.extend((coefficient, -coefficient))
        absolute_variable = base_variables + auxiliary
        rows.extend((row_positive, row_negative))
        columns.extend((absolute_variable, absolute_variable))
        data.extend((-1.0, -1.0))
        base_a = base_phase[phase_index[(bus, phase_a)], slot]
        base_b = base_phase[phase_index[(bus, phase_b)], slot]
        rhs[row_positive] = base_a - base_b
        rhs[row_negative] = -base_a + base_b

    phase_constraints = coo_matrix(
        (data, (rows, columns)),
        shape=(2 * auxiliaries, base_variables + auxiliaries),
    ).tocsr()
    original_ub = hstack(
        [
            csr_matrix(lp["A_ub"]),
            csr_matrix((csr_matrix(lp["A_ub"]).shape[0], auxiliaries)),
        ],
        format="csr",
    )
    primary_row = hstack(
        [
            csr_matrix(base_objective.reshape(1, -1)),
            csr_matrix((1, auxiliaries)),
        ],
        format="csr",
    )
    A_ub = vstack(
        [original_ub, primary_row, phase_constraints], format="csr"
    )
    b_ub = np.concatenate(
        [
            np.asarray(lp["b_ub"], dtype=float),
            np.asarray([primary_upper_bound], dtype=float),
            rhs,
        ]
    )
    A_eq = hstack(
        [
            csr_matrix(lp["A_eq"]),
            csr_matrix((csr_matrix(lp["A_eq"]).shape[0], auxiliaries)),
        ],
        format="csr",
    )
    return {
        "objective": objective,
        "bounds": [*lp["bounds"], *([(0.0, None)] * auxiliaries)],
        "A_ub": A_ub,
        "b_ub": b_ub,
        "A_eq": A_eq,
        "b_eq": np.asarray(lp["b_eq"], dtype=float),
    }


def _decode_lp_schedule(
    lp: Mapping[str, Any],
    fleet: Sequence[Any],
    solution: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = int(lp["n"])
    values = np.asarray(solution, dtype=float)
    schedule = np.zeros((len(fleet), 96), dtype=float)
    charge = np.zeros_like(schedule)
    discharge = np.zeros_like(schedule)
    for variable, (vehicle, slot) in enumerate(lp["pairs"]):
        charge[vehicle, slot] = values[variable]
        discharge[vehicle, slot] = values[n + variable]
        schedule[vehicle, slot] = (
            charge[vehicle, slot] - discharge[vehicle, slot]
        )
    return schedule, charge, discharge


def _schedule_primary_objective(
    lp: Mapping[str, Any],
    baseline: np.ndarray,
    schedule: np.ndarray,
) -> float:
    values = np.zeros(len(lp["objective"]), dtype=float)
    n = int(lp["n"])
    for variable, (vehicle, slot) in enumerate(lp["pairs"]):
        net = float(schedule[vehicle, slot])
        values[variable] = max(net, 0.0)
        values[n + variable] = max(-net, 0.0)
        values[2 * n + variable] = abs(net - float(baseline[vehicle, slot]))
    return float(np.dot(np.asarray(lp["objective"], dtype=float), values))


def _trajectory_primary_objective(
    lp: Mapping[str, Any],
    baseline: np.ndarray,
    schedule: np.ndarray,
    charge: np.ndarray,
    discharge: np.ndarray,
) -> float:
    n = int(lp["n"])
    throughput = 0.0
    deviation = 0.0
    for variable, (vehicle, slot) in enumerate(lp["pairs"]):
        del variable
        throughput += float(charge[vehicle, slot] + discharge[vehicle, slot])
        deviation += abs(
            float(schedule[vehicle, slot] - baseline[vehicle, slot])
        )
    if len(lp["objective"]) != 3 * n:
        raise ValueError("primary objective requires a fixed-alpha trajectory LP")
    return float(deviation + 1e-5 * throughput)


def _trajectory_invariants(
    fleet: Sequence[Any],
    schedule: np.ndarray,
    charge: np.ndarray,
    discharge: np.ndarray,
    mode: str,
) -> dict[str, Any]:
    departure_error = 0.0
    reserve_violation = 0.0
    capacity_violation = 0.0
    discharge_budget_violation = 0.0
    availability_violation = 0.0
    charge_limit_violation = 0.0
    discharge_limit_violation = 0.0
    for row, ev in enumerate(fleet):
        unavailable = np.ones(96, dtype=bool)
        unavailable[int(ev.arrival) : int(ev.departure)] = False
        availability_violation = max(
            availability_violation,
            float(np.max(np.abs(charge[row, unavailable]), initial=0.0)),
            float(np.max(np.abs(discharge[row, unavailable]), initial=0.0)),
        )
        charge_limit_violation = max(
            charge_limit_violation,
            float(np.max(charge[row] - float(ev.pch), initial=0.0)),
        )
        allowed_discharge = (
            float(ev.pdis)
            if mode == "v2g" and bool(ev.v2g)
            else 0.0
        )
        discharge_limit_violation = max(
            discharge_limit_violation,
            float(np.max(discharge[row] - allowed_discharge, initial=0.0)),
        )
        energy = float(ev.initial)
        minimum_energy = energy
        maximum_energy = energy
        for slot in range(int(ev.arrival), int(ev.departure)):
            energy += (
                float(ev.eta_c) * charge[row, slot] * 0.25
                - discharge[row, slot] * 0.25 / float(ev.eta_d)
            )
            minimum_energy = min(minimum_energy, energy)
            maximum_energy = max(maximum_energy, energy)
        departure_error = max(departure_error, abs(energy - float(ev.target)))
        reserve_violation = max(
            reserve_violation, max(0.0, float(ev.reserve) - minimum_energy)
        )
        capacity_violation = max(
            capacity_violation, max(0.0, maximum_energy - float(ev.capacity))
        )
        budget = float(discharge[row].sum() * 0.25)
        allowed_budget = (
            float(ev.max_discharge)
            if mode == "v2g" and bool(ev.v2g)
            else 0.0
        )
        discharge_budget_violation = max(
            discharge_budget_violation, max(0.0, budget - allowed_budget)
        )
    simultaneous = int(
        np.count_nonzero((charge > 1e-7) & (discharge > 1e-7))
    )
    schedule_identity_error = float(
        np.max(np.abs(schedule - (charge - discharge)), initial=0.0)
    )
    maximum_error = max(
        departure_error,
        reserve_violation,
        capacity_violation,
        discharge_budget_violation,
        availability_violation,
        max(0.0, charge_limit_violation),
        max(0.0, discharge_limit_violation),
        schedule_identity_error,
    )
    return {
        "max_departure_error_kwh": float(departure_error),
        "max_reserve_violation_kwh": float(reserve_violation),
        "max_capacity_violation_kwh": float(capacity_violation),
        "max_discharge_budget_violation_kwh": float(
            discharge_budget_violation
        ),
        "max_availability_violation_kw": float(availability_violation),
        "max_charge_limit_violation_kw": float(
            max(0.0, charge_limit_violation)
        ),
        "max_discharge_limit_violation_kw": float(
            max(0.0, discharge_limit_violation)
        ),
        "max_schedule_identity_error_kw": schedule_identity_error,
        "simultaneous_slots": simultaneous,
        "max_ev_invariant_error": float(maximum_error),
    }


def _comparable_offers(
    baseline: np.ndarray,
    original: np.ndarray,
    tied: np.ndarray,
    *,
    direction: str | None,
    call_slots: Sequence[int] | None,
) -> tuple[float, float]:
    original_delta = original.sum(axis=0) - baseline.sum(axis=0)
    tied_delta = tied.sum(axis=0) - baseline.sum(axis=0)
    if call_slots is None:
        indices = np.arange(96, dtype=int)
        original_offer = float(np.max(np.abs(original_delta), initial=0.0))
        tied_offer = float(np.max(np.abs(tied_delta), initial=0.0))
        return original_offer, tied_offer
    indices = np.asarray(list(call_slots), dtype=int)
    if (
        indices.ndim != 1
        or len(indices) == 0
        or np.any(indices < 0)
        or np.any(indices >= 96)
    ):
        raise ValueError("call_slots must contain valid 96-slot indices")
    if direction == "dec":
        original_values = -original_delta[indices]
        tied_values = -tied_delta[indices]
    else:
        original_values = original_delta[indices]
        tied_values = tied_delta[indices]
    return (
        max(0.0, float(np.min(original_values))),
        max(0.0, float(np.min(tied_values))),
    )


def _tie_comparator_cache_key(
    schedule_hash: str,
    direction: str,
    call_slots: Sequence[int] | None,
    offer_kw: float,
) -> tuple[str, str, tuple[int, ...] | None, int]:
    if direction not in {"inc", "dec"}:
        raise ValueError("tie comparator direction must be 'inc' or 'dec'")
    if call_slots is None:
        normalized_slots = None
    else:
        if isinstance(call_slots, (str, bytes, bytearray, Mapping)):
            raise ValueError(
                "tie comparator call_slots must be an integer sequence"
            )
        try:
            values = tuple(call_slots)
        except TypeError as exc:
            raise ValueError(
                "tie comparator call_slots must be an integer sequence"
            ) from exc
        if not values:
            raise ValueError("tie comparator call_slots must not be empty")
        slots: list[int] = []
        for value in values:
            if isinstance(value, (bool, np.bool_)) or not isinstance(
                value, (int, np.integer)
            ):
                raise ValueError(
                    "tie comparator call_slots must contain integer indices"
                )
            slot = int(value)
            if slot < 0 or slot >= 96:
                raise ValueError(
                    "tie comparator call_slots must contain valid 96-slot indices"
                )
            slots.append(slot)
        normalized_slots = tuple(sorted(set(slots)))

    if isinstance(offer_kw, (bool, np.bool_)):
        raise ValueError(
            "tie comparator offer_kw must be finite and nonnegative"
        )
    try:
        offer = float(offer_kw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "tie comparator offer_kw must be finite and nonnegative"
        ) from exc
    if not math.isfinite(offer) or offer < 0:
        raise ValueError(
            "tie comparator offer_kw must be finite and nonnegative"
        )
    offer_identity = int(np.float64(offer).view(np.uint64))
    return schedule_hash, direction, normalized_slots, offer_identity


def evaluate_pilot_work_unit(
    repo_root: str | Path,
    work_unit: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
    perf_counter: Any = time.perf_counter,
) -> list[dict[str, Any]]:
    """Evaluate one three-duration pilot work unit without solving a 3ph optimum."""
    if not isinstance(work_unit, Mapping):
        raise TypeError("work_unit must be a mapping")
    loaded_config: Mapping[str, Any] = (
        load_pilot_config(repo_root) if config is None else config
    )
    durations = tuple(int(value) for value in loaded_config["durations_min"])
    if durations != (15, 30, 60):
        raise ValueError("pilot work units require durations 15, 30, and 60")
    evaluation_ids = _pilot_evaluation_ids(work_unit, durations)
    direction = str(work_unit["direction"])
    if direction not in {"inc", "dec"}:
        raise ValueError("pilot direction must be 'inc' or 'dec'")
    feeder = str(work_unit["feeder"])
    try:
        feeder_kva = float(loaded_config["feeder_kva"][feeder])
        minimum_kw = float(loaded_config["active_offer"]["minimum_kw"])
        feeder_fraction = float(
            loaded_config["active_offer"]["feeder_fraction"]
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("pilot active-offer configuration is incomplete") from exc
    active_threshold = max(minimum_kw, feeder_fraction * feeder_kva)
    if not math.isfinite(active_threshold) or active_threshold <= 0:
        raise ValueError("pilot active-offer threshold must be finite and positive")

    runtime_factory = loaded_config.get("_runtime_factory")
    if runtime_factory is None:
        runtime = _create_real_pilot_runtime(
            Path(repo_root), work_unit, loaded_config
        )
    else:
        if not callable(runtime_factory):
            raise TypeError("_runtime_factory must be callable")
        runtime = runtime_factory(Path(repo_root), work_unit, loaded_config)
    baseline = _validated_schedule(
        runtime.baseline, len(runtime.fleet), "runtime baseline"
    )
    baseline_schedule_hash = canonical_schedule_sha256(
        runtime.fleet, baseline
    )

    raw_by_duration: dict[int, dict[str, Any]] = {}
    raw_failures: dict[int, str] = {}
    for duration in durations:
        try:
            raw = runtime.generate_balanced_raw(duration, "balanced")
            normalized = _normalize_raw_balanced_result(
                raw,
                duration,
                runtime.fleet,
                baseline,
                direction=direction,
            )
        except Exception as exc:
            raw_failures[duration] = f"{type(exc).__name__}: {exc}"
            normalized = {
                "success": False,
                "duration_min": duration,
                "physical_feasible": False,
                "flex_kw": 0.0,
                "failure": raw_failures[duration],
            }
        raw_by_duration[duration] = normalized

    truth_cache = runtime.create_corrected_truth_cache()
    baseline_result = runtime.audit_corrected(
        baseline,
        truth_cache,
        baseline_slot_results=None,
        stop_on_violation=False,
        retain_slot_results=True,
    )
    baseline_summary = _compact_audit_summary(baseline_result)
    baseline_slots = baseline_result.get("slot_results")
    baseline_valid = bool(
        baseline_summary["feasible"]
        and baseline_summary["complete_coverage"]
        and baseline_summary["checked_intervals"] == 96
        and baseline_summary["nonconverged_checks"] == 0
        and baseline_summary["numerical_failure_checks"] == 0
        and baseline_summary["failure_class"] == "NONE"
    )
    if baseline_valid:
        baseline_status = "VALID"
    elif (
        baseline_summary["complete_coverage"]
        and baseline_summary["checked_intervals"] == 96
        and baseline_summary["nonconverged_checks"] == 0
        and baseline_summary["numerical_failure_checks"] == 0
        and baseline_summary["failure_class"] == "PHYSICAL_CONSTRAINT"
        and baseline_summary["explicit_physical_witness"]
    ):
        baseline_status = "BASELINE_PHYSICAL_INVALID"
    else:
        baseline_status = "BASELINE_NUMERICAL_INVALID"

    alpha_settings = loaded_config["alpha_search"]
    coarse_step = float(alpha_settings["coarse_step"])
    refine_tolerance = float(alpha_settings["refine_tolerance"])
    warm_repeats = int(
        loaded_config["scientific_gate_thresholds"]["warm_timing"]["repeats"]
    )
    if warm_repeats != 3:
        raise ValueError("pilot warm timing must use exactly three repeats")

    path_cache: dict[str, dict[str, Any]] = {}
    path_owner: dict[str, tuple[int, str]] = {}
    timing_cache: dict[str, dict[str, Any]] = {}
    timing_owner: dict[str, int] = {}
    legacy_cache: dict[str, dict[str, Any]] = {}
    legacy_owner: dict[str, int] = {}
    tie_cache: dict[
        tuple[str, str, tuple[int, ...] | None, int],
        dict[str, Any],
    ] = {}
    tie_owner: dict[
        tuple[str, str, tuple[int, ...] | None, int],
        int,
    ] = {}
    schedule_owner: dict[str, int] = {}

    def corrected_path(
        schedule: np.ndarray,
        *,
        requested_duration: int,
        role: str,
    ) -> tuple[dict[str, Any], bool, tuple[int, str]]:
        schedule_hash = canonical_schedule_sha256(runtime.fleet, schedule)
        if schedule_hash in path_cache:
            return path_cache[schedule_hash], True, path_owner[schedule_hash]
        result = _evaluate_corrected_schedule_path(
            runtime,
            truth_cache,
            schedule,
            baseline,
            baseline_slots,
            coarse_step=coarse_step,
            refine_tolerance=refine_tolerance,
        )
        path_cache[schedule_hash] = result
        path_owner[schedule_hash] = (requested_duration, role)
        return result, False, (requested_duration, role)

    rows: list[dict[str, Any]] = []
    from evflex.engine import select_nested_candidate

    for requested_duration in durations:
        base_row = _pilot_row_identity(
            work_unit,
            loaded_config,
            evaluation_ids[requested_duration],
            requested_duration,
        )
        base_row.update(
            {
                "baseline_status": baseline_status,
                "baseline_audit": baseline_summary,
                "baseline_schedule_sha256": baseline_schedule_hash,
                "active_offer_threshold_kw": active_threshold,
                "raw_schedule_failure_by_duration": dict(raw_failures),
            }
        )
        try:
            selected = select_nested_candidate(
                raw_by_duration, requested_duration
            )
        except Exception as exc:
            rows.append(
                _strict_json_safe(
                    {
                        **base_row,
                        "source_duration_min": None,
                        "f_bal_kw": None,
                        "active_offer": None,
                        "eligible_for_scientific_denominator": False,
                        "alpha_legacy_verifier": None,
                        "alpha_transfer": None,
                        "alpha_prefix": None,
                        "alpha_sup": None,
                        "alpha_nonmonotone": None,
                        "alpha_transfer_tied": None,
                        "tie_comparator_valid": None,
                        "tie_break_status": "NOT_RUN_SCHEDULE_SOLVER_INVALID",
                        "alpha1_cold_timing_s": None,
                        "alpha1_cold_timing_scope": None,
                        "alpha1_first_replay_timing_s": None,
                        "alpha1_first_replay_scope": None,
                        "alpha1_warm_timing_s": [],
                        "alpha1_warm_p95_s": None,
                        "alpha1_warm_cv": None,
                        "scientific_status": "INVALID_SCHEDULE",
                        "status": "SCHEDULE_SOLVER_INVALID",
                        "status_detail": f"{type(exc).__name__}: {exc}",
                    }
                )
            )
            continue

        schedule = _validated_schedule(
            selected["schedule"],
            len(runtime.fleet),
            "selected balanced schedule",
        )
        f_bal = float(selected["flex_kw"])
        if not math.isfinite(f_bal) or f_bal < 0:
            raise ValueError("balanced offer must be finite and nonnegative")
        active = bool(f_bal >= active_threshold)
        schedule_hash = canonical_schedule_sha256(runtime.fleet, schedule)
        source_duration = int(selected["source_duration_min"])
        reused = schedule_hash in schedule_owner
        reuse_source = schedule_owner.setdefault(
            schedule_hash, requested_duration
        )
        bus_phase_hash = _canonical_bus_phase_time_sha256(
            runtime.fleet, schedule
        )
        row = {
            **base_row,
            "source_duration_min": source_duration,
            "monotonic_closure_promoted": bool(
                selected["monotonic_closure_promoted"]
            ),
            "f_bal_kw": f_bal,
            "active_offer": active,
            "eligible_for_scientific_denominator": bool(
                active and baseline_valid
            ),
            "schedule_sha256": schedule_hash,
            "bus_phase_time_sha256": bus_phase_hash,
            "canonical_schedule_reused": reused,
            "reuse_source_requested_duration_min": (
                reuse_source if reused else None
            ),
            "max_departure_error_kwh": float(
                selected["max_departure_error_kwh"]
            ),
            "max_reserve_violation_kwh": float(
                selected["max_reserve_violation_kwh"]
            ),
            "max_capacity_violation_kwh": float(
                selected["max_capacity_violation_kwh"]
            ),
            "max_discharge_budget_violation_kwh": float(
                selected["max_discharge_budget_violation_kwh"]
            ),
            "max_availability_violation_kw": float(
                selected["max_availability_violation_kw"]
            ),
            "max_charge_limit_violation_kw": float(
                selected["max_charge_limit_violation_kw"]
            ),
            "max_discharge_limit_violation_kw": float(
                selected["max_discharge_limit_violation_kw"]
            ),
            "max_schedule_identity_error_kw": float(
                selected["max_schedule_identity_error_kw"]
            ),
            "max_ev_invariant_error": float(
                selected["max_ev_invariant_error"]
            ),
            "ev_invariant_errors": dict(selected["ev_invariant_errors"]),
            "reported_ev_invariant_errors": dict(
                selected["reported_ev_invariant_errors"]
            ),
            "derived_ev_invariant_errors": dict(
                selected["derived_ev_invariant_errors"]
            ),
            "simultaneous_slots": int(selected["simultaneous_slots"]),
        }
        if not baseline_valid:
            rows.append(
                _strict_json_safe(
                    {
                        **row,
                        "alpha_legacy_verifier": None,
                        "alpha_transfer": None,
                        "alpha_prefix": None,
                        "alpha_sup": None,
                        "alpha_nonmonotone": None,
                        "alpha_transfer_tied": None,
                        "tie_comparator_valid": None,
                        "tie_break_status": "NOT_RUN_BASELINE_INVALID",
                        "alpha1_cold_timing_s": None,
                        "alpha1_cold_timing_scope": None,
                        "alpha1_first_replay_timing_s": None,
                        "alpha1_first_replay_scope": None,
                        "alpha1_warm_timing_s": [],
                        "alpha1_warm_p95_s": None,
                        "alpha1_warm_cv": None,
                        "scientific_status": "INVALID_BASELINE",
                        "status": baseline_status,
                    }
                )
            )
            continue
        if not active:
            rows.append(
                _strict_json_safe(
                    {
                        **row,
                        "alpha_legacy_verifier": None,
                        "alpha_transfer": None,
                        "alpha_prefix": None,
                        "alpha_sup": None,
                        "alpha_nonmonotone": None,
                        "alpha_transfer_tied": None,
                        "tie_comparator_valid": None,
                        "tie_break_status": "NOT_APPLICABLE_INACTIVE",
                        "alpha1_cold_timing_s": None,
                        "alpha1_cold_timing_scope": None,
                        "alpha1_first_replay_timing_s": None,
                        "alpha1_first_replay_scope": None,
                        "alpha1_warm_timing_s": [],
                        "alpha1_warm_p95_s": None,
                        "alpha1_warm_cv": None,
                        "scientific_status": "NOT_APPLICABLE_INACTIVE",
                        "status": "INACTIVE_OFFER",
                    }
                )
            )
            continue

        legacy_reused = schedule_hash in legacy_cache
        if not legacy_reused:
            original_cwd = os.getcwd()
            try:
                legacy_value = runtime.alpha_legacy_verifier(schedule)
                legacy_cache[schedule_hash] = _normalize_legacy_alpha(
                    legacy_value
                )
            except Exception as exc:
                legacy_cache[schedule_hash] = {
                    "alpha": None,
                    "status": "ERROR",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            finally:
                os.chdir(original_cwd)
            legacy_owner[schedule_hash] = requested_duration
        legacy = legacy_cache[schedule_hash]
        if schedule_hash not in timing_cache:
            try:
                timing_cache[schedule_hash] = _benchmark_alpha_one(
                    runtime,
                    truth_cache,
                    schedule,
                    baseline_slots,
                    perf_counter=perf_counter,
                    repeats=warm_repeats,
                )
            except Exception as exc:
                timing_cache[schedule_hash] = {
                    "status": "ERROR",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "first_replay_s": None,
                    "first_replay_scope": (
                        "FIRST_SCHEDULE_REPLAY_AFTER_COMMON_BASELINE_WITH_PREBUILT_TRUTH_CACHE"
                    ),
                    "warm_s": [],
                    "warm_p95_s": None,
                    "warm_cv": None,
                    "checked_intervals": [],
                    "power_flow_evaluations": [],
                    "feasible": [],
                    "numerical_failure_checks": [],
                    "nonconverged_checks": [],
                    "physical_violation_checks": [],
                    "failure_class": [],
                }
            timing_owner[schedule_hash] = requested_duration
        timing = timing_cache[schedule_hash]
        path, path_reused, path_source = corrected_path(
            schedule,
            requested_duration=requested_duration,
            role="original",
        )

        tie_key = None
        try:
            tie_key = _tie_comparator_cache_key(
                schedule_hash,
                direction,
                selected.get("call_slots"),
                f_bal,
            )
        except Exception as exc:
            tie_reused = False
            tie_source = None
            tie = {
                "success": False,
                "comparator_valid": False,
                "status": "ERROR",
                "detail": f"{type(exc).__name__}: {exc}",
                "schedule": None,
            }
        else:
            tie_reused = tie_key in tie_cache
            if not tie_reused:
                try:
                    tie_value = runtime.phase_tie_break(
                        schedule,
                        direction=direction,
                        call_slots=tie_key[2],
                        offer_kw=f_bal,
                    )
                    if not isinstance(tie_value, Mapping):
                        raise TypeError("tie diagnostic must return a mapping")
                    tie_cache[tie_key] = dict(tie_value)
                except Exception as exc:
                    tie_cache[tie_key] = {
                        "success": False,
                        "comparator_valid": False,
                        "status": "ERROR",
                        "detail": f"{type(exc).__name__}: {exc}",
                        "schedule": None,
                    }
                tie_owner[tie_key] = requested_duration
            tie = tie_cache[tie_key]
            tie_source = tie_owner[tie_key]
        tie_valid = bool(
            tie.get("success") is True
            and tie.get("comparator_valid") is True
            and isinstance(tie.get("schedule"), np.ndarray)
        )
        tie_path = None
        tie_path_reused = False
        tie_path_source: tuple[int, str] | None = None
        tie_path_error: str | None = None
        if tie_valid:
            try:
                tied_schedule = _validated_schedule(
                    tie["schedule"], len(runtime.fleet), "tied schedule"
                )
                tie_path, tie_path_reused, tie_path_source = corrected_path(
                    tied_schedule,
                    requested_duration=requested_duration,
                    role="tie",
                )
            except Exception as exc:
                tie_path_error = f"{type(exc).__name__}: {exc}"
                tie_valid = False
                tie = {
                    **tie,
                    "comparator_valid": False,
                    "status": "TIE_PATH_ERROR",
                    "detail": tie_path_error,
                }

        row.update(
            {
                "alpha_legacy_verifier": legacy["alpha"],
                "alpha_legacy_verifier_status": legacy["status"],
                "alpha_legacy_verifier_detail": legacy.get("detail"),
                "legacy_verifier_reused": legacy_reused,
                "legacy_verifier_source_requested_duration_min": legacy_owner[
                    schedule_hash
                ],
                "alpha_transfer": path["alpha_prefix"],
                "alpha_prefix": path["alpha_prefix"],
                "alpha_sup": path["alpha_sup"],
                "alpha_nonmonotone": path["nonmonotone"],
                "alpha_path_status": path["status"],
                "alpha_path_valid_baseline": path["valid_baseline"],
                "alpha_path_scientific_valid": path["scientific_valid"],
                "alpha_path_audit": path["audit_summary"],
                "alpha_path_reused": path_reused,
                "alpha_path_reuse_source_requested_duration_min": (
                    path_source[0] if path_reused else None
                ),
                "alpha_path_reuse_source_role": (
                    path_source[1] if path_reused else None
                ),
                "alpha1_timing_status": timing["status"],
                "alpha1_timing_detail": timing["detail"],
                "alpha1_cold_timing_s": timing["first_replay_s"],
                "alpha1_cold_timing_scope": timing[
                    "first_replay_scope"
                ],
                "alpha1_first_replay_timing_s": timing[
                    "first_replay_s"
                ],
                "alpha1_first_replay_scope": timing[
                    "first_replay_scope"
                ],
                "alpha1_warm_timing_s": timing["warm_s"],
                "alpha1_warm_p95_s": timing["warm_p95_s"],
                "alpha1_warm_cv": timing["warm_cv"],
                "alpha1_timing_checked_intervals": timing[
                    "checked_intervals"
                ],
                "alpha1_timing_power_flow_evaluations": timing[
                    "power_flow_evaluations"
                ],
                "alpha1_timing_numerical_failure_checks": timing[
                    "numerical_failure_checks"
                ],
                "alpha1_timing_nonconverged_checks": timing[
                    "nonconverged_checks"
                ],
                "alpha1_timing_physical_violation_checks": timing[
                    "physical_violation_checks"
                ],
                "alpha1_timing_failure_class": timing["failure_class"],
                "timing_independent_schedule": (
                    timing_owner[schedule_hash] == requested_duration
                ),
                "timing_reused": (
                    timing_owner[schedule_hash] != requested_duration
                ),
                "timing_source_requested_duration_min": timing_owner[
                    schedule_hash
                ],
                "tie_comparator_valid": tie_valid,
                "tie_break_status": str(tie.get("status", "INVALID")),
                "tie_break_detail": tie.get(
                    "detail", tie.get("message")
                ),
                "tie_break_reused": tie_reused,
                "tie_break_source_requested_duration_min": tie_source,
                "tie_original_schedule_sha256": tie.get(
                    "original_schedule_sha256"
                ),
                "tie_schedule_sha256": tie.get("tied_schedule_sha256"),
                "vehicle_identity_sha256": tie.get(
                    "vehicle_identity_sha256"
                ),
                "tie_bus_phase_time_sha256": tie.get(
                    "tied_bus_phase_time_sha256"
                ),
                "tie_offer_relative_difference": tie.get(
                    "offer_relative_difference"
                ),
                "tie_offer_retention": tie.get("offer_retention"),
                "tie_primary_objective_original": tie.get(
                    "primary_objective_original"
                ),
                "tie_primary_objective_optimum": tie.get(
                    "primary_objective_optimum"
                ),
                "tie_primary_objective": tie.get(
                    "primary_objective_tied"
                ),
                "tie_primary_objective_relative_gap": tie.get(
                    "primary_objective_relative_gap"
                ),
                "tie_primary_objective_original_relative_gap": tie.get(
                    "primary_objective_original_relative_gap"
                ),
                "tie_primary_objective_tied_relative_gap": tie.get(
                    "primary_objective_tied_relative_gap"
                ),
                "tie_declared_offer_identity": tie.get(
                    "declared_offer_identity"
                ),
                "tie_declared_offer_absolute_gap_kw": tie.get(
                    "declared_offer_absolute_gap_kw"
                ),
                "tie_original_phase_l1": tie.get(
                    "original_phase_imbalance_objective"
                ),
                "tie_phase_l1": tie.get("phase_imbalance_objective"),
                "tie_max_bus_time_error_kw": tie.get(
                    "max_bus_time_error_kw"
                ),
                "tie_max_ev_invariant_error": tie.get(
                    "max_ev_invariant_error"
                ),
                "tie_simultaneous_slots": tie.get("simultaneous_slots"),
                "alpha_transfer_tied": (
                    tie_path["alpha_prefix"] if tie_path is not None else None
                ),
                "alpha_tie_prefix": (
                    tie_path["alpha_prefix"] if tie_path is not None else None
                ),
                "alpha_tie_sup": (
                    tie_path["alpha_sup"] if tie_path is not None else None
                ),
                "alpha_tie_nonmonotone": (
                    tie_path["nonmonotone"]
                    if tie_path is not None
                    else None
                ),
                "alpha_tie_path_status": (
                    tie_path["status"]
                    if tie_path is not None
                    else (
                        "ERROR"
                        if tie_path_error is not None
                        else "NOT_RUN_TIE_INVALID"
                    )
                ),
                "alpha_tie_path_audit": (
                    tie_path["audit_summary"]
                    if tie_path is not None
                    else None
                ),
                "alpha_tie_path_reused": (
                    tie_path_reused if tie_path is not None else None
                ),
                "alpha_tie_path_reuse_source_requested_duration_min": (
                    tie_path_source[0]
                    if tie_path is not None and tie_path_reused
                    else None
                ),
                "alpha_tie_path_reuse_source_role": (
                    tie_path_source[1]
                    if tie_path is not None and tie_path_reused
                    else None
                ),
                "scientific_status": (
                    "VALID"
                    if path["status"] == "VALID"
                    else (
                        "NUMERICAL_INVALID_ALPHA_PATH"
                        if path["status"] == "NUMERICAL_INVALID"
                        else "INVALID_ALPHA_BASELINE"
                    )
                ),
                "status": (
                    "SUCCESS"
                    if path["status"] == "VALID"
                    else (
                        "ALPHA_PATH_NUMERICAL_INVALID"
                        if path["status"] == "NUMERICAL_INVALID"
                        else "ALPHA_PATH_INVALID"
                    )
                ),
            }
        )
        row["eligible_for_scientific_denominator"] = bool(
            active and baseline_valid and path["scientific_valid"]
        )
        rows.append(_strict_json_safe(row))
    return rows


def _pilot_evaluation_ids(
    work_unit: Mapping[str, Any], durations: Sequence[int]
) -> dict[int, str]:
    raw = work_unit["evaluation_ids"]
    values = json.loads(raw) if isinstance(raw, str) else list(raw)
    result: dict[int, str] = {}
    for value in values:
        text = str(value)
        match = _DURATION_SUFFIX.search(text)
        if match is None:
            raise ValueError(f"pilot evaluation ID lacks duration suffix: {text}")
        duration = int(match.group(1))
        if duration in result:
            raise ValueError(f"duplicate pilot evaluation duration: {duration}")
        result[duration] = text
    if set(result) != set(durations):
        raise ValueError("pilot evaluation IDs do not match configured durations")
    return result


def _normalize_raw_balanced_result(
    raw: Any,
    duration: int,
    fleet: Sequence[Any],
    baseline: Any,
    *,
    direction: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("balanced scheduler must return a mapping")
    if direction not in {"inc", "dec"}:
        raise ValueError("balanced schedule direction must be 'inc' or 'dec'")
    result = dict(raw)
    result["duration_min"] = int(duration)
    _validated_schedule(baseline, len(fleet), "raw balanced baseline")
    result["schedule"] = _validated_schedule(
        result["schedule"], len(fleet), "raw balanced schedule"
    )
    flex = float(result["flex_kw"])
    if not math.isfinite(flex) or flex < 0:
        raise ValueError("raw balanced flex_kw must be finite and nonnegative")
    result["flex_kw"] = flex

    reported: dict[str, float | int] = {}
    for name in (
        "max_departure_error_kwh",
        "max_reserve_violation_kwh",
        "max_capacity_violation_kwh",
    ):
        value = _finite_or_none(result.get(name))
        if value is None or value < 0:
            raise ValueError(
                f"reported EV invariant {name} must be present, finite, and nonnegative"
            )
        reported[name] = value
    simultaneous = _nonnegative_integer(result.get("simultaneous_slots"))
    if simultaneous is None:
        raise ValueError(
            "reported EV invariant simultaneous_slots must be present "
            "and a nonnegative integer"
        )
    reported["simultaneous_slots"] = simultaneous
    reported["max_ev_invariant_error"] = max(
        float(reported["max_departure_error_kwh"]),
        float(reported["max_reserve_violation_kwh"]),
        float(reported["max_capacity_violation_kwh"]),
    )

    has_charge = "charge" in result
    has_discharge = "discharge" in result
    if has_charge != has_discharge:
        raise ValueError(
            "raw balanced charge and discharge witnesses must be supplied together"
        )
    if has_charge:
        charge = _validated_schedule(
            result["charge"], len(fleet), "raw balanced charge"
        )
        discharge = _validated_schedule(
            result["discharge"], len(fleet), "raw balanced discharge"
        )
        if np.any(charge < 0) or np.any(discharge < 0):
            raise ValueError(
                "raw balanced charge and discharge witnesses must be nonnegative"
            )
    else:
        charge = np.maximum(result["schedule"], 0.0)
        discharge = np.maximum(-result["schedule"], 0.0)

    derived = _trajectory_invariants(
        fleet,
        result["schedule"],
        charge,
        discharge,
        "v1g" if direction == "inc" else "v2g",
    )
    combined = dict(derived)
    for name in (
        "max_departure_error_kwh",
        "max_reserve_violation_kwh",
        "max_capacity_violation_kwh",
    ):
        combined[name] = max(float(reported[name]), float(derived[name]))
    combined["simultaneous_slots"] = max(
        int(reported["simultaneous_slots"]),
        int(derived["simultaneous_slots"]),
    )
    combined["max_ev_invariant_error"] = max(
        float(reported["max_ev_invariant_error"]),
        float(derived["max_ev_invariant_error"]),
        float(combined["max_departure_error_kwh"]),
        float(combined["max_reserve_violation_kwh"]),
        float(combined["max_capacity_violation_kwh"]),
    )
    result["reported_ev_invariant_errors"] = dict(reported)
    result["derived_ev_invariant_errors"] = dict(derived)
    result.update(combined)
    result["ev_invariant_errors"] = dict(combined)
    physical = bool(
        result.get("success") is True
        and result.get("physical_feasible") is True
        and combined["max_ev_invariant_error"] <= 1e-6
        and combined["simultaneous_slots"] == 0
    )
    result["physical_feasible"] = physical
    return result


def _finite_below(value: Any, limit: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(math.isfinite(number) and number <= limit)


def _compact_audit_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise TypeError("corrected audit must return a mapping")
    checked = int(result.get("checked_intervals", 0))
    coverage_counts = result.get("coverage_counts")
    if not isinstance(coverage_counts, Mapping):
        records = result.get("slot_results")
        first = records[0] if isinstance(records, Sequence) and records else {}
        coverage_counts = (
            first.get("coverage", {}) if isinstance(first, Mapping) else {}
        )
    violations = result.get("violations", [])
    if not isinstance(violations, Sequence):
        violations = []
    physical_violation_checks = int(
        result.get(
            "physical_violation_checks",
            sum(
                bool(
                    isinstance(item, Mapping)
                    and item.get("physical_witness") is True
                )
                for item in violations
            ),
        )
    )
    numerical_failure_checks = int(
        result.get("numerical_failure_checks", 0)
    )
    nonconverged_checks = int(result.get("nonconverged_checks", 0))
    declared_failure_class = str(result.get("failure_class", "NONE"))
    if numerical_failure_checks or nonconverged_checks:
        failure_class = "NUMERICAL_INVALID"
    elif declared_failure_class in {
        "NUMERICAL_INVALID",
        "UNCLASSIFIED_INVALID",
    }:
        failure_class = declared_failure_class
    elif physical_violation_checks or declared_failure_class == "PHYSICAL_CONSTRAINT":
        failure_class = "PHYSICAL_CONSTRAINT"
    elif violations:
        failure_class = "UNCLASSIFIED_INVALID"
    else:
        failure_class = "NONE"
    raw_trace = result.get("slot_audit_trace", [])
    slot_trace = []
    if isinstance(raw_trace, Sequence):
        for item in raw_trace:
            if not isinstance(item, Mapping):
                continue
            slot_trace.append(
                {
                    "slot": int(item.get("slot", -1)),
                    "feasible": bool(item.get("feasible") is True),
                    "converged": bool(item.get("converged") is True),
                    "numerical_failure": bool(
                        item.get("numerical_failure") is True
                    ),
                    "failure_class": str(
                        item.get("failure_class", "UNCLASSIFIED_INVALID")
                    ),
                    "physical_witness": bool(
                        item.get("physical_witness") is True
                    ),
                }
            )
    failure_slots = [
        int(item["slot"])
        for item in violations
        if isinstance(item, Mapping) and _nonnegative_integer(item.get("slot")) is not None
    ]
    explicit_physical_witness = bool(
        any(item["physical_witness"] for item in slot_trace)
        or any(
            isinstance(item, Mapping)
            and item.get("physical_witness") is True
            for item in violations
        )
    )
    if failure_class == "PHYSICAL_CONSTRAINT" and not explicit_physical_witness:
        failure_class = "UNCLASSIFIED_INVALID"
    return {
        "feasible": bool(result.get("feasible") is True),
        "checked_intervals": checked,
        "coverage_ratio": _finite_or_none(result.get("coverage_ratio")),
        "complete_coverage": bool(
            result.get("complete_coverage") is True and checked == 96
        ),
        "power_flow_evaluations": int(
            result.get("power_flow_evaluations", 0)
        ),
        "reused_baseline_intervals": int(
            result.get("reused_baseline_intervals", 0)
        ),
        "converged_checks": int(result.get("converged_checks", 0)),
        "nonconverged_checks": nonconverged_checks,
        "numerical_failure_checks": numerical_failure_checks,
        "physical_violation_checks": physical_violation_checks,
        "failure_class": failure_class,
        "explicit_physical_witness": explicit_physical_witness,
        "violation_count": len(violations),
        "first_failure_slot": min(failure_slots, default=None),
        "slot_trace": slot_trace,
        "vmin": _finite_or_none(result.get("vmin")),
        "vmax": _finite_or_none(result.get("vmax")),
        "vufmax": _finite_or_none(result.get("vufmax")),
        "transformer_loading_max": _finite_or_none(
            result.get("transformer_loading_max")
        ),
        "feeder_loading_max": _finite_or_none(
            result.get("feeder_loading_max")
        ),
        "coverage_counts": {
            str(key): _strict_json_safe(value)
            for key, value in coverage_counts.items()
            if key
            not in {
                "transformer_ratings_kva",
                "transformer_raw_ratings_kva",
            }
        },
    }


def _evaluate_corrected_schedule_path(
    runtime: Any,
    truth_cache: Any,
    schedule: np.ndarray,
    baseline: np.ndarray,
    baseline_slots: Any,
    *,
    coarse_step: float,
    refine_tolerance: float,
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []

    def audit(alpha: float) -> bool:
        candidate = baseline + float(alpha) * (schedule - baseline)
        raw = runtime.audit_corrected(
            candidate,
            truth_cache,
            baseline_slot_results=baseline_slots,
            stop_on_violation=True,
            retain_slot_results=False,
        )
        summary = _compact_audit_summary(raw)
        summary["alpha"] = float(alpha)
        summaries.append(summary)
        return bool(
            summary["feasible"]
            and summary["complete_coverage"]
            and summary["checked_intervals"] == 96
        )

    path = evaluate_alpha_path(
        audit,
        coarse_step=coarse_step,
        refine_tolerance=refine_tolerance,
    )
    numerical_invalid = any(
        item["numerical_failure_checks"] > 0
        or item["nonconverged_checks"] > 0
        or item["failure_class"] in {
            "NUMERICAL_INVALID",
            "UNCLASSIFIED_INVALID",
        }
        for item in summaries
    )
    valid_baseline = bool(path["valid_baseline"])
    scientific_valid = bool(valid_baseline and not numerical_invalid)
    if numerical_invalid:
        path_status = "NUMERICAL_INVALID"
    elif valid_baseline:
        path_status = "VALID"
    else:
        path_status = "INVALID_BASELINE"
    alpha_trace = [
        {
            "alpha": item["alpha"],
            "feasible": item["feasible"],
            "checked_intervals": item["checked_intervals"],
            "complete_coverage": item["complete_coverage"],
            "failure_class": item["failure_class"],
            "numerical_failure_checks": item[
                "numerical_failure_checks"
            ],
            "nonconverged_checks": item["nonconverged_checks"],
            "physical_violation_checks": item[
                "physical_violation_checks"
            ],
            "first_failure_slot": item["first_failure_slot"],
        }
        for item in summaries
    ]
    return {
        "valid_baseline": valid_baseline,
        "scientific_valid": scientific_valid,
        "status": path_status,
        "alpha_prefix": (
            _finite_or_none(path["alpha_prefix"]) if scientific_valid else None
        ),
        "alpha_sup": (
            _finite_or_none(path["alpha_sup"]) if scientific_valid else None
        ),
        "nonmonotone": (
            bool(path["nonmonotone"]) if scientific_valid else None
        ),
        "audit_calls": int(path["audit_calls"]),
        "prefix_resolution": _finite_or_none(path["prefix_resolution"]),
        "audit_summary": {
            "audit_calls": len(summaries),
            "power_flow_evaluations": sum(
                item["power_flow_evaluations"] for item in summaries
            ),
            "reused_baseline_intervals": sum(
                item["reused_baseline_intervals"] for item in summaries
            ),
            "complete_audits": sum(
                bool(item["complete_coverage"]) for item in summaries
            ),
            "early_stopped_audits": sum(
                not bool(item["complete_coverage"]) for item in summaries
            ),
            "numerical_failure_audits": sum(
                item["numerical_failure_checks"] > 0
                or item["nonconverged_checks"] > 0
                for item in summaries
            ),
            "physical_boundary_audits": sum(
                item["physical_violation_checks"] > 0
                for item in summaries
            ),
            "minimum_checked_intervals": min(
                (item["checked_intervals"] for item in summaries),
                default=0,
            ),
            "maximum_checked_intervals": max(
                (item["checked_intervals"] for item in summaries),
                default=0,
            ),
            "alpha_trace": alpha_trace,
        },
    }


def _benchmark_alpha_one(
    runtime: Any,
    truth_cache: Any,
    schedule: np.ndarray,
    baseline_slots: Any,
    *,
    perf_counter: Any,
    repeats: int,
) -> dict[str, Any]:
    timings: list[float] = []
    summaries: list[dict[str, Any]] = []
    for _ in range(1 + repeats):
        started = float(perf_counter())
        raw = runtime.audit_corrected(
            schedule,
            truth_cache,
            baseline_slot_results=baseline_slots,
            stop_on_violation=False,
            retain_slot_results=False,
        )
        elapsed = float(perf_counter()) - started
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("perf_counter produced an invalid duration")
        summary = _compact_audit_summary(raw)
        if (
            summary["checked_intervals"] != 96
            or not summary["complete_coverage"]
        ):
            raise ValueError("timing audits must check all 96 intervals")
        timings.append(elapsed)
        summaries.append(summary)
    warm = np.asarray(timings[1:], dtype=float)
    mean = float(warm.mean())
    cv = float(warm.std(ddof=0) / mean) if mean > 0 else None
    return {
        "status": (
            "NUMERICAL_INVALID"
            if any(
                item["numerical_failure_checks"] > 0
                or item["nonconverged_checks"] > 0
                for item in summaries
            )
            else "SUCCESS"
        ),
        "detail": (
            "one or more replay audits had numerical or convergence failures"
            if any(
                item["numerical_failure_checks"] > 0
                or item["nonconverged_checks"] > 0
                for item in summaries
            )
            else None
        ),
        "first_replay_s": timings[0],
        "first_replay_scope": (
            "FIRST_SCHEDULE_REPLAY_AFTER_COMMON_BASELINE_WITH_PREBUILT_TRUTH_CACHE"
        ),
        "warm_s": timings[1:],
        "warm_p95_s": float(np.percentile(warm, 95, method="higher")),
        "warm_cv": cv,
        "checked_intervals": [
            item["checked_intervals"] for item in summaries
        ],
        "power_flow_evaluations": [
            item["power_flow_evaluations"] for item in summaries
        ],
        "feasible": [item["feasible"] for item in summaries],
        "numerical_failure_checks": [
            item["numerical_failure_checks"] for item in summaries
        ],
        "nonconverged_checks": [
            item["nonconverged_checks"] for item in summaries
        ],
        "physical_violation_checks": [
            item["physical_violation_checks"] for item in summaries
        ],
        "failure_class": [item["failure_class"] for item in summaries],
    }


def _normalize_legacy_alpha(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        status = str(value.get("status", "SUCCESS"))
        detail = value.get("detail")
        value = value.get("alpha")
    else:
        status = "SUCCESS"
        detail = None
    alpha = _finite_or_none(value)
    if alpha is None or not 0.0 <= alpha <= 1.0:
        return {
            "alpha": None,
            "status": "INVALID",
            "detail": str(detail) if detail is not None else None,
        }
    return {
        "alpha": alpha,
        "status": status,
        "detail": str(detail) if detail is not None else None,
    }


def _pilot_row_identity(
    work_unit: Mapping[str, Any],
    config: Mapping[str, Any],
    evaluation_id: str,
    requested_duration: int,
) -> dict[str, Any]:
    return {
        "evaluation_id": evaluation_id,
        "work_unit_id": str(work_unit["work_unit_id"]),
        "protocol_version": str(config["protocol_version"]),
        "scenario_id": str(work_unit["scenario_id"]),
        "scenario_seed": int(work_unit["scenario_seed"]),
        "data_role": str(work_unit["data_role"]),
        "feeder": str(work_unit["feeder"]),
        "call_time": str(work_unit["call_time"]),
        "direction": str(work_unit["direction"]),
        "duration_min": int(requested_duration),
        "requested_duration_min": int(requested_duration),
    }


def _canonical_bus_phase_time_sha256(
    fleet: Sequence[Any], schedule: np.ndarray
) -> str:
    order, _ = _canonical_fleet_order(fleet)
    sorted_fleet = [fleet[int(index)] for index in order]
    matrix, labels = _bus_phase_time_schedule(sorted_fleet, schedule[order])
    return _hash_labeled_float64_matrix(
        "evflex.pilot.bus-phase-time.v1", labels, matrix
    )


def _finite_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _strict_json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        raise TypeError("compact pilot payload must not contain ndarray values")
    if isinstance(value, np.generic):
        return _strict_json_safe(value.item())
    if isinstance(value, Mapping):
        return {str(key): _strict_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported compact pilot payload type: {type(value).__name__}")


def _create_real_pilot_runtime(
    repo_root: Path,
    work_unit: Mapping[str, Any],
    config: Mapping[str, Any],
) -> Any:
    from evflex.engine import load_archived_engine
    from evflex.fleet import load_fleet_bundle
    from evflex.network import configure_core, load_legacy_core

    repo = repo_root.resolve(strict=True)
    duration_engine_path = (
        repo / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    network_core_path = (
        repo / "legacy" / "d5_v1_2" / "network_core_v1_2.py"
    )
    archived_engine = load_archived_engine(duration_engine_path)

    corrected_core = load_legacy_core(network_core_path)
    configure_core(corrected_core, repo)
    configure_pilot_core(corrected_core, config)

    legacy_core = load_legacy_core(network_core_path)
    configure_core(legacy_core, repo)
    _configure_legacy_verifier_voltage_limit(
        legacy_core, float(config["formal_constraints"]["vmax_pu"])
    )

    bundle = load_fleet_bundle(
        repo,
        str(work_unit["scenario_id"]),
        archived_engine,
        corrected_core,
    )
    if str(bundle.scenario["feeder"]) != str(work_unit["feeder"]):
        raise ValueError("pilot fleet feeder differs from work unit")
    if str(bundle.scenario["call_time"]) != str(work_unit["call_time"]):
        raise ValueError("pilot fleet call time differs from work unit")
    return _RealPilotRuntime(
        archived_engine=archived_engine,
        corrected_core=corrected_core,
        legacy_core=legacy_core,
        bundle=bundle,
        feeder=str(work_unit["feeder"]),
        call_time=str(work_unit["call_time"]),
        direction=str(work_unit["direction"]),
    )


class _RealPilotRuntime:
    def __init__(
        self,
        *,
        archived_engine: Any,
        corrected_core: Any,
        legacy_core: Any,
        bundle: Any,
        feeder: str,
        call_time: str,
        direction: str,
    ) -> None:
        self.archived_engine = archived_engine
        self.corrected_core = corrected_core
        self.legacy_core = legacy_core
        self.fleet = list(bundle.fleet)
        self.baseline = np.asarray(bundle.baseline, dtype=float)
        self.load_scales = np.asarray(bundle.load_scales, dtype=float)
        self.feeder = feeder
        self.call_time = call_time
        self.direction = direction
        self._corrected_truth_cache: Any = None
        self._legacy_truth_cache: Any = None

    def generate_balanced_raw(
        self, duration: int, model: str
    ) -> dict[str, Any]:
        if model != "balanced":
            raise ValueError("pilot scheduler may generate balanced schedules only")
        raw = self.archived_engine.duration_result(
            self.corrected_core,
            self.feeder,
            self.fleet,
            self.baseline,
            int(self.archived_engine.CALL_SLOTS[self.call_time]),
            int(duration),
            self.direction,
            self.load_scales,
            "balanced",
        )
        result = dict(raw)
        result["success"] = bool(result.get("success", True))
        result["physical_feasible"] = bool(
            _finite_below(result.get("max_departure_error_kwh"), 1e-6)
            and _finite_below(result.get("max_reserve_violation_kwh"), 1e-6)
            and _finite_below(result.get("max_capacity_violation_kwh"), 1e-6)
            and result.get("simultaneous_slots") == 0
            and isinstance(result.get("model_network_check"), Mapping)
            and result["model_network_check"].get("feasible") is True
        )
        return result

    def create_corrected_truth_cache(self) -> Any:
        if self._corrected_truth_cache is None:
            self._corrected_truth_cache = self.archived_engine.network_cache(
                self.corrected_core,
                self.feeder,
                self.fleet,
                self.load_scales,
                "3ph",
            )
        return self._corrected_truth_cache

    def audit_corrected(
        self,
        schedule: Any,
        cache: Any,
        *,
        baseline_slot_results: Any,
        stop_on_violation: bool,
        retain_slot_results: bool,
    ) -> dict[str, Any]:
        if cache is not self._corrected_truth_cache:
            raise ValueError("corrected audit must use the work-unit truth cache")
        return full_network_check(
            self.archived_engine,
            self.feeder,
            self.fleet,
            schedule,
            self.baseline,
            self.load_scales,
            "3ph",
            cache,
            baseline_slot_results=baseline_slot_results,
            stop_on_violation=stop_on_violation,
            retain_slot_results=retain_slot_results,
        )

    def alpha_legacy_verifier(self, schedule: Any) -> dict[str, Any]:
        original_cwd = os.getcwd()
        try:
            if self._legacy_truth_cache is None:
                self._legacy_truth_cache = self.archived_engine.network_cache(
                    self.legacy_core,
                    self.feeder,
                    self.fleet,
                    self.load_scales,
                    "3ph",
                )
            alpha, check = self.archived_engine.safe_schedule_alpha(
                self.legacy_core,
                self.feeder,
                self.fleet,
                np.asarray(schedule, dtype=float),
                self.baseline,
                self.load_scales,
                "3ph",
                self._legacy_truth_cache,
            )
        finally:
            os.chdir(original_cwd)
        return {
            "alpha": float(alpha),
            "status": "SUCCESS" if bool(check.get("feasible")) else "INVALID",
        }

    def phase_tie_break(
        self,
        schedule: Any,
        *,
        direction: str,
        call_slots: Sequence[int] | None,
        offer_kw: float,
    ) -> dict[str, Any]:
        return phase_balanced_tie_break(
            self.archived_engine,
            self.fleet,
            self.baseline,
            schedule,
            direction=direction,
            call_slots=call_slots,
            offer_kw=offer_kw,
        )


def _configure_legacy_verifier_voltage_limit(
    core: Any, voltage_max_pu: float
) -> None:
    vmax = float(voltage_max_pu)
    if not math.isfinite(vmax) or not 1.0 <= vmax <= 1.10:
        raise ValueError("legacy verifier voltage limit is invalid")
    base_network = core.Network

    class LegacyVerifierNetwork(base_network):
        _pilot_legacy_verifier_vmax = vmax

        def __init__(
            self,
            feeder: str,
            fleet_frame: Any,
            model: str,
            load_scale: float,
            vmin: float = 0.95,
            vmax: float = vmax,
            vuf: float = 2.0,
        ) -> None:
            del vmax
            super().__init__(
                feeder,
                fleet_frame,
                model,
                load_scale,
                vmin=vmin,
                vmax=LegacyVerifierNetwork._pilot_legacy_verifier_vmax,
                vuf=vuf,
            )

    LegacyVerifierNetwork.__name__ = (
        f"LegacyVerifierNetworkVmax{voltage_max_pu:g}"
    )
    core.Network = LegacyVerifierNetwork


def build_pilot_network_class(
    base_class: type[Any], config: Mapping[str, Any]
) -> type[Any]:
    settings = _pilot_network_settings(config)

    class PilotNetwork(base_class):
        _pilot_network_class = True
        _pilot_base_class = base_class

        def __init__(
            self,
            feeder: str,
            fleet_frame: Any,
            model: str,
            load_scale: float,
            vmin: float | None = None,
            vmax: float | None = None,
            vuf: float | None = None,
        ) -> None:
            if feeder not in settings["feeder_kva"]:
                raise KeyError(f"pilot feeder rating is missing for {feeder}")
            self._pilot_ready = False
            self._pilot_coverage: dict[str, Any] = {}
            self._pilot_feeder_kva = settings["feeder_kva"][feeder]
            original_cwd = os.getcwd()
            try:
                super().__init__(
                    feeder,
                    fleet_frame,
                    model,
                    load_scale,
                    vmin=settings["vmin"],
                    vmax=settings["vmax"],
                    vuf=settings["vuf"],
                )
            finally:
                os.chdir(original_cwd)
            self.vmin = settings["vmin"]
            self.vmax = settings["vmax"]
            self.vuf = settings["vuf"]
            self._pilot_ready = True
            self.labels = None
            self.base = self.evaluate(np.zeros(len(self.groups), dtype=float))

        def evaluate(self, power: Any) -> dict[str, Any]:
            if not getattr(self, "_pilot_ready", False):
                return super().evaluate(power)
            return _evaluate_pilot_network(self, power, settings)

        def bounds(self) -> tuple[np.ndarray, np.ndarray]:
            if not getattr(self, "_pilot_ready", False):
                return super().bounds()
            labels = self.labels or []
            lower = np.full(len(labels), -np.inf)
            upper = np.full(len(labels), np.inf)
            for index, label in enumerate(labels):
                if label.startswith("V:"):
                    lower[index] = self.vmin
                    upper[index] = self.vmax
                elif label.startswith("U:"):
                    upper[index] = self.vuf
                elif label.startswith("S:transformer:"):
                    upper[index] = settings["transformer_limit"]
                elif label == "S:feeder":
                    upper[index] = settings["feeder_limit"]
            return lower, upper

        def coverage_report(self) -> dict[str, Any]:
            report = dict(self._pilot_coverage)
            report["transformer_ratings_kva"] = dict(
                report.get("transformer_ratings_kva", {})
            )
            report["transformer_raw_ratings_kva"] = dict(
                report.get("transformer_raw_ratings_kva", {})
            )
            return report

        def audit_context(self) -> dict[str, Any]:
            (
                transformer_rating_multiplier,
                transformer_rating_basis,
            ) = _transformer_rating_normalization(self)
            return {
                "adapter_schema": _PILOT_ADAPTER_SCHEMA,
                "adapter_version": _PILOT_ADAPTER_VERSION,
                "feeder": str(self.feeder),
                "model": str(self.model),
                "load_scale": float(self.load_scale),
                "vmin_pu": float(self.vmin),
                "vmax_pu": float(self.vmax),
                "vuf_limit_pct": float(self.vuf),
                "transformer_loading_limit_pu": float(
                    settings["transformer_limit"]
                ),
                "feeder_loading_limit_pu": float(settings["feeder_limit"]),
                "feeder_kva": float(self._pilot_feeder_kva),
                "line_thermal_in_scope": False,
                "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
                "transformer_rating_basis": transformer_rating_basis,
                "transformer_rating_multiplier": (
                    transformer_rating_multiplier
                ),
            }

    PilotNetwork.__name__ = f"Pilot{base_class.__name__}"
    PilotNetwork.__qualname__ = PilotNetwork.__name__
    PilotNetwork.__module__ = base_class.__module__
    return PilotNetwork


def configure_pilot_core(core: Any, config: Mapping[str, Any]) -> Any:
    current = core.Network
    base_class = getattr(current, "_pilot_base_class", current)
    core.Network = build_pilot_network_class(base_class, config)
    return core


def _pilot_network_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    try:
        formal = config["formal_constraints"]
        ratings = config["feeder_kva"]
    except (KeyError, TypeError) as exc:
        raise ValueError("pilot network configuration is incomplete") from exc
    if not isinstance(formal, Mapping) or not isinstance(ratings, Mapping):
        raise ValueError("pilot network constraints and feeder ratings must be mappings")
    if formal.get("line_thermal_in_scope") is not False:
        raise ValueError("pilot line thermal constraints must remain out of scope")

    def finite_number(value: Any, label: str, *, positive: bool = False) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{label} must be finite") from exc
        if not math.isfinite(number) or (positive and number <= 0):
            raise ValueError(f"{label} must be finite and positive")
        return number

    vmin = finite_number(formal.get("vmin_pu"), "vmin_pu")
    vmax = finite_number(formal.get("vmax_pu"), "vmax_pu")
    vuf = finite_number(formal.get("vuf_limit_pct"), "vuf_limit_pct", positive=True)
    transformer_limit = finite_number(
        formal.get("transformer_loading_limit_pu"),
        "transformer_loading_limit_pu",
        positive=True,
    )
    feeder_limit = finite_number(
        formal.get("feeder_loading_limit_pu"),
        "feeder_loading_limit_pu",
        positive=True,
    )
    if not vmin < vmax:
        raise ValueError("vmin_pu must be below vmax_pu")
    if transformer_limit != 1.0 or feeder_limit != 1.0:
        raise ValueError("pilot transformer and feeder loading limits must equal 1.0")
    feeder_kva = {
        str(name): finite_number(value, f"feeder_kva[{name}]", positive=True)
        for name, value in ratings.items()
    }
    return {
        "vmin": vmin,
        "vmax": vmax,
        "vuf": vuf,
        "transformer_limit": transformer_limit,
        "feeder_limit": feeder_limit,
        "feeder_kva": feeder_kva,
    }


def _transformer_rating_normalization(
    network: Any,
) -> tuple[float, str]:
    cfg = getattr(network, "cfg", None)
    positive_sequence = bool(
        str(getattr(network, "model", "")) == "balanced"
        and isinstance(cfg, Mapping)
        and cfg.get("balanced") == "posseq"
    )
    multiplier = 3.0 if positive_sequence else 1.0
    basis = (
        "MAKEPOSSEQ_PER_PHASE_KVA_NORMALIZED_TO_SYSTEM_TOTAL"
        if positive_sequence
        else "NATIVE_SYSTEM_TOTAL_KVA"
    )
    return multiplier, basis


def _evaluate_pilot_network(
    network: Any, power: Any, settings: Mapping[str, Any]
) -> dict[str, Any]:
    context = network.ctx
    numerical_violations: list[dict[str, Any]] = []
    physical_violations: list[dict[str, Any]] = []
    metrics: dict[str, float] = {}

    network.setp(np.asarray(power, dtype=float))
    try:
        context.Solution.Solve()
        converged = bool(context.Solution.Converged())
    except Exception as exc:
        converged = False
        numerical_violations.append(
            _numerical_network_violation(
                "solve_exception",
                "power_flow",
                f"{type(exc).__name__}: {exc}",
            )
        )
    if not converged:
        numerical_violations.append(
            _numerical_network_violation("nonconverged", "power_flow")
        )

    try:
        all_buses = [str(name) for name in context.Circuit.AllBusNames()]
    except Exception as exc:
        all_buses = []
        numerical_violations.append(
            _numerical_network_violation(
                "formal_metric_unavailable",
                "all_bus_names",
                f"{type(exc).__name__}: {exc}",
            )
        )
    try:
        node_names = [str(name) for name in context.Circuit.AllNodeNames()]
        node_values = list(context.Circuit.AllBusMagPu())
    except Exception as exc:
        node_names = []
        node_values = []
        numerical_violations.append(
            _numerical_network_violation(
                "formal_metric_unavailable",
                "all_bus_voltage_nodes",
                f"{type(exc).__name__}: {exc}",
            )
        )
    if len(node_names) != len(node_values):
        numerical_violations.append(
            _numerical_network_violation(
                "formal_metric_unavailable",
                "all_bus_voltage_nodes",
                f"name/value length mismatch {len(node_names)} != {len(node_values)}",
            )
        )

    voltage_labels: list[str] = []
    monitored_buses: set[str] = set()
    for index, node_name in enumerate(node_names):
        label = f"V:{node_name.lower()}"
        voltage_labels.append(label)
        try:
            value = float(node_values[index])
        except (IndexError, TypeError, ValueError, OverflowError):
            value = math.nan
        if not math.isfinite(value):
            numerical_violations.append(
                _numerical_network_violation(
                    "formal_metric_unavailable", label
                )
            )
            continue
        metrics[label] = value
        monitored_buses.add(node_name.rsplit(".", 1)[0].lower())

    vuf_labels: list[str] = []
    three_phase_buses = 0
    monitored_vuf_buses = 0
    for bus_name in all_buses:
        label = f"U:{bus_name.lower()}"
        try:
            context.Circuit.SetActiveBus(bus_name)
            nodes = {int(node) for node in context.Bus.Nodes()}
        except Exception as exc:
            numerical_violations.append(
                _numerical_network_violation(
                    "formal_metric_unavailable",
                    label,
                    f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if not {1, 2, 3}.issubset(nodes):
            continue
        three_phase_buses += 1
        vuf_labels.append(label)
        try:
            sequence = list(context.Bus.SeqVoltages())
            positive = float(sequence[1])
            negative = float(sequence[2])
            if (
                len(sequence) < 3
                or not math.isfinite(positive)
                or not math.isfinite(negative)
                or positive <= 1e-12
            ):
                raise ValueError("invalid sequence voltages")
            value = 100.0 * abs(negative) / abs(positive)
        except (IndexError, TypeError, ValueError, OverflowError) as exc:
            numerical_violations.append(
                _numerical_network_violation(
                    "formal_metric_unavailable", label, str(exc)
                )
            )
            continue
        metrics[label] = value
        monitored_vuf_buses += 1

    transformer_labels: list[str] = []
    transformer_ratings: dict[str, float] = {}
    transformer_raw_ratings: dict[str, float] = {}
    (
        transformer_rating_multiplier,
        transformer_rating_basis,
    ) = _transformer_rating_normalization(network)
    enabled_transformers = 0
    rated_transformers = 0
    try:
        transformer_names = [str(name) for name in context.Transformers.AllNames()]
    except Exception as exc:
        transformer_names = []
        numerical_violations.append(
            _numerical_network_violation(
                "formal_metric_unavailable",
                "transformer_names",
                f"{type(exc).__name__}: {exc}",
            )
        )
    for transformer_name in transformer_names:
        label = f"S:transformer:{transformer_name.lower()}"
        try:
            context.Transformers.Name(transformer_name)
            context.Circuit.SetActiveElement(f"Transformer.{transformer_name}")
            enabled = bool(context.CktElement.Enabled())
        except Exception as exc:
            numerical_violations.append(
                _numerical_network_violation(
                    "formal_metric_unavailable",
                    label,
                    f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if not enabled:
            continue
        enabled_transformers += 1
        transformer_labels.append(label)
        try:
            context.Transformers.Wdg(1)
            raw_rating = float(context.Transformers.kVA())
        except (TypeError, ValueError, OverflowError) as exc:
            raw_rating = math.nan
            rating_error = str(exc)
        else:
            rating_error = None
        rating = raw_rating * transformer_rating_multiplier
        if not math.isfinite(rating) or rating <= 0:
            numerical_violations.append(
                _numerical_network_violation(
                    "formal_metric_unavailable",
                    label,
                    rating_error or "transformer rating is not positive and finite",
                )
            )
            continue
        rated_transformers += 1
        transformer_raw_ratings[transformer_name] = raw_rating
        transformer_ratings[transformer_name] = rating
        try:
            terminal_count = int(context.CktElement.NumTerminals())
            terminal_powers = list(context.CktElement.TotalPowers())
            if terminal_count <= 0 or len(terminal_powers) < 2 * terminal_count:
                raise ValueError("terminal power vector is incomplete")
            apparent = [
                math.hypot(
                    float(terminal_powers[2 * terminal]),
                    float(terminal_powers[2 * terminal + 1]),
                )
                for terminal in range(terminal_count)
            ]
            if not apparent or not all(math.isfinite(value) for value in apparent):
                raise ValueError("terminal apparent power is non-finite")
            loading = max(apparent) / rating
        except (TypeError, ValueError, OverflowError) as exc:
            numerical_violations.append(
                _numerical_network_violation(
                    "formal_metric_unavailable", label, str(exc)
                )
            )
            continue
        metrics[label] = loading

    feeder_label = "S:feeder"
    try:
        total_power = list(context.Circuit.TotalPower())
        if len(total_power) < 2:
            raise ValueError("total power vector is incomplete")
        feeder_loading = math.hypot(
            float(total_power[0]), float(total_power[1])
        ) / float(network._pilot_feeder_kva)
        if not math.isfinite(feeder_loading):
            raise ValueError("feeder loading is non-finite")
        metrics[feeder_label] = feeder_loading
    except (TypeError, ValueError, OverflowError) as exc:
        feeder_loading = None
        numerical_violations.append(
            _numerical_network_violation(
                "formal_metric_unavailable", feeder_label, str(exc)
            )
        )

    expected_labels = [
        *voltage_labels,
        *vuf_labels,
        *transformer_labels,
        feeder_label,
    ]
    if network.labels is None:
        network.labels = expected_labels
    elif network.labels != expected_labels:
        numerical_violations.append(
            _numerical_network_violation(
                "formal_metric_set_changed",
                "network_labels",
            )
        )
    vector = np.array(
        [metrics.get(label, math.nan) for label in network.labels], dtype=float
    )

    if converged and not numerical_violations:
        lower, upper = network.bounds()
        for index, label in enumerate(network.labels):
            value = vector[index]
            if not math.isfinite(float(value)):
                numerical_violations.append(
                    _numerical_network_violation(
                        "formal_metric_unavailable", label
                    )
                )
                continue
            if value < lower[index] - 1e-7:
                physical_violations.append(
                    _physical_network_violation(
                        label, float(value), float(lower[index]), "lo"
                    )
                )
            if value > upper[index] + 1e-7:
                physical_violations.append(
                    _physical_network_violation(
                        label, float(value), float(upper[index]), "hi"
                    )
                )

    try:
        line_count = len(list(context.Lines.AllNames()))
    except Exception as exc:
        line_count = 0
        numerical_violations.append(
            _numerical_network_violation(
                "formal_metric_unavailable",
                "line_count",
                f"{type(exc).__name__}: {exc}",
            )
        )
    transformer_coverage = (
        rated_transformers / enabled_transformers
        if enabled_transformers
        else 1.0
    )
    network.monitor_buses = list(all_buses)
    network._pilot_coverage = {
        "all_bus_count": len(all_buses),
        "monitored_bus_count": len(monitored_buses),
        "energized_voltage_node_count": len(node_names),
        "monitored_voltage_node_count": len(
            [label for label in voltage_labels if label in metrics]
        ),
        "three_phase_bus_count": three_phase_buses,
        "monitored_vuf_bus_count": monitored_vuf_buses,
        "enabled_transformer_count": enabled_transformers,
        "rated_transformer_count": rated_transformers,
        "transformer_rating_coverage": transformer_coverage,
        "line_count": line_count,
        "line_thermal_in_scope": False,
        "feeder_rating_multiplier": 1.0,
        "transformer_ratings_kva": transformer_ratings,
        "transformer_raw_ratings_kva": transformer_raw_ratings,
        "transformer_rating_multiplier": transformer_rating_multiplier,
        "transformer_rating_basis": transformer_rating_basis,
        "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
    }
    numerical_failure = bool(numerical_violations)
    violations = [*numerical_violations, *physical_violations]
    voltage_values = [
        value for label, value in metrics.items() if label.startswith("V:")
    ]
    vuf_values = [
        value for label, value in metrics.items() if label.startswith("U:")
    ]
    transformer_values = [
        value
        for label, value in metrics.items()
        if label.startswith("S:transformer:")
    ]
    return {
        "vector": vector,
        "metrics": metrics,
        "feasible": bool(converged and not numerical_failure and not violations),
        "converged": converged,
        "numerical_failure": numerical_failure,
        "violations": violations,
        "vmin": min(voltage_values) if voltage_values else None,
        "vmax": max(voltage_values) if voltage_values else None,
        "vufmax": max(vuf_values) if vuf_values else 0.0,
        "transformer_loading_max": (
            max(transformer_values) if transformer_values else 0.0
        ),
        "feeder_loading": feeder_loading,
        "sload": feeder_loading,
        "linemax": 0.0,
        "line_thermal_in_scope": False,
        "coverage": network.coverage_report(),
    }


def _numerical_network_violation(
    reason: str, metric: str, detail: str | None = None
) -> dict[str, Any]:
    violation = {
        "kind": "numerical_failure",
        "reason": reason,
        "metric": metric,
    }
    if detail:
        violation["detail"] = detail
    return violation


def _physical_network_violation(
    metric: str, value: float, limit: float, direction: str
) -> dict[str, Any]:
    return {
        "kind": "physical_constraint",
        "metric": metric,
        "value": value,
        "limit": limit,
        "direction": direction,
    }


def full_network_check(
    engine: Any,
    feeder: str,
    fleet: list[Any],
    schedule: Any,
    baseline: Any,
    load_scales: Any,
    model: str,
    cache: Mapping[float, Any],
    *,
    baseline_slot_results: Mapping[int, Any] | Sequence[Any] | None = None,
    stop_on_violation: bool = False,
    retain_slot_results: bool = True,
) -> dict[str, Any]:
    schedule_array = np.asarray(schedule, dtype=float)
    baseline_array = np.asarray(baseline, dtype=float)
    scale_array = np.asarray(load_scales, dtype=float)
    if schedule_array.ndim != 2 or schedule_array.shape[1] != 96:
        raise ValueError("schedule must be a two-dimensional array with 96 slots")
    if baseline_array.shape != schedule_array.shape:
        raise ValueError("baseline must have the same shape as schedule")
    if schedule_array.shape[0] != len(fleet):
        raise ValueError("schedule row count must equal fleet size")
    if scale_array.shape != (96,):
        raise ValueError("load_scales must contain exactly 96 values")
    if not (
        np.isfinite(schedule_array).all()
        and np.isfinite(baseline_array).all()
        and np.isfinite(scale_array).all()
    ):
        raise ValueError("schedule, baseline, and load_scales must be finite")
    if model not in {"3ph", "balanced"}:
        raise ValueError("model must be '3ph' or 'balanced'")
    if not cache:
        raise ValueError("network cache must not be empty")
    if not isinstance(retain_slot_results, (bool, np.bool_)):
        raise TypeError("retain_slot_results must be boolean")

    baseline_records = _index_baseline_slot_results(baseline_slot_results)
    aggregate: dict[str, float | None] = {
        "vmin": None,
        "vmax": None,
        "vufmax": None,
        "transformer_loading_max": None,
        "feeder_loading_max": None,
    }
    violations = []
    slot_results = []
    slot_audit_trace = []
    coverage_counts: dict[str, Any] | None = None
    checked_intervals = 0
    power_flow_evaluations = 0
    reused_baseline_intervals = 0
    converged_checks = 0
    nonconverged_checks = 0
    numerical_failure_checks = 0
    physical_violation_checks = 0

    for slot in range(96):
        scale = float(scale_array[slot])
        if scale not in cache:
            raise KeyError(f"network cache has no entry for load scale {scale}")
        network = cache[scale]
        audit_context = _capture_network_audit_context(
            network,
            feeder=feeder,
            model=model,
            load_scale=scale,
        )
        power = np.asarray(
            engine.group_vector(
                fleet,
                schedule_array[:, slot],
                network.groups,
                model,
            ),
            dtype=float,
        )
        if power.shape != (len(network.groups),) or not np.isfinite(power).all():
            raise ValueError("group power vector must be finite and match network groups")
        exact_baseline = bool(
            np.array_equal(schedule_array[:, slot], baseline_array[:, slot])
        )
        cached = baseline_records.get(slot)
        reusable = bool(
            exact_baseline
            and cached is not None
            and _baseline_slot_is_reusable(
                cached,
                slot=slot,
                feeder=feeder,
                model=model,
                load_scale=scale,
                baseline_column=baseline_array[:, slot],
                audit_context=audit_context,
                group_power=power,
            )
        )

        if reusable:
            evaluation = _normalize_slot_evaluation(cached["result"])
            reused_baseline_intervals += 1
            source = "baseline_reuse"
        else:
            power_flow_evaluations += 1
            try:
                raw_evaluation = network.evaluate(power)
            except Exception as exc:
                raw_evaluation = {
                    "feasible": False,
                    "converged": False,
                    "numerical_failure": True,
                    "violations": [
                        {
                            "kind": "evaluation_exception",
                            "detail": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                    "metrics": {},
                    "vmin": None,
                    "vmax": None,
                    "vufmax": None,
                    "transformer_loading_max": None,
                    "feeder_loading": None,
                }
            evaluation = _normalize_slot_evaluation(raw_evaluation)
            source = "power_flow"

        if evaluation["converged"]:
            converged_checks += 1
        else:
            nonconverged_checks += 1
        if evaluation["numerical_failure"]:
            numerical_failure_checks += 1

        _update_audit_extrema(aggregate, evaluation)
        checked_intervals += 1
        if coverage_counts is None:
            coverage_counts = _copy_formal_coverage(evaluation["coverage"])
        physical_witness = bool(
            not evaluation["numerical_failure"]
            and any(
                isinstance(item, Mapping)
                and item.get("kind") == "physical_constraint"
                for item in evaluation["violations"]
            )
        )
        if evaluation["numerical_failure"]:
            failure_class = "NUMERICAL_INVALID"
        elif physical_witness:
            failure_class = "PHYSICAL_CONSTRAINT"
        elif evaluation["feasible"]:
            failure_class = "NONE"
        else:
            failure_class = "UNCLASSIFIED_INVALID"
        if physical_witness:
            physical_violation_checks += 1
        slot_audit_trace.append(
            {
                "slot": slot,
                "feasible": bool(evaluation["feasible"]),
                "converged": bool(evaluation["converged"]),
                "numerical_failure": bool(evaluation["numerical_failure"]),
                "failure_class": failure_class,
                "physical_witness": physical_witness,
            }
        )
        if retain_slot_results:
            slot_results.append(
                {
                    "slot": slot,
                    "verified": True,
                    "baseline_exact": exact_baseline,
                    "baseline_schedule": (
                        baseline_array[:, slot].tolist()
                        if exact_baseline
                        else None
                    ),
                    "load_scale": scale,
                    "feeder": str(feeder),
                    "model": str(model),
                    "source": source,
                    "audit_context": _copy_audit_context(audit_context),
                    "group_power": power.tolist(),
                    "coverage": _copy_formal_coverage(evaluation["coverage"]),
                    "formal_integrity": dict(evaluation["formal_integrity"]),
                    "result": evaluation,
                }
            )

        if not evaluation["feasible"]:
            violations.append(
                {
                    "slot": slot,
                    "converged": evaluation["converged"],
                    "numerical_failure": evaluation["numerical_failure"],
                    "failure_class": failure_class,
                    "physical_witness": physical_witness,
                    "violations": evaluation["violations"],
                }
            )
            if stop_on_violation and physical_witness:
                break

    complete_coverage = checked_intervals == 96
    feasible = bool(complete_coverage and not violations)
    if numerical_failure_checks:
        aggregate_failure_class = "NUMERICAL_INVALID"
    elif physical_violation_checks:
        aggregate_failure_class = "PHYSICAL_CONSTRAINT"
    elif violations:
        aggregate_failure_class = "UNCLASSIFIED_INVALID"
    else:
        aggregate_failure_class = "NONE"
    return {
        "feasible": feasible,
        "checked_intervals": checked_intervals,
        "coverage_ratio": checked_intervals / 96.0,
        "complete_coverage": complete_coverage,
        "eligible_for_v01_pass": bool(feasible and complete_coverage),
        "power_flow_evaluations": power_flow_evaluations,
        "reused_baseline_intervals": reused_baseline_intervals,
        "converged_checks": converged_checks,
        "nonconverged_checks": nonconverged_checks,
        "numerical_failure_checks": numerical_failure_checks,
        "physical_violation_checks": physical_violation_checks,
        "failure_class": aggregate_failure_class,
        "nonconverged_slots": [
            item["slot"] for item in violations if not item["converged"]
        ],
        "violations": violations,
        "slot_results": slot_results,
        "slot_audit_trace": slot_audit_trace,
        "coverage_counts": coverage_counts or {},
        **aggregate,
    }


def _index_baseline_slot_results(
    records: Mapping[int, Any] | Sequence[Any] | None,
) -> dict[int, Mapping[str, Any]]:
    if records is None:
        return {}
    values = records.values() if isinstance(records, Mapping) else records
    indexed: dict[int, Mapping[str, Any]] = {}
    for record in values:
        if not isinstance(record, Mapping) or "slot" not in record:
            raise ValueError("baseline slot results must contain mapped slot records")
        slot = int(record["slot"])
        if slot in indexed:
            raise ValueError(f"duplicate baseline slot result for slot {slot}")
        indexed[slot] = record
    return indexed


def _baseline_slot_is_reusable(
    record: Mapping[str, Any],
    *,
    slot: int,
    feeder: str,
    model: str,
    load_scale: float,
    baseline_column: np.ndarray,
    audit_context: Mapping[str, Any],
    group_power: np.ndarray,
) -> bool:
    if record.get("verified") is not True or record.get("baseline_exact") is not True:
        return False
    if record.get("slot") != slot:
        return False
    if record.get("feeder") != str(feeder) or record.get("model") != str(model):
        return False
    try:
        cached_scale = float(record["load_scale"])
        cached_baseline = np.asarray(record["baseline_schedule"], dtype=float)
    except (KeyError, TypeError, ValueError):
        return False
    if cached_scale != load_scale:
        return False
    if cached_baseline.shape != baseline_column.shape:
        return False
    if not np.array_equal(cached_baseline, baseline_column):
        return False
    cached_context = record.get("audit_context")
    try:
        cached_group_power = np.asarray(record["group_power"], dtype=float)
    except (KeyError, TypeError, ValueError):
        return False
    if not (
        isinstance(cached_context, Mapping)
        and dict(cached_context) == dict(audit_context)
        and cached_group_power.shape == group_power.shape
        and np.isfinite(cached_group_power).all()
        and np.array_equal(cached_group_power, group_power)
    ):
        return False
    result = record.get("result")
    record_coverage = record.get("coverage")
    record_integrity = record.get("formal_integrity")
    if not (
        isinstance(result, Mapping)
        and isinstance(record_coverage, Mapping)
        and isinstance(record_integrity, Mapping)
        and record_integrity.get("validated") is True
    ):
        return False
    result_coverage = result.get("coverage")
    result_integrity = result.get("formal_integrity")
    if not (
        isinstance(result_coverage, Mapping)
        and isinstance(result_integrity, Mapping)
        and dict(result_coverage) == dict(record_coverage)
        and dict(result_integrity) == dict(record_integrity)
    ):
        return False
    observed_integrity = _assess_formal_result_integrity(result)
    return bool(
        observed_integrity["validated"]
        and observed_integrity == dict(record_integrity)
    )


def _capture_network_audit_context(
    network: Any,
    *,
    feeder: str,
    model: str,
    load_scale: float,
) -> dict[str, Any]:
    provider = getattr(network, "audit_context", None)
    if not callable(provider):
        raise ValueError("network must provide a versioned pilot audit context")
    declared = provider()
    if not isinstance(declared, Mapping):
        raise ValueError("network audit context must be a mapping")
    required_numbers = (
        "load_scale",
        "vmin_pu",
        "vmax_pu",
        "vuf_limit_pct",
        "transformer_loading_limit_pu",
        "feeder_loading_limit_pu",
        "feeder_kva",
        "transformer_rating_multiplier",
    )
    if not all(_is_finite_number(declared.get(name)) for name in required_numbers):
        raise ValueError("network audit context contains non-finite constraints")
    if (
        declared.get("adapter_schema") != _PILOT_ADAPTER_SCHEMA
        or declared.get("adapter_version") != _PILOT_ADAPTER_VERSION
        or declared.get("feeder") != str(feeder)
        or declared.get("model") != str(model)
        or float(declared["load_scale"]) != float(load_scale)
        or float(declared["vmin_pu"]) >= float(declared["vmax_pu"])
        or float(declared["vuf_limit_pct"]) <= 0
        or float(declared["transformer_loading_limit_pu"]) != 1.0
        or float(declared["feeder_loading_limit_pu"]) != 1.0
        or float(declared["feeder_kva"]) <= 0
        or declared.get("line_thermal_in_scope") is not False
        or declared.get("transformer_power_basis")
        != "SYSTEM_TOTAL_TERMINAL_POWER"
        or declared.get("transformer_rating_basis")
        not in {
            "NATIVE_SYSTEM_TOTAL_KVA",
            "MAKEPOSSEQ_PER_PHASE_KVA_NORMALIZED_TO_SYSTEM_TOTAL",
        }
        or float(declared["transformer_rating_multiplier"])
        not in {1.0, 3.0}
    ):
        raise ValueError("network audit context is incompatible with the pilot schema")
    return {
        "adapter_schema": _PILOT_ADAPTER_SCHEMA,
        "adapter_version": _PILOT_ADAPTER_VERSION,
        "network_class": (
            f"{type(network).__module__}.{type(network).__qualname__}"
        ),
        "network_instance_id": id(network),
        "feeder": str(feeder),
        "model": str(model),
        "load_scale": float(load_scale),
        "vmin_pu": float(declared["vmin_pu"]),
        "vmax_pu": float(declared["vmax_pu"]),
        "vuf_limit_pct": float(declared["vuf_limit_pct"]),
        "transformer_loading_limit_pu": float(
            declared["transformer_loading_limit_pu"]
        ),
        "feeder_loading_limit_pu": float(
            declared["feeder_loading_limit_pu"]
        ),
        "feeder_kva": float(declared["feeder_kva"]),
        "line_thermal_in_scope": False,
        "transformer_power_basis": str(
            declared["transformer_power_basis"]
        ),
        "transformer_rating_basis": str(
            declared["transformer_rating_basis"]
        ),
        "transformer_rating_multiplier": float(
            declared["transformer_rating_multiplier"]
        ),
        "groups": [
            {
                "type": f"{type(group).__module__}.{type(group).__qualname__}",
                "repr": repr(group),
            }
            for group in network.groups
        ],
    }


def _copy_audit_context(context: Mapping[str, Any]) -> dict[str, Any]:
    copied = dict(context)
    copied["groups"] = [dict(group) for group in context["groups"]]
    return copied


def _normalize_slot_evaluation(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("network.evaluate must return a mapping")
    schema_errors = _result_schema_errors(raw)
    if schema_errors:
        violations: list[Any] = [
            {
                "kind": "result_schema_failure",
                "invalid_fields": schema_errors,
            }
        ]
        feasible_value = False
        converged = False
        numerical_failure = True
    else:
        violations = list(raw["violations"])
        feasible_value = bool(raw["feasible"])
        converged = bool(raw["converged"])
        numerical_failure = bool(raw["numerical_failure"]) or not converged
    integrity = _assess_formal_result_integrity(raw)
    if not integrity["validated"]:
        numerical_failure = True
        violations.append(
            {
                "kind": "formal_integrity_failure",
                "failed_checks": [
                    name
                    for name, passed in integrity.items()
                    if name != "validated" and not passed
                ],
            }
        )
    formal_metrics: dict[str, float | None] = {}
    for output_name, input_name in (
        ("vmin", "vmin"),
        ("vmax", "vmax"),
        ("vufmax", "vufmax"),
        ("transformer_loading_max", "transformer_loading_max"),
        ("feeder_loading", "feeder_loading"),
    ):
        try:
            value = float(raw[input_name])
        except (KeyError, TypeError, ValueError, OverflowError):
            value = math.nan
        if not math.isfinite(value):
            formal_metrics[output_name] = None
            numerical_failure = True
            violations.append(
                {
                    "kind": "formal_metric_unavailable",
                    "metric": input_name,
                }
            )
        else:
            formal_metrics[output_name] = value

    feasible = bool(
        feasible_value and converged and not numerical_failure and not violations
    )
    metrics = raw.get("metrics", {})
    coverage = raw.get("coverage", {})
    return {
        "feasible": feasible,
        "converged": converged,
        "numerical_failure": numerical_failure,
        "violations": violations,
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "coverage": (
            _copy_formal_coverage(coverage)
            if isinstance(coverage, Mapping)
            else {}
        ),
        "formal_integrity": integrity,
        **formal_metrics,
    }


def _assess_formal_result_integrity(raw: Mapping[str, Any]) -> dict[str, bool]:
    result_schema_valid = not _result_schema_errors(raw)
    metrics = raw.get("metrics")
    metrics_finite = bool(
        isinstance(metrics, Mapping)
        and metrics
        and all(
            isinstance(name, str) and _is_finite_number(value)
            for name, value in metrics.items()
        )
    )
    summary_finite = all(
        _is_finite_number(raw.get(name))
        for name in (
            "vmin",
            "vmax",
            "vufmax",
            "transformer_loading_max",
            "feeder_loading",
        )
    )
    coverage = raw.get("coverage")
    coverage_complete = bool(
        metrics_finite
        and isinstance(coverage, Mapping)
        and _formal_coverage_is_complete(coverage, metrics)
    )
    summary_consistent = bool(
        metrics_finite
        and summary_finite
        and _formal_summary_matches_metrics(raw, metrics)
    )
    return {
        "validated": bool(
            result_schema_valid
            and metrics_finite
            and summary_finite
            and coverage_complete
            and summary_consistent
        ),
        "result_schema_valid": result_schema_valid,
        "metrics_finite": metrics_finite,
        "summary_finite": summary_finite,
        "coverage_complete": coverage_complete,
        "summary_consistent": summary_consistent,
    }


def _result_schema_errors(raw: Mapping[str, Any]) -> list[str]:
    errors = [
        name
        for name in ("feasible", "converged", "numerical_failure")
        if not isinstance(raw.get(name), (bool, np.bool_))
    ]
    violations = raw.get("violations")
    if not (
        isinstance(violations, (list, tuple))
        and all(
            isinstance(item, Mapping)
            or (
                isinstance(item, (list, tuple))
                and len(item) > 0
            )
            for item in violations
        )
    ):
        errors.append("violations")
    return errors


def _formal_coverage_is_complete(
    coverage: Mapping[str, Any], metrics: Mapping[str, Any]
) -> bool:
    count_names = (
        "all_bus_count",
        "monitored_bus_count",
        "energized_voltage_node_count",
        "monitored_voltage_node_count",
        "three_phase_bus_count",
        "monitored_vuf_bus_count",
        "enabled_transformer_count",
        "rated_transformer_count",
        "line_count",
    )
    counts = {
        name: _nonnegative_integer(coverage.get(name)) for name in count_names
    }
    if any(value is None for value in counts.values()):
        return False
    voltage_metrics = [name for name in metrics if name.startswith("V:")]
    vuf_metrics = [name for name in metrics if name.startswith("U:")]
    transformer_metrics = [
        name for name in metrics if name.startswith("S:transformer:")
    ]
    ratings = coverage.get("transformer_ratings_kva")
    raw_ratings = coverage.get("transformer_raw_ratings_kva")
    if not isinstance(ratings, Mapping) or not isinstance(raw_ratings, Mapping):
        return False
    if not all(
        isinstance(name, str)
        and _is_finite_number(rating)
        and float(rating) > 0
        for name, rating in ratings.items()
    ):
        return False
    if not all(
        isinstance(name, str)
        and _is_finite_number(rating)
        and float(rating) > 0
        for name, rating in raw_ratings.items()
    ):
        return False
    transformer_metric_names = {
        name.removeprefix("S:transformer:").lower()
        for name in transformer_metrics
    }
    transformer_rating_names = {str(name).lower() for name in ratings}
    try:
        transformer_rating_coverage = float(
            coverage["transformer_rating_coverage"]
        )
        feeder_rating_multiplier = float(coverage["feeder_rating_multiplier"])
        transformer_rating_multiplier = float(
            coverage["transformer_rating_multiplier"]
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    expected_rating_basis = (
        "MAKEPOSSEQ_PER_PHASE_KVA_NORMALIZED_TO_SYSTEM_TOTAL"
        if transformer_rating_multiplier == 3.0
        else "NATIVE_SYSTEM_TOTAL_KVA"
    )
    rating_basis_valid = bool(
        transformer_rating_multiplier in {1.0, 3.0}
        and coverage.get("transformer_rating_basis")
        == expected_rating_basis
        and coverage.get("transformer_power_basis")
        == "SYSTEM_TOTAL_TERMINAL_POWER"
        and {str(name).lower() for name in raw_ratings}
        == transformer_rating_names
        and all(
            math.isclose(
                float(ratings[name]),
                float(raw_ratings[name]) * transformer_rating_multiplier,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for name in ratings
        )
    )
    return bool(
        counts["all_bus_count"] > 0
        and counts["all_bus_count"] == counts["monitored_bus_count"]
        and counts["energized_voltage_node_count"] > 0
        and counts["energized_voltage_node_count"]
        == counts["monitored_voltage_node_count"]
        == len(voltage_metrics)
        and counts["three_phase_bus_count"]
        == counts["monitored_vuf_bus_count"]
        == len(vuf_metrics)
        and counts["enabled_transformer_count"]
        == counts["rated_transformer_count"]
        == len(transformer_metrics)
        == len(ratings)
        and transformer_metric_names == transformer_rating_names
        and rating_basis_valid
        and math.isfinite(transformer_rating_coverage)
        and transformer_rating_coverage == 1.0
        and coverage.get("line_thermal_in_scope") is False
        and math.isfinite(feeder_rating_multiplier)
        and feeder_rating_multiplier == 1.0
        and "S:feeder" in metrics
    )


def _formal_summary_matches_metrics(
    raw: Mapping[str, Any], metrics: Mapping[str, Any]
) -> bool:
    voltage_values = [
        float(value) for name, value in metrics.items() if name.startswith("V:")
    ]
    vuf_values = [
        float(value) for name, value in metrics.items() if name.startswith("U:")
    ]
    transformer_values = [
        float(value)
        for name, value in metrics.items()
        if name.startswith("S:transformer:")
    ]
    if not voltage_values or "S:feeder" not in metrics:
        return False
    expected = {
        "vmin": min(voltage_values),
        "vmax": max(voltage_values),
        "vufmax": max(vuf_values, default=0.0),
        "transformer_loading_max": max(transformer_values, default=0.0),
        "feeder_loading": float(metrics["S:feeder"]),
    }
    return all(
        math.isclose(
            float(raw[name]),
            value,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        for name, value in expected.items()
    )


def _copy_formal_coverage(coverage: Mapping[str, Any]) -> dict[str, Any]:
    copied = dict(coverage)
    for field in (
        "transformer_ratings_kva",
        "transformer_raw_ratings_kva",
    ):
        ratings = copied.get(field)
        if isinstance(ratings, Mapping):
            copied[field] = dict(ratings)
    return copied


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _update_audit_extrema(
    aggregate: dict[str, float | None], evaluation: Mapping[str, Any]
) -> None:
    for output_name, input_name, reducer in (
        ("vmin", "vmin", min),
        ("vmax", "vmax", max),
        ("vufmax", "vufmax", max),
        ("transformer_loading_max", "transformer_loading_max", max),
        ("feeder_loading_max", "feeder_loading", max),
    ):
        value = evaluation[input_name]
        if value is None:
            continue
        current = aggregate[output_name]
        aggregate[output_name] = value if current is None else reducer(current, value)


def validate_pilot_manifest(
    frame: pd.DataFrame, config: dict[str, Any]
) -> dict[str, object]:
    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        _fail(f"missing columns {missing}")

    scenario_ids = tuple(config["scenario_ids"])
    feeders = tuple(config["feeders"])
    call_times = tuple(config["call_times"])
    directions = tuple(config["directions"])
    durations_expected = tuple(
        _strict_int(value, "config duration") for value in config["durations_min"]
    )
    expected_work_units = len(scenario_ids) * len(directions)

    if len(frame) != expected_work_units:
        _fail(f"expected {expected_work_units} work units, got {len(frame)}")
    if frame["work_unit_id"].duplicated().any():
        _fail("work_unit_id values must be unique")
    if set(frame["scenario_id"]) != set(scenario_ids):
        _fail("scenario set differs from the frozen pilot")
    if set(frame["feeder"]) != set(feeders):
        _fail("feeder set differs from the frozen pilot")
    if set(frame["call_time"]) != set(call_times):
        _fail("call-time set differs from the frozen pilot")
    if set(frame["direction"]) != set(directions):
        _fail("direction set differs from the frozen pilot")

    expected_scenario_directions = {
        (scenario_id, direction)
        for scenario_id in scenario_ids
        for direction in directions
    }
    actual_scenario_directions = set(
        zip(frame["scenario_id"], frame["direction"], strict=True)
    )
    if actual_scenario_directions != expected_scenario_directions:
        _fail("each scenario must have one paired inc/dec direction")

    expected_factorial = {
        (feeder, call_time, direction)
        for feeder in feeders
        for call_time in call_times
        for direction in directions
    }
    actual_factorial = set(
        zip(frame["feeder"], frame["call_time"], frame["direction"], strict=True)
    )
    if actual_factorial != expected_factorial:
        _fail("expected complete 2 feeder x 4 call-time x 2 direction design")

    for column, expected in (
        ("protocol_version", config["protocol_version"]),
        ("data_role", "development_pilot"),
        ("holdout_access", "prohibited"),
        ("status", "PENDING"),
    ):
        if not frame[column].eq(expected).all():
            _fail(f"{column} must be fixed to {expected}")

    scenario_design = config.get("_source_scenario_design", config["scenario_design"])
    source_rows = config.get("_source_rows")
    if source_rows is None:
        _fail("config must be loaded with V2 source-row identities")
    evaluation_ids: list[str] = []
    for row in frame.itertuples(index=False):
        expected_scenario = scenario_design[row.scenario_id]
        if row.feeder != expected_scenario["feeder"]:
            _fail(f"scenario {row.scenario_id} has the wrong feeder")
        if row.call_time != expected_scenario["call_time"]:
            _fail(f"scenario {row.scenario_id} has the wrong call time")
        observed_seed = _strict_int(
            row.scenario_seed, f"scenario {row.scenario_id} seed"
        )
        if observed_seed != expected_scenario["scenario_seed"]:
            _fail(f"scenario {row.scenario_id} seed differs from the V2 manifest")
        try:
            row_evaluation_ids = _evaluation_ids(row.evaluation_ids)
        except (json.JSONDecodeError, TypeError) as exc:
            _fail(f"invalid evaluation_ids for {row.work_unit_id}: {exc}")
        source_key = (row.scenario_id, row.direction)
        source_row = source_rows.get(source_key)
        if source_row is None:
            _fail(f"work unit has no V2 source row for {source_key}")
        observed_source_fields = {
            "work_unit_id": row.work_unit_id,
            "scenario_id": row.scenario_id,
            "feeder": row.feeder,
            "call_time": row.call_time,
            "direction": row.direction,
            "scenario_seed": observed_seed,
            "evaluation_ids": row_evaluation_ids,
        }
        for field, observed in observed_source_fields.items():
            if observed != source_row[field]:
                _fail(f"{field} for {source_key} differs from the V2 source row")
        expected_evaluation_ids = [
            f"v20_core_{row.scenario_id}__{row.direction}__{duration}m"
            for duration in durations_expected
        ]
        if row_evaluation_ids != expected_evaluation_ids:
            _fail(
                f"work unit {row.work_unit_id} must contain exactly "
                f"{list(durations_expected)} minute evaluation IDs"
            )
        evaluation_ids.extend(row_evaluation_ids)

    if len(set(evaluation_ids)) != len(evaluation_ids):
        _fail("evaluation IDs must be unique")

    durations = sorted(
        {
            _strict_int(match.group(1), f"evaluation ID {evaluation_id} duration")
            for evaluation_id in evaluation_ids
            if (match := _DURATION_SUFFIX.search(evaluation_id))
        }
    )
    return {
        "work_units": len(frame),
        "unique_scenarios": frame["scenario_id"].nunique(),
        "evaluations": len(evaluation_ids),
        "call_times": sorted(frame["call_time"].unique().tolist()),
        "feeders": sorted(frame["feeder"].unique().tolist()),
        "directions": sorted(frame["direction"].unique().tolist()),
        "durations": durations,
    }


_GATE_NOT_EVALUATED = "NOT_EVALUATED_VALIDITY_STOP"
_GATE_SCIENTIFIC_STATUS_FIELDS = (
    "baseline_status",
    "active_offer_status",
    "core_topic_status",
    "scenario_dominance_status",
    "direction_claim_status",
    "duration_claim_status",
    "feeder_replication_status",
    "tie_break_route_status",
    "screening_compute_status",
    "v2_0_reuse_status",
)
_GATE_SHA256 = re.compile(r"[0-9a-f]{64}")
_GATE_SCENARIO_DESIGN = {
    "ieee13_1900_17": {
        "feeder": "ieee13",
        "call_time": "19:00",
        "scenario_seed": 2026071616,
    },
    "ieee13_0000_09": {
        "feeder": "ieee13",
        "call_time": "00:00",
        "scenario_seed": 2026071708,
    },
    "ieee13_0200_17": {
        "feeder": "ieee13",
        "call_time": "02:00",
        "scenario_seed": 2026071816,
    },
    "ieee13_0600_24": {
        "feeder": "ieee13",
        "call_time": "06:00",
        "scenario_seed": 2026071923,
    },
    "lv906_1900_18": {
        "feeder": "lv906",
        "call_time": "19:00",
        "scenario_seed": 2026072017,
    },
    "lv906_0000_11": {
        "feeder": "lv906",
        "call_time": "00:00",
        "scenario_seed": 2026072110,
    },
    "lv906_0200_03": {
        "feeder": "lv906",
        "call_time": "02:00",
        "scenario_seed": 2026072202,
    },
    "lv906_0600_02": {
        "feeder": "lv906",
        "call_time": "06:00",
        "scenario_seed": 2026072301,
    },
}


def assess_pilot_gate(
    evidence: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Assess the frozen V2.1 development pilot without starting a formal run."""
    try:
        context = _gate_config_context(config)
    except Exception as exc:
        return _gate_validity_stop(
            [("GATE_CONFIG_INVALID", f"{type(exc).__name__}: {exc}")]
        )

    try:
        errors, rows = _gate_validate_evidence(evidence, context)
    except Exception as exc:
        return _gate_validity_stop(
            [
                (
                    "GATE_VALIDATION_EXCEPTION",
                    f"{type(exc).__name__}: {exc}",
                )
            ]
        )
    if errors:
        return _gate_validity_stop(errors)

    try:
        return _gate_scientific_decision(rows, context)
    except Exception as exc:
        return _gate_validity_stop(
            [
                (
                    "GATE_DECISION_EXCEPTION",
                    f"{type(exc).__name__}: {exc}",
                )
            ]
        )


def _gate_config_context(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    if config.get("protocol_version") != "EV-FLEX-BIAS-V2.1-PILOT":
        raise ValueError("protocol_version is not the frozen V2.1 pilot")
    if (
        config.get("source_protocol_version") != "EV-FLEX-BIAS-V2.0"
        or config.get("source_manifest") != "manifests/core_work_units_v2_0.csv"
        or config.get("pilot_manifest")
        != "manifests/audit_pilot_work_units_v2_1.csv"
        or not _gate_is_int(config.get("workers"))
        or config.get("workers") != 1
        or not _gate_is_int(config.get("numeric_threads"))
        or config.get("numeric_threads") != 1
    ):
        raise ValueError("pilot provenance or execution settings are not frozen")

    scenario_ids = _gate_string_list(config.get("scenario_ids"), "scenario_ids")
    feeders = _gate_string_list(config.get("feeders"), "feeders")
    call_times = _gate_string_list(config.get("call_times"), "call_times")
    directions = _gate_string_list(config.get("directions"), "directions")
    durations = _gate_int_list(config.get("durations_min"), "durations_min")
    if (
        len(scenario_ids) != 8
        or len(set(scenario_ids)) != 8
        or len(feeders) != 2
        or len(set(feeders)) != 2
        or len(call_times) != 4
        or len(set(call_times)) != 4
        or directions != ["inc", "dec"]
        or durations != [15, 30, 60]
    ):
        raise ValueError("pilot factorial design is not the frozen 8x2x3 design")
    if (
        scenario_ids != list(_GATE_SCENARIO_DESIGN)
        or feeders != ["ieee13", "lv906"]
        or call_times != ["19:00", "00:00", "02:00", "06:00"]
    ):
        raise ValueError("pilot design labels differ from the frozen design")

    scenario_design = config.get("scenario_design")
    if not isinstance(scenario_design, Mapping):
        raise TypeError("scenario_design must be a mapping")
    if set(scenario_design) != set(scenario_ids):
        raise ValueError("scenario_design keys differ from scenario_ids")
    normalized_design: dict[str, dict[str, Any]] = {}
    for scenario_id in scenario_ids:
        item = scenario_design.get(scenario_id)
        if not isinstance(item, Mapping):
            raise TypeError(f"scenario_design[{scenario_id}] must be a mapping")
        feeder = item.get("feeder")
        call_time = item.get("call_time")
        seed = item.get("scenario_seed")
        if (
            not isinstance(feeder, str)
            or feeder not in feeders
            or not isinstance(call_time, str)
            or call_time not in call_times
            or not _gate_is_int(seed)
        ):
            raise ValueError(f"scenario_design[{scenario_id}] is invalid")
        normalized_design[scenario_id] = {
            "feeder": feeder,
            "call_time": call_time,
            "scenario_seed": seed,
        }
    if normalized_design != _GATE_SCENARIO_DESIGN:
        raise ValueError("scenario_design differs from the frozen design")
    factorial = {
        (item["feeder"], item["call_time"])
        for item in normalized_design.values()
    }
    if factorial != {
        (feeder, call_time)
        for feeder in feeders
        for call_time in call_times
    }:
        raise ValueError("scenario_design is not the frozen feeder/time factorial")

    feeder_kva = config.get("feeder_kva")
    if not isinstance(feeder_kva, Mapping) or set(feeder_kva) != set(feeders):
        raise ValueError("feeder_kva does not cover the exact feeder set")
    normalized_kva = {
        feeder: _gate_required_number(
            feeder_kva.get(feeder), f"feeder_kva[{feeder}]"
        )
        for feeder in feeders
    }
    if any(value <= 0 for value in normalized_kva.values()):
        raise ValueError("feeder_kva values must be positive")
    if normalized_kva != {"ieee13": 5000.0, "lv906": 800.0}:
        raise ValueError("feeder_kva differs from the frozen ratings")

    active = _gate_mapping(config, "active_offer")
    if active.get("rule") != "max(minimum_kw, feeder_fraction * feeder_kva)":
        raise ValueError("active-offer rule differs from the frozen rule")
    alpha_search = _gate_mapping(config, "alpha_search")
    if (
        not _gate_is_number(alpha_search.get("coarse_step"))
        or float(alpha_search.get("coarse_step")) != 0.02
        or not _gate_is_number(alpha_search.get("refine_tolerance"))
        or float(alpha_search.get("refine_tolerance")) != 0.002
    ):
        raise ValueError("alpha search settings differ from the frozen settings")
    formal = _gate_mapping(config, "formal_constraints")
    expected_formal = {
        "vmin_pu": 0.95,
        "vmax_pu": 1.06,
        "vuf_limit_pct": 2.0,
        "transformer_loading_limit_pu": 1.0,
        "feeder_loading_limit_pu": 1.0,
        "line_thermal_in_scope": False,
    }
    if dict(formal) != expected_formal:
        raise ValueError("formal constraints differ from the frozen constraints")
    online = _gate_mapping(config, "online_latency")
    thresholds = _gate_mapping(config, "scientific_gate_thresholds")
    baseline = _gate_mapping(thresholds, "baseline")
    active_gate = _gate_mapping(thresholds, "active_offer")
    core = _gate_mapping(thresholds, "core_bad_alpha")
    dominance = _gate_mapping(thresholds, "dominance")
    direction_duration = _gate_mapping(thresholds, "direction_duration")
    tie = _gate_mapping(thresholds, "tie_rescue")
    warm = _gate_mapping(thresholds, "warm_timing")

    frozen_numbers = (
        (active, "minimum_kw", 7.2),
        (active, "feeder_fraction", 0.005),
        (online, "budget_seconds", 5.0),
        (online, "direct_audit_material_threshold_seconds", 1.0),
        (baseline, "pass_count", 8),
        (baseline, "warn_count", 7),
        (baseline, "hard_stop_max_count", 6),
        (active_gate, "pass_min_proportion", 0.75),
        (active_gate, "warn_min_proportion", 0.5),
        (core, "bad_if_below", 0.95),
        (core, "pass_min_bad_rate", 0.1),
        (core, "pass_min_bad_count", 4),
        (core, "pass_min_bad_scenarios", 3),
        (core, "hard_no_go_bad_rate_below", 0.05),
        (core, "hard_no_go_bad_count_max", 1),
        (dominance, "pass_max", 0.5),
        (dominance, "hard_above", 0.7),
        (thresholds, "material_delta", 0.05),
        (direction_duration, "pass_min_proportion", 0.25),
        (direction_duration, "drop_below", 0.1),
        (tie, "pivot_min", 0.8),
        (tie, "total_bad_max", 0.05),
        (tie, "new_unsafe_max", 0.05),
        (tie, "offer_retention_min", 0.995),
        (warm, "repeats", 3),
        (warm, "cv_pass_max", 0.2),
        (warm, "cv_indeterminate_above", 0.3),
    )
    normalized: dict[tuple[int, str], float] = {}
    for owner, name, frozen in frozen_numbers:
        raw_value = owner.get(name)
        value = _gate_required_number(raw_value, name)
        if (
            isinstance(frozen, int)
            and not _gate_is_int(raw_value)
            or isinstance(frozen, float)
            and not isinstance(raw_value, float)
            or value != float(frozen)
        ):
            raise ValueError(f"{name} differs from the frozen threshold {frozen}")
        normalized[(id(owner), name)] = value
    if core.get("hard_no_go_logic") != "or":
        raise ValueError("core hard no-go logic must be 'or'")

    minimum_kw = normalized[(id(active), "minimum_kw")]
    feeder_fraction = normalized[(id(active), "feeder_fraction")]
    expected_work_units = [
        f"v20_work_{scenario_id}__{direction}"
        for scenario_id in scenario_ids
        for direction in directions
    ]
    expected_evaluations = [
        f"v20_core_{scenario_id}__{direction}__{duration}m"
        for scenario_id in scenario_ids
        for direction in directions
        for duration in durations
    ]
    return {
        "protocol_version": config["protocol_version"],
        "scenario_ids": scenario_ids,
        "feeders": feeders,
        "call_times": call_times,
        "directions": directions,
        "durations": durations,
        "scenario_design": normalized_design,
        "feeder_kva": normalized_kva,
        "active_thresholds": {
            feeder: max(minimum_kw, feeder_fraction * normalized_kva[feeder])
            for feeder in feeders
        },
        "expected_work_units": expected_work_units,
        "expected_evaluations": expected_evaluations,
        "baseline_pass_count": int(
            normalized[(id(baseline), "pass_count")]
        ),
        "baseline_warn_count": int(
            normalized[(id(baseline), "warn_count")]
        ),
        "baseline_hard_max": int(
            normalized[(id(baseline), "hard_stop_max_count")]
        ),
        "active_pass": normalized[
            (id(active_gate), "pass_min_proportion")
        ],
        "active_warn": normalized[
            (id(active_gate), "warn_min_proportion")
        ],
        "bad_below": normalized[(id(core), "bad_if_below")],
        "core_pass_rate": normalized[(id(core), "pass_min_bad_rate")],
        "core_pass_count": int(
            normalized[(id(core), "pass_min_bad_count")]
        ),
        "core_pass_scenarios": int(
            normalized[(id(core), "pass_min_bad_scenarios")]
        ),
        "core_hard_rate": normalized[
            (id(core), "hard_no_go_bad_rate_below")
        ],
        "core_hard_count": int(
            normalized[(id(core), "hard_no_go_bad_count_max")]
        ),
        "dominance_pass": normalized[(id(dominance), "pass_max")],
        "dominance_hard": normalized[(id(dominance), "hard_above")],
        "material_delta": normalized[(id(thresholds), "material_delta")],
        "claim_pass": normalized[
            (id(direction_duration), "pass_min_proportion")
        ],
        "claim_drop": normalized[(id(direction_duration), "drop_below")],
        "tie_pivot": normalized[(id(tie), "pivot_min")],
        "tie_total_bad": normalized[(id(tie), "total_bad_max")],
        "tie_new_unsafe": normalized[(id(tie), "new_unsafe_max")],
        "tie_offer_retention": normalized[
            (id(tie), "offer_retention_min")
        ],
        "timing_repeats": int(normalized[(id(warm), "repeats")]),
        "timing_cv_pass": normalized[(id(warm), "cv_pass_max")],
        "timing_cv_indeterminate": normalized[
            (id(warm), "cv_indeterminate_above")
        ],
        "direct_material_seconds": normalized[
            (id(online), "direct_audit_material_threshold_seconds")
        ],
        "direct_budget_seconds": normalized[(id(online), "budget_seconds")],
    }


def _gate_validate_evidence(
    evidence: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[list[tuple[str, str]], list[Mapping[str, Any]]]:
    errors: list[tuple[str, str]] = []
    if not isinstance(evidence, Mapping):
        return [("EVIDENCE_SCHEMA_INVALID", "evidence must be a mapping")], []

    loader = evidence.get("loader_validation")
    if not isinstance(loader, Mapping):
        errors.append(
            ("LOADER_VALIDATION_FAILED", "loader_validation must be a mapping")
        )
    else:
        loader_errors = loader.get("errors")
        if (
            loader.get("status") != "VALID"
            or not isinstance(loader_errors, list)
            or any(not isinstance(item, str) for item in loader_errors)
            or bool(loader_errors)
        ):
            errors.append(
                ("LOADER_VALIDATION_FAILED", "loader did not report clean VALID")
            )

    for field, reason in (
        ("active_lock_files", "ACTIVE_LOCK_FILES_PRESENT"),
        ("attempt_state_files", "ATTEMPT_STATE_FILES_PRESENT"),
        ("temporary_files", "TEMPORARY_FILES_PRESENT"),
        ("unexpected_raw_files", "UNEXPECTED_RAW_FILES_PRESENT"),
    ):
        paths = evidence.get(field)
        if field == "temporary_files" and paths is None:
            paths = []
        if not isinstance(paths, list) or any(
            not isinstance(item, str) for item in paths
        ):
            errors.append(("EVIDENCE_SCHEMA_INVALID", f"{field} must be a string list"))
        elif paths:
            errors.append((reason, f"{field} is nonempty"))

    expected_work_ids = _gate_validate_id_vector(
        evidence.get("expected_work_unit_ids"),
        "expected_work_unit_ids",
        errors,
    )
    actual_work_ids = _gate_validate_id_vector(
        evidence.get("actual_work_unit_ids"),
        "actual_work_unit_ids",
        errors,
    )
    expected_eval_ids = _gate_validate_id_vector(
        evidence.get("expected_evaluation_ids"),
        "expected_evaluation_ids",
        errors,
    )
    actual_eval_ids = _gate_validate_id_vector(
        evidence.get("actual_evaluation_ids"),
        "actual_evaluation_ids",
        errors,
    )
    frozen_work_ids = list(context["expected_work_units"])
    frozen_eval_ids = list(context["expected_evaluations"])
    if not _gate_exact_id_set(expected_work_ids, frozen_work_ids):
        errors.append(
            ("WORK_UNIT_ID_SET_MISMATCH", "expected work-unit IDs differ from config")
        )
    if not _gate_exact_id_set(actual_work_ids, frozen_work_ids):
        errors.append(
            ("WORK_UNIT_ID_SET_MISMATCH", "actual work-unit IDs differ from config")
        )
    if not _gate_exact_id_set(expected_eval_ids, frozen_eval_ids):
        errors.append(
            ("EVALUATION_ID_SET_MISMATCH", "expected evaluation IDs differ from config")
        )
    if not _gate_exact_id_set(actual_eval_ids, frozen_eval_ids):
        errors.append(
            ("EVALUATION_ID_SET_MISMATCH", "actual evaluation IDs differ from config")
        )

    work_units_raw = evidence.get("work_units")
    if not isinstance(work_units_raw, list):
        errors.append(("WORK_UNIT_SCHEMA_INVALID", "work_units must be a list"))
        work_units_raw = []
    if len(work_units_raw) != 16:
        errors.append(
            ("WORK_UNIT_COUNT_INVALID", f"expected 16 work units, got {len(work_units_raw)}")
        )
    evaluations_raw = evidence.get("evaluations")
    if not isinstance(evaluations_raw, list):
        errors.append(("EVALUATION_SCHEMA_INVALID", "evaluations must be a list"))
        evaluations_raw = []
    if len(evaluations_raw) != 48:
        errors.append(
            (
                "EVALUATION_COUNT_INVALID",
                f"expected 48 evaluations, got {len(evaluations_raw)}",
            )
        )

    rows: list[Mapping[str, Any]] = []
    flat_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(evaluations_raw):
        if not isinstance(raw, Mapping):
            errors.append(
                ("EVALUATION_SCHEMA_INVALID", f"evaluation {index} is not a mapping")
            )
            continue
        rows.append(raw)
        evaluation_id = raw.get("evaluation_id")
        if not isinstance(evaluation_id, str) or not evaluation_id:
            errors.append(
                (
                    "EVALUATION_SCHEMA_INVALID",
                    f"evaluation {index} lacks a string evaluation_id",
                )
            )
        elif evaluation_id in flat_by_id:
            errors.append(
                ("EVALUATION_ID_SET_MISMATCH", f"duplicate {evaluation_id}")
            )
        else:
            flat_by_id[evaluation_id] = raw
        _gate_validate_row_identity(raw, context, errors)

    if set(flat_by_id) != set(frozen_eval_ids):
        errors.append(
            (
                "EVALUATION_ID_SET_MISMATCH",
                "flattened evaluation IDs differ from the frozen design",
            )
        )
    if actual_eval_ids and set(flat_by_id) != set(actual_eval_ids):
        errors.append(
            (
                "EVALUATION_ID_SET_MISMATCH",
                "actual evaluation IDs differ from flattened rows",
            )
        )

    wrapper_by_id: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(work_units_raw):
        if not isinstance(raw, Mapping):
            errors.append(
                ("WORK_UNIT_SCHEMA_INVALID", f"work unit {index} is not a mapping")
            )
            continue
        work_unit_id = raw.get("work_unit_id")
        if not isinstance(work_unit_id, str) or not work_unit_id:
            errors.append(
                (
                    "WORK_UNIT_SCHEMA_INVALID",
                    f"work unit {index} lacks a string work_unit_id",
                )
            )
            continue
        if work_unit_id in wrapper_by_id:
            errors.append(("WORK_UNIT_ID_SET_MISMATCH", f"duplicate {work_unit_id}"))
            continue
        wrapper_by_id[work_unit_id] = raw
        _gate_validate_wrapper(raw, flat_by_id, context, errors)

    if set(wrapper_by_id) != set(frozen_work_ids):
        errors.append(
            (
                "WORK_UNIT_ID_SET_MISMATCH",
                "wrapper work-unit IDs differ from the frozen design",
            )
        )
    if actual_work_ids and set(wrapper_by_id) != set(actual_work_ids):
        errors.append(
            (
                "WORK_UNIT_ID_SET_MISMATCH",
                "actual work-unit IDs differ from wrappers",
            )
        )

    _gate_validate_hash_rows(
        evidence.get("raw_hash_rows"), set(frozen_work_ids), errors
    )
    _gate_validate_baselines(rows, context, errors)
    _gate_validate_scientific_rows(rows, context, errors)
    return errors, rows


def _gate_validate_row_identity(
    row: Mapping[str, Any],
    context: Mapping[str, Any],
    errors: list[tuple[str, str]],
) -> None:
    evaluation_id = row.get("evaluation_id")
    scenario_id = row.get("scenario_id")
    direction = row.get("direction")
    duration = row.get("duration_min")
    label = str(evaluation_id)
    if (
        not isinstance(scenario_id, str)
        or scenario_id not in context["scenario_ids"]
        or not isinstance(direction, str)
        or direction not in context["directions"]
        or not _gate_is_int(duration)
        or duration not in context["durations"]
    ):
        errors.append(
            ("EVALUATION_IDENTITY_INVALID", f"{label} has invalid design coordinates")
        )
        return
    expected_evaluation_id = (
        f"v20_core_{scenario_id}__{direction}__{duration}m"
    )
    expected_work_unit_id = f"v20_work_{scenario_id}__{direction}"
    design = context["scenario_design"][scenario_id]
    if (
        evaluation_id != expected_evaluation_id
        or row.get("work_unit_id") != expected_work_unit_id
        or row.get("protocol_version") != context["protocol_version"]
        or row.get("data_role") != "development_pilot"
        or row.get("feeder") != design["feeder"]
        or row.get("call_time") != design["call_time"]
        or not _gate_is_int(row.get("scenario_seed"))
        or row.get("scenario_seed") != design["scenario_seed"]
        or not _gate_is_int(row.get("requested_duration_min"))
        or row.get("requested_duration_min") != duration
    ):
        errors.append(
            ("EVALUATION_IDENTITY_INVALID", f"{label} differs from frozen identity")
        )
    source_duration = row.get("source_duration_min")
    if not _gate_is_int(source_duration) or source_duration not in context["durations"]:
        errors.append(
            ("EVALUATION_SCHEMA_INVALID", f"{label} has invalid source_duration_min")
        )
    for path_field in ("source_result_file",):
        if path_field in row and not _gate_relative_path(row.get(path_field)):
            errors.append(
                ("EVIDENCE_PATH_INVALID", f"{label} has invalid {path_field}")
            )


def _gate_validate_wrapper(
    wrapper: Mapping[str, Any],
    flat_by_id: Mapping[str, Mapping[str, Any]],
    context: Mapping[str, Any],
    errors: list[tuple[str, str]],
) -> None:
    work_unit_id = str(wrapper.get("work_unit_id"))
    match = re.fullmatch(r"v20_work_(.+)__(inc|dec)", work_unit_id)
    if match is None:
        errors.append(
            ("WORK_UNIT_SCHEMA_INVALID", f"{work_unit_id} has invalid identity")
        )
        return
    scenario_id, direction = match.groups()
    if scenario_id not in context["scenario_design"]:
        errors.append(
            ("WORK_UNIT_SCHEMA_INVALID", f"{work_unit_id} has unknown scenario")
        )
        return
    design = context["scenario_design"][scenario_id]
    if (
        wrapper.get("protocol_version") != context["protocol_version"]
        or wrapper.get("data_role") != "development_pilot"
        or not _gate_is_int(wrapper.get("scenario_seed"))
        or wrapper.get("scenario_seed") != design["scenario_seed"]
        or not _gate_is_int(wrapper.get("attempt_count"))
        or wrapper.get("attempt_count") < 1
        or wrapper.get("attempt_count") > 3
    ):
        errors.append(
            ("WORK_UNIT_SCHEMA_INVALID", f"{work_unit_id} wrapper identity is invalid")
        )
    status = wrapper.get("status")
    if status not in {"SUCCESS", "SCIENTIFIC_TERMINAL"}:
        code = (
            "UNHANDLED_WORK_UNIT_FAILURE"
            if status == "UNHANDLED_FAILURE"
            else "WORK_UNIT_SCHEMA_INVALID"
        )
        errors.append((code, f"{work_unit_id} has terminal status {status!r}"))
    evaluations = wrapper.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != 3:
        errors.append(
            ("WORK_UNIT_SCHEMA_INVALID", f"{work_unit_id} must contain 3 evaluations")
        )
        return
    expected_ids = {
        f"v20_core_{scenario_id}__{direction}__{duration}m"
        for duration in context["durations"]
    }
    wrapper_ids: list[str] = []
    row_statuses: list[Any] = []
    for wrapped in evaluations:
        if not isinstance(wrapped, Mapping):
            errors.append(
                ("WORK_UNIT_SCHEMA_INVALID", f"{work_unit_id} contains a non-mapping row")
            )
            continue
        evaluation_id = wrapped.get("evaluation_id")
        if not isinstance(evaluation_id, str):
            errors.append(
                ("WORK_UNIT_SCHEMA_INVALID", f"{work_unit_id} row lacks evaluation_id")
            )
            continue
        wrapper_ids.append(evaluation_id)
        row_statuses.append(wrapped.get("status"))
        flat = flat_by_id.get(evaluation_id)
        if flat is None:
            errors.append(
                (
                    "WORK_UNIT_EVALUATION_LINK_INVALID",
                    f"{evaluation_id} is absent from flattened evaluations",
                )
            )
            continue
        for key, value in wrapped.items():
            if key not in flat or flat[key] != value:
                errors.append(
                    (
                        "WORK_UNIT_EVALUATION_LINK_INVALID",
                        f"{evaluation_id} differs between wrapper and flattened row",
                    )
                )
                break
        if flat.get("work_unit_id") != work_unit_id:
            errors.append(
                (
                    "WORK_UNIT_EVALUATION_LINK_INVALID",
                    f"{evaluation_id} links to the wrong work unit",
                )
            )
        if "work_unit_status" in flat and flat.get("work_unit_status") != status:
            errors.append(
                (
                    "WORK_UNIT_EVALUATION_LINK_INVALID",
                    f"{evaluation_id} has inconsistent work_unit_status",
                )
            )
    if len(wrapper_ids) != len(set(wrapper_ids)) or set(wrapper_ids) != expected_ids:
        errors.append(
            (
                "WORK_UNIT_EVALUATION_LINK_INVALID",
                f"{work_unit_id} evaluation IDs differ from the frozen triplet",
            )
        )
    expected_status = (
        "SUCCESS"
        if len(row_statuses) == 3
        and all(item == "SUCCESS" for item in row_statuses)
        else "SCIENTIFIC_TERMINAL"
    )
    if status in {"SUCCESS", "SCIENTIFIC_TERMINAL"} and status != expected_status:
        errors.append(
            (
                "WORK_UNIT_STATUS_INCONSISTENT",
                f"{work_unit_id} status differs from its evaluation statuses",
            )
        )


def _gate_validate_hash_rows(
    raw_hash_rows: Any,
    expected_work_ids: set[str],
    errors: list[tuple[str, str]],
) -> None:
    if not isinstance(raw_hash_rows, list):
        errors.append(("RAW_HASH_ROWS_INVALID", "raw_hash_rows must be a list"))
        return
    if len(raw_hash_rows) != len(expected_work_ids):
        errors.append(
            (
                "RAW_HASH_ROWS_INVALID",
                f"expected {len(expected_work_ids)} hash rows, got {len(raw_hash_rows)}",
            )
        )
    observed: set[str] = set()
    observed_hashes: set[str] = set()
    observed_paths: set[str] = set()
    for index, item in enumerate(raw_hash_rows):
        if not isinstance(item, Mapping):
            errors.append(
                ("RAW_HASH_ROWS_INVALID", f"hash row {index} is not a mapping")
            )
            continue
        work_unit_id = item.get("work_unit_id")
        if (
            not isinstance(work_unit_id, str)
            or work_unit_id not in expected_work_ids
            or work_unit_id in observed
        ):
            errors.append(
                ("RAW_HASH_ROWS_INVALID", f"hash row {index} has invalid work_unit_id")
            )
        else:
            observed.add(work_unit_id)
        hash_value = next(
            (
                item.get(name)
                for name in (
                    "sha256",
                    "raw_sha256",
                    "result_sha256",
                    "file_sha256",
                )
                if name in item
            ),
            None,
        )
        if (
            not isinstance(hash_value, str)
            or _GATE_SHA256.fullmatch(hash_value) is None
            or hash_value in observed_hashes
        ):
            errors.append(
                ("RAW_HASH_ROWS_INVALID", f"hash row {index} has invalid SHA-256")
            )
        else:
            observed_hashes.add(hash_value)
        for name in ("source_result_file", "path", "relative_path"):
            if name in item:
                path_value = item.get(name)
                if not _gate_relative_path(path_value):
                    errors.append(
                        ("EVIDENCE_PATH_INVALID", f"hash row {index} has invalid {name}")
                    )
                elif path_value in observed_paths:
                    errors.append(
                        ("RAW_HASH_ROWS_INVALID", f"hash row {index} duplicates a path")
                    )
                else:
                    observed_paths.add(path_value)
    if observed != expected_work_ids:
        errors.append(
            (
                "RAW_HASH_ROWS_INVALID",
                "hash-row work-unit IDs do not close the frozen 16-unit set",
            )
        )


def _gate_validate_baselines(
    rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
    errors: list[tuple[str, str]],
) -> None:
    by_scenario: dict[str, list[Mapping[str, Any]]] = {
        scenario_id: [] for scenario_id in context["scenario_ids"]
    }
    for row in rows:
        scenario_id = row.get("scenario_id")
        if scenario_id in by_scenario:
            by_scenario[scenario_id].append(row)
    for scenario_id, scenario_rows in by_scenario.items():
        if len(scenario_rows) != 6:
            errors.append(
                (
                    "BASELINE_IDENTITY_INVALID",
                    f"{scenario_id} does not have six baseline-linked rows",
                )
            )
            continue
        statuses = {row.get("baseline_status") for row in scenario_rows}
        hashes = {row.get("baseline_schedule_sha256") for row in scenario_rows}
        if len(statuses) != 1 or len(hashes) != 1:
            errors.append(
                (
                    "BASELINE_IDENTITY_INVALID",
                    f"{scenario_id} has inconsistent paired baseline evidence",
                )
            )
        baseline_hash = next(iter(hashes), None)
        if (
            not isinstance(baseline_hash, str)
            or _GATE_SHA256.fullmatch(baseline_hash) is None
        ):
            errors.append(
                ("BASELINE_IDENTITY_INVALID", f"{scenario_id} has invalid baseline hash")
            )
        signatures = set()
        for row in scenario_rows:
            status = row.get("baseline_status")
            audit = row.get("baseline_audit")
            signature = _gate_baseline_signature(status, audit)
            if signature is None:
                code = (
                    "BASELINE_NUMERICAL_EVIDENCE_INVALID"
                    if status == "BASELINE_NUMERICAL_INVALID"
                    else "BASELINE_EVIDENCE_INVALID"
                )
                errors.append((code, f"{row.get('evaluation_id')} baseline is invalid"))
            else:
                signatures.add(signature)
        if len(signatures) > 1:
            errors.append(
                (
                    "BASELINE_IDENTITY_INVALID",
                    f"{scenario_id} baseline audit summaries disagree",
                )
            )


def _gate_baseline_signature(status: Any, audit: Any) -> tuple[Any, ...] | None:
    if status not in {"VALID", "BASELINE_PHYSICAL_INVALID"}:
        return None
    if not isinstance(audit, Mapping):
        return None
    required_ints = (
        "checked_intervals",
        "power_flow_evaluations",
        "reused_baseline_intervals",
        "converged_checks",
        "nonconverged_checks",
        "numerical_failure_checks",
        "physical_violation_checks",
        "violation_count",
    )
    if any(not _gate_is_int(audit.get(name)) for name in required_ints):
        return None
    if (
        not isinstance(audit.get("feasible"), bool)
        or not isinstance(audit.get("complete_coverage"), bool)
        or not isinstance(audit.get("explicit_physical_witness"), bool)
        or not _gate_is_number(audit.get("coverage_ratio"))
        or audit.get("checked_intervals") != 96
        or audit.get("complete_coverage") is not True
        or not math.isclose(
            float(audit.get("coverage_ratio")), 1.0, rel_tol=0.0, abs_tol=1e-12
        )
        or audit.get("nonconverged_checks") != 0
        or audit.get("numerical_failure_checks") != 0
        or audit.get("power_flow_evaluations") != 96
        or audit.get("reused_baseline_intervals") != 0
        or audit.get("converged_checks") != 96
        or not _gate_baseline_slot_trace_valid(status, audit)
        or not _gate_compact_coverage_valid(audit.get("coverage_counts"))
        or any(
            not _gate_is_number(audit.get(name))
            for name in (
                "vmin",
                "vmax",
                "vufmax",
                "transformer_loading_max",
                "feeder_loading_max",
            )
        )
        or not _gate_baseline_extrema_valid(status, audit)
    ):
        return None
    if status == "VALID":
        if (
            audit.get("feasible") is not True
            or audit.get("failure_class") != "NONE"
            or audit.get("physical_violation_checks") != 0
            or audit.get("explicit_physical_witness") is not False
        ):
            return None
    else:
        if (
            audit.get("feasible") is not False
            or audit.get("failure_class") != "PHYSICAL_CONSTRAINT"
            or audit.get("physical_violation_checks") < 1
            or audit.get("explicit_physical_witness") is not True
        ):
            return None
    return (
        status,
        audit.get("feasible"),
        audit.get("checked_intervals"),
        audit.get("complete_coverage"),
        audit.get("nonconverged_checks"),
        audit.get("numerical_failure_checks"),
        audit.get("physical_violation_checks"),
        audit.get("failure_class"),
        audit.get("explicit_physical_witness"),
    )


def _gate_baseline_extrema_valid(
    status: str,
    audit: Mapping[str, Any],
) -> bool:
    vmin = float(audit["vmin"])
    vmax = float(audit["vmax"])
    vuf = float(audit["vufmax"])
    transformer = float(audit["transformer_loading_max"])
    feeder = float(audit["feeder_loading_max"])
    if (
        vmin > vmax
        or vuf < 0
        or transformer < 0
        or feeder < 0
    ):
        return False
    within_limits = bool(
        vmin >= 0.95
        and vmax <= 1.06
        and vuf <= 2.0
        and transformer <= 1.0
        and feeder <= 1.0
    )
    return within_limits if status == "VALID" else not within_limits


def _gate_baseline_slot_trace_valid(
    status: str,
    audit: Mapping[str, Any],
) -> bool:
    trace = audit.get("slot_trace")
    if not isinstance(trace, list) or len(trace) != 96:
        return False
    witnessed_slots: list[int] = []
    for expected_slot, item in enumerate(trace):
        if not isinstance(item, Mapping):
            return False
        if (
            not _gate_is_int(item.get("slot"))
            or item.get("slot") != expected_slot
            or not isinstance(item.get("feasible"), bool)
            or item.get("converged") is not True
            or item.get("numerical_failure") is not False
            or not isinstance(item.get("physical_witness"), bool)
            or item.get("failure_class")
            not in {"NONE", "PHYSICAL_CONSTRAINT"}
        ):
            return False
        if item.get("physical_witness") is True:
            if (
                item.get("feasible") is not False
                or item.get("failure_class") != "PHYSICAL_CONSTRAINT"
            ):
                return False
            witnessed_slots.append(expected_slot)
        elif (
            item.get("feasible") is not True
            or item.get("failure_class") != "NONE"
        ):
            return False
    if status == "VALID":
        return bool(
            not witnessed_slots
            and audit.get("physical_violation_checks") == 0
            and audit.get("violation_count") == 0
            and audit.get("first_failure_slot") is None
        )
    return bool(
        witnessed_slots
        and len(witnessed_slots) == audit.get("physical_violation_checks")
        == audit.get("violation_count")
        and audit.get("first_failure_slot") == min(witnessed_slots)
    )


def _gate_compact_coverage_valid(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    count_names = (
        "all_bus_count",
        "monitored_bus_count",
        "energized_voltage_node_count",
        "monitored_voltage_node_count",
        "three_phase_bus_count",
        "monitored_vuf_bus_count",
        "enabled_transformer_count",
        "rated_transformer_count",
        "line_count",
    )
    if any(
        not _gate_is_int(value.get(name)) or value.get(name) < 0
        for name in count_names
    ):
        return False
    multiplier = value.get("transformer_rating_multiplier")
    expected_basis = (
        "MAKEPOSSEQ_PER_PHASE_KVA_NORMALIZED_TO_SYSTEM_TOTAL"
        if multiplier == 3.0
        else "NATIVE_SYSTEM_TOTAL_KVA"
    )
    return bool(
        value.get("all_bus_count") > 0
        and value.get("all_bus_count") == value.get("monitored_bus_count")
        and value.get("energized_voltage_node_count") > 0
        and value.get("energized_voltage_node_count")
        == value.get("monitored_voltage_node_count")
        and value.get("three_phase_bus_count")
        == value.get("monitored_vuf_bus_count")
        and value.get("enabled_transformer_count")
        == value.get("rated_transformer_count")
        and _gate_is_number(value.get("transformer_rating_coverage"))
        and math.isclose(
            float(value.get("transformer_rating_coverage")),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and value.get("line_thermal_in_scope") is False
        and _gate_is_number(value.get("feeder_rating_multiplier"))
        and math.isclose(
            float(value.get("feeder_rating_multiplier")),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and multiplier in {1.0, 3.0}
        and value.get("transformer_rating_basis") == expected_basis
        and value.get("transformer_power_basis")
        == "SYSTEM_TOTAL_TERMINAL_POWER"
    )


def _gate_validate_scientific_rows(
    rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
    errors: list[tuple[str, str]],
) -> None:
    for row in rows:
        label = str(row.get("evaluation_id"))
        feeder = row.get("feeder")
        threshold = context["active_thresholds"].get(feeder)
        f_bal = row.get("f_bal_kw")
        declared_threshold = row.get("active_offer_threshold_kw")
        active = row.get("active_offer")
        if (
            threshold is None
            or not _gate_is_number(f_bal)
            or float(f_bal) < 0
            or not _gate_is_number(declared_threshold)
            or not math.isclose(
                float(declared_threshold),
                float(threshold),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not isinstance(active, bool)
            or active is not bool(float(f_bal) >= float(threshold))
        ):
            errors.append(
                ("ACTIVE_OFFER_EVIDENCE_INVALID", f"{label} active offer is invalid")
            )
            continue
        schedule_hash = row.get("schedule_sha256")
        bus_phase_hash = row.get("bus_phase_time_sha256")
        if (
            not isinstance(schedule_hash, str)
            or _GATE_SHA256.fullmatch(schedule_hash) is None
            or not isinstance(bus_phase_hash, str)
            or _GATE_SHA256.fullmatch(bus_phase_hash) is None
        ):
            errors.append(
                ("SCHEDULE_HASH_INVALID", f"{label} schedule hashes are invalid")
            )
        if not _gate_schedule_invariants_valid(row):
            errors.append(
                (
                    "SCHEDULE_INVARIANT_INVALID",
                    f"{label} selected schedule invariants are invalid",
                )
            )

        baseline_valid = row.get("baseline_status") == "VALID"
        if not baseline_valid or not active:
            if not _gate_non_denominator_row_valid(
                row, baseline_valid=baseline_valid, active=active
            ):
                errors.append(
                    (
                        "NULL_SEMANTICS_INVALID",
                        f"{label} non-denominator fields are inconsistent",
                    )
                )
            continue

        if row.get("status") in {
            "ALPHA_PATH_NUMERICAL_INVALID",
            "BASELINE_NUMERICAL_INVALID",
        }:
            errors.append(
                (
                    "CORE_NUMERICAL_EVIDENCE_INVALID",
                    f"{label} reports numerical invalidity",
                )
            )
            continue
        if row.get("status") != "SUCCESS":
            errors.append(
                (
                    "CORE_PATH_EVIDENCE_INVALID",
                    f"{label} has invalid core status {row.get('status')!r}",
                )
            )
            continue
        if (
            row.get("scientific_status") != "VALID"
            or row.get("eligible_for_scientific_denominator") is not True
            or row.get("alpha_path_status") != "VALID"
            or row.get("alpha_path_valid_baseline") is not True
            or row.get("alpha_path_scientific_valid") is not True
            or not isinstance(row.get("alpha_nonmonotone"), bool)
        ):
            errors.append(
                ("CORE_PATH_EVIDENCE_INVALID", f"{label} path flags are invalid")
            )
            continue
        alpha = row.get("alpha_transfer")
        prefix = row.get("alpha_prefix")
        alpha_sup = row.get("alpha_sup")
        if (
            not _gate_unit_interval(alpha)
            or not _gate_unit_interval(prefix)
            or not _gate_unit_interval(alpha_sup)
            or not math.isclose(
                float(alpha), float(prefix), rel_tol=0.0, abs_tol=1e-12
            )
            or float(alpha_sup) + 1e-12 < float(alpha)
        ):
            errors.append(
                (
                    "CORE_NUMERICAL_EVIDENCE_INVALID",
                    f"{label} corrected alpha is invalid",
                )
            )
            continue
        path_valid, path_numerical = _gate_path_evidence_valid(
            row.get("alpha_path_audit"),
            float(alpha),
            float(alpha_sup),
            bool(row.get("alpha_nonmonotone")),
        )
        if not path_valid:
            errors.append(
                (
                    (
                        "CORE_NUMERICAL_EVIDENCE_INVALID"
                        if path_numerical
                        else "CORE_PATH_EVIDENCE_INVALID"
                    ),
                    f"{label} corrected alpha path audit is invalid",
                )
            )


def _gate_schedule_invariants_valid(row: Mapping[str, Any]) -> bool:
    component_names = (
        "max_departure_error_kwh",
        "max_reserve_violation_kwh",
        "max_capacity_violation_kwh",
        "max_discharge_budget_violation_kwh",
        "max_availability_violation_kw",
        "max_charge_limit_violation_kw",
        "max_discharge_limit_violation_kw",
        "max_schedule_identity_error_kw",
    )
    error_names = (*component_names, "max_ev_invariant_error")
    if (
        any(
            not _gate_is_number(row.get(name))
            or float(row.get(name)) < 0
            or float(row.get(name)) > 1e-6
            for name in error_names
        )
        or not _gate_is_int(row.get("simultaneous_slots"))
        or row.get("simultaneous_slots") != 0
        or not isinstance(row.get("monotonic_closure_promoted"), bool)
        or not isinstance(row.get("canonical_schedule_reused"), bool)
    ):
        return False
    combined = row.get("ev_invariant_errors")
    reported = row.get("reported_ev_invariant_errors")
    derived = row.get("derived_ev_invariant_errors")
    full_keys = {*component_names, "max_ev_invariant_error", "simultaneous_slots"}
    reported_keys = {
        "max_departure_error_kwh",
        "max_reserve_violation_kwh",
        "max_capacity_violation_kwh",
        "max_ev_invariant_error",
        "simultaneous_slots",
    }
    if (
        not isinstance(combined, Mapping)
        or set(combined) != full_keys
        or not isinstance(derived, Mapping)
        or set(derived) != full_keys
        or not isinstance(reported, Mapping)
        or set(reported) != reported_keys
    ):
        return False
    for values, names in (
        (combined, error_names),
        (derived, error_names),
        (
            reported,
            (
                "max_departure_error_kwh",
                "max_reserve_violation_kwh",
                "max_capacity_violation_kwh",
                "max_ev_invariant_error",
            ),
        ),
    ):
        if any(
            not _gate_is_number(values.get(name))
            or float(values.get(name)) < 0
            or float(values.get(name)) > 1e-6
            for name in names
        ):
            return False
        if (
            not _gate_is_int(values.get("simultaneous_slots"))
            or values.get("simultaneous_slots") != 0
        ):
            return False
    reported_components = (
        "max_departure_error_kwh",
        "max_reserve_violation_kwh",
        "max_capacity_violation_kwh",
    )
    if float(reported["max_ev_invariant_error"]) != max(
        float(reported[name]) for name in reported_components
    ):
        return False
    if float(derived["max_ev_invariant_error"]) != max(
        float(derived[name]) for name in component_names
    ):
        return False
    for name in component_names:
        expected = float(derived[name])
        if name in reported_components:
            expected = max(expected, float(reported[name]))
        if (
            float(combined[name]) != expected
            or float(row[name]) != expected
        ):
            return False
    expected_maximum = max(float(combined[name]) for name in component_names)
    return bool(
        float(combined["max_ev_invariant_error"]) == expected_maximum
        and float(row["max_ev_invariant_error"]) == expected_maximum
    )


def _gate_non_denominator_row_valid(
    row: Mapping[str, Any],
    *,
    baseline_valid: bool,
    active: bool,
) -> bool:
    expected_status = (
        "INACTIVE_OFFER" if baseline_valid and not active else "BASELINE_PHYSICAL_INVALID"
    )
    expected_scientific_status = (
        "NOT_APPLICABLE_INACTIVE"
        if baseline_valid and not active
        else "INVALID_BASELINE"
    )
    expected_tie_status = (
        "NOT_APPLICABLE_INACTIVE"
        if baseline_valid and not active
        else "NOT_RUN_BASELINE_INVALID"
    )
    if (
        row.get("status") != expected_status
        or row.get("scientific_status") != expected_scientific_status
        or row.get("tie_break_status") != expected_tie_status
        or row.get("eligible_for_scientific_denominator") is not False
    ):
        return False
    null_fields = (
        "alpha_legacy_verifier",
        "alpha_transfer",
        "alpha_prefix",
        "alpha_sup",
        "alpha_nonmonotone",
        "alpha_transfer_tied",
        "tie_comparator_valid",
        "alpha1_cold_timing_s",
        "alpha1_first_replay_timing_s",
        "alpha1_warm_p95_s",
        "alpha1_warm_cv",
        "alpha1_cold_timing_scope",
        "alpha1_first_replay_scope",
        "alpha_legacy_verifier_status",
        "alpha_legacy_verifier_detail",
        "alpha_path_status",
        "alpha_path_valid_baseline",
        "alpha_path_scientific_valid",
        "alpha_path_audit",
        "alpha1_timing_status",
        "alpha1_timing_detail",
        "alpha1_timing_checked_intervals",
        "alpha1_timing_power_flow_evaluations",
        "alpha1_timing_numerical_failure_checks",
        "alpha1_timing_nonconverged_checks",
        "alpha1_timing_physical_violation_checks",
        "alpha1_timing_failure_class",
        "tie_original_schedule_sha256",
        "tie_schedule_sha256",
        "tie_offer_retention",
        "alpha_tie_prefix",
        "alpha_tie_sup",
        "alpha_tie_nonmonotone",
        "alpha_tie_path_status",
        "alpha_tie_path_audit",
    )
    if any(row.get(name) is not None for name in null_fields):
        return False
    return row.get("alpha1_warm_timing_s") == []


def _gate_path_evidence_valid(
    audit: Any,
    alpha_prefix: float,
    alpha_sup: float,
    declared_nonmonotone: bool,
) -> tuple[bool, bool]:
    if not isinstance(audit, Mapping):
        return False, False
    trace = audit.get("alpha_trace")
    audit_calls = audit.get("audit_calls")
    if (
        not isinstance(trace, list)
        or not trace
        or not _gate_is_int(audit_calls)
        or audit_calls != len(trace)
        or not _gate_is_int(audit.get("power_flow_evaluations"))
        or audit.get("power_flow_evaluations") < 0
        or not _gate_is_int(audit.get("reused_baseline_intervals"))
        or audit.get("reused_baseline_intervals") < 0
    ):
        return False, False
    normalized: list[tuple[float, bool, int, bool]] = []
    numerical = False
    seen_alpha: dict[float, bool] = {}
    for item in trace:
        if not isinstance(item, Mapping):
            return False, numerical
        value = item.get("alpha")
        feasible = item.get("feasible")
        checked = item.get("checked_intervals")
        complete = item.get("complete_coverage")
        numerical_checks = item.get("numerical_failure_checks")
        nonconverged = item.get("nonconverged_checks")
        physical = item.get("physical_violation_checks")
        failure_class = item.get("failure_class")
        first_failure_slot = item.get("first_failure_slot")
        if (
            not _gate_unit_interval(value)
            or not isinstance(feasible, bool)
            or not _gate_is_int(checked)
            or checked < 1
            or checked > 96
            or not isinstance(complete, bool)
            or complete is not (checked == 96)
            or not _gate_is_int(numerical_checks)
            or numerical_checks < 0
            or not _gate_is_int(nonconverged)
            or nonconverged < 0
            or not _gate_is_int(physical)
            or physical < 0
            or not isinstance(failure_class, str)
        ):
            return False, numerical
        if (
            numerical_checks > 0
            or nonconverged > 0
            or failure_class in {"NUMERICAL_INVALID", "UNCLASSIFIED_INVALID"}
        ):
            numerical = True
        if feasible:
            if (
                checked != 96
                or complete is not True
                or failure_class != "NONE"
                or physical != 0
                or first_failure_slot is not None
            ):
                return False, numerical
        elif (
            failure_class != "PHYSICAL_CONSTRAINT"
            or physical < 1
            or not _gate_is_int(first_failure_slot)
            or first_failure_slot < 0
            or first_failure_slot >= checked
        ):
            return False, numerical
        numeric_alpha = float(value)
        if numeric_alpha in seen_alpha:
            return False, numerical
        seen_alpha[numeric_alpha] = feasible
        normalized.append((numeric_alpha, feasible, checked, complete))
    if numerical:
        return False, True
    ordered = sorted(normalized, key=lambda item: item[0])
    if (
        not math.isclose(ordered[0][0], 0.0, rel_tol=0.0, abs_tol=1e-12)
        or ordered[0][1] is not True
        or ordered[0][2] != 96
    ):
        return False, False
    prefix = None
    failure_seen = False
    nonmonotone = False
    feasible_values: list[float] = []
    for value, feasible, _, _ in ordered:
        if feasible:
            feasible_values.append(value)
            if failure_seen:
                nonmonotone = True
            else:
                prefix = value
        else:
            failure_seen = True
    if prefix is None or not feasible_values:
        return False, False
    if (
        not math.isclose(prefix, alpha_prefix, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(
            max(feasible_values), alpha_sup, rel_tol=0.0, abs_tol=1e-12
        )
        or nonmonotone is not declared_nonmonotone
    ):
        return False, False
    required_counts = (
        "complete_audits",
        "early_stopped_audits",
        "numerical_failure_audits",
        "physical_boundary_audits",
        "minimum_checked_intervals",
        "maximum_checked_intervals",
    )
    if any(not _gate_is_int(audit.get(name)) for name in required_counts):
        return False, False
    if (
        audit.get("power_flow_evaluations")
        + audit.get("reused_baseline_intervals")
        != sum(item[2] for item in normalized)
        or
        audit.get("complete_audits") != sum(item[3] for item in normalized)
        or audit.get("early_stopped_audits")
        != sum(not item[3] for item in normalized)
        or audit.get("numerical_failure_audits") != 0
        or audit.get("physical_boundary_audits")
        != sum(
            isinstance(item, Mapping)
            and _gate_is_int(item.get("physical_violation_checks"))
            and item.get("physical_violation_checks") > 0
            for item in trace
        )
        or audit.get("minimum_checked_intervals")
        != min(item[2] for item in normalized)
        or audit.get("maximum_checked_intervals")
        != max(item[2] for item in normalized)
    ):
        return False, False
    return True, False


def _gate_scientific_decision(
    rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: set[str] = set()
    actions: set[str] = set()
    metrics: dict[str, Any] = {}

    scenario_baseline_valid = {
        scenario_id: all(
            row.get("baseline_status") == "VALID"
            for row in rows
            if row.get("scenario_id") == scenario_id
        )
        for scenario_id in context["scenario_ids"]
    }
    baseline_count = sum(scenario_baseline_valid.values())
    metrics["baseline_coverage"] = _gate_ratio_metric(
        baseline_count, len(context["scenario_ids"])
    )
    if baseline_count >= context["baseline_pass_count"]:
        baseline_status = "PASS_ALL_BASELINES"
    elif baseline_count >= context["baseline_warn_count"]:
        baseline_status = "WARN_REPEAT_BASELINE_COVERAGE"
        reasons.add("BASELINE_COVERAGE_WARNING")
    else:
        baseline_status = "HARD_STOP_BASELINE_COVERAGE"
        reasons.add("BASELINE_COVERAGE_HARD_STOP")

    active_rows = [row for row in rows if row.get("active_offer") is True]
    active_metric = _gate_ratio_metric(len(active_rows), len(rows))
    metrics["active_offer_coverage"] = active_metric
    if active_metric["rate"] >= context["active_pass"]:
        active_status = "PASS_ACTIVE_COVERAGE"
    elif active_metric["rate"] >= context["active_warn"]:
        active_status = "WARN_REPEAT_ACTIVE_COVERAGE"
        reasons.add("ACTIVE_OFFER_COVERAGE_WARNING")
    else:
        active_status = "NO_GO_LOW_ACTIVE_COVERAGE"
        reasons.add("ACTIVE_OFFER_COVERAGE_NO_GO")

    q_rows = [
        row
        for row in rows
        if row.get("active_offer") is True
        and row.get("baseline_status") == "VALID"
        and row.get("eligible_for_scientific_denominator") is True
    ]
    bad_rows = [
        row
        for row in q_rows
        if float(row["alpha_transfer"]) < context["bad_below"]
    ]
    bad_scenarios = {row["scenario_id"] for row in bad_rows}
    core_metric = _gate_ratio_metric(len(bad_rows), len(q_rows))
    core_metric["unique_bad_scenarios"] = len(bad_scenarios)
    metrics["core_bad_alpha"] = core_metric
    hard_core = bool(
        len(q_rows) == 0
        or core_metric["rate"] < context["core_hard_rate"]
        or len(bad_rows) <= context["core_hard_count"]
    )
    raw_core_go = bool(
        len(q_rows) > 0
        and core_metric["rate"] >= context["core_pass_rate"]
        and len(bad_rows) >= context["core_pass_count"]
        and len(bad_scenarios) >= context["core_pass_scenarios"]
    )
    if hard_core:
        raw_core_status = "NO_GO"
        reasons.add(
            "CORE_DENOMINATOR_EMPTY"
            if not q_rows
            else "CORE_BAD_ALPHA_SIGNAL_NO_GO"
        )
    elif raw_core_go:
        raw_core_status = "GO"
        reasons.add("CORE_BAD_ALPHA_SIGNAL_PRESENT")
    else:
        raw_core_status = "REPEAT_PILOT"
        reasons.add("CORE_BAD_ALPHA_SIGNAL_INDETERMINATE")

    scenario_counts = {
        scenario_id: sum(
            row.get("scenario_id") == scenario_id for row in bad_rows
        )
        for scenario_id in context["scenario_ids"]
    }
    scenario_numerator = max(scenario_counts.values(), default=0)
    scenario_metric = _gate_ratio_metric(scenario_numerator, len(bad_rows))
    scenario_metric["by_scenario"] = scenario_counts
    metrics["scenario_dominance"] = scenario_metric
    if not bad_rows:
        scenario_status = "NOT_APPLICABLE_NO_BAD_ALPHA"
    elif scenario_metric["rate"] <= context["dominance_pass"]:
        scenario_status = "DISTRIBUTED"
    elif scenario_metric["rate"] > context["dominance_hard"]:
        scenario_status = "NO_GO_SCENARIO_DOMINATED"
        reasons.add("BAD_ALPHA_SCENARIO_DOMINATED_NO_GO")
    else:
        scenario_status = "DOMINANCE_REPEAT"
        reasons.add("BAD_ALPHA_SCENARIO_DOMINANCE_REPEAT")

    if raw_core_status == "NO_GO" or scenario_status == "NO_GO_SCENARIO_DOMINATED":
        core_status = "NO_GO"
    elif raw_core_status == "GO" and scenario_status == "DISTRIBUTED":
        core_status = "GO"
    else:
        core_status = "REPEAT_PILOT"

    direction_status, direction_metric = _gate_claim_status(
        _gate_direction_deltas(q_rows, context),
        context,
    )
    metrics["direction_materiality"] = direction_metric
    if direction_status == "DROP_CLAIM":
        actions.add("DROP_DIRECTION_CLAIM")
        reasons.add("DIRECTION_CLAIM_DROPPED")
    elif direction_status == "INDETERMINATE_REPEAT":
        reasons.add("DIRECTION_CLAIM_INDETERMINATE")

    duration_status, duration_metric = _gate_claim_status(
        _gate_duration_deltas(q_rows, context),
        context,
    )
    metrics["duration_materiality"] = duration_metric
    if duration_status == "DROP_CLAIM":
        actions.add("DROP_DURATION_CLAIM")
        reasons.add("DURATION_CLAIM_DROPPED")
    elif duration_status == "INDETERMINATE_REPEAT":
        reasons.add("DURATION_CLAIM_INDETERMINATE")

    feeder_counts = {
        feeder: sum(row.get("feeder") == feeder for row in bad_rows)
        for feeder in context["feeders"]
    }
    feeder_numerator = max(feeder_counts.values(), default=0)
    feeder_metric = _gate_ratio_metric(feeder_numerator, len(bad_rows))
    feeder_metric["by_feeder"] = feeder_counts
    metrics["feeder_bad_alpha"] = feeder_metric
    if raw_core_status != "GO" or scenario_status != "DISTRIBUTED":
        feeder_status = "NOT_ASSESSABLE_CORE_SIGNAL"
    elif feeder_metric["rate"] <= context["dominance_pass"]:
        feeder_status = "REPLICATED"
    elif feeder_metric["rate"] > context["dominance_hard"]:
        feeder_status = "NO_GO_SINGLE_FEEDER_DOMINATED"
        reasons.add("BAD_ALPHA_SINGLE_FEEDER_DOMINATED_NO_GO")
    else:
        feeder_status = "WEAK_REPLICATION_REPEAT"
        reasons.add("BAD_ALPHA_FEEDER_REPLICATION_WEAK")

    tie_status, tie_metrics, tie_reason = _gate_tie_status(
        q_rows, bad_rows, context
    )
    metrics.update(tie_metrics)
    if tie_reason is not None:
        reasons.add(tie_reason)

    screening_status, timing_metric, timing_reason = _gate_screening_status(
        q_rows, context
    )
    metrics["screening_compute"] = timing_metric
    if timing_reason is not None:
        reasons.add(timing_reason)
    if screening_status == "DROP_SCREENING":
        actions.add("DROP_ONLINE_SCREENING")
    elif screening_status == "KEEP_SCREENING_DIRECT_AUDIT_OVER_BUDGET":
        actions.add("REPORT_DIRECT_AUDIT_OVER_BUDGET")

    reuse_status, reuse_metrics, reuse_reason = _gate_reuse_status(
        q_rows, context
    )
    metrics.update(reuse_metrics)
    reasons.add(reuse_reason)
    if reuse_status in {
        "BLOCKED_LABEL_FLIP",
        "BLOCKED_LEGACY_DIAGNOSTIC_FAILURE",
    }:
        actions.add("BLOCK_V2_0_EVIDENCE_REUSE")
    else:
        actions.add("REPORT_V2_0_REUSE_AS_DIAGNOSTIC_ONLY")

    hard_no_go = bool(
        baseline_status == "HARD_STOP_BASELINE_COVERAGE"
        or active_status == "NO_GO_LOW_ACTIVE_COVERAGE"
        or core_status == "NO_GO"
        or scenario_status == "NO_GO_SCENARIO_DOMINATED"
        or feeder_status == "NO_GO_SINGLE_FEEDER_DOMINATED"
    )
    warning_axes = {
        name
        for name, condition in (
            ("baseline", baseline_status == "WARN_REPEAT_BASELINE_COVERAGE"),
            ("active", active_status == "WARN_REPEAT_ACTIVE_COVERAGE"),
            ("core", core_status == "REPEAT_PILOT"),
            ("scenario", scenario_status == "DOMINANCE_REPEAT"),
            ("direction", direction_status == "INDETERMINATE_REPEAT"),
            ("duration", duration_status == "INDETERMINATE_REPEAT"),
            ("feeder", feeder_status == "WEAK_REPLICATION_REPEAT"),
            ("tie", tie_status == "INDETERMINATE_REPEAT"),
            (
                "timing",
                screening_status in {"REPEAT_TIMING", "INDETERMINATE_TIMING"},
            ),
        )
        if condition
    }
    if hard_no_go:
        overall_action = "NO_GO_REASSESS_BROAD_TOPIC"
        decision_class = "NO_GO"
        repeat_scope = "NONE"
    elif core_status == "GO" and tie_status == "PIVOT_TO_PHASE_BALANCED":
        overall_action = "PIVOT_TO_PHASE_BALANCED_AND_REPEAT_16_WU_AUDIT"
        decision_class = "PIVOT"
        repeat_scope = "FULL_16_WU_PILOT"
    elif warning_axes:
        if warning_axes == {"timing"}:
            overall_action = "REPEAT_TIMING_BENCHMARK_ONLY"
            repeat_scope = "TIMING_ONLY"
        else:
            overall_action = "REPEAT_16_WU_PILOT"
            repeat_scope = "FULL_16_WU_PILOT"
        decision_class = "REPEAT_PILOT"
    else:
        overall_action = "GO_TO_FORMAL_V2_1_WITH_REPORTED_SCOPE"
        decision_class = "GO"
        repeat_scope = "NONE"

    return {
        "validator_status": "VALID",
        "baseline_status": baseline_status,
        "active_offer_status": active_status,
        "core_topic_status": core_status,
        "scenario_dominance_status": scenario_status,
        "direction_claim_status": direction_status,
        "duration_claim_status": duration_status,
        "feeder_replication_status": feeder_status,
        "tie_break_route_status": tie_status,
        "screening_compute_status": screening_status,
        "v2_0_reuse_status": reuse_status,
        "overall_action": overall_action,
        "decision_class": decision_class,
        "formal_v2_1_run_started": False,
        "metrics": metrics,
        "reason_codes": sorted(reasons),
        "mandatory_scope_actions": sorted(actions),
        "repeat_scope": repeat_scope,
    }


def _gate_direction_deltas(
    q_rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> list[float]:
    lookup = {
        (row["scenario_id"], row["direction"], row["duration_min"]): float(
            row["alpha_transfer"]
        )
        for row in q_rows
    }
    deltas = []
    for scenario_id in context["scenario_ids"]:
        for duration in context["durations"]:
            inc = lookup.get((scenario_id, "inc", duration))
            dec = lookup.get((scenario_id, "dec", duration))
            if inc is not None and dec is not None:
                deltas.append(abs(inc - dec))
    return deltas


def _gate_duration_deltas(
    q_rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> list[float]:
    lookup = {
        (row["scenario_id"], row["direction"], row["duration_min"]): float(
            row["alpha_transfer"]
        )
        for row in q_rows
    }
    deltas = []
    for scenario_id in context["scenario_ids"]:
        for direction in context["directions"]:
            values = [
                lookup.get((scenario_id, direction, duration))
                for duration in context["durations"]
            ]
            if all(value is not None for value in values):
                complete = [float(value) for value in values if value is not None]
                deltas.append(max(complete) - min(complete))
    return deltas


def _gate_claim_status(
    deltas: Sequence[float],
    context: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    numerator = sum(value >= context["material_delta"] for value in deltas)
    metric = _gate_ratio_metric(numerator, len(deltas))
    if not deltas:
        return "INDETERMINATE_REPEAT", metric
    if metric["rate"] >= context["claim_pass"]:
        return "KEEP_CLAIM", metric
    if metric["rate"] < context["claim_drop"]:
        return "DROP_CLAIM", metric
    return "INDETERMINATE_REPEAT", metric


def _gate_tie_status(
    q_rows: Sequence[Mapping[str, Any]],
    bad_rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> tuple[str, dict[str, Any], str | None]:
    bad_ids = {row["evaluation_id"] for row in bad_rows}
    if not bad_rows:
        empty = _gate_ratio_metric(0, 0)
        return (
            "NOT_APPLICABLE_NO_BAD_ALPHA",
            {
                "tie_rescue": empty,
                "tie_post_bad": empty,
                "tie_new_unsafe": empty,
                "tie_offer_retention": {
                    "minimum": None,
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
            },
            None,
        )
    tied: dict[str, float] = {}
    retentions: list[float] = []
    valid = True
    for row in q_rows:
        alpha = row.get("alpha_transfer_tied")
        alpha_sup = row.get("alpha_tie_sup")
        nonmonotone = row.get("alpha_tie_nonmonotone")
        if (
            row.get("tie_comparator_valid") is not True
            or row.get("tie_break_status") not in {"SUCCESS", "NO_OP"}
            or row.get("alpha_tie_path_status") != "VALID"
            or not _gate_unit_interval(alpha)
            or not _gate_unit_interval(row.get("alpha_tie_prefix"))
            or not _gate_unit_interval(alpha_sup)
            or not isinstance(nonmonotone, bool)
            or not math.isclose(
                float(alpha),
                float(row.get("alpha_tie_prefix")),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or float(alpha_sup) + 1e-12 < float(alpha)
            or not _gate_is_number(row.get("tie_offer_retention"))
            or float(row.get("tie_offer_retention")) < 0
            or row.get("tie_original_schedule_sha256")
            != row.get("schedule_sha256")
            or not isinstance(row.get("tie_schedule_sha256"), str)
            or _GATE_SHA256.fullmatch(row.get("tie_schedule_sha256")) is None
        ):
            valid = False
            continue
        path_valid, _ = _gate_path_evidence_valid(
            row.get("alpha_tie_path_audit"),
            float(alpha),
            float(alpha_sup),
            bool(nonmonotone),
        )
        if not path_valid:
            valid = False
            continue
        tie_break_status = row.get("tie_break_status")
        if tie_break_status == "NO_OP":
            if (
                row.get("tie_schedule_sha256") != row.get("schedule_sha256")
                or float(alpha) != float(row.get("alpha_transfer"))
                or float(row.get("alpha_tie_prefix"))
                != float(row.get("alpha_prefix"))
                or float(alpha_sup) != float(row.get("alpha_sup"))
                or nonmonotone is not row.get("alpha_nonmonotone")
                or float(row.get("tie_offer_retention")) != 1.0
                or row.get("alpha_tie_path_audit")
                != row.get("alpha_path_audit")
            ):
                valid = False
                continue
        elif row.get("tie_schedule_sha256") == row.get("schedule_sha256"):
            valid = False
            continue
        tied[row["evaluation_id"]] = float(alpha)
        retentions.append(float(row["tie_offer_retention"]))

    rescued = sum(
        evaluation_id in tied and tied[evaluation_id] >= context["bad_below"]
        for evaluation_id in bad_ids
    )
    post_bad = sum(
        tied.get(row["evaluation_id"], -math.inf) < context["bad_below"]
        for row in q_rows
        if row["evaluation_id"] in tied
    )
    safe_rows = [
        row for row in q_rows if row["evaluation_id"] not in bad_ids
    ]
    new_unsafe = sum(
        tied.get(row["evaluation_id"], math.inf) < context["bad_below"]
        for row in safe_rows
        if row["evaluation_id"] in tied
    )
    rescue_metric = _gate_ratio_metric(rescued, len(bad_rows))
    post_metric = _gate_ratio_metric(post_bad, len(q_rows))
    new_metric = _gate_ratio_metric(new_unsafe, len(safe_rows))
    if not safe_rows:
        new_metric["rate"] = 0.0
    retention_min = min(retentions, default=None)
    retention_metric = {
        "minimum": retention_min,
        "numerator": sum(
            value >= context["tie_offer_retention"] for value in retentions
        ),
        "denominator": len(q_rows),
        "rate": (
            sum(value >= context["tie_offer_retention"] for value in retentions)
            / len(q_rows)
            if q_rows
            else None
        ),
    }
    metrics = {
        "tie_rescue": rescue_metric,
        "tie_post_bad": post_metric,
        "tie_new_unsafe": new_metric,
        "tie_offer_retention": retention_metric,
    }
    if not valid or len(tied) != len(q_rows) or len(retentions) != len(q_rows):
        return "INDETERMINATE_REPEAT", metrics, "TIE_BREAK_EVIDENCE_INDETERMINATE"
    pivot = bool(
        rescue_metric["rate"] >= context["tie_pivot"]
        and post_metric["rate"] <= context["tie_total_bad"]
        and new_metric["rate"] <= context["tie_new_unsafe"]
        and retention_min is not None
        and retention_min >= context["tie_offer_retention"]
    )
    if pivot:
        return (
            "PIVOT_TO_PHASE_BALANCED",
            metrics,
            "PHASE_BALANCED_TIE_BREAK_PIVOT",
        )
    return "KEEP_ORIGINAL_ROUTE", metrics, None


def _gate_screening_status(
    q_rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> tuple[str, dict[str, Any], str | None]:
    groups: dict[tuple[str, str], Mapping[str, Any]] = {}
    malformed = False
    for row in q_rows:
        key = (str(row.get("feeder")), str(row.get("schedule_sha256")))
        existing = groups.get(key)
        if existing is None:
            groups[key] = row
        elif _gate_timing_signature(existing) != _gate_timing_signature(row):
            malformed = True

    by_feeder: dict[str, dict[str, Any]] = {}
    schedule_cvs: list[float] = []
    for feeder in context["feeders"]:
        feeder_rows = [
            row for (row_feeder, _), row in groups.items() if row_feeder == feeder
        ]
        pooled: list[float] = []
        feeder_schedule_cvs: list[float] = []
        valid_schedule_count = 0
        for row in feeder_rows:
            timing_valid, warm = _gate_timing_evidence_valid(
                row, context["timing_repeats"]
            )
            if not timing_valid:
                malformed = True
                continue
            valid_schedule_count += 1
            pooled.extend(warm)
            mean = sum(warm) / len(warm)
            schedule_cv = math.sqrt(
                sum((value - mean) ** 2 for value in warm) / len(warm)
            ) / mean
            feeder_schedule_cvs.append(schedule_cv)
            schedule_cvs.append(schedule_cv)
        if not pooled:
            malformed = True
            p95 = None
            cv = None
        else:
            p95 = _gate_higher_quantile(pooled, 0.95)
            mean = sum(pooled) / len(pooled)
            pooled_cv = (
                math.sqrt(
                    sum((value - mean) ** 2 for value in pooled) / len(pooled)
                )
                / mean
                if mean > 0
                else None
            )
            if pooled_cv is None:
                malformed = True
            cv = max(feeder_schedule_cvs, default=None)
        by_feeder[feeder] = {
            "unique_schedules": len(feeder_rows),
            "valid_unique_schedules": valid_schedule_count,
            "warm_sample_count": len(pooled),
            "warm_p95_s": p95,
            "warm_cv": cv,
            "maximum_schedule_warm_cv": cv,
            "pooled_warm_cv_diagnostic": pooled_cv if pooled else None,
        }
    metric = {
        "numerator": sum(
            item["valid_unique_schedules"] for item in by_feeder.values()
        ),
        "denominator": len(groups),
        "rate": (
            sum(item["valid_unique_schedules"] for item in by_feeder.values())
            / len(groups)
            if groups
            else None
        ),
        "unique_schedule_count": len(groups),
        "by_feeder": by_feeder,
    }
    if malformed:
        return "INDETERMINATE_TIMING", metric, "TIMING_EVIDENCE_INDETERMINATE"
    p95s = [float(item["warm_p95_s"]) for item in by_feeder.values()]
    if any(
        value > context["timing_cv_indeterminate"] for value in schedule_cvs
    ):
        return "INDETERMINATE_TIMING", metric, "TIMING_CV_INDETERMINATE"
    if any(value > context["timing_cv_pass"] for value in schedule_cvs):
        return "REPEAT_TIMING", metric, "TIMING_CV_REPEAT"
    if all(value <= context["direct_material_seconds"] for value in p95s):
        return "DROP_SCREENING", metric, "DIRECT_AUDIT_FAST_DROP_SCREENING"
    if any(value > context["direct_budget_seconds"] for value in p95s):
        return (
            "KEEP_SCREENING_DIRECT_AUDIT_OVER_BUDGET",
            metric,
            "DIRECT_AUDIT_OVER_BUDGET",
        )
    return "KEEP_SCREENING_MATERIAL", metric, None


def _gate_timing_evidence_valid(
    row: Mapping[str, Any],
    repeats: int,
) -> tuple[bool, list[float]]:
    warm = row.get("alpha1_warm_timing_s")
    if (
        row.get("alpha1_timing_status") != "SUCCESS"
        or not isinstance(warm, list)
        or len(warm) != repeats
        or any(not _gate_is_number(value) or float(value) < 0 for value in warm)
    ):
        return False, []
    values = [float(value) for value in warm]
    replay_scope = (
        "FIRST_SCHEDULE_REPLAY_AFTER_COMMON_BASELINE_WITH_PREBUILT_TRUTH_CACHE"
    )
    mean = sum(values) / len(values)
    expected_cv = (
        math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
        / mean
        if mean > 0
        else None
    )
    expected_p95 = _gate_higher_quantile(values, 0.95)
    if (
        expected_cv is None
        or not _gate_is_number(row.get("alpha1_warm_p95_s"))
        or not _gate_is_number(row.get("alpha1_warm_cv"))
        or not math.isclose(
            float(row.get("alpha1_warm_p95_s")),
            expected_p95,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        or not math.isclose(
            float(row.get("alpha1_warm_cv")),
            expected_cv,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        or not _gate_is_number(row.get("alpha1_cold_timing_s"))
        or float(row.get("alpha1_cold_timing_s")) < 0
        or not _gate_is_number(row.get("alpha1_first_replay_timing_s"))
        or float(row.get("alpha1_first_replay_timing_s")) < 0
        or not math.isclose(
            float(row.get("alpha1_cold_timing_s")),
            float(row.get("alpha1_first_replay_timing_s")),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or row.get("alpha1_cold_timing_scope") != replay_scope
        or row.get("alpha1_first_replay_scope") != replay_scope
    ):
        return False, []
    for name, expected in (
        ("alpha1_timing_checked_intervals", [96] * (1 + repeats)),
        ("alpha1_timing_numerical_failure_checks", [0] * (1 + repeats)),
        ("alpha1_timing_nonconverged_checks", [0] * (1 + repeats)),
    ):
        if row.get(name) != expected:
            return False, []
    for name in (
        "alpha1_timing_power_flow_evaluations",
        "alpha1_timing_physical_violation_checks",
    ):
        counters = row.get(name)
        if (
            not isinstance(counters, list)
            or len(counters) != 1 + repeats
            or any(
                not _gate_is_int(value) or value < 0 or value > 96
                for value in counters
            )
        ):
            return False, []
    failure_classes = row.get("alpha1_timing_failure_class")
    if (
        not isinstance(failure_classes, list)
        or len(failure_classes) != 1 + repeats
        or any(
            value not in {"NONE", "PHYSICAL_CONSTRAINT"}
            for value in failure_classes
        )
    ):
        return False, []
    physical_counts = row["alpha1_timing_physical_violation_checks"]
    if any(
        (count == 0 and failure_class != "NONE")
        or (count > 0 and failure_class != "PHYSICAL_CONSTRAINT")
        for count, failure_class in zip(
            physical_counts, failure_classes, strict=True
        )
    ):
        return False, []
    return True, values


def _gate_timing_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    names = (
        "alpha1_timing_status",
        "alpha1_timing_detail",
        "alpha1_cold_timing_s",
        "alpha1_cold_timing_scope",
        "alpha1_first_replay_timing_s",
        "alpha1_first_replay_scope",
        "alpha1_warm_timing_s",
        "alpha1_warm_p95_s",
        "alpha1_warm_cv",
        "alpha1_timing_checked_intervals",
        "alpha1_timing_power_flow_evaluations",
        "alpha1_timing_numerical_failure_checks",
        "alpha1_timing_nonconverged_checks",
        "alpha1_timing_physical_violation_checks",
        "alpha1_timing_failure_class",
    )
    return tuple(_gate_freeze(row.get(name)) for name in names)


def _gate_reuse_status(
    q_rows: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> tuple[str, dict[str, Any], str]:
    flips = 0
    failures = 0
    for row in q_rows:
        legacy = row.get("alpha_legacy_verifier")
        if (
            row.get("alpha_legacy_verifier_status") != "SUCCESS"
            or not _gate_unit_interval(legacy)
        ):
            failures += 1
            continue
        legacy_bad = float(legacy) < context["bad_below"]
        corrected_bad = float(row["alpha_transfer"]) < context["bad_below"]
        flips += legacy_bad != corrected_bad
    flip_metric = _gate_ratio_metric(flips, len(q_rows))
    failure_metric = _gate_ratio_metric(failures, len(q_rows))
    metrics = {
        "v2_0_label_flip": flip_metric,
        "v2_0_legacy_diagnostic_failure": failure_metric,
    }
    if flips:
        return "BLOCKED_LABEL_FLIP", metrics, "V2_0_LABEL_FLIP_BLOCK"
    if failures:
        return (
            "BLOCKED_LEGACY_DIAGNOSTIC_FAILURE",
            metrics,
            "V2_0_LEGACY_DIAGNOSTIC_FAILURE",
        )
    return (
        "DIAGNOSTIC_ONLY_NO_FLIP",
        metrics,
        "V2_0_REUSE_DIAGNOSTIC_ONLY",
    )


def _gate_validity_stop(
    errors: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    result = {
        "validator_status": "VALIDITY_STOP",
        **{
            field: _GATE_NOT_EVALUATED
            for field in _GATE_SCIENTIFIC_STATUS_FIELDS
        },
        "overall_action": "STOP_FIX_AND_REPEAT_16_WU_AUDIT",
        "decision_class": "VALIDITY_STOP",
        "formal_v2_1_run_started": False,
        "metrics": {
            "validation": {
                "numerator": 0,
                "denominator": len(errors),
                "rate": 0.0 if errors else None,
                "error_count": len(errors),
                "errors": [
                    {"reason_code": code, "detail": detail}
                    for code, detail in errors
                ],
            }
        },
        "reason_codes": sorted({code for code, _ in errors}),
        "mandatory_scope_actions": [],
        "repeat_scope": "FULL_16_WU_PILOT",
    }
    return result


def _gate_validate_id_vector(
    value: Any,
    label: str,
    errors: list[tuple[str, str]],
) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        errors.append(("EVIDENCE_SCHEMA_INVALID", f"{label} must be a string list"))
        return []
    if len(value) != len(set(value)):
        errors.append(("EVIDENCE_SCHEMA_INVALID", f"{label} contains duplicates"))
    return list(value)


def _gate_exact_id_set(observed: Sequence[str], expected: Sequence[str]) -> bool:
    return len(observed) == len(expected) and set(observed) == set(expected)


def _gate_ratio_metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "rate": numerator / denominator if denominator else 0.0,
    }


def _gate_mapping(owner: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = owner.get(name)
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _gate_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise TypeError(f"{label} must be a nonempty-string list")
    return list(value)


def _gate_int_list(value: Any, label: str) -> list[int]:
    if not isinstance(value, list) or any(not _gate_is_int(item) for item in value):
        raise TypeError(f"{label} must be an integer list")
    return list(value)


def _gate_required_number(value: Any, label: str) -> float:
    if not _gate_is_number(value):
        raise TypeError(f"{label} must be a finite number")
    return float(value)


def _gate_is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _gate_is_number(value: Any) -> bool:
    return (
        isinstance(value, Number)
        and not isinstance(value, (bool, np.bool_))
        and math.isfinite(float(value))
    )


def _gate_unit_interval(value: Any) -> bool:
    return _gate_is_number(value) and 0.0 <= float(value) <= 1.0


def _gate_higher_quantile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(quantile * (len(ordered) - 1)))
    return ordered[index]


def _gate_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _gate_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _gate_freeze(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_gate_freeze(item) for item in value)
    return value
