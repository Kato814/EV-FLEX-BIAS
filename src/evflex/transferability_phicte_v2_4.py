from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import linprog

from evflex.transferability_baseline_comparison_v2_3 import (
    POLICY_SPECS,
    apply_fitted_policy,
    fit_policy,
    is_material_false_safe,
    load_project_evaluations,
    validate_evaluation_rows,
    wilson_interval,
)


ANALYSIS_VERSION = "EV-FLEX-BIAS-V2.4-PHICTE-RETROSPECTIVE-EXPLORATORY"
DEFAULT_PENALTIES = (0.0005, 0.002, 0.01)
DEFAULT_QUANTILE = 0.10
DEFAULT_TARGET_RISK = 0.05


FEATURE_NAMES = (
    "offer_stress",
    "voltage_margin",
    "vuf_margin",
    "transformer_margin",
    "feeder_margin",
    "feeder_lv906",
    "direction_inc",
    "duration_30",
    "duration_60",
    "time_0000",
    "time_0200",
    "time_0600",
    "lv906_x_inc",
    "lv906_x_duration_30",
    "lv906_x_duration_60",
    "inc_x_duration_30",
    "inc_x_duration_60",
)

CONTINUOUS_FEATURE_NAMES = FEATURE_NAMES[:5]
PHYSICAL_NONPOSITIVE_COEFFICIENTS = {"offer_stress"}
PHYSICAL_NONNEGATIVE_COEFFICIENTS = {
    "voltage_margin",
    "vuf_margin",
    "transformer_margin",
    "feeder_margin",
}


def _required_finite(value: Any, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _required_category(
    row: Mapping[str, Any], field: str, allowed: set[Any]
) -> Any:
    value = row.get(field)
    if value not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed, key=str)!r}")
    return value


def build_feature_row(
    row: Mapping[str, Any], *, feeder_kva: Mapping[str, float]
) -> dict[str, float]:
    """Build the allowlisted pre-call PHiCTE features for one offer."""

    feeder = _required_category(row, "feeder", {"ieee13", "lv906"})
    direction = _required_category(row, "direction", {"inc", "dec"})
    duration = _required_category(row, "duration_min", {15, 30, 60})
    call_time = _required_category(
        row, "call_time", {"19:00", "00:00", "02:00", "06:00"}
    )
    if feeder not in feeder_kva:
        raise ValueError(f"feeder_kva lacks {feeder!r}")
    rating = _required_finite(feeder_kva[feeder], f"feeder_kva[{feeder}]")
    if rating <= 0.0:
        raise ValueError(f"feeder_kva[{feeder}] must be positive")

    audit = row.get("baseline_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("baseline_audit must be a mapping")
    f_bal_kw = _required_finite(row.get("f_bal_kw"), "f_bal_kw")
    vmin = _required_finite(audit.get("vmin"), "baseline_audit.vmin")
    vmax = _required_finite(audit.get("vmax"), "baseline_audit.vmax")
    vufmax = _required_finite(audit.get("vufmax"), "baseline_audit.vufmax")
    transformer_loading = _required_finite(
        audit.get("transformer_loading_max"),
        "baseline_audit.transformer_loading_max",
    )
    feeder_loading = _required_finite(
        audit.get("feeder_loading_max"), "baseline_audit.feeder_loading_max"
    )

    lv906 = float(feeder == "lv906")
    inc = float(direction == "inc")
    duration_30 = float(duration == 30)
    duration_60 = float(duration == 60)
    values = {
        "offer_stress": abs(f_bal_kw) / rating,
        "voltage_margin": min(vmin - 0.95, 1.06 - vmax),
        "vuf_margin": 2.0 - vufmax,
        "transformer_margin": 1.0 - transformer_loading,
        "feeder_margin": 1.0 - feeder_loading,
        "feeder_lv906": lv906,
        "direction_inc": inc,
        "duration_30": duration_30,
        "duration_60": duration_60,
        "time_0000": float(call_time == "00:00"),
        "time_0200": float(call_time == "02:00"),
        "time_0600": float(call_time == "06:00"),
        "lv906_x_inc": lv906 * inc,
        "lv906_x_duration_30": lv906 * duration_30,
        "lv906_x_duration_60": lv906 * duration_60,
        "inc_x_duration_30": inc * duration_30,
        "inc_x_duration_60": inc * duration_60,
    }
    return {name: values[name] for name in FEATURE_NAMES}


def deterministic_group_folds(
    rows: Sequence[Mapping[str, Any]], *, n_splits: int
) -> list[tuple[list[int], list[int]]]:
    """Return deterministic balanced folds without splitting scenario identities."""

    if not isinstance(n_splits, int) or isinstance(n_splits, bool) or n_splits < 2:
        raise ValueError("n_splits must be an integer of at least two")
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        scenario_id = row.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ValueError(f"row {index} has invalid scenario_id")
        grouped[scenario_id].append(index)
    if len(grouped) < n_splits:
        raise ValueError("n_splits exceeds the number of distinct scenarios")

    fold_groups: list[list[str]] = [[] for _ in range(n_splits)]
    fold_sizes = [0] * n_splits
    ordered_groups = sorted(grouped, key=lambda key: (-len(grouped[key]), key))
    for scenario_id in ordered_groups:
        destination = min(
            range(n_splits),
            key=lambda index: (
                fold_sizes[index],
                len(fold_groups[index]),
                index,
            ),
        )
        fold_groups[destination].append(scenario_id)
        fold_sizes[destination] += len(grouped[scenario_id])

    all_indices = set(range(len(rows)))
    folds: list[tuple[list[int], list[int]]] = []
    for scenarios in fold_groups:
        test = sorted(
            index for scenario_id in scenarios for index in grouped[scenario_id]
        )
        train = sorted(all_indices.difference(test))
        folds.append((train, test))
    return folds


def penalty_weight(term: str) -> float:
    """Return the fixed hierarchical L1 weight for a model term."""

    if term == "intercept":
        return 0.0
    if term not in FEATURE_NAMES:
        raise ValueError(f"unknown model term: {term}")
    return 4.0 if "_x_" in term else 1.0


def _feature_matrix(features: Sequence[Mapping[str, float]]) -> np.ndarray:
    if not features:
        raise ValueError("at least one feature row is required")
    matrix = np.empty((len(features), len(FEATURE_NAMES)), dtype=float)
    for row_index, feature in enumerate(features):
        for column_index, name in enumerate(FEATURE_NAMES):
            value = feature.get(name)
            matrix[row_index, column_index] = _required_finite(
                value, f"feature row {row_index} {name}"
            )
    return matrix


@dataclass(frozen=True)
class ConstrainedQuantileModel:
    """A fitted sign-constrained quantile model and its training-only scaler."""

    quantile: float
    penalty: float
    standardized_intercept: float
    standardized_coefficients: tuple[float, ...]
    centers: Mapping[str, float]
    scales: Mapping[str, float]
    training_n: int

    def coefficient(self, name: str) -> float:
        if name not in FEATURE_NAMES:
            raise ValueError(f"unknown feature: {name}")
        index = FEATURE_NAMES.index(name)
        return self.standardized_coefficients[index] / self.scales[name]

    @property
    def intercept(self) -> float:
        adjustment = sum(
            self.standardized_coefficients[index]
            * self.centers[name]
            / self.scales[name]
            for index, name in enumerate(FEATURE_NAMES)
        )
        return self.standardized_intercept - adjustment

    def predict(self, features: Sequence[Mapping[str, float]]) -> list[float]:
        raw = _feature_matrix(features)
        center = np.asarray([self.centers[name] for name in FEATURE_NAMES])
        scale = np.asarray([self.scales[name] for name in FEATURE_NAMES])
        standardized = (raw - center) / scale
        coefficients = np.asarray(self.standardized_coefficients)
        predicted = self.standardized_intercept + standardized @ coefficients
        return [float(value) for value in predicted]


def fit_constrained_quantile(
    features: Sequence[Mapping[str, float]],
    targets: Sequence[float],
    *,
    quantile: float,
    penalty: float,
) -> ConstrainedQuantileModel:
    """Fit the PHiCTE sign-constrained, hierarchically shrunk quantile model."""

    raw = _feature_matrix(features)
    if len(targets) != len(features):
        raise ValueError("targets and features must have the same length")
    y = np.asarray(
        [_required_finite(value, f"target {index}") for index, value in enumerate(targets)],
        dtype=float,
    )
    if np.any((y < 0.0) | (y > 1.0)):
        raise ValueError("targets must lie in [0, 1]")
    quantile_value = _required_finite(quantile, "quantile")
    if not 0.0 < quantile_value < 1.0:
        raise ValueError("quantile must lie strictly between zero and one")
    penalty_value = _required_finite(penalty, "penalty")
    if penalty_value < 0.0:
        raise ValueError("penalty must be nonnegative")

    centers = np.zeros(len(FEATURE_NAMES), dtype=float)
    scales = np.ones(len(FEATURE_NAMES), dtype=float)
    for name in CONTINUOUS_FEATURE_NAMES:
        index = FEATURE_NAMES.index(name)
        centers[index] = float(np.mean(raw[:, index]))
        candidate_scale = float(np.std(raw[:, index]))
        scales[index] = candidate_scale if candidate_scale > 1e-12 else 1.0
    standardized = (raw - centers) / scales
    design = np.column_stack([np.ones(len(raw), dtype=float), standardized])

    term_names = ("intercept", *FEATURE_NAMES)
    term_count = len(term_names)
    sample_count = len(raw)
    coefficient_penalties = np.asarray(
        [penalty_value * penalty_weight(name) for name in term_names], dtype=float
    )
    objective = np.concatenate(
        [
            coefficient_penalties,
            coefficient_penalties,
            np.full(sample_count, quantile_value / sample_count),
            np.full(sample_count, (1.0 - quantile_value) / sample_count),
        ]
    )
    equality = np.hstack(
        [
            design,
            -design,
            np.eye(sample_count, dtype=float),
            -np.eye(sample_count, dtype=float),
        ]
    )

    positive_bounds: list[tuple[float, float | None]] = []
    negative_bounds: list[tuple[float, float | None]] = []
    for name in term_names:
        positive_bounds.append(
            (0.0, 0.0)
            if name in PHYSICAL_NONPOSITIVE_COEFFICIENTS
            else (0.0, None)
        )
        negative_bounds.append(
            (0.0, 0.0)
            if name in PHYSICAL_NONNEGATIVE_COEFFICIENTS
            else (0.0, None)
        )
    bounds = [
        *positive_bounds,
        *negative_bounds,
        *([(0.0, None)] * (2 * sample_count)),
    ]
    result = linprog(
        objective,
        A_eq=equality,
        b_eq=y,
        bounds=bounds,
        method="highs",
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"constrained quantile fit failed: {result.message}")

    beta = result.x[:term_count] - result.x[term_count : 2 * term_count]
    beta[np.abs(beta) < 1e-12] = 0.0
    return ConstrainedQuantileModel(
        quantile=quantile_value,
        penalty=penalty_value,
        standardized_intercept=float(beta[0]),
        standardized_coefficients=tuple(float(value) for value in beta[1:]),
        centers={name: float(centers[index]) for index, name in enumerate(FEATURE_NAMES)},
        scales={name: float(scales[index]) for index, name in enumerate(FEATURE_NAMES)},
        training_n=sample_count,
    )


def _validated_target_risk(target_risk: float) -> float:
    value = _required_finite(target_risk, "target_risk")
    if not 0.0 < value < 1.0:
        raise ValueError("target_risk must lie strictly between zero and one")
    return value


def calibration_rank_status(
    *, sample_n: int, target_risk: float
) -> dict[str, int | float | str]:
    """Describe whether a finite-sample one-sided rank is nontrivial."""

    if not isinstance(sample_n, int) or isinstance(sample_n, bool) or sample_n <= 0:
        raise ValueError("sample_n must be a positive integer")
    risk = _validated_target_risk(target_risk)
    rank = math.ceil((sample_n + 1) * (1.0 - risk))
    minimum_sample_n = max(1, math.ceil(1.0 / risk) - 1)
    return {
        "status": (
            "EVALUABLE_NONTRIVIAL"
            if rank <= sample_n
            else "NOT_EVALUABLE_NONTRIVIAL_95_PERCENT"
        ),
        "sample_n": sample_n,
        "target_risk": risk,
        "rank": rank,
        "minimum_sample_n": minimum_sample_n,
    }


def one_sided_correction(
    scores: Sequence[float], *, target_risk: float
) -> tuple[float, int]:
    """Return the upper finite-sample score quantile used for a lower bound."""

    if not scores:
        raise ValueError("at least one calibration score is required")
    risk = _validated_target_risk(target_risk)
    ordered = sorted(
        _required_finite(value, f"calibration score {index}")
        for index, value in enumerate(scores)
    )
    rank = math.ceil((len(ordered) + 1) * (1.0 - risk))
    return ordered[min(rank, len(ordered)) - 1], rank


def _pinball_loss(observed: float, predicted: float, quantile: float) -> float:
    residual = observed - predicted
    return quantile * residual if residual >= 0.0 else (quantile - 1.0) * residual


def _scenario_macro_pinball_loss(
    rows: Sequence[Mapping[str, Any]],
    observed: Sequence[float],
    predicted: Sequence[float],
    *,
    quantile: float,
) -> float:
    by_scenario: dict[str, list[float]] = defaultdict(list)
    for row, actual, estimate in zip(rows, observed, predicted, strict=True):
        scenario_id = row["scenario_id"]
        by_scenario[str(scenario_id)].append(
            _pinball_loss(float(actual), float(estimate), quantile)
        )
    scenario_means = [sum(values) / len(values) for values in by_scenario.values()]
    return sum(scenario_means) / len(scenario_means)


def cross_fit(
    rows: Sequence[Mapping[str, Any]],
    *,
    feeder_kva: Mapping[str, float],
    penalties: Sequence[float],
    n_splits: int,
    quantile: float,
    target_risk: float,
) -> dict[str, Any]:
    """Select shrinkage by scenario-grouped OOF loss and calibrate a lower bound."""

    if not rows:
        raise ValueError("cross_fit requires at least one row")
    quantile_value = _required_finite(quantile, "quantile")
    if not 0.0 < quantile_value < 1.0:
        raise ValueError("quantile must lie strictly between zero and one")
    risk = _validated_target_risk(target_risk)
    penalty_values = tuple(
        _required_finite(value, f"penalty {index}")
        for index, value in enumerate(penalties)
    )
    if not penalty_values or any(value < 0.0 for value in penalty_values):
        raise ValueError("penalties must contain nonnegative values")
    if len(set(penalty_values)) != len(penalty_values):
        raise ValueError("penalties must be unique")

    features = [build_feature_row(row, feeder_kva=feeder_kva) for row in rows]
    targets = [
        _required_finite(row.get("alpha_transfer"), f"row {index} alpha_transfer")
        for index, row in enumerate(rows)
    ]
    if any(not 0.0 <= value <= 1.0 for value in targets):
        raise ValueError("alpha_transfer values must lie in [0, 1]")
    folds = deterministic_group_folds(rows, n_splits=n_splits)
    scenario_overlap_count = 0
    for train_indices, test_indices in folds:
        train_scenarios = {str(rows[index]["scenario_id"]) for index in train_indices}
        test_scenarios = {str(rows[index]["scenario_id"]) for index in test_indices}
        scenario_overlap_count += len(train_scenarios & test_scenarios)

    candidate_predictions: dict[float, list[float]] = {}
    candidate_counts: dict[float, list[int]] = {}
    candidate_losses: dict[float, float] = {}
    for penalty_value in penalty_values:
        predictions = [math.nan] * len(rows)
        counts = [0] * len(rows)
        for train_indices, test_indices in folds:
            model = fit_constrained_quantile(
                [features[index] for index in train_indices],
                [targets[index] for index in train_indices],
                quantile=quantile_value,
                penalty=penalty_value,
            )
            fold_predictions = model.predict(
                [features[index] for index in test_indices]
            )
            for index, prediction in zip(
                test_indices, fold_predictions, strict=True
            ):
                predictions[index] = prediction
                counts[index] += 1
        if counts != [1] * len(rows) or any(
            not math.isfinite(value) for value in predictions
        ):
            raise RuntimeError("cross-fitting did not produce one finite prediction per row")
        candidate_predictions[penalty_value] = predictions
        candidate_counts[penalty_value] = counts
        candidate_losses[penalty_value] = _scenario_macro_pinball_loss(
            rows,
            targets,
            predictions,
            quantile=quantile_value,
        )

    selected_penalty = min(
        sorted(penalty_values, reverse=True),
        key=lambda value: candidate_losses[value],
    )
    oof_predictions = candidate_predictions[selected_penalty]
    scores = [
        prediction - observed
        for prediction, observed in zip(oof_predictions, targets, strict=True)
    ]
    correction, correction_rank = one_sided_correction(scores, target_risk=risk)
    oof_lower_bounds = [
        float(np.clip(prediction - correction, 0.0, 1.0))
        for prediction in oof_predictions
    ]
    final_model = fit_constrained_quantile(
        features,
        targets,
        quantile=quantile_value,
        penalty=selected_penalty,
    )
    return {
        "selected_penalty": selected_penalty,
        "candidate_scenario_macro_pinball_loss": candidate_losses,
        "oof_quantile_predictions": oof_predictions,
        "oof_lower_bounds": oof_lower_bounds,
        "prediction_counts": candidate_counts[selected_penalty],
        "scenario_overlap_count": scenario_overlap_count,
        "calibration_scores": scores,
        "correction": correction,
        "correction_rank": correction_rank,
        "row_calibration_rank_status": calibration_rank_status(
            sample_n=len(rows), target_risk=risk
        ),
        "final_model": final_model,
    }


def evaluate_predictions(
    rows: Sequence[Mapping[str, Any]],
    factors: Sequence[float | None],
) -> dict[str, Any]:
    """Evaluate risk and three retention weightings with explicit abstention."""

    if len(rows) != len(factors):
        raise ValueError("rows and factors must have the same length")
    validate_evaluation_rows(rows, dataset_name="PHiCTE evaluation")
    active: list[tuple[Mapping[str, Any], float]] = []
    for index, (row, factor) in enumerate(zip(rows, factors, strict=True)):
        if not bool(row["active_offer"]):
            if factor is not None:
                raise ValueError(f"inactive row {index} must have no factor")
            continue
        factor_value = _required_finite(factor, f"factor {index}")
        if not 0.0 <= factor_value <= 1.0:
            raise ValueError("active factors must lie in [0, 1]")
        active.append((row, factor_value))

    prescribed = [(row, factor) for row, factor in active if factor > 0.0]
    material_n = sum(
        is_material_false_safe(float(row["alpha_transfer"]), factor)
        for row, factor in prescribed
    )
    exceeds_n = sum(
        factor > float(row["alpha_transfer"]) + 1e-12
        for row, factor in prescribed
    )
    risk_n = len(prescribed)
    if risk_n:
        material_rate = material_n / risk_n
        exceeds_rate = exceeds_n / risk_n
        wilson_low, wilson_high = wilson_interval(material_n, risk_n)
    else:
        material_rate = None
        exceeds_rate = None
        wilson_low = None
        wilson_high = None

    active_n = len(active)
    equal_retention = (
        sum(factor for _, factor in active) / active_n if active_n else None
    )
    feeder_totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    pooled_retained = 0.0
    pooled_offer = 0.0
    for row, factor in active:
        offer = abs(float(row["f_bal_kw"]))
        feeder = str(row["feeder"])
        feeder_totals[feeder][0] += factor * offer
        feeder_totals[feeder][1] += offer
        pooled_retained += factor * offer
        pooled_offer += offer
    if any(total <= 0.0 for _, total in feeder_totals.values()):
        raise ValueError("each active feeder must have positive absolute offer kW")
    feeder_macro = (
        sum(retained / total for retained, total in feeder_totals.values())
        / len(feeder_totals)
        if feeder_totals
        else None
    )
    pooled_retention = pooled_retained / pooled_offer if pooled_offer > 0.0 else None

    return {
        "planned_n": len(rows),
        "active_n": active_n,
        "inactive_n": len(rows) - active_n,
        "offer_coverage": active_n / len(rows) if rows else None,
        "risk_denominator_n": risk_n,
        "prescribed_n": risk_n,
        "abstention_n": active_n - risk_n,
        "decision_coverage": risk_n / active_n if active_n else None,
        "material_false_safe_n": material_n,
        "material_false_safe_rate": material_rate,
        "material_false_safe_wilson95_low": wilson_low,
        "material_false_safe_wilson95_high": wilson_high,
        "exceeds_verified_bound_n": exceeds_n,
        "exceeds_verified_bound_rate": exceeds_rate,
        "equal_case_retention": equal_retention,
        "feeder_macro_kw_retention": feeder_macro,
        "pooled_kw_retention_sensitivity": pooled_retention,
        "empirical_material_risk_target_met": (
            material_rate is not None and material_rate <= 0.05 + 1e-12
        ),
        "wilson95_upper_risk_target_met": (
            wilson_high is not None and wilson_high <= 0.05 + 1e-12
        ),
    }


def build_decision(
    phicte_metrics: Mapping[str, Any],
    feeder_only_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the frozen exploratory risk and dual-retention decision rule."""

    required = (
        "material_false_safe_rate",
        "equal_case_retention",
        "feeder_macro_kw_retention",
        "pooled_kw_retention_sensitivity",
    )
    values: dict[str, float] = {}
    for prefix, metrics in (
        ("phicte", phicte_metrics),
        ("feeder_only", feeder_only_metrics),
    ):
        for name in required:
            value = metrics.get(name)
            if value is None:
                return {
                    "status": "NOT_EVALUABLE",
                    "blind_holdout_claim": False,
                    "confirmatory_risk_guarantee": False,
                    "basis": "required retrospective metric is unavailable",
                }
            values[f"{prefix}_{name}"] = _required_finite(
                value, f"{prefix} {name}"
            )

    equal_delta = (
        values["phicte_equal_case_retention"]
        - values["feeder_only_equal_case_retention"]
    )
    feeder_macro_delta = (
        values["phicte_feeder_macro_kw_retention"]
        - values["feeder_only_feeder_macro_kw_retention"]
    )
    pooled_delta = (
        values["phicte_pooled_kw_retention_sensitivity"]
        - values["feeder_only_pooled_kw_retention_sensitivity"]
    )
    risk_met = values["phicte_material_false_safe_rate"] <= 0.05 + 1e-12
    dual_gain = equal_delta > 1e-12 and feeder_macro_delta > 1e-12
    if not risk_met:
        status = "NO_EXPLORATORY_SIGNAL_RISK_TARGET_NOT_MET"
    elif not dual_gain:
        status = "NO_EXPLORATORY_SIGNAL_NO_DUAL_RETENTION_GAIN"
    else:
        status = "EXPLORATORY_POSITIVE_SIGNAL"
    return {
        "status": status,
        "blind_holdout_claim": False,
        "confirmatory_risk_guarantee": False,
        "empirical_material_risk_target_met": risk_met,
        "positive_equal_case_gain": equal_delta > 1e-12,
        "positive_feeder_macro_kw_gain": feeder_macro_delta > 1e-12,
        "retention_delta_vs_feeder_only": {
            "equal_case": equal_delta,
            "feeder_macro_kw": feeder_macro_delta,
            "pooled_kw_sensitivity": pooled_delta,
        },
        "basis": (
            "exploratory signal requires empirical material false-safe risk <= 5% "
            "and positive retention deltas versus feeder-only under both equal-case "
            "and feeder-macro-kW weighting; pooled-kW is sensitivity only"
        ),
    }


def _phicte_factors(
    rows: Sequence[Mapping[str, Any]],
    *,
    model: ConstrainedQuantileModel,
    correction: float,
    feeder_kva: Mapping[str, float],
) -> tuple[list[float | None], list[float | None]]:
    active_indices = [
        index for index, row in enumerate(rows) if bool(row["active_offer"])
    ]
    features = [
        build_feature_row(rows[index], feeder_kva=feeder_kva)
        for index in active_indices
    ]
    active_predictions = model.predict(features) if features else []
    quantile_predictions: list[float | None] = [None] * len(rows)
    factors: list[float | None] = [None] * len(rows)
    for index, prediction in zip(active_indices, active_predictions, strict=True):
        quantile_predictions[index] = prediction
        factors[index] = float(np.clip(prediction - correction, 0.0, 1.0))
    return quantile_predictions, factors


def _baseline_policies(
    development_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {
        "raw_balanced_offer": {"grouping_fields": None, "fixed_factor": 1.0}
    }
    for name, grouping_fields in POLICY_SPECS.items():
        if name == "raw_balanced_offer":
            continue
        assert grouping_fields is not None
        policies[name] = fit_policy(
            development_rows,
            grouping_fields=grouping_fields,
            maximum_risk=DEFAULT_TARGET_RISK,
        )
    return policies


def _apply_baseline_policy(
    rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> list[float | None]:
    factors: list[float | None] = []
    for row in rows:
        if not bool(row["active_offer"]):
            factors.append(None)
            continue
        factor, matched = apply_fitted_policy(row, policy)
        factors.append(float(factor) if matched else 0.0)
    return factors


def _subset_metrics(
    rows: Sequence[Mapping[str, Any]],
    factor_maps: Mapping[str, Sequence[float | None]],
    indices: Sequence[int],
) -> dict[str, dict[str, Any]]:
    selected_rows = [rows[index] for index in indices]
    return {
        name: evaluate_predictions(
            selected_rows, [factors[index] for index in indices]
        )
        for name, factors in factor_maps.items()
    }


def _serialize_model(model: ConstrainedQuantileModel) -> dict[str, Any]:
    coefficients = {name: model.coefficient(name) for name in FEATURE_NAMES}
    return {
        "quantile": model.quantile,
        "penalty": model.penalty,
        "training_n": model.training_n,
        "intercept": model.intercept,
        "coefficients_original_scale": coefficients,
        "training_scaler": {
            "centers": dict(model.centers),
            "scales": dict(model.scales),
            "continuous_features_scaled": list(CONTINUOUS_FEATURE_NAMES),
            "categorical_features_unscaled": [
                name for name in FEATURE_NAMES if name not in CONTINUOUS_FEATURE_NAMES
            ],
        },
        "physical_sign_checks": {
            "offer_stress_nonpositive": coefficients["offer_stress"] <= 1e-10,
            "margin_coefficients_nonnegative": all(
                coefficients[name] >= -1e-10
                for name in PHYSICAL_NONNEGATIVE_COEFFICIENTS
            ),
        },
    }


def _prediction_records(
    cohort: str,
    rows: Sequence[Mapping[str, Any]],
    quantile_predictions: Sequence[float | None],
    factor_maps: Mapping[str, Sequence[float | None]],
) -> list[dict[str, Any]]:
    records = []
    for index, row in enumerate(rows):
        phicte_factor = factor_maps["phicte"][index]
        records.append(
            {
                "cohort": cohort,
                "evaluation_id": row["evaluation_id"],
                "scenario_id": row.get("scenario_id"),
                "feeder": row["feeder"],
                "call_time": row.get("call_time"),
                "direction": row["direction"],
                "duration_min": row["duration_min"],
                "active_offer": row["active_offer"],
                "f_bal_kw": row["f_bal_kw"],
                "alpha_transfer": row.get("alpha_transfer"),
                "phicte_quantile_prediction": quantile_predictions[index],
                "phicte_factor": phicte_factor,
                "phicte_abstained": (
                    None
                    if phicte_factor is None
                    else float(phicte_factor) <= 0.0
                ),
                "raw_balanced_offer_factor": factor_maps[
                    "raw_balanced_offer"
                ][index],
                "global_derating_factor": factor_maps["global_derating"][index],
                "feeder_only_factor": factor_maps["feeder_only"][index],
                "direction_only_factor": factor_maps["direction_only"][index],
                "local_feeder_direction_duration_factor": factor_maps[
                    "local_feeder_direction_duration"
                ][index],
            }
        )
    return records


def build_analysis(
    development_rows: Sequence[Mapping[str, Any]],
    external_rows: Sequence[Mapping[str, Any]],
    *,
    feeder_kva: Mapping[str, float],
    code_commit: str,
    generated_at_utc: str,
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fit on V2.2 only, then evaluate the frozen factors on opened V2.3A."""

    validate_evaluation_rows(development_rows, dataset_name="V2.2 development")
    validate_evaluation_rows(external_rows, dataset_name="V2.3A external")
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise ValueError("code_commit must be a 40-character Git commit")
    development_active_indices = [
        index
        for index, row in enumerate(development_rows)
        if bool(row["active_offer"])
    ]
    development_active = [development_rows[index] for index in development_active_indices]
    cross_fitted = cross_fit(
        development_active,
        feeder_kva=feeder_kva,
        penalties=DEFAULT_PENALTIES,
        n_splits=4,
        quantile=DEFAULT_QUANTILE,
        target_risk=DEFAULT_TARGET_RISK,
    )
    final_model = cross_fitted["final_model"]
    correction = float(cross_fitted["correction"])

    development_quantile: list[float | None] = [None] * len(development_rows)
    development_phicte: list[float | None] = [None] * len(development_rows)
    for active_position, row_index in enumerate(development_active_indices):
        development_quantile[row_index] = cross_fitted[
            "oof_quantile_predictions"
        ][active_position]
        development_phicte[row_index] = cross_fitted["oof_lower_bounds"][
            active_position
        ]
    external_quantile, external_phicte = _phicte_factors(
        external_rows,
        model=final_model,
        correction=correction,
        feeder_kva=feeder_kva,
    )

    policies = _baseline_policies(development_rows)
    development_factor_maps: dict[str, list[float | None]] = {
        "phicte": development_phicte
    }
    external_factor_maps: dict[str, list[float | None]] = {"phicte": external_phicte}
    for name, policy in policies.items():
        development_factor_maps[name] = _apply_baseline_policy(
            development_rows, policy
        )
        external_factor_maps[name] = _apply_baseline_policy(external_rows, policy)

    primary_indices = [
        index
        for index, row in enumerate(external_rows)
        if int(row["duration_min"]) == 15
    ]
    all_indices = list(range(len(external_rows)))
    primary_metrics = _subset_metrics(
        external_rows, external_factor_maps, primary_indices
    )
    all_duration_metrics = _subset_metrics(
        external_rows, external_factor_maps, all_indices
    )
    decision = build_decision(
        primary_metrics["phicte"], primary_metrics["feeder_only"]
    )

    cluster_scores: dict[str, list[float]] = defaultdict(list)
    for row, score in zip(
        development_active,
        cross_fitted["calibration_scores"],
        strict=True,
    ):
        cluster_scores[str(row["scenario_id"])].append(float(score))
    cluster_max_scores = {
        scenario_id: max(values)
        for scenario_id, values in sorted(cluster_scores.items())
    }
    cluster_status = calibration_rank_status(
        sample_n=len(cluster_max_scores), target_risk=DEFAULT_TARGET_RISK
    )
    cluster_status.update(
        {
            "score_definition": (
                "maximum OOF (quantile_prediction - alpha_transfer) within scenario"
            ),
            "correction_applied": False,
            "scores_by_scenario": cluster_max_scores,
        }
    )

    development_metrics = {
        "phicte_oof": evaluate_predictions(
            development_rows, development_factor_maps["phicte"]
        ),
        "baseline_resubstitution": {
            name: evaluate_predictions(development_rows, factors)
            for name, factors in development_factor_maps.items()
            if name != "phicte"
        },
    }
    summary = {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_role": "retrospective_exploratory_method_screen",
        "generated_at_utc": generated_at_utc,
        "blind_holdout_claim": False,
        "confirmatory_risk_guarantee": False,
        "fitting_rule": {
            "training_source": "V2.2 development active offers only",
            "external_source": "V2.3A previously opened external cohort",
            "external_outcomes_used_for_fitting_or_tuning": False,
            "quantile": DEFAULT_QUANTILE,
            "candidate_penalties": list(DEFAULT_PENALTIES),
            "penalty_selection": (
                "minimum scenario-macro OOF pinball loss; exact ties choose larger penalty"
            ),
            "folding": "four folds grouped by scenario_id",
            "abstention": "factor zero; inactive offers have no decision",
        },
        "risk_definitions": {
            "material_false_safe": "alpha_transfer < 0.95 * prescribed_factor",
            "strict_bound_exceedance": "prescribed_factor > alpha_transfer",
            "empirical_target": DEFAULT_TARGET_RISK,
        },
        "calibration": {
            "row_level_exploratory": {
                "selected_penalty": cross_fitted["selected_penalty"],
                "candidate_scenario_macro_pinball_loss": {
                    str(key): value
                    for key, value in cross_fitted[
                        "candidate_scenario_macro_pinball_loss"
                    ].items()
                },
                "correction": correction,
                "rank": cross_fitted["correction_rank"],
                "rank_status": cross_fitted["row_calibration_rank_status"],
                "prediction_count_all_one": all(
                    count == 1 for count in cross_fitted["prediction_counts"]
                ),
                "scenario_overlap_count": cross_fitted[
                    "scenario_overlap_count"
                ],
                "formal_exchangeability_claim": False,
            },
            "scenario_cluster_diagnostic": cluster_status,
        },
        "model": _serialize_model(final_model),
        "development_diagnostics": development_metrics,
        "external_scopes": {
            "primary_15min": {
                "role": "V2.3A primary duration retrospective",
                "policies": primary_metrics,
            },
            "descriptive_all_durations": {
                "role": "V2.3A amendment descriptive sensitivity",
                "policies": all_duration_metrics,
            },
        },
        "decision": decision,
        "data_quality": {
            "development_planned_n": len(development_rows),
            "development_active_n": len(development_active),
            "development_scenario_n": len(
                {row["scenario_id"] for row in development_rows}
            ),
            "external_planned_n": len(external_rows),
            "external_active_n": sum(
                bool(row["active_offer"]) for row in external_rows
            ),
            "external_scenario_n": len({row["scenario_id"] for row in external_rows}),
            "cross_cohort_scenario_intersection_n": len(
                {row["scenario_id"] for row in development_rows}
                & {row["scenario_id"] for row in external_rows}
            ),
        },
        "limitations": [
            "V2.3A had already been opened and is not a blind holdout.",
            "The row-level conformal-style correction is exploratory because within-scenario rows are dependent and penalty selection reuses OOF predictions.",
            "Only 16 V2.2 scenarios are available, so a nontrivial 95% scenario-cluster finite-sample correction is unavailable.",
            "The 30- and 60-minute V2.3A results are descriptive under the protocol amendment.",
            "Line thermal constraints are outside the audited constraint set.",
        ],
        "provenance": {"code_commit": code_commit, **dict(provenance)},
    }
    predictions = [
        *_prediction_records(
            "development_oof",
            development_rows,
            development_quantile,
            development_factor_maps,
        ),
        *_prediction_records(
            "external",
            external_rows,
            external_quantile,
            external_factor_maps,
        ),
    ]
    return summary, predictions


PREDICTION_FIELDS = (
    "cohort",
    "evaluation_id",
    "scenario_id",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "active_offer",
    "f_bal_kw",
    "alpha_transfer",
    "phicte_quantile_prediction",
    "phicte_factor",
    "phicte_abstained",
    "raw_balanced_offer_factor",
    "global_derating_factor",
    "feeder_only_factor",
    "direction_only_factor",
    "local_feeder_direction_duration_factor",
)


def write_results(
    summary: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
    output_directory: str | Path,
) -> list[Path]:
    """Write exactly the two compact PHiCTE result artifacts."""

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    allowed = {"summary.json", "predictions.csv"}
    unexpected = {path.name for path in output.iterdir()} - allowed
    if unexpected:
        raise ValueError(f"output directory contains unexpected files: {sorted(unexpected)}")
    summary_path = output / "summary.json"
    prediction_path = output / "predictions.csv"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with prediction_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=PREDICTION_FIELDS, extrasaction="raise"
        )
        writer.writeheader()
        for record in predictions:
            writer.writerow({name: record.get(name) for name in PREDICTION_FIELDS})
    return [summary_path, prediction_path]


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the PHiCTE V2.4 retrospective exploratory evaluation."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--output-directory", default="results/transferability_phicte_v2_4"
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve(strict=True)
    development, external, provenance = load_project_evaluations(root)
    development_config = json.loads(
        (root / "config/transferability_dev_v2_2.json").read_text(encoding="utf-8")
    )
    external_config = json.loads(
        (root / "config/transferability_external_validation_v2_3.json").read_text(
            encoding="utf-8"
        )
    )
    feeder_kva = development_config.get("feeder_kva")
    if not isinstance(feeder_kva, Mapping) or feeder_kva != external_config.get(
        "feeder_kva"
    ):
        raise ValueError("development and external feeder_kva mappings must match")
    summary, predictions = build_analysis(
        development,
        external,
        feeder_kva=feeder_kva,
        code_commit=_git_commit(root),
        generated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance=provenance,
    )
    paths = write_results(summary, predictions, root / args.output_directory)
    print(
        json.dumps(
            {
                "status": summary["decision"]["status"],
                "outputs": [path.relative_to(root).as_posix() for path in paths],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
