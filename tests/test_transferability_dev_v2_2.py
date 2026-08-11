from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frozen_development_design_is_small_fresh_and_factorial():
    from evflex.transferability_dev_v2_2 import load_development_design

    config, frame = load_development_design(REPO_ROOT)

    assert config["protocol_version"] == "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-DEV"
    assert config["workers"] == 1
    assert config["numeric_threads"] == 1
    assert len(frame) == 32
    assert frame["scenario_id"].nunique() == 16
    assert set(frame["feeder"]) == {"ieee13", "lv906"}
    assert set(frame["call_time"]) == {"19:00", "00:00", "02:00", "06:00"}
    assert set(frame["direction"]) == {"inc", "dec"}
    assert set(frame["data_role"]) == {"development_transferability"}
    assert set(frame["holdout_access"]) == {"prohibited"}
    assert set(frame["status"]) == {"PENDING"}

    expected_scenarios = {
        f"{feeder}_{call_time}_{index:02d}"
        for feeder in ("ieee13", "lv906")
        for call_time in ("1900", "0000", "0200", "0600")
        for index in (5, 13)
    }
    assert set(frame["scenario_id"]) == expected_scenarios

    pilot = json.loads(
        (REPO_ROOT / "config" / "pilot_gate_v2_1.json").read_text(
            encoding="utf-8"
        )
    )
    assert expected_scenarios.isdisjoint(pilot["scenario_ids"])

    paired = frame.groupby("scenario_id")["direction"].apply(set)
    assert all(directions == {"inc", "dec"} for directions in paired)
    assert frame["work_unit_id"].is_unique
    assert all(value.startswith("v22_dev_") for value in frame["work_unit_id"])
    assert all(
        len(json.loads(value)) == 3 for value in frame["evaluation_ids"]
    )


def test_owned_paths_are_isolated_from_every_frozen_result_namespace():
    from evflex.transferability_dev_v2_2 import owned_paths

    paths = owned_paths(REPO_ROOT, "v22_dev_ieee13_1900_05__inc")

    assert paths.result.relative_to(REPO_ROOT).as_posix().startswith(
        "results/transferability_dev_v2_2/work_units/"
    )
    assert paths.lock.relative_to(REPO_ROOT).as_posix().startswith(
        "state/runtime/locks/transferability_dev_v2_2/"
    )
    assert paths.attempt.relative_to(REPO_ROOT).as_posix().startswith(
        "state/runtime/attempts/transferability_dev_v2_2/"
    )
    frozen_namespaces = {
        "results/pilot_v2_1",
        "results/mechanism_diagnostic_v2_1",
        "results/mechanism_diagnostic_v2_1_d1r_lite",
        "results/numerical_certainty_replay_v2_1_d1r_lite",
    }
    assert all(
        not paths.result.relative_to(REPO_ROOT).as_posix().startswith(namespace)
        for namespace in frozen_namespaces
    )
