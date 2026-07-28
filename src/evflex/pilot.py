from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from numbers import Number
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


_DURATION_SUFFIX = re.compile(r"__(\d+)m$")
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
            return report

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
            rating = float(context.Transformers.kVA())
        except (TypeError, ValueError, OverflowError) as exc:
            rating = math.nan
            rating_error = str(exc)
        else:
            rating_error = None
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
    power_flow_evaluations = 0
    reused_baseline_intervals = 0
    converged_checks = 0
    nonconverged_checks = 0
    numerical_failure_checks = 0

    for slot in range(96):
        scale = float(scale_array[slot])
        if scale not in cache:
            raise KeyError(f"network cache has no entry for load scale {scale}")
        network = cache[scale]
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
            )
        )

        if reusable:
            evaluation = _normalize_slot_evaluation(cached["result"])
            reused_baseline_intervals += 1
            source = "baseline_reuse"
        else:
            power = engine.group_vector(
                fleet,
                schedule_array[:, slot],
                network.groups,
                model,
            )
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
        slot_record = {
            "slot": slot,
            "verified": True,
            "baseline_exact": exact_baseline,
            "baseline_schedule": (
                baseline_array[:, slot].tolist() if exact_baseline else None
            ),
            "load_scale": scale,
            "feeder": str(feeder),
            "model": str(model),
            "source": source,
            "coverage": _copy_formal_coverage(evaluation["coverage"]),
            "formal_integrity": dict(evaluation["formal_integrity"]),
            "result": evaluation,
        }
        slot_results.append(slot_record)

        if not evaluation["feasible"]:
            violations.append(
                {
                    "slot": slot,
                    "converged": evaluation["converged"],
                    "numerical_failure": evaluation["numerical_failure"],
                    "violations": evaluation["violations"],
                }
            )
            if stop_on_violation:
                break

    checked_intervals = len(slot_results)
    complete_coverage = checked_intervals == 96
    feasible = bool(complete_coverage and not violations)
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
        "nonconverged_slots": [
            item["slot"] for item in violations if not item["converged"]
        ],
        "violations": violations,
        "slot_results": slot_results,
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


def _normalize_slot_evaluation(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("network.evaluate must return a mapping")
    violations = list(raw.get("violations", []))
    converged = bool(raw.get("converged", False))
    numerical_failure = bool(raw.get("numerical_failure", False)) or not converged
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

    feasible = bool(raw.get("feasible", False))
    feasible = bool(feasible and converged and not numerical_failure and not violations)
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
            metrics_finite
            and summary_finite
            and coverage_complete
            and summary_consistent
        ),
        "metrics_finite": metrics_finite,
        "summary_finite": summary_finite,
        "coverage_complete": coverage_complete,
        "summary_consistent": summary_consistent,
    }


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
    if not isinstance(ratings, Mapping):
        return False
    if not all(
        isinstance(name, str)
        and _is_finite_number(rating)
        and float(rating) > 0
        for name, rating in ratings.items()
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
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
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
    ratings = copied.get("transformer_ratings_kva")
    if isinstance(ratings, Mapping):
        copied["transformer_ratings_kva"] = dict(ratings)
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
