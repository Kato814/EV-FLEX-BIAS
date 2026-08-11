from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, NamedTuple

import pandas as pd


PROTOCOL_VERSION = "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-DEV"
CONFIG_RELATIVE_PATH = Path("config/transferability_dev_v2_2.json")
RESULT_DIRECTORY = Path("results/transferability_dev_v2_2/work_units")
LOCK_DIRECTORY = Path("state/runtime/locks/transferability_dev_v2_2")
ATTEMPT_DIRECTORY = Path("state/runtime/attempts/transferability_dev_v2_2")
_SAFE_ID = re.compile(r"v22_dev_[a-z0-9_]+__(?:inc|dec)")


class OwnedPaths(NamedTuple):
    result: Path
    lock: Path
    attempt: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def owned_paths(repo_root: str | Path, work_unit_id: str) -> OwnedPaths:
    root = Path(repo_root).resolve(strict=False)
    unit_id = str(work_unit_id)
    if _SAFE_ID.fullmatch(unit_id) is None:
        raise ValueError(f"unsafe V2.2 development work-unit ID: {unit_id!r}")
    return OwnedPaths(
        result=root / RESULT_DIRECTORY / f"{unit_id}.json",
        lock=root / LOCK_DIRECTORY / f"{unit_id}.lock",
        attempt=root / ATTEMPT_DIRECTORY / f"{unit_id}.json",
    )


def load_development_design(
    repo_root: str | Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    root = Path(repo_root).resolve(strict=True)
    config_path = root / CONFIG_RELATIVE_PATH
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)

    source_path = root / str(config["source_manifest"])
    observed_hash = _sha256(source_path)
    if observed_hash != config["source_manifest_sha256"]:
        raise ValueError(
            "V2.2 development source manifest hash differs from the frozen hash"
        )
    source = pd.read_csv(source_path)
    scenario_ids = list(config["scenario_ids"])
    selected = source[source["scenario_id"].isin(scenario_ids)].copy()
    if len(selected) != 32:
        raise ValueError(f"V2.2 development design requires 32 rows, got {len(selected)}")
    if set(selected["scenario_id"]) != set(scenario_ids):
        raise ValueError("V2.2 development scenario set is incomplete")
    if set(selected["protocol_version"]) != {config["source_protocol_version"]}:
        raise ValueError("V2.2 source protocol version differs from the frozen value")
    if set(selected["data_role"]) != {"development"}:
        raise ValueError("V2.2 development design must not access holdout rows")
    if set(selected["holdout_access"]) != {"development_only"}:
        raise ValueError("V2.2 development source rows have unexpected access labels")

    source_by_key = {
        (str(row.scenario_id), str(row.direction)): row
        for row in selected.itertuples(index=False)
    }
    if len(source_by_key) != 32:
        raise ValueError("V2.2 development source rows are not unique")

    records: list[dict[str, Any]] = []
    durations = [int(value) for value in config["durations_min"]]
    for scenario_id in scenario_ids:
        scenario_rows = selected[selected["scenario_id"] == scenario_id]
        if set(scenario_rows["direction"]) != {"inc", "dec"}:
            raise ValueError(f"scenario {scenario_id} does not have paired directions")
        for column in ("feeder", "call_time", "scenario_seed"):
            if scenario_rows[column].nunique(dropna=False) != 1:
                raise ValueError(f"scenario {scenario_id} varies in {column}")
        first = scenario_rows.iloc[0]
        if str(first["feeder"]) not in config["feeders"]:
            raise ValueError(f"scenario {scenario_id} has an unexpected feeder")
        if str(first["call_time"]) not in config["call_times"]:
            raise ValueError(f"scenario {scenario_id} has an unexpected call time")
        for direction in config["directions"]:
            source_row = source_by_key[(scenario_id, direction)]
            unit_id = f"v22_dev_{scenario_id}__{direction}"
            evaluation_ids = [
                f"v22_dev_{scenario_id}__{direction}__{duration}m"
                for duration in durations
            ]
            records.append(
                {
                    "work_unit_id": unit_id,
                    "protocol_version": config["protocol_version"],
                    "scenario_id": scenario_id,
                    "feeder": str(source_row.feeder),
                    "call_time": str(source_row.call_time),
                    "direction": direction,
                    "scenario_seed": int(source_row.scenario_seed),
                    "data_role": config["design_role"],
                    "evaluation_ids": json.dumps(
                        evaluation_ids, ensure_ascii=False, separators=(",", ":")
                    ),
                    "holdout_access": "prohibited",
                    "status": "PENDING",
                }
            )

    frame = pd.DataFrame.from_records(records)
    if len(frame) != 32 or frame["work_unit_id"].duplicated().any():
        raise ValueError("V2.2 development manifest construction failed")
    config["_config_sha256"] = _sha256(config_path)
    return config, frame


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("V2.2 development protocol version is not frozen")
    if config.get("source_protocol_version") != "EV-FLEX-BIAS-V2.0":
        raise ValueError("V2.2 development source protocol is not frozen")
    if config.get("source_manifest") != "manifests/core_work_units_v2_0.csv":
        raise ValueError("V2.2 development source manifest is not frozen")
    if config.get("workers") != 1 or config.get("numeric_threads") != 1:
        raise ValueError("V2.2 development resource policy must be exactly one thread")
    if config.get("design_role") != "development_transferability":
        raise ValueError("V2.2 development role is not frozen")
    if config.get("directions") != ["inc", "dec"]:
        raise ValueError("V2.2 development directions are not frozen")
    if config.get("durations_min") != [15, 30, 60]:
        raise ValueError("V2.2 development durations are not frozen")
    scenario_ids = config.get("scenario_ids")
    if not isinstance(scenario_ids, list) or len(scenario_ids) != 16:
        raise ValueError("V2.2 development requires exactly 16 scenarios")
    if len(set(scenario_ids)) != 16:
        raise ValueError("V2.2 development scenario IDs must be unique")
    if config.get("feeders") != ["ieee13", "lv906"]:
        raise ValueError("V2.2 development feeders are not frozen")
    if config.get("call_times") != ["19:00", "00:00", "02:00", "06:00"]:
        raise ValueError("V2.2 development call times are not frozen")
    constraints = config.get("formal_constraints")
    if not isinstance(constraints, dict) or constraints.get(
        "line_thermal_in_scope"
    ) is not False:
        raise ValueError("V2.2 line-thermal scope must remain explicitly false")
    warm = config.get("scientific_gate_thresholds", {}).get("warm_timing", {})
    if warm.get("repeats") != 3:
        raise ValueError("V2.2 development timing repeats must remain three")
