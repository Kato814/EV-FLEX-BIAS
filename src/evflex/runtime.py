"""Final fixed-schedule reconstruction and full three-phase feasibility audits."""
from __future__ import annotations
import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from numbers import Number
from pathlib import Path
from typing import Any
import numpy as np


_PILOT_ADAPTER_SCHEMA = "evflex.pilot.network-audit"

_PILOT_ADAPTER_VERSION = 2

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
    from evflex.engine import load_duration_engine
    from evflex.fleet import load_fleet_bundle
    from evflex.network import configure_core, load_network_core

    repo = repo_root.resolve(strict=True)
    duration_engine_path = (
        Path(__file__).resolve().parent / "solver" / "duration_engine.py"
    )
    network_core_path = (
        Path(__file__).resolve().parent / "solver" / "network_core.py"
    )
    archived_engine = load_duration_engine(duration_engine_path)

    corrected_core = load_network_core(network_core_path)
    configure_core(corrected_core, repo)
    configure_pilot_core(corrected_core, config)

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
        bundle: Any,
        feeder: str,
        call_time: str,
        direction: str,
    ) -> None:
        self.archived_engine = archived_engine
        self.corrected_core = corrected_core
        self.fleet = list(bundle.fleet)
        self.baseline = np.asarray(bundle.baseline, dtype=float)
        self.load_scales = np.asarray(bundle.load_scales, dtype=float)
        self.feeder = feeder
        self.call_time = call_time
        self.direction = direction
        self._corrected_truth_cache: Any = None


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
