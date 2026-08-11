from __future__ import annotations

import math

import pytest

from evflex.transferability_phicte_v2_4 import (
    FEATURE_NAMES,
    build_feature_row,
    deterministic_group_folds,
    fit_constrained_quantile,
    penalty_weight,
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


def _model_feature(**overrides: float) -> dict[str, float]:
    feature = {name: 0.0 for name in FEATURE_NAMES}
    feature.update(overrides)
    return feature


def test_model_respects_physical_signs_and_uses_training_scaler() -> None:
    features = []
    targets = []
    for index in range(24):
        position = index / 23.0
        features.append(
            _model_feature(
                offer_stress=position,
                voltage_margin=1.0 - position,
                vuf_margin=0.5 + (index % 4) / 10.0,
                transformer_margin=0.2 + (index % 3) / 10.0,
                feeder_margin=0.4 + (index % 5) / 10.0,
                feeder_lv906=float(index % 2),
                direction_inc=float((index // 2) % 2),
                lv906_x_inc=float(index % 4 == 3),
            )
        )
        targets.append(0.2 + 0.7 * position)

    model = fit_constrained_quantile(
        features, targets, quantile=0.10, penalty=0.002
    )

    assert model.coefficient("offer_stress") <= 1e-10
    for name in (
        "voltage_margin",
        "vuf_margin",
        "transformer_margin",
        "feeder_margin",
    ):
        assert model.coefficient(name) >= -1e-10
    assert model.centers["offer_stress"] == pytest.approx(0.5)
    predictions = model.predict(features)
    assert len(predictions) == len(features)
    assert all(math.isfinite(value) for value in predictions)


def test_interactions_are_shrunk_more_than_main_effects() -> None:
    assert penalty_weight("lv906_x_inc") == 4.0
    assert penalty_weight("inc_x_duration_60") == 4.0
    assert penalty_weight("offer_stress") == 1.0
    assert penalty_weight("feeder_lv906") == 1.0
    assert penalty_weight("intercept") == 0.0
