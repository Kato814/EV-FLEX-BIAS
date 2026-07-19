from __future__ import annotations

import hashlib
import math
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from evflex.schema import DURATIONS, FEEDERS


CV_SEED = 2026072000
CV_FOLDS = 5
C_GRID = (0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0)
MINIMUM_SELECTED_N = 20
MAXIMUM_FALSE_SAFE_RATE = 0.05
RISK_ALPHA_THRESHOLD = 0.95

COMMON_NUMERIC_FEATURES = (
    "actual_nameplate_to_transformer_ratio",
    "native_load_multiplier",
    "phase_imbalance_index",
    "far_zone_probability",
    "median_natural_urgency",
    "call_time_sin",
    "call_time_cos",
)
DEC_NUMERIC_FEATURES = COMMON_NUMERIC_FEATURES + ("realized_v2g_participation",)
CATEGORICAL_FEATURES = ("dominant_phase",)
DOMINANT_PHASE_CATEGORIES = ("a", "b", "c")


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def phase_imbalance_index(value: str) -> float:
    try:
        parts = np.asarray([float(part) for part in str(value).split(":")], dtype=float)
    except ValueError as exc:
        raise ValueError(f"invalid phase ratio: {value!r}") from exc
    if parts.size != 3 or not np.isfinite(parts).all() or (parts <= 0).any():
        raise ValueError(f"invalid phase ratio: {value!r}")
    return float((parts.max() - parts.min()) / parts.sum())


def call_time_encoding(value: str) -> tuple[float, float]:
    try:
        hour_text, minute_text = str(value).split(":", maxsplit=1)
        hours = int(hour_text) + int(minute_text) / 60.0
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid call time: {value!r}") from exc
    if not 0 <= hours < 24:
        raise ValueError(f"invalid call time: {value!r}")
    angle = 2.0 * math.pi * hours / 24.0
    return math.sin(angle), math.cos(angle)


def build_feature_frame(
    evaluations: pd.DataFrame,
    scenarios: pd.DataFrame,
    populations: pd.DataFrame,
) -> pd.DataFrame:
    _require_columns(
        evaluations,
        (
            "evaluation_id",
            "scenario_id",
            "data_role",
            "feeder",
            "call_time",
            "direction",
            "duration_min",
            "status",
            "alpha_map",
        ),
        "development evaluations",
    )
    _require_columns(
        scenarios,
        (
            "scenario_id",
            "data_split",
            "native_load_multiplier",
            "phase_ratio",
            "dominant_phase",
            "far_zone_probability",
        ),
        "base scenarios",
    )
    _require_columns(
        populations,
        (
            "scenario_id",
            "data_split",
            "actual_nameplate_to_transformer_ratio",
            "median_natural_urgency",
            "v2g_actual_rate",
        ),
        "population summary",
    )
    if evaluations["evaluation_id"].duplicated().any():
        duplicate = evaluations.loc[
            evaluations["evaluation_id"].duplicated(), "evaluation_id"
        ].iloc[0]
        raise ValueError(f"duplicate evaluation_id: {duplicate}")
    if set(evaluations["data_role"].dropna().astype(str)) != {"development"}:
        raise ValueError("applicability modeling accepts development evaluations only")
    if scenarios["scenario_id"].duplicated().any():
        raise ValueError("base scenarios contain duplicate scenario_id values")
    if populations["scenario_id"].duplicated().any():
        raise ValueError("population summary contains duplicate scenario_id values")

    eligible = evaluations.loc[evaluations["status"].eq("SUCCESS")].copy()
    if eligible.empty:
        raise ValueError("no successful development evaluations are modeling-eligible")
    eligible["alpha_map"] = pd.to_numeric(eligible["alpha_map"], errors="raise")
    if not np.isfinite(eligible["alpha_map"]).all():
        raise ValueError("successful evaluations contain non-finite alpha_map values")

    scenario_columns = scenarios.loc[
        :,
        [
            "scenario_id",
            "data_split",
            "native_load_multiplier",
            "phase_ratio",
            "dominant_phase",
            "far_zone_probability",
        ],
    ].rename(columns={"data_split": "scenario_data_split"})
    population_columns = populations.loc[
        :,
        [
            "scenario_id",
            "data_split",
            "actual_nameplate_to_transformer_ratio",
            "median_natural_urgency",
            "v2g_actual_rate",
        ],
    ].rename(
        columns={
            "data_split": "population_data_split",
            "v2g_actual_rate": "realized_v2g_participation",
        }
    )
    merged = eligible.merge(
        scenario_columns, on="scenario_id", how="left", validate="many_to_one"
    ).merge(population_columns, on="scenario_id", how="left", validate="many_to_one")
    if len(merged) != len(eligible):
        raise ValueError("feature join changed the number of eligible evaluations")
    feature_inputs = [
        "scenario_data_split",
        "population_data_split",
        "native_load_multiplier",
        "phase_ratio",
        "dominant_phase",
        "far_zone_probability",
        "actual_nameplate_to_transformer_ratio",
        "median_natural_urgency",
        "realized_v2g_participation",
    ]
    if merged[feature_inputs].isna().any().any():
        missing_ids = merged.loc[
            merged[feature_inputs].isna().any(axis=1), "scenario_id"
        ].unique()
        raise ValueError(f"missing frozen features for scenarios: {missing_ids.tolist()}")
    if not merged["scenario_data_split"].eq("development").all():
        raise ValueError("base-scenario feature join crossed the sealed split")
    if not merged["population_data_split"].eq("development").all():
        raise ValueError("population feature join crossed the sealed split")
    if not set(merged["dominant_phase"].astype(str)).issubset(
        DOMINANT_PHASE_CATEGORIES
    ):
        raise ValueError("dominant_phase contains a value outside a, b, c")

    merged["phase_imbalance_index"] = merged["phase_ratio"].map(
        phase_imbalance_index
    )
    encodings = merged["call_time"].map(call_time_encoding)
    merged["call_time_sin"] = encodings.map(lambda pair: pair[0])
    merged["call_time_cos"] = encodings.map(lambda pair: pair[1])
    merged["false_safe"] = merged["alpha_map"].lt(RISK_ALPHA_THRESHOLD)
    return merged


def select_threshold_candidate(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (int(item["selected_n"]), -float(item["risk_threshold"])),
    )


def choose_threshold(
    scores: np.ndarray,
    labels: np.ndarray,
    minimum_n: int = MINIMUM_SELECTED_N,
    maximum_rate: float = MAXIMUM_FALSE_SAFE_RATE,
) -> dict | None:
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=int)
    if scores.ndim != 1 or labels.ndim != 1 or len(scores) != len(labels):
        raise ValueError("scores and labels must be aligned one-dimensional arrays")
    if len(scores) == 0 or not np.isfinite(scores).all():
        raise ValueError("scores must be non-empty and finite")
    if not set(np.unique(labels)).issubset({0, 1}):
        raise ValueError("labels must contain only 0 and 1")
    candidates = []
    for threshold in sorted(set(float(value) for value in scores)):
        mask = scores <= threshold
        count = int(mask.sum())
        if count < minimum_n:
            continue
        rate = float(labels[mask].mean())
        if rate <= maximum_rate:
            candidates.append(
                {
                    "risk_threshold": threshold,
                    "selected_n": count,
                    "false_safe_rate": rate,
                }
            )
    return select_threshold_candidate(candidates)


def numeric_features(direction: str) -> tuple[str, ...]:
    if direction == "inc":
        return COMMON_NUMERIC_FEATURES
    if direction == "dec":
        return DEC_NUMERIC_FEATURES
    raise ValueError(f"unsupported direction: {direction!r}")


def _make_pipeline(direction: str, c_value: float) -> Pipeline:
    numeric = list(numeric_features(direction))
    preprocess = ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), numeric),
            (
                "dominant_phase",
                OneHotEncoder(
                    categories=[list(DOMINANT_PHASE_CATEGORIES)],
                    drop="first",
                    handle_unknown="error",
                    sparse_output=False,
                ),
                list(CATEGORICAL_FEATURES),
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    classifier = LogisticRegression(
        penalty="l2",
        C=float(c_value),
        solver="lbfgs",
        max_iter=5000,
        random_state=CV_SEED,
    )
    return Pipeline([("preprocess", preprocess), ("classifier", classifier)])


def _serialize_fitted_pipeline(pipeline: Pipeline, direction: str) -> dict:
    preprocess = pipeline.named_steps["preprocess"]
    scaler = preprocess.named_transformers_["numeric"]
    encoder = preprocess.named_transformers_["dominant_phase"]
    classifier = pipeline.named_steps["classifier"]
    categories = [str(value) for value in encoder.categories_[0]]
    reference_index = int(encoder.drop_idx_[0])
    return {
        "numeric_features": list(numeric_features(direction)),
        "numeric_mean": [float(value) for value in scaler.mean_],
        "numeric_scale": [float(value) for value in scaler.scale_],
        "categorical_feature": "dominant_phase",
        "dominant_phase_categories": categories,
        "dominant_phase_reference": categories[reference_index],
        "transformed_feature_names": [
            str(value) for value in preprocess.get_feature_names_out()
        ],
        "coefficient": [float(value) for value in classifier.coef_[0]],
        "intercept": float(classifier.intercept_[0]),
    }


def fit_cell_model(cell: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    _require_columns(
        cell,
        (
            "evaluation_id",
            "scenario_id",
            "data_role",
            "feeder",
            "direction",
            "duration_min",
            "alpha_map",
            "false_safe",
            "dominant_phase",
            *COMMON_NUMERIC_FEATURES,
        ),
        "modeling cell",
    )
    if len(cell) < 2:
        raise ValueError("modeling cell must contain at least two observations")
    keys = cell[["feeder", "direction", "duration_min"]].drop_duplicates()
    if len(keys) != 1:
        raise ValueError("fit_cell_model requires exactly one feeder-direction-duration cell")
    feeder, direction, duration = keys.iloc[0].tolist()
    if set(cell["data_role"].astype(str)) != {"development"}:
        raise ValueError("modeling cells must contain development observations only")
    required_features = list(numeric_features(str(direction))) + ["dominant_phase"]
    _require_columns(cell, required_features, "modeling cell")
    if cell[required_features].isna().any().any():
        raise ValueError("modeling cell contains missing feature values")

    labels = cell["false_safe"].astype(int).to_numpy()
    class_counts = np.bincount(labels, minlength=2)
    if int(class_counts.min()) < CV_FOLDS:
        raise ValueError(
            f"cell {feeder}|{direction}|{int(duration)} has fewer than {CV_FOLDS} "
            "observations in a risk class"
        )
    features = cell.loc[:, required_features]
    splitter = StratifiedKFold(
        n_splits=CV_FOLDS, shuffle=True, random_state=CV_SEED
    )
    search_records = []
    score_cache: dict[float, np.ndarray] = {}
    for c_value in C_GRID:
        scores = np.empty(len(cell), dtype=float)
        fold_briers = []
        for train_index, validation_index in splitter.split(features, labels):
            pipeline = _make_pipeline(str(direction), c_value)
            pipeline.fit(features.iloc[train_index], labels[train_index])
            fold_scores = pipeline.predict_proba(features.iloc[validation_index])[:, 1]
            scores[validation_index] = fold_scores
            fold_briers.append(
                float(brier_score_loss(labels[validation_index], fold_scores))
            )
        mean_fold_brier = float(np.mean(fold_briers))
        search_records.append(
            {
                "c": float(c_value),
                "mean_fold_brier": mean_fold_brier,
                "overall_oof_brier": float(brier_score_loss(labels, scores)),
                "fold_briers": fold_briers,
            }
        )
        score_cache[float(c_value)] = scores
    selected_search = min(
        search_records, key=lambda item: (item["overall_oof_brier"], item["c"])
    )
    selected_c = float(selected_search["c"])
    selected_scores = score_cache[selected_c]
    threshold = choose_threshold(selected_scores, labels)

    final_pipeline = _make_pipeline(str(direction), selected_c)
    final_pipeline.fit(features, labels)
    final_model = _serialize_fitted_pipeline(final_pipeline, str(direction))
    evaluation_hash = hashlib.sha256(
        "\n".join(sorted(cell["evaluation_id"].astype(str))).encode("utf-8")
    ).hexdigest()
    record = {
        "cell_id": f"{feeder}|{direction}|{int(duration)}",
        "feeder": str(feeder),
        "direction": str(direction),
        "duration_min": int(duration),
        "training_role": "development",
        "training_n": int(len(cell)),
        "false_safe_n": int(labels.sum()),
        "safe_n": int(len(labels) - labels.sum()),
        "training_evaluation_ids_sha256": evaluation_hash,
        "risk_label": "alpha_map < 0.95",
        "cv_folds": CV_FOLDS,
        "cv_seed": CV_SEED,
        "c_grid": [float(value) for value in C_GRID],
        "c_search": search_records,
        "selected_c": selected_c,
        "selected_mean_fold_brier": float(selected_search["mean_fold_brier"]),
        "selected_overall_oof_brier": float(selected_search["overall_oof_brier"]),
        "threshold_rule": {
            "minimum_selected_n": MINIMUM_SELECTED_N,
            "maximum_false_safe_rate": MAXIMUM_FALSE_SAFE_RATE,
            "selection": "maximum OOF coverage; equal coverage chooses lower risk threshold",
        },
        "applicability_threshold": threshold,
        "final_model": final_model,
    }

    oof = cell.loc[
        :,
        [
            "evaluation_id",
            "scenario_id",
            "data_role",
            "feeder",
            "direction",
            "duration_min",
            "alpha_map",
            "false_safe",
            *required_features,
        ],
    ].copy()
    oof["oof_risk_score"] = selected_scores
    oof["selected_c"] = selected_c
    if threshold is None:
        oof["risk_threshold"] = np.nan
        oof["candidate_selected"] = False
        oof["development_selected_n"] = 0
        oof["development_false_safe_rate"] = np.nan
    else:
        oof["risk_threshold"] = float(threshold["risk_threshold"])
        oof["candidate_selected"] = oof["oof_risk_score"].le(
            threshold["risk_threshold"]
        )
        oof["development_selected_n"] = int(threshold["selected_n"])
        oof["development_false_safe_rate"] = float(
            threshold["false_safe_rate"]
        )
    return record, oof


def fit_all_models(feature_frame: pd.DataFrame) -> tuple[list[dict], pd.DataFrame]:
    expected_cells = [
        (feeder, direction, duration)
        for feeder in FEEDERS
        for direction in ("inc", "dec")
        for duration in DURATIONS
    ]
    actual_cells = {
        (str(feeder), str(direction), int(duration))
        for feeder, direction, duration in feature_frame[
            ["feeder", "direction", "duration_min"]
        ].itertuples(index=False, name=None)
    }
    if actual_cells != set(expected_cells):
        missing = sorted(set(expected_cells) - actual_cells)
        extra = sorted(actual_cells - set(expected_cells))
        raise ValueError(f"modeling cell mismatch: missing={missing}, extra={extra}")

    records = []
    oof_frames = []
    for feeder, direction, duration in expected_cells:
        mask = (
            feature_frame["feeder"].eq(feeder)
            & feature_frame["direction"].eq(direction)
            & feature_frame["duration_min"].eq(duration)
        )
        record, oof = fit_cell_model(feature_frame.loc[mask].reset_index(drop=True))
        records.append(record)
        oof_frames.append(oof)
    combined = pd.concat(oof_frames, ignore_index=True)
    return records, combined


def assess_modeling_gate(
    records: list[dict],
    oof: pd.DataFrame,
    expected_model_records: int = 12,
) -> dict:
    violations: dict[str, object] = {}
    if len(records) != expected_model_records:
        violations["model_record_count"] = {
            "expected": expected_model_records,
            "actual": len(records),
        }
    duplicate_cells = pd.Series([record["cell_id"] for record in records]).duplicated()
    if duplicate_cells.any():
        violations["duplicate_model_cells"] = True
    roles = sorted(set(oof["data_role"].astype(str)))
    if roles != ["development"]:
        violations["nondevelopment_oof_roles"] = roles
    duplicate_ids = sorted(
        oof.loc[oof["evaluation_id"].duplicated(), "evaluation_id"].astype(str)
    )
    if duplicate_ids:
        violations["duplicate_oof_evaluation_ids"] = duplicate_ids
    if not np.isfinite(pd.to_numeric(oof["oof_risk_score"], errors="coerce")).all():
        violations["nonfinite_oof_scores"] = True

    threshold_summaries = []
    invalid_thresholds = []
    inconsistent_thresholds = []
    inconsistent_training_counts = []
    for record in records:
        threshold = record["applicability_threshold"]
        feeder = record["feeder"]
        direction = record["direction"]
        duration = record["duration_min"]
        cell = oof.loc[
            oof["feeder"].eq(feeder)
            & oof["direction"].eq(direction)
            & oof["duration_min"].eq(duration)
        ]
        if len(cell) != int(record["training_n"]):
            inconsistent_training_counts.append(record["cell_id"])
        recomputed_threshold = choose_threshold(
            cell["oof_risk_score"].to_numpy(),
            cell["false_safe"].astype(int).to_numpy(),
        )
        if threshold != recomputed_threshold:
            inconsistent_thresholds.append(record["cell_id"])
        summary = {
            "cell_id": record["cell_id"],
            "training_n": record["training_n"],
            "selected_c": record["selected_c"],
            "overall_oof_brier": record["selected_overall_oof_brier"],
            "has_applicability_region": threshold is not None,
            "threshold": threshold,
        }
        threshold_summaries.append(summary)
        if threshold is not None and (
            int(threshold["selected_n"]) < MINIMUM_SELECTED_N
            or float(threshold["false_safe_rate"]) > MAXIMUM_FALSE_SAFE_RATE
        ):
            invalid_thresholds.append(record["cell_id"])
    if invalid_thresholds:
        violations["invalid_candidate_thresholds"] = invalid_thresholds
    if inconsistent_thresholds:
        violations["nonmaximal_or_inconsistent_thresholds"] = inconsistent_thresholds
    if inconsistent_training_counts:
        violations["model_oof_count_mismatch"] = inconsistent_training_counts

    return {
        "gate": "G3_MODEL_THRESHOLD_FREEZE",
        "gate_status": "PASS" if not violations else "FAIL",
        "model_records": len(records),
        "expected_model_records": expected_model_records,
        "oof_predictions": int(len(oof)),
        "oof_roles": roles,
        "cells_with_applicability_region": int(
            sum(record["applicability_threshold"] is not None for record in records)
        ),
        "cells_without_applicability_region": [
            record["cell_id"]
            for record in records
            if record["applicability_threshold"] is None
        ],
        "threshold_summaries": threshold_summaries,
        "violations": violations,
    }


def predict_risk_scores(record: dict, frame: pd.DataFrame) -> np.ndarray:
    model = record["final_model"]
    numeric = frame.loc[:, model["numeric_features"]].to_numpy(dtype=float)
    mean = np.asarray(model["numeric_mean"], dtype=float)
    scale = np.asarray(model["numeric_scale"], dtype=float)
    transformed = [(numeric - mean) / scale]

    categories = list(model["dominant_phase_categories"])
    reference = str(model["dominant_phase_reference"])
    observed = frame[model["categorical_feature"]].astype(str)
    unknown = sorted(set(observed) - set(categories))
    if unknown:
        raise ValueError(f"unknown dominant_phase categories: {unknown}")
    for category in categories:
        if category != reference:
            transformed.append(observed.eq(category).to_numpy(dtype=float)[:, None])
    design = np.concatenate(transformed, axis=1)
    coefficient = np.asarray(model["coefficient"], dtype=float)
    if design.shape[1] != coefficient.size:
        raise ValueError("serialized model coefficient count does not match features")
    logits = float(model["intercept"]) + design @ coefficient
    return 1.0 / (1.0 + np.exp(-logits))
