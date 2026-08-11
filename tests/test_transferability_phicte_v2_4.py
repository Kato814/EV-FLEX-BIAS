from __future__ import annotations

import math

import pytest

from evflex.transferability_phicte_v2_4 import (
    FEATURE_NAMES,
    build_feature_row,
    deterministic_group_folds,
)


def _feature_source(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "evaluation_id": "evaluation_01",
        "scenario_id": "ieee13_0000_01",
        "feeder": "ieee13",
        "call_time": "00:00",
        "direction": "inc",
        "duration_min": 30,
        "f_bal_kw": -100.0,
        "alpha_transfer": 0.01,
        "target_audit": {"vmin": -999.0},
        "witness": {"failure": "outcome-only"},
        "baseline_audit": {
            "vmin": 0.98,
            "vmax": 1.02,
            "vufmax": 0.5,
            "transformer_loading_max": 0.6,
            "feeder_loading_max": 0.7,
        },
    }
    row.update(overrides)
    return row


def test_feature_row_uses_only_allowlisted_pre_call_information() -> None:
    row = _feature_source()

    feature = build_feature_row(row, feeder_kva={"ieee13": 500.0})

    assert tuple(feature) == FEATURE_NAMES
    assert feature["offer_stress"] == pytest.approx(0.2)
    assert feature["voltage_margin"] == pytest.approx(0.03)
    assert feature["vuf_margin"] == pytest.approx(1.5)
    assert feature["transformer_margin"] == pytest.approx(0.4)
    assert feature["feeder_margin"] == pytest.approx(0.3)
    assert feature["feeder_lv906"] == 0.0
    assert feature["direction_inc"] == 1.0
    assert feature["duration_30"] == 1.0
    assert feature["duration_60"] == 0.0
    assert feature["time_0000"] == 1.0
    assert feature["time_0200"] == 0.0
    assert feature["time_0600"] == 0.0
    assert "alpha_transfer" not in feature
    assert "target_audit" not in feature
    assert "witness" not in feature

    changed_outcome = _feature_source(
        alpha_transfer=1.0,
        target_audit={"vmin": 999.0},
        witness={"failure": "changed"},
    )
    assert build_feature_row(
        changed_outcome, feeder_kva={"ieee13": 500.0}
    ) == feature


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"f_bal_kw": math.nan}, "f_bal_kw"),
        (
            {
                "baseline_audit": {
                    "vmin": 0.98,
                    "vmax": 1.02,
                    "vufmax": math.inf,
                    "transformer_loading_max": 0.6,
                    "feeder_loading_max": 0.7,
                }
            },
            "vufmax",
        ),
    ],
)
def test_feature_row_rejects_nonfinite_required_inputs(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_feature_row(
            _feature_source(**override), feeder_kva={"ieee13": 500.0}
        )


def test_grouped_folds_never_split_scenarios() -> None:
    rows = [
        {"scenario_id": f"scenario_{scenario}", "replicate": replicate}
        for scenario in range(8)
        for replicate in range(3)
    ]

    folds = deterministic_group_folds(rows, n_splits=4)

    assert len(folds) == 4
    tested: list[int] = []
    for train, test in folds:
        assert {rows[index]["scenario_id"] for index in train}.isdisjoint(
            {rows[index]["scenario_id"] for index in test}
        )
        tested.extend(test)
    assert sorted(tested) == list(range(len(rows)))
    assert deterministic_group_folds(rows, n_splits=4) == folds
