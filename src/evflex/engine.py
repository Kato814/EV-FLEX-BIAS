from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pandas as pd

from evflex.fleet import load_fleet_bundle
from evflex.network import configure_core, load_legacy_core


DURATIONS = (15, 30, 60)
PHYSICAL_TOLERANCE_KWH = 1e-6


def select_nested_candidate(
    raw_by_duration: Mapping[int, Mapping[str, Any]], requested_duration: int
) -> dict[str, Any]:
    candidates = []
    for source_duration, result in raw_by_duration.items():
        if int(source_duration) < int(requested_duration):
            continue
        if not bool(result.get("physical_feasible", True)):
            continue
        candidates.append(
            (float(result["flex_kw"]), -int(source_duration), int(source_duration), result)
        )
    if not candidates:
        raise RuntimeError(f"no feasible nested candidate for {requested_duration}")
    _, _, source, result = max(candidates, key=lambda item: (item[0], item[1]))
    selected = dict(result)
    selected["requested_duration_min"] = int(requested_duration)
    selected["source_duration_min"] = int(source)
    selected["monotonic_closure_promoted"] = source != requested_duration
    return selected


def load_archived_engine(path: Path) -> ModuleType:
    source = path.resolve(strict=True)
    module_name = f"evflex_archived_duration_engine_{source.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load archived duration engine: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def compare_all_durations(
    repo_root: Path,
    work_unit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Solve one scenario-direction bundle and apply model-specific duration closure."""
    repo = repo_root.resolve(strict=True)
    scenario_id = str(work_unit["scenario_id"])
    feeder = str(work_unit["feeder"])
    call_time = str(work_unit["call_time"])
    direction = str(work_unit["direction"])
    if direction not in {"inc", "dec"}:
        raise ValueError(f"Unsupported direction: {direction}")

    archived_engine = load_archived_engine(
        repo / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    legacy_core = load_legacy_core(repo / "legacy" / "d5_v1_2" / "network_core_v1_2.py")
    configure_core(legacy_core, repo)
    bundle = load_fleet_bundle(repo, scenario_id, archived_engine, legacy_core)
    if str(bundle.scenario["feeder"]) != feeder:
        raise ValueError(f"Feeder mismatch for {scenario_id}")
    if str(bundle.scenario["call_time"]) != call_time:
        raise ValueError(f"Call-time mismatch for {scenario_id}")

    raw_by_model: dict[str, dict[int, dict[str, Any]]] = {
        "balanced": {},
        "3ph": {},
    }
    raw_runtime: dict[int, float] = {}
    for duration in DURATIONS:
        started = time.perf_counter()
        for model in ("balanced", "3ph"):
            result = archived_engine.duration_result(
                legacy_core,
                feeder,
                bundle.fleet,
                bundle.baseline,
                archived_engine.CALL_SLOTS[call_time],
                duration,
                direction,
                bundle.load_scales,
                model,
            )
            result = dict(result)
            result["physical_feasible"] = _model_result_is_physical(result)
            raw_by_model[model][duration] = result
        raw_runtime[duration] = time.perf_counter() - started

    evaluation_ids = _evaluation_ids_by_duration(work_unit)
    hashes = _provenance_hashes(repo)
    truth_cache = archived_engine.network_cache(
        legacy_core, feeder, bundle.fleet, bundle.load_scales, "3ph"
    )
    rows: list[dict[str, Any]] = []
    for requested_duration in DURATIONS:
        balanced = select_nested_candidate(
            raw_by_model["balanced"], requested_duration
        )
        three_phase = select_nested_candidate(raw_by_model["3ph"], requested_duration)
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

        f_bal = float(balanced["flex_kw"])
        f_3ph = float(three_phase["flex_kw"])
        physical = bool(
            balanced["physical_feasible"]
            and three_phase["physical_feasible"]
            and mapped_check["feasible"]
        )
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
            int(balanced["simultaneous_slots"]),
            int(three_phase["simultaneous_slots"]),
        )
        rows.append(
            {
                "evaluation_id": evaluation_ids[requested_duration],
                "work_unit_id": str(work_unit["work_unit_id"]),
                "protocol_version": "EV-FLEX-BIAS-V2.0",
                "scenario_id": scenario_id,
                "scenario_seed": int(work_unit["scenario_seed"]),
                "data_role": str(work_unit["data_role"]),
                "feeder": feeder,
                "call_time": call_time,
                "direction": direction,
                "duration_min": requested_duration,
                "requested_duration_min": requested_duration,
                "source_duration_min": int(balanced["source_duration_min"]),
                "balanced_source_duration_min": int(balanced["source_duration_min"]),
                "three_phase_source_duration_min": int(three_phase["source_duration_min"]),
                "balanced_closure_promoted": bool(
                    balanced["monotonic_closure_promoted"]
                ),
                "three_phase_closure_promoted": bool(
                    three_phase["monotonic_closure_promoted"]
                ),
                "n_ev": len(bundle.fleet),
                "f_bal_kw": f_bal,
                "f_3ph_kw": f_3ph,
                "bias_pct": (f_bal - f_3ph) / max(f_3ph, 1e-9) * 100.0,
                "alpha_map": float(alpha_map),
                "mapped_flex_kw": f_bal * float(alpha_map),
                "raw_balanced_schedule_feasible": bool(alpha_map >= 0.999999),
                "balanced_trajectory_alpha": float(balanced["trajectory_alpha"]),
                "three_phase_trajectory_alpha": float(three_phase["trajectory_alpha"]),
                "balanced_network_alpha": float(balanced["model_network_alpha"]),
                "three_phase_network_alpha": float(three_phase["model_network_alpha"]),
                "max_departure_error_kwh": maximum_departure_error,
                "max_reserve_violation_kwh": maximum_reserve_violation,
                "max_capacity_violation_kwh": maximum_capacity_violation,
                "simultaneous_slots": simultaneous_slots,
                "balanced_network_feasible": bool(
                    balanced["model_network_check"]["feasible"]
                ),
                "three_phase_network_feasible": bool(
                    three_phase["model_network_check"]["feasible"]
                ),
                "mapped_network_feasible": bool(mapped_check["feasible"]),
                "physical_feasible": physical,
                "status": "SUCCESS" if physical else "PHYSICAL_INVARIANT_FAILED",
                "raw_solve_runtime_s": sum(
                    raw_runtime[source]
                    for source in {
                        int(balanced["source_duration_min"]),
                        int(three_phase["source_duration_min"]),
                    }
                ),
                "provenance_sha256": hashes,
            }
        )

    validate_result_bundle(rows, work_unit)
    return rows


def validate_result_bundle(
    rows: list[Mapping[str, Any]], work_unit: Mapping[str, Any] | None = None
) -> None:
    if len(rows) != 3:
        raise ValueError(f"A work unit must contain three evaluations, found {len(rows)}")
    durations = {int(row["duration_min"]) for row in rows}
    if durations != set(DURATIONS):
        raise ValueError(f"Invalid duration bundle: {sorted(durations)}")
    ids = [str(row["evaluation_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate evaluation ID in result bundle")
    for row in rows:
        if not bool(row["physical_feasible"]):
            raise ValueError(f"Physical invariant failed: {row['evaluation_id']}")
        if float(row["max_reserve_violation_kwh"]) > PHYSICAL_TOLERANCE_KWH:
            raise ValueError(f"Reserve violation: {row['evaluation_id']}")
        if int(row["simultaneous_slots"]) != 0:
            raise ValueError(f"Simultaneous charging/discharging: {row['evaluation_id']}")
    ordered = sorted(rows, key=lambda row: int(row["duration_min"]))
    for capacity_field in ("f_bal_kw", "f_3ph_kw"):
        capacities = [float(row[capacity_field]) for row in ordered]
        if any(right - left > 1e-5 for left, right in zip(capacities, capacities[1:])):
            raise ValueError(f"Duration monotonicity failed for {capacity_field}: {capacities}")
    if work_unit is not None:
        expected = set(_evaluation_ids_by_duration(work_unit).values())
        if set(ids) != expected:
            raise ValueError("Result evaluation IDs do not match work-unit manifest")


def _model_result_is_physical(result: Mapping[str, Any]) -> bool:
    return bool(
        float(result["max_departure_error_kwh"]) <= PHYSICAL_TOLERANCE_KWH
        and float(result["max_reserve_violation_kwh"]) <= PHYSICAL_TOLERANCE_KWH
        and float(result["max_capacity_violation_kwh"]) <= PHYSICAL_TOLERANCE_KWH
        and int(result["simultaneous_slots"]) == 0
        and bool(result["model_network_check"]["feasible"])
    )


def _evaluation_ids_by_duration(work_unit: Mapping[str, Any]) -> dict[int, str]:
    raw = work_unit["evaluation_ids"]
    ids = json.loads(raw) if isinstance(raw, str) else list(raw)
    result: dict[int, str] = {}
    for evaluation_id in ids:
        matched = False
        for duration in DURATIONS:
            if str(evaluation_id).endswith(f"__{duration}m"):
                result[duration] = str(evaluation_id)
                matched = True
                break
        if not matched:
            raise ValueError(f"Cannot identify duration from evaluation ID: {evaluation_id}")
    if set(result) != set(DURATIONS):
        raise ValueError(f"Incomplete work-unit evaluation IDs: {ids}")
    return result


def _provenance_hashes(repo: Path) -> dict[str, str]:
    manifest = pd.read_csv(repo / "manifests" / "inherited_asset_manifest_v2_0.csv")
    by_id = manifest.set_index("asset_id")["sha256"].to_dict()
    required = {
        "base_scenarios": "base_scenarios_v1_2",
        "native_load_profile": "native_load_profile_v1_2",
        "formal_ev_populations": "formal_ev_populations_v1_2",
        "duration_engine": "d5_duration_engine_v1_2",
        "network_core": "d5_network_core_v1_2",
    }
    missing = [asset_id for asset_id in required.values() if asset_id not in by_id]
    if missing:
        raise ValueError(f"Missing provenance hashes: {missing}")
    return {name: str(by_id[asset_id]) for name, asset_id in required.items()}
