from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from pathlib import Path
import time
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from opendssdirect import dss

from evflex.engine import (
    _configure_network_voltage_limit,
    _model_result_is_physical,
    load_archived_engine,
)
from evflex.manifests import ABLATION_CALL_TIMES, BLOCK_LEVELS, REPLICATES
from evflex.network import configure_core, load_legacy_core
from evflex.provenance import sha256_file


BOOTSTRAP_SEED = 2026072001
BOOTSTRAP_RESAMPLES = 10_000
EXPECTED_BLOCK_COUNTS = {
    "A1_phase": 72,
    "A2_location": 72,
    "A3_load": 72,
    "A4_urgency": 72,
    "A5_v2g": 48,
}
REFERENCE_LEVELS = {
    "A1_phase": "2:1:1",
    "A2_location": "0.5",
    "A3_load": "0.9",
    "A4_urgency": "0.65",
    "A5_v2g": "0.5",
}
CAPACITIES = np.array([50.0, 60.0, 70.0, 82.0, 90.0])
CAPACITY_WEIGHTS = np.array([0.15, 0.25, 0.25, 0.20, 0.15])
CHARGERS = np.array([7.2, 11.0])
CHARGER_WEIGHTS = np.array([0.75, 0.25])
ETA_C = 0.95
ETA_D = 0.95
RESERVE_SOC = 0.20
TARGET_SOC = 0.90
KWH_PER_MILE = 0.30
CALL_SLOTS = {"19:00": 28, "00:00": 48, "02:00": 56, "06:00": 72}
TRANSFORMER_KVA = {"ieee13": 5000.0, "lv906": 800.0}
PHYSICAL_TOLERANCE_KWH = 1e-6

ABLATION_REQUIRED_COLUMNS = (
    "ablation_id",
    "protocol_version",
    "block",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "seed",
    "replicate",
    "varied_factor",
    "factor_level",
    "ev_nameplate_to_transformer_ratio",
    "native_load_multiplier",
    "phase_ratio",
    "far_zone_probability",
    "v2g_participation",
    "urgency_quantile",
    "dominant_phase",
    "data_role",
    "holdout_access",
)


@dataclass(frozen=True)
class AblationFleet:
    population: pd.DataFrame
    fleet: list
    baseline: np.ndarray
    load_scales: np.ndarray
    summary: dict[str, Any]


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def validate_ablation_manifest(frame: pd.DataFrame) -> dict[str, Any]:
    _require_columns(frame, ABLATION_REQUIRED_COLUMNS, "ablation manifest")
    if len(frame) != 336:
        raise ValueError(f"ablation manifest has {len(frame)} rows, expected 336")
    if frame["ablation_id"].duplicated().any():
        raise ValueError("ablation manifest contains duplicate IDs")
    if frame["seed"].duplicated().any():
        raise ValueError("ablation manifest contains duplicate seeds")
    if not frame["protocol_version"].eq("EV-FLEX-BIAS-V2.0").all():
        raise ValueError("ablation manifest protocol mismatch")
    if not frame["data_role"].eq("development_ablation").all():
        raise ValueError("ablation data_role must be development_ablation")
    if not frame["holdout_access"].eq("prohibited").all():
        raise ValueError("holdout access must remain prohibited for ablations")
    if set(frame["duration_min"].astype(int)) != {15}:
        raise ValueError("all ablation durations must equal 15 minutes")
    if set(frame["call_time"].astype(str)) != set(ABLATION_CALL_TIMES):
        raise ValueError("ablation call times differ from the frozen design")
    if set(frame["replicate"].astype(int)) != set(REPLICATES):
        raise ValueError("ablation replicate set differs from the frozen design")
    block_counts = frame.groupby("block", sort=True).size().to_dict()
    if block_counts != EXPECTED_BLOCK_COUNTS:
        raise ValueError(f"ablation block counts differ: {block_counts}")

    for block, (factor, levels, directions) in BLOCK_LEVELS.items():
        selected = frame.loc[frame["block"].eq(block)]
        if not selected["varied_factor"].eq(factor).all():
            raise ValueError(f"{block} varied_factor mismatch")
        if set(selected["factor_level"].astype(str)) != {str(value) for value in levels}:
            raise ValueError(f"{block} factor levels differ from the frozen design")
        if set(selected["direction"].astype(str)) != set(directions):
            raise ValueError(f"{block} directions differ from the frozen design")

    return {
        "rows": int(len(frame)),
        "block_counts": {key: int(value) for key, value in block_counts.items()},
        "duration_min": sorted(frame["duration_min"].astype(int).unique().tolist()),
        "call_times": sorted(frame["call_time"].astype(str).unique().tolist()),
        "unique_ids": int(frame["ablation_id"].nunique()),
        "unique_seeds": int(frame["seed"].nunique()),
        "holdout_prohibited": bool(frame["holdout_access"].eq("prohibited").all()),
    }


def merge_manifest_fields(
    evaluation: Mapping[str, Any], manifest_row: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(evaluation)
    for column, value in manifest_row.items():
        target = "manifest_status" if column == "status" else str(column)
        merged[target] = value
    return merged


def stratified_bootstrap_indices(
    frame: pd.DataFrame,
    strata: list[str],
    n_resamples: int,
    seed: int,
) -> list[np.ndarray]:
    _require_columns(frame, strata, "bootstrap frame")
    if n_resamples < 1:
        raise ValueError("n_resamples must be positive")
    groups = [
        np.asarray(indices, dtype=int)
        for indices in frame.groupby(strata, sort=True, dropna=False).indices.values()
    ]
    if not groups:
        raise ValueError("bootstrap frame is empty")
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n_resamples):
        sampled = [rng.choice(indices, size=len(indices), replace=True) for indices in groups]
        samples.append(np.concatenate(sampled))
    return samples


def bootstrap_contrast(
    level_values: np.ndarray,
    reference_values: np.ndarray,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, float | int]:
    level = np.asarray(level_values, dtype=float)
    reference = np.asarray(reference_values, dtype=float)
    if level.ndim != 1 or reference.ndim != 1 or len(level) != len(reference):
        raise ValueError("paired bootstrap values must be aligned one-dimensional arrays")
    if len(level) == 0 or not np.isfinite(level).all() or not np.isfinite(reference).all():
        raise ValueError("paired bootstrap values must be non-empty and finite")
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(level), size=(n_resamples, len(level)))
    samples = np.median(level[indices], axis=1) - np.median(reference[indices], axis=1)
    return {
        "paired_n": int(len(level)),
        "median_contrast": float(np.median(level) - np.median(reference)),
        "ci_low": float(np.quantile(samples, 0.025)),
        "ci_high": float(np.quantile(samples, 0.975)),
    }


def weighted_quantile_rank(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ordered_weights = np.asarray(weights, dtype=float)[order]
    ordered_weights = np.where(
        np.isfinite(ordered_weights) & (ordered_weights > 0), ordered_weights, 1.0
    )
    cumulative = np.cumsum(ordered_weights) - 0.5 * ordered_weights
    cumulative /= ordered_weights.sum()
    output = np.empty_like(cumulative)
    output[order] = cumulative
    return output


def phase_sequence(
    n: int, ratio_text: str, dominant: str, rng: np.random.Generator
) -> list[int]:
    ratio = [int(value) for value in str(ratio_text).split(":")]
    if len(ratio) != 3 or any(value <= 0 for value in ratio):
        raise ValueError(f"invalid phase ratio: {ratio_text!r}")
    try:
        dominant_phase = {"a": 1, "b": 2, "c": 3}[str(dominant)]
    except KeyError as exc:
        raise ValueError(f"invalid dominant phase: {dominant!r}") from exc
    others = [phase for phase in (1, 2, 3) if phase != dominant_phase]
    weights = {dominant_phase: ratio[0], others[0]: ratio[1], others[1]: ratio[2]}
    raw = np.array([weights[phase] for phase in (1, 2, 3)], dtype=float)
    target = raw / raw.sum() * n
    counts = np.floor(target).astype(int)
    for index in np.argsort(-(target - counts))[: n - counts.sum()]:
        counts[index] += 1
    sequence = [
        phase
        for phase, count in zip((1, 2, 3), counts)
        for _ in range(int(count))
    ]
    rng.shuffle(sequence)
    return sequence


def pick_capacity(energy_need: float, rng: np.random.Generator) -> float | None:
    feasible = CAPACITIES[
        (TARGET_SOC - RESERVE_SOC) * CAPACITIES >= float(energy_need) - 1e-9
    ]
    if len(feasible) == 0:
        return None
    mask = np.isin(CAPACITIES, feasible)
    probability = CAPACITY_WEIGHTS[mask]
    probability = probability / probability.sum()
    return float(rng.choice(CAPACITIES[mask], p=probability))


def _clean_bus(name: str) -> str:
    return str(name).split(".")[0].lower()


def extract_connection_points(repo_root: Path) -> pd.DataFrame:
    repo = repo_root.resolve(strict=True)
    masters = {
        "ieee13": repo / "data" / "feeders" / "ieee13" / "IEEE13Nodeckt.dss",
        "lv906": repo / "data" / "feeders" / "lv906_core" / "MasterStaticAudit.dss",
    }
    all_rows: list[dict[str, Any]] = []
    for feeder, master in masters.items():
        context = dss.NewContext()
        context.Command("clear")
        context.Command(f'compile "{master}"')
        if not context.Solution.Converged():
            raise RuntimeError(f"{feeder} failed while extracting connection points")

        graph: dict[str, list[tuple[str, float]]] = {}

        def add_edge(first: str, second: str, weight: float) -> None:
            graph.setdefault(first, []).append((second, weight))
            graph.setdefault(second, []).append((first, weight))

        for name in context.Lines.AllNames():
            context.Lines.Name(name)
            context.Circuit.SetActiveElement("Line." + name)
            buses = context.CktElement.BusNames()
            if len(buses) >= 2:
                add_edge(
                    _clean_bus(buses[0]),
                    _clean_bus(buses[1]),
                    max(float(context.Lines.Length()), 1e-6),
                )
        for name in context.Transformers.AllNames():
            context.Transformers.Name(name)
            context.Circuit.SetActiveElement("Transformer." + name)
            buses = [_clean_bus(value) for value in context.CktElement.BusNames()]
            for first, second in zip(buses[:-1], buses[1:]):
                add_edge(first, second, 1e-6)

        if context.Vsources.First() > 0:
            context.Circuit.SetActiveElement("Vsource." + context.Vsources.Name())
            source = _clean_bus(context.CktElement.BusNames()[0])
        else:
            source = "sourcebus"
        distance = {source: 0.0}
        queue = [(0.0, source)]
        while queue:
            current_distance, bus = heapq.heappop(queue)
            if current_distance != distance[bus]:
                continue
            for neighbor, weight in graph.get(bus, []):
                candidate = current_distance + weight
                if candidate < distance.get(neighbor, float("inf")):
                    distance[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))

        for load_name in context.Loads.AllNames():
            context.Loads.Name(load_name)
            context.Circuit.SetActiveElement("Load." + load_name)
            bus_spec = context.CktElement.BusNames()[0]
            parts = bus_spec.split(".")
            bus = parts[0].lower()
            nodes = [
                int(value)
                for value in parts[1:]
                if value.isdigit() and int(value) in (1, 2, 3)
            ]
            if int(context.Loads.Phases()) != 1 or bool(context.Loads.IsDelta()) or len(nodes) != 1:
                continue
            all_rows.append(
                {
                    "feeder": feeder,
                    "load_name": str(load_name),
                    "bus": bus,
                    "phase": nodes[0],
                    "kv_ln": float(context.Loads.kV()),
                    "native_kw": float(context.Loads.kW()),
                    "electrical_distance": float(distance.get(bus, float("nan"))),
                }
            )
    frame = pd.DataFrame(all_rows).sort_values(
        ["feeder", "phase", "electrical_distance", "bus", "load_name"],
        kind="mergesort",
    ).reset_index(drop=True)
    if frame.empty or frame["electrical_distance"].isna().any():
        raise RuntimeError("connection-point extraction is incomplete")
    if set(frame["feeder"]) != {"ieee13", "lv906"}:
        raise RuntimeError("connection-point extraction is missing a feeder")
    return frame


def build_ablation_fleet(
    repo_root: Path,
    work_unit: Mapping[str, Any],
    archived_engine: Any,
    legacy_core: Any,
) -> AblationFleet:
    if str(work_unit.get("data_role")) != "development_ablation":
        raise ValueError("ablation fleet construction requires development_ablation role")
    if str(work_unit.get("holdout_access")) != "prohibited":
        raise ValueError("holdout access must be prohibited during ablation construction")
    repo = repo_root.resolve(strict=True)
    behavior = pd.read_csv(
        repo / "data" / "inherited" / "nhts2022_vehicle_days.csv",
        dtype={
            "source_vehicle_id": str,
            "houseid": str,
            "driver_person_ids": str,
        },
    )
    points = extract_connection_points(repo)
    rng = np.random.default_rng(int(work_unit["seed"]))
    call_time = str(work_unit["call_time"])
    tau = CALL_SLOTS[call_time]
    pool = behavior.loc[
        behavior["arrival_slot"].le(tau) & behavior["departure_slot"].gt(tau)
    ].copy()
    pool["trip_energy_kwh"] = pool["daily_miles"] * KWH_PER_MILE
    pool = pool.loc[
        pool["trip_energy_kwh"].le(
            (TARGET_SOC - RESERVE_SOC) * CAPACITIES.max()
        )
    ].copy()
    pool["base_urgency"] = pool["trip_energy_kwh"] / (
        ETA_C * 7.2 * (pool["parking_duration_min"] / 60.0)
    )
    pool = pool.loc[pool["base_urgency"].gt(0) & pool["base_urgency"].le(1.0)].copy()
    if len(pool) < 500:
        raise RuntimeError(f"insufficient NHTS pool for ablation {work_unit['ablation_id']}")
    pool["urgency_rank"] = weighted_quantile_rank(
        pool["base_urgency"].to_numpy(), pool["survey_weight"].to_numpy()
    )
    kernel = np.exp(
        -0.5
        * (
            (pool["urgency_rank"] - float(work_unit["urgency_quantile"])) / 0.14
        )
        ** 2
    )
    probability = pool["survey_weight"].to_numpy(dtype=float) * kernel
    probability = probability / probability.sum()

    feeder = str(work_unit["feeder"])
    target_nameplate = (
        float(work_unit["ev_nameplate_to_transformer_ratio"])
        * TRANSFORMER_KVA[feeder]
    )
    n_estimated = max(
        1, int(round(target_nameplate / float(np.dot(CHARGERS, CHARGER_WEIGHTS))))
    )
    if n_estimated > len(pool):
        raise RuntimeError("NHTS pool is smaller than the frozen ablation fleet target")
    selected_index = rng.choice(
        pool.index.to_numpy(), size=n_estimated, replace=False, p=probability
    )
    selected = pool.loc[selected_index].reset_index(drop=True)
    chargers = rng.choice(CHARGERS, size=n_estimated, p=CHARGER_WEIGHTS)
    phases = phase_sequence(
        n_estimated,
        str(work_unit["phase_ratio"]),
        str(work_unit["dominant_phase"]),
        rng,
    )

    feeder_points = points.loc[points["feeder"].eq(feeder)].copy()
    threshold = feeder_points["electrical_distance"].quantile(2 / 3)
    feeder_points["zone"] = np.where(
        feeder_points["electrical_distance"].ge(threshold), "far", "near"
    )
    rows = []
    urgency_values = []
    far_count = 0
    for ev_id, (profile, charger, phase) in enumerate(
        zip(selected.itertuples(index=False), chargers, phases), start=1
    ):
        trip_energy = float(profile.trip_energy_kwh)
        capacity = pick_capacity(trip_energy, rng)
        if capacity is None:
            raise RuntimeError("capacity feasibility filter failed")
        target_energy = TARGET_SOC * capacity
        initial_energy = target_energy - trip_energy
        reserve_energy = RESERVE_SOC * capacity
        natural_urgency = trip_energy / (
            ETA_C * float(charger) * (float(profile.parking_duration_min) / 60.0)
        )
        if natural_urgency > 1.0 + 1e-9:
            raise RuntimeError("selected NHTS profile cannot restore trip energy")

        phase_points = feeder_points.loc[feeder_points["phase"].eq(int(phase))]
        desired_zone = (
            "far"
            if rng.random() < float(work_unit["far_zone_probability"])
            else "near"
        )
        zone_points = phase_points.loc[phase_points["zone"].eq(desired_zone)]
        if zone_points.empty:
            zone_points = phase_points
        if zone_points.empty:
            raise RuntimeError(f"no connection point for feeder={feeder}, phase={phase}")
        weights = np.clip(zone_points["native_kw"].to_numpy(dtype=float), 0.0, None)
        weights = weights / weights.sum() if weights.sum() > 0 else np.full(len(weights), 1 / len(weights))
        point = zone_points.iloc[int(rng.choice(np.arange(len(zone_points)), p=weights))]
        far_count += int(point["zone"] == "far")

        v2g = bool(rng.random() < float(work_unit["v2g_participation"]))
        budget = float(rng.choice([6.0, 8.0, 10.0, 12.0])) if v2g else 0.0
        urgency_values.append(natural_urgency)
        rows.append(
            {
                "scenario_id": str(work_unit["ablation_id"]),
                "ev_id": ev_id,
                "battery_kwh": capacity,
                "initial_energy_kwh": initial_energy,
                "target_energy_kwh": target_energy,
                "reserve_energy_kwh": reserve_energy,
                "arrival_slot": int(profile.arrival_slot),
                "departure_slot": int(profile.departure_slot),
                "p_charge_kw": float(charger),
                "p_discharge_kw": float(charger) if v2g else 0.0,
                "eta_charge": ETA_C,
                "eta_discharge": ETA_D,
                "v2g_flag": int(v2g),
                "v2g_budget_kwh": budget,
                "bus": str(point.bus),
                "phase": int(phase),
                "kv_ln": float(point.kv_ln),
                "electrical_distance": float(point.electrical_distance),
                "natural_urgency": natural_urgency,
            }
        )
    population = pd.DataFrame(rows)
    fleet = archived_engine.build_fleet(population, legacy_core.EV)
    baseline = archived_engine.uniform_baseline(fleet)
    load_profile = pd.read_csv(
        repo / "data" / "inherited" / "controlled_native_load_profile_v1_2.csv"
    )
    native = load_profile.sort_values("slot")["normalized_native_load"].to_numpy(
        dtype=float
    )
    if len(native) != 96:
        raise RuntimeError("controlled native-load profile must contain 96 intervals")
    load_scales = np.round(native * float(work_unit["native_load_multiplier"]), 8)
    phase_counts = population.groupby("phase").size().reindex([1, 2, 3], fill_value=0)
    summary = {
        "n_ev": int(len(population)),
        "target_nameplate_kw": float(target_nameplate),
        "actual_nameplate_kw": float(population["p_charge_kw"].sum()),
        "actual_nameplate_to_transformer_ratio": float(
            population["p_charge_kw"].sum() / TRANSFORMER_KVA[feeder]
        ),
        "realized_v2g_participation": float(population["v2g_flag"].mean()),
        "realized_far_zone_share": float(far_count / len(population)),
        "median_natural_urgency": float(np.median(urgency_values)),
        "phase_imbalance_index": float(
            (phase_counts.max() - phase_counts.min()) / len(population)
        ),
    }
    return AblationFleet(population, fleet, baseline, load_scales, summary)


def evaluate_ablation(
    repo_root: Path,
    work_unit: Mapping[str, Any],
    *,
    network_voltage_max_pu: float = 1.06,
) -> list[dict[str, Any]]:
    if int(work_unit["duration_min"]) != 15:
        raise ValueError("the compact ablation adapter supports only 15-minute runs")
    if str(work_unit["holdout_access"]) != "prohibited":
        raise ValueError("holdout access must remain prohibited")
    repo = repo_root.resolve(strict=True)
    archived_engine = load_archived_engine(
        repo / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    legacy_core = load_legacy_core(
        repo / "legacy" / "d5_v1_2" / "network_core_v1_2.py"
    )
    configure_core(legacy_core, repo)
    _configure_network_voltage_limit(legacy_core, network_voltage_max_pu)
    bundle = build_ablation_fleet(repo, work_unit, archived_engine, legacy_core)
    feeder = str(work_unit["feeder"])
    direction = str(work_unit["direction"])
    duration = int(work_unit["duration_min"])
    tau = CALL_SLOTS[str(work_unit["call_time"])]
    started = time.perf_counter()
    balanced = archived_engine.duration_result(
        legacy_core,
        feeder,
        bundle.fleet,
        bundle.baseline,
        tau,
        duration,
        direction,
        bundle.load_scales,
        "balanced",
    )
    three_phase = archived_engine.duration_result(
        legacy_core,
        feeder,
        bundle.fleet,
        bundle.baseline,
        tau,
        duration,
        direction,
        bundle.load_scales,
        "3ph",
    )
    truth_cache = archived_engine.network_cache(
        legacy_core, feeder, bundle.fleet, bundle.load_scales, "3ph"
    )
    alpha_map, mapped_check = archived_engine.safe_schedule_alpha(
        legacy_core,
        feeder,
        bundle.fleet,
        balanced["schedule"],
        bundle.baseline,
        bundle.load_scales,
        "3ph",
        truth_cache,
    )
    runtime = time.perf_counter() - started
    balanced = dict(balanced)
    three_phase = dict(three_phase)
    balanced["physical_feasible"] = _model_result_is_physical(balanced)
    three_phase["physical_feasible"] = _model_result_is_physical(three_phase)
    maximum_departure_error = max(
        float(balanced["max_departure_error_kwh"]),
        float(three_phase["max_departure_error_kwh"]),
    )
    maximum_reserve_violation = max(
        float(balanced["max_reserve_violation_kwh"]),
        float(three_phase["max_reserve_violation_kwh"]),
    )
    maximum_capacity_violation = max(
        float(balanced["max_capacity_violation_kwh"]),
        float(three_phase["max_capacity_violation_kwh"]),
    )
    simultaneous_slots = max(
        int(balanced["simultaneous_slots"]), int(three_phase["simultaneous_slots"])
    )
    physical = bool(
        balanced["physical_feasible"]
        and three_phase["physical_feasible"]
        and mapped_check["feasible"]
        and maximum_departure_error <= PHYSICAL_TOLERANCE_KWH
        and maximum_reserve_violation <= PHYSICAL_TOLERANCE_KWH
        and maximum_capacity_violation <= PHYSICAL_TOLERANCE_KWH
        and simultaneous_slots == 0
    )
    f_balanced = float(balanced["flex_kw"])
    f_three_phase = float(three_phase["flex_kw"])
    provenance = {
        "ablation_manifest": sha256_file(repo / "manifests" / "compact_ablation_v2_0.csv"),
        "nhts_vehicle_days": sha256_file(
            repo / "data" / "inherited" / "nhts2022_vehicle_days.csv"
        ),
        "native_load_profile": sha256_file(
            repo
            / "data"
            / "inherited"
            / "controlled_native_load_profile_v1_2.csv"
        ),
        "duration_engine": sha256_file(
            repo / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
        ),
        "network_core": sha256_file(
            repo / "legacy" / "d5_v1_2" / "network_core_v1_2.py"
        ),
    }
    row = {
        "evaluation_id": str(work_unit["ablation_id"]),
        "work_unit_id": str(work_unit["ablation_id"]),
        "ablation_id": str(work_unit["ablation_id"]),
        "protocol_version": "EV-FLEX-BIAS-V2.0",
        "scenario_seed": int(work_unit["seed"]),
        "data_role": "development_ablation",
        "block": str(work_unit["block"]),
        "varied_factor": str(work_unit["varied_factor"]),
        "factor_level": str(work_unit["factor_level"]),
        "replicate": int(work_unit["replicate"]),
        "feeder": feeder,
        "call_time": str(work_unit["call_time"]),
        "direction": direction,
        "duration_min": duration,
        "network_voltage_max_pu": float(network_voltage_max_pu),
        "ev_nameplate_to_transformer_ratio": float(
            work_unit["ev_nameplate_to_transformer_ratio"]
        ),
        "native_load_multiplier": float(work_unit["native_load_multiplier"]),
        "phase_ratio": str(work_unit["phase_ratio"]),
        "dominant_phase": str(work_unit["dominant_phase"]),
        "far_zone_probability": float(work_unit["far_zone_probability"]),
        "v2g_participation": float(work_unit["v2g_participation"]),
        "urgency_quantile": float(work_unit["urgency_quantile"]),
        **bundle.summary,
        "f_bal_kw": f_balanced,
        "f_3ph_kw": f_three_phase,
        "bias_pct": (f_balanced - f_three_phase) / max(f_three_phase, 1e-9) * 100.0,
        "alpha_map": float(alpha_map),
        "false_safe": bool(float(alpha_map) < 0.95),
        "mapped_flex_kw": f_balanced * float(alpha_map),
        "raw_balanced_schedule_feasible": bool(float(alpha_map) >= 0.999999),
        "balanced_trajectory_alpha": float(balanced["trajectory_alpha"]),
        "three_phase_trajectory_alpha": float(three_phase["trajectory_alpha"]),
        "balanced_network_alpha": float(balanced["model_network_alpha"]),
        "three_phase_network_alpha": float(three_phase["model_network_alpha"]),
        "max_departure_error_kwh": maximum_departure_error,
        "max_reserve_violation_kwh": maximum_reserve_violation,
        "max_capacity_violation_kwh": maximum_capacity_violation,
        "min_soc_margin_kwh": -maximum_reserve_violation,
        "simultaneous_slots": simultaneous_slots,
        "balanced_network_feasible": bool(balanced["model_network_check"]["feasible"]),
        "three_phase_network_feasible": bool(
            three_phase["model_network_check"]["feasible"]
        ),
        "mapped_network_feasible": bool(mapped_check["feasible"]),
        "physical_feasible": physical,
        "raw_solve_runtime_s": runtime,
        "provenance_sha256": provenance,
        "status": "SUCCESS" if physical else "PHYSICAL_INVARIANT_FAILED",
    }
    validate_ablation_evaluation(row, work_unit)
    return [row]


def validate_ablation_evaluation(
    row: Mapping[str, Any], work_unit: Mapping[str, Any]
) -> None:
    if str(row["evaluation_id"]) != str(work_unit["ablation_id"]):
        raise ValueError("ablation evaluation ID differs from the manifest")
    if int(row["scenario_seed"]) != int(work_unit["seed"]):
        raise ValueError("ablation seed differs from the manifest")
    if int(row["duration_min"]) != 15:
        raise ValueError("ablation duration differs from the frozen design")
    if str(row["data_role"]) != "development_ablation":
        raise ValueError("ablation result role mismatch")
    if str(row["status"]) == "SUCCESS":
        if not bool(row["physical_feasible"]):
            raise ValueError("successful ablation is not physically feasible")
        if float(row["max_reserve_violation_kwh"]) > PHYSICAL_TOLERANCE_KWH:
            raise ValueError("ablation reserve violation")
        if int(row["simultaneous_slots"]) != 0:
            raise ValueError("ablation has simultaneous charging/discharging")


def analyze_ablation_contrasts(
    results: pd.DataFrame,
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> pd.DataFrame:
    _require_columns(
        results,
        (
            "ablation_id",
            "block",
            "varied_factor",
            "factor_level",
            "feeder",
            "call_time",
            "direction",
            "replicate",
            "status",
            "alpha_map",
            "bias_pct",
        ),
        "ablation results",
    )
    if results["ablation_id"].duplicated().any():
        raise ValueError("ablation results contain duplicate IDs")
    frame = results.copy()
    frame["factor_level_text"] = frame["factor_level"].astype(str)
    frame["eligible"] = frame["status"].eq("SUCCESS")
    frame["false_safe"] = pd.to_numeric(frame["alpha_map"], errors="coerce").lt(0.95)
    rng = np.random.default_rng(seed)
    output: list[dict[str, Any]] = []
    stream_index = 0

    for block, (factor, levels, directions) in BLOCK_LEVELS.items():
        reference_level = REFERENCE_LEVELS[block]
        level_order = [str(value) for value in levels]
        block_frame = frame.loc[frame["block"].eq(block)]
        for feeder in ("ieee13", "lv906"):
            for call_time in ABLATION_CALL_TIMES:
                for direction in directions:
                    cell = block_frame.loc[
                        block_frame["feeder"].eq(feeder)
                        & block_frame["call_time"].eq(call_time)
                        & block_frame["direction"].eq(direction)
                    ]
                    reference = cell.loc[
                        cell["factor_level_text"].eq(reference_level)
                        & cell["eligible"]
                    ]
                    for level in level_order:
                        level_all = cell.loc[cell["factor_level_text"].eq(level)]
                        level_success = level_all.loc[level_all["eligible"]]
                        failed_ids = sorted(
                            level_all.loc[~level_all["eligible"], "ablation_id"].astype(str)
                        )
                        base_row: dict[str, Any] = {
                            "block": block,
                            "varied_factor": factor,
                            "feeder": feeder,
                            "call_time": call_time,
                            "direction": direction,
                            "factor_level": level,
                            "reference_level": reference_level,
                            "n_total": int(len(level_all)),
                            "n_success": int(len(level_success)),
                            "n_terminal_non_success": int(len(failed_ids)),
                            "terminal_non_success_ids": ";".join(failed_ids),
                            "median_alpha_map": _finite_stat(
                                level_success["alpha_map"], np.median
                            ),
                            "median_bias_pct": _finite_stat(
                                level_success["bias_pct"], np.median
                            ),
                            "false_safe_rate": _finite_stat(
                                level_success["false_safe"].astype(float), np.mean
                            ),
                            "bootstrap_seed": seed,
                            "bootstrap_resamples": n_resamples,
                            "bootstrap_strata": "feeder|call_time|direction|replicate",
                        }
                        paired = level_success.merge(
                            reference,
                            on="replicate",
                            how="inner",
                            suffixes=("_level", "_reference"),
                            validate="one_to_one",
                        )
                        base_row["paired_n"] = int(len(paired))
                        if level == reference_level and len(level_success):
                            base_row.update(_zero_contrasts())
                            base_row["bootstrap_stream_index"] = None
                        elif len(paired):
                            indices = rng.integers(
                                0, len(paired), size=(n_resamples, len(paired))
                            )
                            base_row.update(
                                _paired_contrast_statistics(paired, indices)
                            )
                            base_row["bootstrap_stream_index"] = stream_index
                            stream_index += 1
                        else:
                            base_row.update(_missing_contrasts())
                            base_row["bootstrap_stream_index"] = None
                        output.append(base_row)
    return pd.DataFrame(output)


def assess_ablation_gate(
    manifest: pd.DataFrame,
    results: pd.DataFrame,
    contrasts: pd.DataFrame,
    input_errors: list[str] | None = None,
) -> dict[str, Any]:
    design = validate_ablation_manifest(manifest)
    input_errors = list(input_errors or [])
    manifest_ids = manifest["ablation_id"].astype(str).tolist()
    result_ids = results["ablation_id"].astype(str).tolist()
    duplicate_ids = sorted(
        results.loc[results["ablation_id"].duplicated(), "ablation_id"].astype(str)
    )
    missing_ids = sorted(set(manifest_ids) - set(result_ids))
    extra_ids = sorted(set(result_ids) - set(manifest_ids))
    unhandled_ids = sorted(
        results.loc[results["work_unit_status"].eq("UNHANDLED_FAILURE"), "ablation_id"].astype(str)
    )
    seed_mismatch_ids = sorted(
        results.loc[
            pd.to_numeric(results["scenario_seed"], errors="coerce").ne(
                pd.to_numeric(results["seed"], errors="coerce")
            ),
            "ablation_id",
        ].astype(str)
    )
    physical_ids = sorted(
        results.loc[
            results["status"].eq("SUCCESS")
            & ~results["physical_feasible"].fillna(False).astype(bool),
            "ablation_id",
        ].astype(str)
    )
    invalid_analysis_rows = contrasts.loc[
        contrasts["n_total"].ne(3)
        | contrasts["n_success"].eq(0)
        | contrasts["paired_n"].eq(0)
    ]
    violations = {
        "input_errors": input_errors,
        "duplicate_ids": duplicate_ids,
        "missing_ids": missing_ids,
        "extra_ids": extra_ids,
        "unhandled_failure_ids": unhandled_ids,
        "seed_mismatch_ids": seed_mismatch_ids,
        "physical_invariant_ids": physical_ids,
        "contrast_row_count": None if len(contrasts) == 112 else int(len(contrasts)),
        "incomplete_analysis_cells": invalid_analysis_rows[
            ["block", "feeder", "call_time", "direction", "factor_level"]
        ].to_dict(orient="records"),
    }
    violations = {
        key: value
        for key, value in violations.items()
        if value not in ([], None, False)
    }
    status_counts = results["status"].astype(str).value_counts().sort_index().to_dict()
    wrapper_counts = (
        results["work_unit_status"].astype(str).value_counts().sort_index().to_dict()
    )
    return {
        "gate": "G4_ABLATION_FREEZE",
        "gate_status": "PASS" if not violations else "FAIL",
        "expected_evaluations": 336,
        "actual_evaluations": int(len(results)),
        "unique_evaluation_ids": int(results["ablation_id"].nunique()),
        "design": design,
        "status_counts": {key: int(value) for key, value in status_counts.items()},
        "work_unit_status_counts": {
            key: int(value) for key, value in wrapper_counts.items()
        },
        "terminal_non_success_ids": sorted(
            results.loc[~results["status"].eq("SUCCESS"), "ablation_id"].astype(str)
        ),
        "contrast_rows": int(len(contrasts)),
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "violations": violations,
    }


def render_ablation_markdown(report: Mapping[str, Any], contrasts: pd.DataFrame) -> str:
    lines = [
        "# EV-FLEX-BIAS-V2.0 compact ablation analysis",
        "",
        f"**Gate status: {report['gate_status']}**",
        "",
        f"- Terminal evaluations: {report['actual_evaluations']} / {report['expected_evaluations']}",
        f"- Unique IDs: {report['unique_evaluation_ids']}",
        f"- Contrast rows: {report['contrast_rows']} / 112",
        f"- Bootstrap: {report['bootstrap_resamples']:,} resamples, seed {report['bootstrap_seed']}",
        f"- Terminal non-success IDs: {len(report['terminal_non_success_ids'])}",
        "",
        "## Block-level ranges",
        "",
        "| Block | Rows | Median alpha range | Median bias range (%) |",
        "|---|---:|---:|---:|",
    ]
    for block in EXPECTED_BLOCK_COUNTS:
        selected = contrasts.loc[contrasts["block"].eq(block)]
        alpha = pd.to_numeric(selected["median_alpha_map"], errors="coerce")
        bias = pd.to_numeric(selected["median_bias_pct"], errors="coerce")
        lines.append(
            f"| {block} | {len(selected)} | {_format_range(alpha)} | {_format_range(bias)} |"
        )
    if report["terminal_non_success_ids"]:
        lines.extend(
            [
                "",
                "## Terminal non-success IDs",
                "",
                ", ".join(report["terminal_non_success_ids"]),
            ]
        )
    if report["violations"]:
        lines.extend(["", "## Gate violations", "", f"`{report['violations']}`"])
    return "\n".join(lines) + "\n"


def _paired_contrast_statistics(
    paired: pd.DataFrame, indices: np.ndarray
) -> dict[str, float]:
    output: dict[str, float] = {}
    specifications = (
        ("alpha", "alpha_map", np.median),
        ("bias", "bias_pct", np.median),
        ("false_safe", "false_safe", np.mean),
    )
    for prefix, column, statistic in specifications:
        level = paired[f"{column}_level"].to_numpy(dtype=float)
        reference = paired[f"{column}_reference"].to_numpy(dtype=float)
        samples = statistic(level[indices], axis=1) - statistic(
            reference[indices], axis=1
        )
        output[f"{prefix}_contrast"] = float(statistic(level) - statistic(reference))
        output[f"{prefix}_contrast_ci_low"] = float(np.quantile(samples, 0.025))
        output[f"{prefix}_contrast_ci_high"] = float(np.quantile(samples, 0.975))
    return output


def _zero_contrasts() -> dict[str, float]:
    return {
        f"{prefix}{suffix}": 0.0
        for prefix in ("alpha_contrast", "bias_contrast", "false_safe_contrast")
        for suffix in ("", "_ci_low", "_ci_high")
    }


def _missing_contrasts() -> dict[str, None]:
    return {
        f"{prefix}{suffix}": None
        for prefix in ("alpha_contrast", "bias_contrast", "false_safe_contrast")
        for suffix in ("", "_ci_low", "_ci_high")
    }


def _finite_stat(series: pd.Series, statistic: Any) -> float | None:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    return float(statistic(values)) if len(values) else None


def _format_range(series: pd.Series) -> str:
    values = series.dropna()
    return "NA" if values.empty else f"{values.min():.3f} to {values.max():.3f}"
