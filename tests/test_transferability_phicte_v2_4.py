from __future__ import annotations

import math

import pytest

from evflex.transferability_phicte_v2_4 import (
    FEATURE_NAMES,
    build_feature_row,
    calibration_rank_status,
    cross_fit,
    deterministic_group_folds,
    fit_constrained_quantile,
    one_sided_correction,
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


def _cross_fit_rows() -> list[dict[str, object]]:
    rows = []
    for scenario_index in range(8):
        feeder = "ieee13" if scenario_index < 4 else "lv906"
        for duration in (15, 30, 60):
            stress = 0.05 + scenario_index / 20.0 + duration / 1000.0
            rows.append(
                _feature_source(
                    evaluation_id=f"evaluation_{scenario_index}_{duration}",
                    scenario_id=f"scenario_{scenario_index}",
                    feeder=feeder,
                    direction="inc" if scenario_index % 2 else "dec",
                    duration_min=duration,
                    f_bal_kw=stress * (500.0 if feeder == "ieee13" else 100.0),
                    alpha_transfer=max(0.05, 0.95 - 0.8 * stress),
                )
            )
    return rows


def test_cross_fit_predicts_each_row_once_without_scenario_overlap() -> None:
    rows = _cross_fit_rows()

    result = cross_fit(
        rows,
        feeder_kva={"ieee13": 500.0, "lv906": 100.0},
        penalties=(0.0005, 0.002, 0.01),
        n_splits=4,
        quantile=0.10,
        target_risk=0.05,
    )

    assert result["prediction_counts"] == [1] * len(rows)
    assert result["scenario_overlap_count"] == 0
    assert len(result["oof_quantile_predictions"]) == len(rows)
    assert len(result["oof_lower_bounds"]) == len(rows)
    assert result["selected_penalty"] in {0.0005, 0.002, 0.01}
    assert result["final_model"].training_n == len(rows)


def test_one_sided_correction_uses_finite_sample_rank() -> None:
    correction, rank = one_sided_correction(
        [0.1, -0.1, 0.2, 0.0], target_risk=0.20
    )

    assert rank == 4
    assert correction == pytest.approx(0.2)


def test_sixteen_scenarios_cannot_support_nontrivial_95_percent_rank() -> None:
    status = calibration_rank_status(sample_n=16, target_risk=0.05)

    assert status["status"] == "NOT_EVALUABLE_NONTRIVIAL_95_PERCENT"
    assert status["rank"] == 17
    assert status["minimum_sample_n"] == 19
