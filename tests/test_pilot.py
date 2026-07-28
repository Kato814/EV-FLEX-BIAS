from __future__ import annotations

from pathlib import Path
import json

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _pilot_api():
    try:
        from evflex.pilot import load_pilot_config, validate_pilot_manifest
    except ModuleNotFoundError:
        pytest.fail("pilot validator is not implemented", pytrace=False)
    return load_pilot_config, validate_pilot_manifest


def _valid_frame() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "manifests" / "audit_pilot_work_units_v2_1.csv")


def test_exact_pilot_manifest_passes():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()

    report = validate_pilot_manifest(frame, config)

    assert report == {
        "work_units": 16,
        "unique_scenarios": 8,
        "evaluations": 48,
        "call_times": ["00:00", "02:00", "06:00", "19:00"],
        "feeders": ["ieee13", "lv906"],
        "directions": ["dec", "inc"],
        "durations": [15, 30, 60],
    }
    assert config["protocol_version"] == "EV-FLEX-BIAS-V2.1-PILOT"
    assert config["workers"] == 1
    assert config["numeric_threads"] == 1
    assert config["scientific_gate_thresholds"]["warm_timing"] == {
        "repeats": 3,
        "cv_pass_max": 0.2,
        "cv_indeterminate_above": 0.3,
    }


def test_core_manifest_head_is_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = pd.read_csv(REPO_ROOT / "manifests" / "core_work_units_v2_0.csv").head(16)

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_duplicate_work_unit_id_is_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    frame.loc[frame.index[1], "work_unit_id"] = frame.loc[frame.index[0], "work_unit_id"]

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_seed_that_differs_from_v2_manifest_is_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    frame.loc[frame.index[0], "scenario_seed"] += 1

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def _drop_one_direction(frame: pd.DataFrame) -> None:
    frame.drop(index=frame.index[1], inplace=True)


def _change_scenario_feeder(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "feeder"] = "lv906"


def _change_scenario_call_time(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "call_time"] = "00:00"


def _change_protocol(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "protocol_version"] = "EV-FLEX-BIAS-V2.0"


def _change_role(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "data_role"] = "development"


def _change_holdout_access(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "holdout_access"] = "development_only"


def _change_status(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "status"] = "SUCCESS"


def _change_evaluation_durations(frame: pd.DataFrame) -> None:
    evaluation_ids = json.loads(frame.loc[frame.index[0], "evaluation_ids"])
    evaluation_ids[-1] = evaluation_ids[-1].replace("__60m", "__45m")
    frame.loc[frame.index[0], "evaluation_ids"] = json.dumps(evaluation_ids)


def _change_evaluation_direction(frame: pd.DataFrame) -> None:
    evaluation_ids = json.loads(frame.loc[frame.index[0], "evaluation_ids"])
    evaluation_ids[0] = evaluation_ids[0].replace("__inc__", "__dec__")
    frame.loc[frame.index[0], "evaluation_ids"] = json.dumps(evaluation_ids)


@pytest.mark.parametrize(
    "mutate",
    [
        _drop_one_direction,
        _change_scenario_feeder,
        _change_scenario_call_time,
        _change_protocol,
        _change_role,
        _change_holdout_access,
        _change_status,
        _change_evaluation_durations,
        _change_evaluation_direction,
    ],
    ids=[
        "paired-directions",
        "scenario-feeder",
        "scenario-call-time",
        "protocol",
        "role",
        "holdout-access",
        "status",
        "durations",
        "evaluation-direction",
    ],
)
def test_invalid_pilot_design_is_rejected(mutate):
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    mutate(frame)

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)
