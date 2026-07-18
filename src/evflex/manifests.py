from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from evflex.schema import CALL_TIMES, DURATIONS, FEEDERS


CORE_REQUIRED_COLUMNS = (
    "run_id",
    "protocol_version",
    "scenario_id",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "scenario_seed",
    "data_split",
    "status",
)

BLOCK_LEVELS = {
    "A1_phase": ("phase_ratio", ("1:1:1", "2:1:1", "4:1:1"), ("inc", "dec")),
    "A2_location": ("far_zone_probability", (0.20, 0.50, 0.80), ("inc", "dec")),
    "A3_load": ("native_load_multiplier", (0.75, 0.90, 1.05), ("inc", "dec")),
    "A4_urgency": ("urgency_quantile", (0.40, 0.65, 0.90), ("inc", "dec")),
    "A5_v2g": ("v2g_participation", (0.25, 0.50, 0.75, 1.00), ("dec",)),
}
ABLATION_CALL_TIMES = ("19:00", "02:00")
REPLICATES = (0, 1, 2)
SEED_BASE = 2026072001


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def normalize_core_manifest(inherited: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    _require_columns(inherited, CORE_REQUIRED_COLUMNS, "inherited core manifest")
    frame = inherited.copy()
    if frame["run_id"].duplicated().any():
        raise ValueError("duplicate inherited run_id")
    if not set(frame["data_split"]).issubset({"development", "holdout"}):
        raise ValueError("unexpected data_split")

    frame["duration_min"] = frame["duration_min"].astype(int)
    frame["scenario_seed"] = frame["scenario_seed"].astype(int)
    frame["evaluation_id"] = frame.apply(
        lambda row: (
            f"v20_core_{row['scenario_id']}__{row['direction']}__"
            f"{int(row['duration_min'])}m"
        ),
        axis=1,
    )
    frame["work_unit_id"] = frame.apply(
        lambda row: f"v20_work_{row['scenario_id']}__{row['direction']}", axis=1
    )
    frame["data_role"] = frame["data_split"]
    frame["holdout_access"] = frame["data_role"].map(
        {"development": "development_only", "holdout": "sealed"}
    )
    frame["protocol_version"] = "EV-FLEX-BIAS-V2.0"
    frame["inherited_run_id"] = frame["run_id"]
    frame["status"] = "PENDING"
    evaluation_columns = [
        "evaluation_id",
        "protocol_version",
        "inherited_run_id",
        "scenario_id",
        "feeder",
        "call_time",
        "direction",
        "duration_min",
        "scenario_seed",
        "data_role",
        "work_unit_id",
        "holdout_access",
        "status",
    ]
    evaluations = frame[evaluation_columns].copy()

    work_rows: list[dict[str, object]] = []
    for work_unit_id, group in evaluations.groupby("work_unit_id", sort=False):
        group = group.sort_values("duration_min", kind="stable")
        durations = tuple(int(value) for value in group["duration_min"])
        if durations != DURATIONS:
            raise ValueError(f"work unit {work_unit_id} durations are {durations}")
        for column in (
            "scenario_id",
            "feeder",
            "call_time",
            "direction",
            "scenario_seed",
            "data_role",
            "holdout_access",
        ):
            if group[column].nunique(dropna=False) != 1:
                raise ValueError(f"work unit {work_unit_id} varies in {column}")
        first = group.iloc[0]
        work_rows.append(
            {
                "work_unit_id": work_unit_id,
                "protocol_version": "EV-FLEX-BIAS-V2.0",
                "scenario_id": first["scenario_id"],
                "feeder": first["feeder"],
                "call_time": first["call_time"],
                "direction": first["direction"],
                "scenario_seed": int(first["scenario_seed"]),
                "data_role": first["data_role"],
                "evaluation_ids": json.dumps(group["evaluation_id"].tolist(), separators=(",", ":")),
                "holdout_access": first["holdout_access"],
                "status": "PENDING",
            }
        )
    work_units = pd.DataFrame(work_rows)
    validate_core_manifests(evaluations, work_units)
    return evaluations, work_units


def validate_core_manifests(evaluations: pd.DataFrame, work_units: pd.DataFrame) -> None:
    if len(evaluations) != 1536:
        raise ValueError(f"expected 1536 evaluations, got {len(evaluations)}")
    if len(work_units) != 512:
        raise ValueError(f"expected 512 work units, got {len(work_units)}")
    if evaluations["evaluation_id"].nunique() != len(evaluations):
        raise ValueError("duplicate evaluation_id")
    if work_units["work_unit_id"].nunique() != len(work_units):
        raise ValueError("duplicate work_unit_id")
    expected_roles = {"development": 1152, "holdout": 384}
    if evaluations["data_role"].value_counts().to_dict() != expected_roles:
        raise ValueError(f"evaluation role counts differ: {evaluations['data_role'].value_counts().to_dict()}")
    expected_work_roles = {"development": 384, "holdout": 128}
    if work_units["data_role"].value_counts().to_dict() != expected_work_roles:
        raise ValueError(f"work role counts differ: {work_units['data_role'].value_counts().to_dict()}")
    if set(evaluations["duration_min"].astype(int)) != set(DURATIONS):
        raise ValueError("unexpected duration set")
    if set(evaluations["feeder"]) != set(FEEDERS):
        raise ValueError("unexpected feeder set")
    if set(evaluations["call_time"]) != set(CALL_TIMES):
        raise ValueError("unexpected call-time set")
    grouped = evaluations.groupby("work_unit_id", sort=False)
    if not (grouped.size() == 3).all():
        raise ValueError("every core work unit must contain three evaluations")
    if set(grouped.groups) != set(work_units["work_unit_id"]):
        raise ValueError("evaluation/work-unit ID sets differ")
    expected_access = evaluations["data_role"].map(
        {"development": "development_only", "holdout": "sealed"}
    )
    if not evaluations["holdout_access"].equals(expected_access):
        raise ValueError("holdout_access does not match data_role")


def build_ablation_manifest() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    counter = 0
    base = {
        "ev_nameplate_to_transformer_ratio": 0.35,
        "native_load_multiplier": 0.90,
        "phase_ratio": "2:1:1",
        "far_zone_probability": 0.50,
        "v2g_participation": 0.50,
        "urgency_quantile": 0.65,
    }
    phases = ("a", "b", "c")
    for block, (factor, levels, directions) in BLOCK_LEVELS.items():
        for feeder in FEEDERS:
            for call_time in ABLATION_CALL_TIMES:
                for direction in directions:
                    for level in levels:
                        for replicate in REPLICATES:
                            settings = dict(base)
                            settings[factor] = level
                            counter += 1
                            rows.append(
                                {
                                    "ablation_id": f"v20_abl_{counter:04d}",
                                    "protocol_version": "EV-FLEX-BIAS-V2.0",
                                    "block": block,
                                    "feeder": feeder,
                                    "call_time": call_time,
                                    "direction": direction,
                                    "duration_min": 15,
                                    "seed": SEED_BASE + counter - 1,
                                    "replicate": replicate,
                                    "varied_factor": factor,
                                    "factor_level": level,
                                    **settings,
                                    "dominant_phase": phases[replicate],
                                    "data_role": "development_ablation",
                                    "holdout_access": "prohibited",
                                    "status": "PENDING",
                                }
                            )
    frame = pd.DataFrame(rows)
    if len(frame) != 336:
        raise AssertionError(f"compact ablation count is {len(frame)}, expected 336")
    if frame["ablation_id"].nunique() != 336 or frame["seed"].nunique() != 336:
        raise AssertionError("ablation IDs and seeds must be unique")
    return frame


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    frame.to_csv(temp, index=False, encoding="utf-8", lineterminator="\n")
    temp.replace(path)
