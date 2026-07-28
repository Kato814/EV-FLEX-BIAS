from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from numbers import Number
from pathlib import Path
from typing import Any

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
