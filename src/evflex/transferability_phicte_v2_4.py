from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import linprog


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
