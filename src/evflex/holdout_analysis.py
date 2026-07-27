from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

from evflex.modeling import (
    MAXIMUM_FALSE_SAFE_RATE,
    MINIMUM_SELECTED_N,
    RISK_ALPHA_THRESHOLD,
    call_time_encoding,
    phase_imbalance_index,
    predict_risk_scores,
)


HOLDOUT_BOOTSTRAP_SEED = 2026072002
HOLDOUT_BOOTSTRAP_RESAMPLES = 10_000
WILSON_95_Z = 1.959963984540054


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def build_holdout_feature_frame(
    evaluations: pd.DataFrame,
    scenarios: pd.DataFrame,
    populations: pd.DataFrame,
) -> pd.DataFrame:
    """Build sealed holdout features without fitting or changing any model."""
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
        "holdout evaluations",
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
    if set(evaluations["data_role"].dropna().astype(str)) != {"holdout"}:
        raise ValueError("frozen applicability evaluation accepts holdout rows only")
    if scenarios["scenario_id"].duplicated().any():
        raise ValueError("base scenarios contain duplicate scenario_id values")
    if populations["scenario_id"].duplicated().any():
        raise ValueError("population summary contains duplicate scenario_id values")

    eligible = evaluations.loc[evaluations["status"].eq("SUCCESS")].copy()
    if eligible.empty:
        raise ValueError("no successful holdout evaluations are scoring-eligible")
    eligible["alpha_map"] = pd.to_numeric(eligible["alpha_map"], errors="raise")
    if not np.isfinite(eligible["alpha_map"]).all():
        raise ValueError("successful holdout evaluations contain non-finite alpha_map")

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

    required_inputs = [
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
    if merged[required_inputs].isna().any().any():
        missing_ids = merged.loc[
            merged[required_inputs].isna().any(axis=1), "scenario_id"
        ].unique()
        raise ValueError(f"missing frozen features for scenarios: {missing_ids.tolist()}")
    if not merged["scenario_data_split"].eq("holdout").all():
        raise ValueError("base-scenario feature join crossed the sealed split")
    if not merged["population_data_split"].eq("holdout").all():
        raise ValueError("population feature join crossed the sealed split")
    if not set(merged["dominant_phase"].astype(str)).issubset({"a", "b", "c"}):
        raise ValueError("dominant_phase contains a value outside a, b, c")

    merged["phase_imbalance_index"] = merged["phase_ratio"].map(
        phase_imbalance_index
    )
    encoded = merged["call_time"].map(call_time_encoding)
    merged["call_time_sin"] = encoded.map(lambda pair: pair[0])
    merged["call_time_cos"] = encoded.map(lambda pair: pair[1])
    merged["false_safe"] = merged["alpha_map"].lt(RISK_ALPHA_THRESHOLD)
    return merged


def wilson_interval(
    failures: int,
    total: int,
    *,
    z: float = WILSON_95_Z,
) -> tuple[float | None, float | None]:
    """Return the two-sided Wilson interval for a binomial failure rate."""
    failures = int(failures)
    total = int(total)
    if total < 0 or failures < 0 or failures > total:
        raise ValueError("failures must satisfy 0 <= failures <= total")
    if total == 0:
        return None, None
    proportion = failures / total
    z_squared = z * z
    denominator = 1.0 + z_squared / total
    center = (proportion + z_squared / (2.0 * total)) / denominator
    half_width = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z_squared / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def evaluate_frozen_applicability(
    models_payload: dict,
    feature_frame: pd.DataFrame,
    *,
    model_sha256: str,
) -> pd.DataFrame:
    """Apply serialized development models and thresholds without fitting."""
    records = models_payload.get("models")
    if not isinstance(records, list) or len(records) != 12:
        raise ValueError("frozen model payload must contain exactly 12 models")
    if len({str(record.get("cell_id")) for record in records}) != len(records):
        raise ValueError("frozen model payload contains duplicate cell IDs")
    _require_columns(
        feature_frame,
        (
            "evaluation_id",
            "data_role",
            "feeder",
            "direction",
            "duration_min",
            "alpha_map",
            "false_safe",
        ),
        "holdout feature frame",
    )
    if set(feature_frame["data_role"].astype(str)) != {"holdout"}:
        raise ValueError("frozen model scoring accepts holdout features only")

    rows = []
    for record in sorted(
        records,
        key=lambda item: (
            str(item["feeder"]),
            str(item["direction"]),
            int(item["duration_min"]),
        ),
    ):
        cell = feature_frame.loc[
            feature_frame["feeder"].eq(record["feeder"])
            & feature_frame["direction"].eq(record["direction"])
            & feature_frame["duration_min"].eq(int(record["duration_min"]))
        ].copy()
        scores = (
            predict_risk_scores(record, cell)
            if len(cell)
            else np.asarray([], dtype=float)
        )
        if len(scores) and (not np.isfinite(scores).all()):
            raise ValueError(f"non-finite holdout scores for {record['cell_id']}")

        threshold = record.get("applicability_threshold")
        if threshold is None:
            threshold_value = None
            development_selected_n = 0
            development_false_safe_rate = None
            selected_n = 0
            false_safe_n = 0
            false_safe_rate = None
            lower, upper = None, None
            coverage = 0.0
            claim_status = "NO_DEVELOPMENT_RULE"
        else:
            threshold_value = float(threshold["risk_threshold"])
            development_selected_n = int(threshold["selected_n"])
            development_false_safe_rate = float(threshold["false_safe_rate"])
            selected = scores <= threshold_value
            selected_n = int(selected.sum())
            false_safe_n = int(cell.loc[selected, "false_safe"].astype(bool).sum())
            false_safe_rate = (
                float(false_safe_n / selected_n) if selected_n else None
            )
            lower, upper = wilson_interval(false_safe_n, selected_n)
            coverage = float(selected_n / len(cell)) if len(cell) else 0.0
            if selected_n < MINIMUM_SELECTED_N:
                claim_status = "INSUFFICIENT_HOLDOUT_N"
            elif false_safe_rate is not None and false_safe_rate <= MAXIMUM_FALSE_SAFE_RATE:
                claim_status = "VALIDATED"
            else:
                claim_status = "NOT_VALIDATED_FALSE_SAFE"

        rows.append(
            {
                "cell_id": str(record["cell_id"]),
                "feeder": str(record["feeder"]),
                "direction": str(record["direction"]),
                "duration_min": int(record["duration_min"]),
                "eligible_holdout_n": int(len(cell)),
                "risk_threshold": threshold_value,
                "development_selected_n": development_selected_n,
                "development_false_safe_rate": development_false_safe_rate,
                "holdout_selected_n": selected_n,
                "holdout_false_safe_n": false_safe_n,
                "holdout_false_safe_rate": false_safe_rate,
                "wilson_95_lower": lower,
                "wilson_95_upper": upper,
                "holdout_coverage": coverage,
                "minimum_selected_n": MINIMUM_SELECTED_N,
                "maximum_false_safe_rate": MAXIMUM_FALSE_SAFE_RATE,
                "claim_status": claim_status,
                "formal_claim_validated": claim_status == "VALIDATED",
                "selected_c": float(record["selected_c"]),
                "development_oof_brier": float(
                    record["selected_overall_oof_brier"]
                ),
                "model_sha256": model_sha256,
            }
        )
    return pd.DataFrame(rows)


def _bootstrap_paired_median_intervals(
    paired: pd.DataFrame,
    *,
    columns: list[str],
    resamples: int,
    rng: np.random.Generator,
) -> dict[str, tuple[float, float]]:
    if resamples <= 0:
        raise ValueError("bootstrap_resamples must be positive")
    samples = {column: np.empty(resamples, dtype=float) for column in columns}
    strata = [
        group.reset_index(drop=True)
        for _, group in paired.groupby("call_time", sort=True, dropna=False)
    ]
    for sample_index in range(resamples):
        sampled_parts = []
        for stratum in strata:
            indices = rng.integers(0, len(stratum), size=len(stratum))
            sampled_parts.append(stratum.iloc[indices])
        sampled = pd.concat(sampled_parts, ignore_index=True)
        for column in columns:
            samples[column][sample_index] = float(sampled[column].median())
    return {
        column: (
            float(np.quantile(values, 0.025)),
            float(np.quantile(values, 0.975)),
        )
        for column, values in samples.items()
    }


def directional_summary(
    evaluations: pd.DataFrame,
    *,
    bootstrap_resamples: int = HOLDOUT_BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = HOLDOUT_BOOTSTRAP_SEED,
) -> tuple[pd.DataFrame, dict]:
    """Summarize paired inc-minus-dec holdout effects by feeder and duration."""
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
            "bias_pct",
            "f_3ph_kw",
        ),
        "holdout directional evaluations",
    )
    if set(evaluations["data_role"].dropna().astype(str)) != {"holdout"}:
        raise ValueError("directional summary accepts holdout rows only")
    if not set(evaluations["direction"].dropna().astype(str)).issubset({"inc", "dec"}):
        raise ValueError("directional summary supports inc and dec only")

    failed_ids = sorted(
        evaluations.loc[~evaluations["status"].eq("SUCCESS"), "evaluation_id"]
        .astype(str)
        .tolist()
    )
    successful = evaluations.loc[evaluations["status"].eq("SUCCESS")].copy()
    key_columns = ["scenario_id", "feeder", "call_time", "duration_min"]
    if successful.duplicated(key_columns + ["direction"]).any():
        duplicate = successful.loc[
            successful.duplicated(key_columns + ["direction"]),
            key_columns + ["direction"],
        ].iloc[0]
        raise ValueError(f"duplicate directional pairing key: {duplicate.to_dict()}")

    inc = successful.loc[
        successful["direction"].eq("inc"),
        key_columns + ["evaluation_id", "alpha_map", "bias_pct", "f_3ph_kw"],
    ].rename(
        columns={
            "evaluation_id": "evaluation_id_inc",
            "alpha_map": "alpha_map_inc",
            "bias_pct": "bias_pct_inc",
            "f_3ph_kw": "f_3ph_kw_inc",
        }
    )
    dec = successful.loc[
        successful["direction"].eq("dec"),
        key_columns + ["evaluation_id", "alpha_map", "bias_pct", "f_3ph_kw"],
    ].rename(
        columns={
            "evaluation_id": "evaluation_id_dec",
            "alpha_map": "alpha_map_dec",
            "bias_pct": "bias_pct_dec",
            "f_3ph_kw": "f_3ph_kw_dec",
        }
    )
    outer = inc.merge(dec, on=key_columns, how="outer", indicator=True)
    unpaired_ids = sorted(
        [
            str(value)
            for value in pd.concat(
                [
                    outer.loc[outer["_merge"].eq("left_only"), "evaluation_id_inc"],
                    outer.loc[outer["_merge"].eq("right_only"), "evaluation_id_dec"],
                ],
                ignore_index=True,
            ).dropna()
        ]
    )
    paired = outer.loc[outer["_merge"].eq("both")].drop(columns="_merge").copy()
    numeric_columns = [
        "alpha_map_inc",
        "alpha_map_dec",
        "bias_pct_inc",
        "bias_pct_dec",
        "f_3ph_kw_inc",
        "f_3ph_kw_dec",
    ]
    for column in numeric_columns:
        paired[column] = pd.to_numeric(paired[column], errors="raise")
    if len(paired) and not np.isfinite(paired[numeric_columns].to_numpy()).all():
        raise ValueError("paired holdout metrics contain non-finite values")

    paired["alpha_difference_inc_minus_dec"] = (
        paired["alpha_map_inc"] - paired["alpha_map_dec"]
    )
    paired["bias_difference_inc_minus_dec"] = (
        paired["bias_pct_inc"] - paired["bias_pct_dec"]
    )
    paired["capacity_difference_inc_minus_dec_kw"] = (
        paired["f_3ph_kw_inc"] - paired["f_3ph_kw_dec"]
    )
    paired["false_safe_inc"] = paired["alpha_map_inc"].lt(RISK_ALPHA_THRESHOLD)
    paired["false_safe_dec"] = paired["alpha_map_dec"].lt(RISK_ALPHA_THRESHOLD)

    difference_columns = [
        "alpha_difference_inc_minus_dec",
        "bias_difference_inc_minus_dec",
        "capacity_difference_inc_minus_dec_kw",
    ]
    rng = np.random.default_rng(int(bootstrap_seed))
    rows = []
    for (feeder, duration), cell in paired.groupby(
        ["feeder", "duration_min"], sort=True
    ):
        cell = cell.sort_values(
            ["call_time", "scenario_id"], kind="stable"
        ).reset_index(drop=True)
        intervals = _bootstrap_paired_median_intervals(
            cell,
            columns=difference_columns,
            resamples=int(bootstrap_resamples),
            rng=rng,
        )
        rows.append(
            {
                "feeder": str(feeder),
                "duration_min": int(duration),
                "paired_n": int(len(cell)),
                "call_time_strata_n": int(cell["call_time"].nunique()),
                "median_alpha_inc": float(cell["alpha_map_inc"].median()),
                "median_alpha_dec": float(cell["alpha_map_dec"].median()),
                "median_alpha_difference_inc_minus_dec": float(
                    cell["alpha_difference_inc_minus_dec"].median()
                ),
                "alpha_difference_ci95_lower": intervals[
                    "alpha_difference_inc_minus_dec"
                ][0],
                "alpha_difference_ci95_upper": intervals[
                    "alpha_difference_inc_minus_dec"
                ][1],
                "median_bias_pct_inc": float(cell["bias_pct_inc"].median()),
                "median_bias_pct_dec": float(cell["bias_pct_dec"].median()),
                "median_bias_difference_inc_minus_dec": float(
                    cell["bias_difference_inc_minus_dec"].median()
                ),
                "bias_difference_ci95_lower": intervals[
                    "bias_difference_inc_minus_dec"
                ][0],
                "bias_difference_ci95_upper": intervals[
                    "bias_difference_inc_minus_dec"
                ][1],
                "median_f_3ph_kw_inc": float(cell["f_3ph_kw_inc"].median()),
                "median_f_3ph_kw_dec": float(cell["f_3ph_kw_dec"].median()),
                "median_capacity_difference_inc_minus_dec_kw": float(
                    cell["capacity_difference_inc_minus_dec_kw"].median()
                ),
                "capacity_difference_ci95_lower_kw": intervals[
                    "capacity_difference_inc_minus_dec_kw"
                ][0],
                "capacity_difference_ci95_upper_kw": intervals[
                    "capacity_difference_inc_minus_dec_kw"
                ][1],
                "false_safe_rate_inc": float(cell["false_safe_inc"].mean()),
                "false_safe_rate_dec": float(cell["false_safe_dec"].mean()),
                "bootstrap_seed": int(bootstrap_seed),
                "bootstrap_resamples": int(bootstrap_resamples),
                "bootstrap_stratification": "call_time within feeder-duration",
                "paired_difference_definition": "inc minus dec",
            }
        )
    audit = {
        "bootstrap_seed": int(bootstrap_seed),
        "bootstrap_resamples": int(bootstrap_resamples),
        "bootstrap_stratification": "call_time within feeder-duration",
        "successful_evaluations": int(len(successful)),
        "paired_scenario_duration_records": int(len(paired)),
        "failed_evaluation_ids": failed_ids,
        "unpaired_evaluation_ids": unpaired_ids,
    }
    return pd.DataFrame(rows), audit
