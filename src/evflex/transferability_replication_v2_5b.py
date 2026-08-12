from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from evflex.transferability_baseline_comparison_v2_3 import (
    POLICY_SPECS,
    apply_fitted_policy,
    fit_policy,
    load_project_evaluations,
    validate_evaluation_rows,
    wilson_interval,
)
from evflex.transferability_phicte_v2_4 import (
    DEFAULT_PENALTIES,
    DEFAULT_QUANTILE,
    DEFAULT_TARGET_RISK,
    build_feature_row,
    cross_fit,
    evaluate_predictions,
)


PROTOCOL_VERSION = (
    "EV-FLEX-BIAS-V2.5B-R1-PHICTE-EXPANDED-RETROSPECTIVE-REPLICATION"
)
CONFIG_RELATIVE_PATH = Path("config/transferability_replication_v2_5b.json")
OUTPUT_DIRECTORY = Path("results/transferability_replication_v2_5b")
CHECKPOINT_PATH = Path("state/runtime/transferability_replication_v2_5b/checkpoint.json")
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)
THREAD_ENVIRONMENT = {name: "1" for name in THREAD_VARIABLES}
for _name, _value in THREAD_ENVIRONMENT.items():
    os.environ[_name] = _value


PREDICTION_FIELDS = (
    "evaluation_id",
    "scenario_id",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "active_offer",
    "f_bal_kw",
    "alpha_transfer",
    "alpha_transfer_tied",
    "phase_repair_gain",
    "phicte_quantile_prediction",
    "phicte_factor",
    "raw_balanced_offer_factor",
    "global_derating_factor",
    "feeder_only_factor",
    "direction_only_factor",
    "local_feeder_direction_duration_factor",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = completed.stdout.strip()
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("Git HEAD is not a 40-character lowercase commit SHA")
    return value


def _git_blob_sha(repo_root: Path, relative_path: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "hash-object", relative_path],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    value = completed.stdout.strip()
    if len(value) != 40:
        raise ValueError(f"invalid Git blob SHA for {relative_path}")
    return value


def _require_clean_worktree(repo_root: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.stdout.strip():
        raise ValueError(
            "V2.5B execution requires the protocol/code to be committed and the worktree clean"
        )


def _expected_scenario_ids(config: Mapping[str, Any]) -> list[str]:
    scenario_ids = []
    for feeder in config["feeders"]:
        for call_time in config["call_times"]:
            hhmm = str(call_time).replace(":", "")
            for suffix in config["scenario_suffixes"]:
                scenario_ids.append(f"{feeder}_{hhmm}_{int(suffix):02d}")
    return scenario_ids


def _validate_config(config: Mapping[str, Any]) -> None:
    if config.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("V2.5B protocol version differs from the frozen protocol")
    if config.get("source_protocol_version") != "EV-FLEX-BIAS-V2.0":
        raise ValueError("V2.5B source protocol must remain V2.0")
    if config.get("source_manifest") != "manifests/core_work_units_v2_0.csv":
        raise ValueError("V2.5B source manifest differs")
    if config.get("source_data_role") != "holdout":
        raise ValueError("V2.5B must draw only from the prior V2.0 holdout role")
    if config.get("prior_v2_0_holdout_open_count") != 1:
        raise ValueError("V2.5B must acknowledge the prior V2.0 holdout opening")
    if config.get("blind_holdout_claim") is not False:
        raise ValueError("V2.5B must not claim a blind holdout")
    if config.get("confirmatory_claim") is not False:
        raise ValueError("V2.5B must not be labelled confirmatory")
    if config.get("design_role") != "expanded_retrospective_replication":
        raise ValueError("V2.5B design role differs")
    if config.get("scenario_suffixes") != [26, 27, 28, 29, 30, 31]:
        raise ValueError("V2.5B must use the complete unused suffix set 26-31")
    if config.get("feeders") != ["ieee13", "lv906"]:
        raise ValueError("V2.5B feeders differ")
    if config.get("call_times") != ["19:00", "00:00", "02:00", "06:00"]:
        raise ValueError("V2.5B call times differ")
    if config.get("directions") != ["inc", "dec"]:
        raise ValueError("V2.5B directions differ")
    if config.get("durations_min") != [15, 30, 60]:
        raise ValueError("The shared pilot evaluator requires durations 15, 30, and 60")
    if config.get("primary_duration_min") != 15:
        raise ValueError("V2.5B primary duration must remain 15 minutes")
    if config.get("workers") != 1 or config.get("numeric_threads") != 1:
        raise ValueError("V2.5B must run with one worker and one numeric thread")
    formal = config.get("formal_constraints")
    expected_formal = {
        "vmin_pu": 0.95,
        "vmax_pu": 1.06,
        "vuf_limit_pct": 2.0,
        "transformer_loading_limit_pu": 1.0,
        "feeder_loading_limit_pu": 1.0,
        "line_thermal_in_scope": False,
    }
    if formal != expected_formal:
        raise ValueError("V2.5B formal constraints differ from V2.2/V2.3A")
    if config.get("feeder_kva") != {"ieee13": 5000, "lv906": 800}:
        raise ValueError("V2.5B feeder ratings differ")
    if config.get("active_offer") != {
        "rule": "max(minimum_kw, feeder_fraction * feeder_kva)",
        "minimum_kw": 7.2,
        "feeder_fraction": 0.005,
    }:
        raise ValueError("V2.5B active-offer rule differs")
    if config.get("alpha_search") != {"coarse_step": 0.02, "refine_tolerance": 0.002}:
        raise ValueError("V2.5B alpha-search rule differs")
    if config.get("scientific_gate_thresholds") != {"warm_timing": {"repeats": 3}}:
        raise ValueError("V2.5B timing contract differs")
    frozen = config.get("frozen_phicte_v2_4")
    if not isinstance(frozen, Mapping):
        raise ValueError("V2.5B frozen PHiCTE identity is missing")
    if frozen.get("selected_penalty") != 0.01:
        raise ValueError("V2.5B selected PHiCTE penalty differs")
    if frozen.get("quantile") != 0.10 or frozen.get("target_empirical_material_risk") != 0.05:
        raise ValueError("V2.5B PHiCTE quantile/risk identity differs")
    amendment = config.get("protocol_amendment")
    if (
        not isinstance(amendment, Mapping)
        or amendment.get("amendment_id") != "V2.5B-R1-PREEXECUTION-RISK-DENOMINATOR"
        or amendment.get("execution_started_before_amendment") is not False
        or amendment.get("v2_5b_outcomes_observed_before_amendment") is not False
        or amendment.get("selection_changed") is not False
        or amendment.get("scenario_ids_changed") is not False
        or amendment.get("phicte_model_or_hyperparameters_changed") is not False
    ):
        raise ValueError("V2.5B-R1 pre-execution protocol amendment is not frozen")
    rules = config.get("primary_evidence_rules")
    expected_rule_values = {
        "minimum_active_primary_n": 73,
        "minimum_primary_risk_denominator_n": 73,
        "minimum_primary_risk_denominator_n_per_feeder": 24,
        "phicte_empirical_material_false_safe_rate_max": 0.05,
        "phicte_empirical_material_false_safe_rate_max_each_feeder": 0.05,
        "require_no_numerical_failure_audits": True,
        "require_phicte_pareto_nondominated_within_each_feeder": True,
        "require_positive_phicte_kw_delta_vs_global_within_each_feeder": True,
        "require_positive_phicte_kw_delta_vs_direction_only_within_each_feeder": True,
        "require_positive_lv906_kw_delta_vs_feeder_only": True,
        "require_positive_ieee13_kw_delta_vs_feeder_only": False,
        "require_zero_phicte_strict_bound_exceedance": True,
        "require_zero_phicte_strict_bound_exceedance_each_feeder": True,
        "wilson95_upper_below_5_percent_is_required": False,
        "pooled_kw_superiority_is_required": False,
    }
    if not isinstance(rules, Mapping) or any(
        rules.get(name) != value for name, value in expected_rule_values.items()
    ):
        raise ValueError("V2.5B-R1 primary evidence rules are not frozen")
    bootstrap = config.get("bootstrap")
    if (
        not isinstance(bootstrap, Mapping)
        or bootstrap.get("seed") != 2026081202
        or bootstrap.get("resamples") != 100000
        or bootstrap.get("resampling_unit") != "scenario_id"
        or bootstrap.get("stratify_by") != "feeder"
    ):
        raise ValueError("V2.5B bootstrap contract differs")


def load_replication_design(
    repo_root: str | Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    root = Path(repo_root).resolve(strict=True)
    config_path = root / CONFIG_RELATIVE_PATH
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)
    config["_config_sha256"] = _sha256(config_path)

    unlock_path = root / str(config["prior_v2_0_holdout_open_record"])
    if _sha256(unlock_path) != config["prior_v2_0_holdout_open_record_sha256"]:
        raise ValueError("prior V2.0 holdout-open record hash differs")
    unlock = json.loads(unlock_path.read_text(encoding="utf-8"))
    if unlock.get("status") != "UNLOCKED" or unlock.get("holdout_open_count") != 1:
        raise ValueError("prior V2.0 holdout-open record is inconsistent")

    source_path = root / str(config["source_manifest"])
    if _sha256(source_path) != config["source_manifest_sha256"]:
        raise ValueError("V2.5B source manifest hash differs")
    source = pd.read_csv(source_path)
    expected_scenarios = _expected_scenario_ids(config)
    selected = source[source["scenario_id"].isin(expected_scenarios)].copy()
    if len(expected_scenarios) != 48 or len(set(expected_scenarios)) != 48:
        raise ValueError("V2.5B expected scenario construction failed")
    if len(selected) != 96 or set(selected["scenario_id"]) != set(expected_scenarios):
        raise ValueError("V2.5B source manifest does not contain all 48 paired scenarios")
    if set(selected["protocol_version"]) != {config["source_protocol_version"]}:
        raise ValueError("V2.5B source protocol differs")
    if set(selected["data_role"]) != {config["source_data_role"]}:
        raise ValueError("V2.5B source rows are not all prior holdout rows")
    if set(selected["holdout_access"]) != {"sealed"}:
        raise ValueError("V2.5B source access labels are not the prior sealed labels")
    by_key = {
        (str(row.scenario_id), str(row.direction)): row
        for row in selected.itertuples(index=False)
    }
    if len(by_key) != 96:
        raise ValueError("V2.5B source scenario-direction identities are not unique")

    records: list[dict[str, Any]] = []
    for scenario_id in expected_scenarios:
        for direction in config["directions"]:
            source_row = by_key[(scenario_id, direction)]
            unit_id = f"v25b_replication_{scenario_id}__{direction}"
            records.append(
                {
                    "work_unit_id": unit_id,
                    "protocol_version": config["protocol_version"],
                    "scenario_id": scenario_id,
                    "feeder": str(source_row.feeder),
                    "call_time": str(source_row.call_time),
                    "direction": direction,
                    "scenario_seed": int(source_row.scenario_seed),
                    "data_role": config["design_role"],
                    "source_data_role": str(source_row.data_role),
                    "source_holdout_access": str(source_row.holdout_access),
                    "prior_holdout_open_acknowledged": True,
                    "evaluation_ids": json.dumps(
                        [
                            f"v25b_replication_{scenario_id}__{direction}__{duration}m"
                            for duration in config["durations_min"]
                        ],
                        separators=(",", ":"),
                    ),
                    "status": "PENDING",
                }
            )
    frame = pd.DataFrame.from_records(records)
    if len(frame) != 96 or frame["work_unit_id"].duplicated().any():
        raise ValueError("V2.5B design must contain exactly 96 unique work units")
    return config, frame


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        record = {key: (None if pd.isna(value) else value) for key, value in raw.items()}
        record["scenario_seed"] = int(record["scenario_seed"])
        record["prior_holdout_open_acknowledged"] = bool(
            record["prior_holdout_open_acknowledged"]
        )
        records.append(record)
    return records


def _is_analysis_eligible(row: Mapping[str, Any]) -> bool:
    """Return whether a row is a valid active or legitimate inactive scientific row."""

    status = row.get("status")
    valid_active = bool(
        status == "SUCCESS"
        and row.get("scientific_status") == "VALID"
        and row.get("active_offer") is True
        and row.get("eligible_for_scientific_denominator") is True
        and row.get("alpha_path_scientific_valid") is True
        and row.get("alpha_path_status") == "VALID"
        and isinstance(row.get("alpha_transfer"), (int, float))
        and not isinstance(row.get("alpha_transfer"), bool)
        and 0.0 <= float(row["alpha_transfer"]) <= 1.0
        and isinstance(row.get("alpha_path_audit"), Mapping)
        and row["alpha_path_audit"].get("numerical_failure_audits") == 0
    )
    valid_inactive = bool(
        status == "INACTIVE_OFFER"
        and row.get("scientific_status") == "NOT_APPLICABLE_INACTIVE"
        and row.get("active_offer") is False
        and row.get("eligible_for_scientific_denominator") is False
        and row.get("alpha_transfer") is None
        and row.get("alpha_path_scientific_valid") is None
        and row.get("alpha_path_status") is None
        and row.get("alpha_path_audit") is None
    )
    return valid_active or valid_inactive


def _is_planned_noneligible(row: Mapping[str, Any]) -> bool:
    """Accept explicitly classified scientific ineligibility without aborting the batch."""

    return bool(
        row.get("eligible_for_scientific_denominator") is False
        and row.get("scientific_status")
        in {"INVALID_SCHEDULE", "INVALID_BASELINE", "NUMERICAL_INVALID_ALPHA_PATH"}
        and row.get("status")
        in {
            "SCHEDULE_SOLVER_INVALID",
            "BASELINE_PHYSICAL_INVALID",
            "BASELINE_NUMERICAL_INVALID",
            "ALPHA_PATH_NUMERICAL_INVALID",
            "ALPHA_PATH_INVALID",
        }
    )


def _noneligible_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    noneligible = [row for row in rows if not _is_analysis_eligible(row)]
    by_status: dict[str, int] = defaultdict(int)
    by_baseline: dict[str, int] = defaultdict(int)
    by_feeder: dict[str, int] = defaultdict(int)
    for row in noneligible:
        by_status[str(row.get("status"))] += 1
        by_baseline[str(row.get("baseline_status"))] += 1
        by_feeder[str(row.get("feeder"))] += 1
    return {
        "n": len(noneligible),
        "by_status": dict(sorted(by_status.items())),
        "by_baseline_status": dict(sorted(by_baseline.items())),
        "by_feeder": dict(sorted(by_feeder.items())),
        "baseline_physical_invalid_n": sum(
            row.get("baseline_status") == "BASELINE_PHYSICAL_INVALID" for row in noneligible
        ),
        "baseline_numerical_invalid_n": sum(
            row.get("baseline_status") == "BASELINE_NUMERICAL_INVALID" for row in noneligible
        ),
        "interpretation": (
            "Planned rows with an infeasible or invalid baseline/schedule are retained as coverage outcomes "
            "but excluded from alpha-transfer risk/retention denominators because transferability along the "
            "baseline-to-call ray is not scientifically defined from an infeasible alpha=0 operating point."
        ),
    }


def _validate_unit_evaluations(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    unit: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    expected_ids = json.loads(str(unit["evaluation_ids"]))
    if len(evaluations) != 3 or [row.get("evaluation_id") for row in evaluations] != expected_ids:
        raise ValueError("V2.5B evaluator returned different evaluation identities")
    for row in evaluations:
        identity_valid = bool(
            row.get("work_unit_id") == unit["work_unit_id"]
            and row.get("protocol_version") == config["protocol_version"]
            and row.get("scenario_id") == unit["scenario_id"]
            and row.get("data_role") == config["design_role"]
        )
        if not identity_valid:
            raise ValueError(
                f"V2.5B produced an identity-invalid evaluation: {row.get('evaluation_id')}"
            )
        if not _is_analysis_eligible(row) and not _is_planned_noneligible(row):
            raise ValueError(
                "V2.5B produced an unclassified evaluation state: "
                f"{row.get('evaluation_id')} status={row.get('status')} "
                f"scientific_status={row.get('scientific_status')} "
                f"baseline_status={row.get('baseline_status')}"
            )


def execute_replication_unit(
    repo_root: str | Path,
    unit: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    code_commit: str | None = None,
) -> dict[str, Any]:
    from evflex.pilot import evaluate_pilot_work_unit

    root = Path(repo_root).resolve(strict=True)
    evaluations = evaluate_pilot_work_unit(root, unit, config=config)
    _validate_unit_evaluations(evaluations, unit=unit, config=config)
    status_counts: dict[str, int] = defaultdict(int)
    for row in evaluations:
        status_counts[str(row["status"])] += 1
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": "SUCCESS",
        "work_unit_id": str(unit["work_unit_id"]),
        "scenario_id": str(unit["scenario_id"]),
        "scenario_seed": int(unit["scenario_seed"]),
        "data_role": str(unit["data_role"]),
        "evaluation_status_counts": dict(sorted(status_counts.items())),
        "resource_policy": {
            "workers": 1,
            "numeric_threads": 1,
            "environment": dict(THREAD_ENVIRONMENT),
            "gpu_used": False,
        },
        "run_provenance": {
            "code_commit": code_commit or _git_commit(root),
            "config_sha256": config["_config_sha256"],
            "source_manifest_sha256": config["source_manifest_sha256"],
            "prior_v2_0_holdout_open_count": 1,
            "blind_holdout_claim": False,
            "confirmatory_claim": False,
            "source_outcomes_used_for_selection": False,
        },
        "evaluations": deepcopy(list(evaluations)),
    }


def _apply_policy_to_rows(
    rows: Sequence[Mapping[str, Any]],
    fitted_policy: Mapping[str, Any],
) -> list[float | None]:
    factors: list[float | None] = []
    for row in rows:
        if not _is_analysis_eligible(row) or row.get("active_offer") is not True:
            factors.append(None)
            continue
        factor, matched = apply_fitted_policy(row, fitted_policy)
        factors.append(float(factor) if matched else 0.0)
    return factors


def _fit_baseline_policies(
    development_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    fitted: dict[str, dict[str, Any]] = {
        "raw_balanced_offer": {"grouping_fields": None, "fixed_factor": 1.0}
    }
    for name, grouping_fields in POLICY_SPECS.items():
        if name == "raw_balanced_offer":
            continue
        assert grouping_fields is not None
        fitted[name] = fit_policy(
            development_rows,
            grouping_fields=grouping_fields,
            maximum_risk=0.05,
        )
    return fitted


def _apply_phicte(
    rows: Sequence[Mapping[str, Any]],
    *,
    model: Any,
    correction: float,
    feeder_kva: Mapping[str, float],
) -> tuple[list[float | None], list[float | None]]:
    quantile_predictions: list[float | None] = [None] * len(rows)
    factors: list[float | None] = [None] * len(rows)
    active_indices = [
        index for index, row in enumerate(rows)
        if _is_analysis_eligible(row) and row.get("active_offer") is True
    ]
    if not active_indices:
        return quantile_predictions, factors
    features = [
        build_feature_row(rows[index], feeder_kva=feeder_kva)
        for index in active_indices
    ]
    predictions = model.predict(features)
    for index, prediction in zip(active_indices, predictions, strict=True):
        quantile_predictions[index] = float(prediction)
        factors[index] = float(np.clip(float(prediction) - correction, 0.0, 1.0))
    return quantile_predictions, factors


def _subset(
    rows: Sequence[Mapping[str, Any]],
    factors: Mapping[str, Sequence[float | None]],
    indices: Sequence[int],
) -> tuple[list[Mapping[str, Any]], dict[str, list[float | None]]]:
    return (
        [rows[index] for index in indices],
        {name: [values[index] for index in indices] for name, values in factors.items()},
    )


def _metrics(
    rows: Sequence[Mapping[str, Any]],
    factors: Mapping[str, Sequence[float | None]],
    indices: Sequence[int],
) -> dict[str, dict[str, Any]]:
    eligible_indices = [index for index in indices if _is_analysis_eligible(rows[index])]
    selected_rows, selected_factors = _subset(rows, factors, eligible_indices)
    return {
        name: evaluate_predictions(selected_rows, values)
        for name, values in selected_factors.items()
    }


def _pareto_status(metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    phicte = metrics["phicte"]
    p_risk = phicte.get("material_false_safe_rate")
    p_ret = phicte.get("pooled_kw_retention_sensitivity")
    if p_risk is None or p_ret is None:
        return {"status": "NOT_EVALUABLE", "dominated_by": []}
    dominated_by: list[str] = []
    for name, candidate in metrics.items():
        if name == "phicte":
            continue
        risk = candidate.get("material_false_safe_rate")
        retention = candidate.get("pooled_kw_retention_sensitivity")
        if risk is None or retention is None:
            continue
        no_more_risky = float(risk) <= float(p_risk) + 1e-12
        no_less_retention = float(retention) >= float(p_ret) - 1e-12
        strictly_better = (
            float(risk) < float(p_risk) - 1e-12
            or float(retention) > float(p_ret) + 1e-12
        )
        if no_more_risky and no_less_retention and strictly_better:
            dominated_by.append(name)
    return {
        "status": "NONDOMINATED" if not dominated_by else "DOMINATED",
        "dominated_by": sorted(dominated_by),
    }


def _scenario_aggregates(
    rows: Sequence[Mapping[str, Any]],
    phicte: Sequence[float | None],
    feeder_only: Sequence[float | None],
) -> dict[str, list[dict[str, float]]]:
    by_feeder_scenario: dict[tuple[str, str], dict[str, float]] = {}
    for row, ph_factor, feeder_factor in zip(rows, phicte, feeder_only, strict=True):
        if not _is_analysis_eligible(row) or row.get("active_offer") is not True:
            continue
        if ph_factor is None or feeder_factor is None:
            raise ValueError("active bootstrap row lacks a factor")
        key = (str(row["feeder"]), str(row["scenario_id"]))
        item = by_feeder_scenario.setdefault(
            key,
            {
                "n": 0.0,
                "ph_factor_sum": 0.0,
                "feeder_factor_sum": 0.0,
                "offer": 0.0,
                "ph_kw": 0.0,
                "feeder_kw": 0.0,
            },
        )
        offer = abs(float(row["f_bal_kw"]))
        item["n"] += 1.0
        item["ph_factor_sum"] += float(ph_factor)
        item["feeder_factor_sum"] += float(feeder_factor)
        item["offer"] += offer
        item["ph_kw"] += offer * float(ph_factor)
        item["feeder_kw"] += offer * float(feeder_factor)
    result: dict[str, list[dict[str, float]]] = defaultdict(list)
    for (feeder, _scenario), values in sorted(by_feeder_scenario.items()):
        result[feeder].append(values)
    return dict(result)


def _bootstrap_primary_deltas(
    rows: Sequence[Mapping[str, Any]],
    phicte: Sequence[float | None],
    feeder_only: Sequence[float | None],
    *,
    seed: int,
    resamples: int,
) -> dict[str, Any]:
    grouped = _scenario_aggregates(rows, phicte, feeder_only)
    if set(grouped) != {"ieee13", "lv906"}:
        raise ValueError("bootstrap requires both feeder strata")
    rng = np.random.default_rng(seed)
    feeder_draws: dict[str, dict[str, np.ndarray]] = {}
    for feeder, records in grouped.items():
        matrix = np.asarray(
            [
                [
                    item["n"],
                    item["ph_factor_sum"],
                    item["feeder_factor_sum"],
                    item["offer"],
                    item["ph_kw"],
                    item["feeder_kw"],
                ]
                for item in records
            ],
            dtype=float,
        )
        n_scenarios = len(matrix)
        if n_scenarios <= 1:
            raise ValueError("each feeder needs at least two bootstrap scenarios")
        draws = rng.integers(0, n_scenarios, size=(resamples, n_scenarios))
        sums = matrix[draws].sum(axis=1)
        feeder_draws[feeder] = {
            "n": sums[:, 0],
            "ph_factor": sums[:, 1],
            "feeder_factor": sums[:, 2],
            "offer": sums[:, 3],
            "ph_kw": sums[:, 4],
            "feeder_kw": sums[:, 5],
        }

    def describe(values: np.ndarray) -> dict[str, float]:
        q = np.quantile(values, [0.025, 0.5, 0.975])
        return {
            "p2_5": float(q[0]),
            "median": float(q[1]),
            "p97_5": float(q[2]),
            "probability_positive": float(np.mean(values > 0.0)),
        }

    feeder_delta: dict[str, np.ndarray] = {}
    feeder_output: dict[str, Any] = {}
    for feeder, values in feeder_draws.items():
        delta = values["ph_kw"] / values["offer"] - values["feeder_kw"] / values["offer"]
        feeder_delta[feeder] = delta
        feeder_output[feeder] = describe(delta)

    all_n = feeder_draws["ieee13"]["n"] + feeder_draws["lv906"]["n"]
    equal_delta = (
        (feeder_draws["ieee13"]["ph_factor"] + feeder_draws["lv906"]["ph_factor"]) / all_n
        - (feeder_draws["ieee13"]["feeder_factor"] + feeder_draws["lv906"]["feeder_factor"]) / all_n
    )
    macro_delta = 0.5 * (feeder_delta["ieee13"] + feeder_delta["lv906"])
    total_offer = feeder_draws["ieee13"]["offer"] + feeder_draws["lv906"]["offer"]
    pooled_delta = (
        (feeder_draws["ieee13"]["ph_kw"] + feeder_draws["lv906"]["ph_kw"]) / total_offer
        - (feeder_draws["ieee13"]["feeder_kw"] + feeder_draws["lv906"]["feeder_kw"]) / total_offer
    )
    return {
        "seed": seed,
        "resamples": resamples,
        "resampling_unit": "scenario_id",
        "stratify_by": "feeder",
        "delta_vs_feeder_only": {
            "equal_case": describe(equal_delta),
            "feeder_macro_kw": describe(macro_delta),
            "pooled_kw": describe(pooled_delta),
            "by_feeder_kw": feeder_output,
        },
    }


def _numerical_failure_audits(rows: Sequence[Mapping[str, Any]]) -> int:
    total = 0
    for row in rows:
        if not _is_analysis_eligible(row) or row.get("active_offer") is not True:
            continue
        audit = row.get("alpha_path_audit")
        if not isinstance(audit, Mapping):
            raise ValueError("active row lacks alpha_path_audit")
        total += int(audit.get("numerical_failure_audits", 0))
    return total



def _scenario_risk_summary(
    rows: Sequence[Mapping[str, Any]],
    factors: Sequence[float | None],
) -> dict[str, Any]:
    by_scenario: dict[str, list[bool]] = defaultdict(list)
    for row, factor in zip(rows, factors, strict=True):
        if (
            not _is_analysis_eligible(row)
            or row.get("active_offer") is not True
            or factor is None
            or float(factor) <= 0.0
        ):
            continue
        event = float(row["alpha_transfer"]) + 1e-12 < 0.95 * float(factor)
        by_scenario[str(row["scenario_id"])].append(bool(event))
    scenario_events = [any(values) for values in by_scenario.values()]
    n = len(scenario_events)
    event_n = sum(scenario_events)
    if n:
        low, high = wilson_interval(event_n, n)
        rate = event_n / n
    else:
        low = high = rate = None
    return {
        "scenario_denominator_n": n,
        "scenario_material_false_safe_n": event_n,
        "scenario_material_false_safe_rate": rate,
        "scenario_material_false_safe_wilson95_low": low,
        "scenario_material_false_safe_wilson95_high": high,
        "definition": "scenario is false-safe if any prescribed active 15-minute direction in the scenario is materially false-safe",
    }


def _performance_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for feeder in ("ieee13", "lv906"):
        values = [
            float(row["alpha1_warm_p95_s"])
            for row in rows
            if row["feeder"] == feeder
            and _is_analysis_eligible(row)
            and row.get("active_offer") is True
            and isinstance(row.get("alpha1_warm_p95_s"), (int, float))
            and not isinstance(row.get("alpha1_warm_p95_s"), bool)
            and math.isfinite(float(row["alpha1_warm_p95_s"]))
        ]
        if values:
            result[feeder] = {
                "active_timing_n": len(values),
                "alpha1_warm_p95_median_s": float(np.median(values)),
                "alpha1_warm_p95_case_p95_s": float(np.quantile(values, 0.95, method="higher")),
                "alpha1_warm_p95_min_s": min(values),
                "alpha1_warm_p95_max_s": max(values),
                "timing_scope": "one fixed-schedule alpha=1 three-phase replay after common baseline with prebuilt truth cache",
            }
        else:
            result[feeder] = {"active_timing_n": 0}
    return result


def _benchmark_phicte_inference(
    rows: Sequence[Mapping[str, Any]],
    *,
    model: Any,
    correction: float,
    feeder_kva: Mapping[str, float],
    repeats: int = 200,
) -> dict[str, Any]:
    active = [
        row for row in rows
        if _is_analysis_eligible(row) and row.get("active_offer") is True
    ]
    if not active:
        return {"active_n": 0, "repeats": repeats}
    start = time.perf_counter()
    for _ in range(repeats):
        features = [build_feature_row(row, feeder_kva=feeder_kva) for row in active]
        prediction = model.predict(features)
        _ = [float(np.clip(value - correction, 0.0, 1.0)) for value in prediction]
    elapsed = time.perf_counter() - start
    return {
        "active_n": len(active),
        "repeats": repeats,
        "batch_mean_s": elapsed / repeats,
        "per_offer_mean_s": elapsed / (repeats * len(active)),
        "scope": "feature extraction plus frozen PHiCTE prediction and clipping; excludes disk I/O and power flow",
        "not_a_scientific_gate": True,
    }

def _repairability_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize phase-aware tie-break repair without changing bus-time aggregate schedules."""

    def summarize(group: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        active = [
            row for row in group
            if _is_analysis_eligible(row) and row.get("active_offer") is True
        ]
        paired = []
        for row in active:
            tied = row.get("alpha_transfer_tied")
            if (
                row.get("tie_comparator_valid") is True
                and row.get("tie_break_status") == "SUCCESS"
                and row.get("alpha_tie_path_status") == "VALID"
                and isinstance(tied, (int, float))
                and not isinstance(tied, bool)
                and math.isfinite(float(tied))
                and 0.0 <= float(tied) <= 1.0
            ):
                paired.append((row, float(row["alpha_transfer"]), float(tied)))
        if not paired:
            return {"active_n": len(active), "paired_valid_n": 0}
        fixed = np.asarray([item[1] for item in paired], dtype=float)
        tied = np.asarray([item[2] for item in paired], dtype=float)
        delta = tied - fixed
        offers = np.asarray([abs(float(item[0]["f_bal_kw"])) for item in paired], dtype=float)
        bad = fixed < 0.95 - 1e-12
        return {
            "active_n": len(active),
            "paired_valid_n": len(paired),
            "paired_coverage": len(paired) / len(active) if active else None,
            "alpha_fixed_mean": float(np.mean(fixed)),
            "alpha_repaired_mean": float(np.mean(tied)),
            "repair_gain_mean": float(np.mean(delta)),
            "repair_gain_median": float(np.median(delta)),
            "repair_gain_offer_weighted": float(np.sum(offers * delta) / np.sum(offers)),
            "positive_repair_n": int(np.sum(delta > 1e-12)),
            "material_repair_ge_0_05_n": int(np.sum(delta >= 0.05 - 1e-12)),
            "worsened_n": int(np.sum(delta < -1e-12)),
            "fixed_bad_alpha_lt_0_95_n": int(np.sum(bad)),
            "rescued_to_alpha_ge_0_95_n": int(np.sum(bad & (tied >= 0.95 - 1e-12))),
            "full_transfer_rescue_n": int(np.sum((fixed < 1.0 - 1e-12) & (tied >= 1.0 - 1e-12))),
            "definition": (
                "Phase-aware tie-break redispatch preserves each bus-time aggregate schedule and declared offer "
                "while reallocating feasible EV trajectories across the fixed fleet; repair gain is "
                "alpha_transfer_tied - alpha_transfer."
            ),
        }

    primary = [row for row in rows if int(row.get("duration_min", -1)) == 15]
    return {
        "overall": summarize(primary),
        "by_feeder": {
            feeder: summarize([row for row in primary if row.get("feeder") == feeder])
            for feeder in ("ieee13", "lv906")
        },
        "by_direction": {
            direction: summarize([row for row in primary if row.get("direction") == direction])
            for direction in ("inc", "dec")
        },
        "claim_boundary": (
            "This is a constrained schedule-repair diagnostic, not a full three-phase reoptimization or a proof "
            "of maximum deliverable flexibility."
        ),
    }


def build_replication_analysis(
    repo_root: str | Path,
    replication_rows: Sequence[Mapping[str, Any]],
    *,
    config: Mapping[str, Any],
    code_commit: str,
    generated_at_utc: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = Path(repo_root).resolve(strict=True)
    if len(replication_rows) != 288:
        raise ValueError("V2.5B must contain 288 duration-level evaluations")
    if len({row["scenario_id"] for row in replication_rows}) != 48:
        raise ValueError("V2.5B must contain 48 unique scenarios")
    analysis_rows = [row for row in replication_rows if _is_analysis_eligible(row)]
    validate_evaluation_rows(analysis_rows, dataset_name="V2.5B eligible replication")
    noneligible = _noneligible_summary(replication_rows)

    development_rows, _opened_external, development_provenance = load_project_evaluations(root)
    validate_evaluation_rows(development_rows, dataset_name="V2.2 development")
    development_active = [row for row in development_rows if bool(row["active_offer"])]
    if len(development_active) != 96:
        raise ValueError("V2.5B expects the frozen 96 active V2.2 development evaluations")

    frozen = config["frozen_phicte_v2_4"]
    if _git_blob_sha(root, "src/evflex/transferability_phicte_v2_4.py") != frozen[
        "source_module_git_blob_sha"
    ]:
        raise ValueError("V2.4 PHiCTE implementation changed before V2.5B")
    if _git_blob_sha(root, "results/transferability_phicte_v2_4/summary.json") != frozen[
        "source_result_summary_git_blob_sha"
    ]:
        raise ValueError("V2.4 PHiCTE summary changed before V2.5B")
    if _git_blob_sha(root, "results/transferability_phicte_v2_4/predictions.csv") != frozen[
        "source_predictions_git_blob_sha"
    ]:
        raise ValueError("V2.4 PHiCTE predictions changed before V2.5B")

    feeder_kva = config["feeder_kva"]
    fitted_phicte = cross_fit(
        development_active,
        feeder_kva=feeder_kva,
        penalties=DEFAULT_PENALTIES,
        n_splits=4,
        quantile=DEFAULT_QUANTILE,
        target_risk=DEFAULT_TARGET_RISK,
    )
    if not math.isclose(
        float(fitted_phicte["selected_penalty"]),
        float(frozen["selected_penalty"]),
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        raise ValueError("V2.5B refit did not reproduce the frozen selected penalty")
    if not math.isclose(
        float(fitted_phicte["correction"]),
        float(frozen["row_level_correction"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("V2.5B refit did not reproduce the frozen row-level correction")
    final_model = fitted_phicte["final_model"]
    correction = float(fitted_phicte["correction"])

    quantile_predictions, phicte_factors = _apply_phicte(
        replication_rows,
        model=final_model,
        correction=correction,
        feeder_kva=feeder_kva,
    )
    policies = _fit_baseline_policies(development_rows)
    factor_maps: dict[str, list[float | None]] = {"phicte": phicte_factors}
    for name, policy in policies.items():
        factor_maps[name] = _apply_policy_to_rows(replication_rows, policy)

    primary_duration = int(config["primary_duration_min"])
    primary_indices = [
        index for index, row in enumerate(replication_rows)
        if int(row["duration_min"]) == primary_duration
    ]
    if len(primary_indices) != 96:
        raise ValueError("V2.5B primary 15-minute scope must contain 96 planned rows")
    primary_metrics = _metrics(replication_rows, factor_maps, primary_indices)
    primary_by_feeder: dict[str, Any] = {}
    for feeder in config["feeders"]:
        indices = [
            index for index in primary_indices
            if replication_rows[index]["feeder"] == feeder
        ]
        metrics = _metrics(replication_rows, factor_maps, indices)
        ph = metrics["phicte"]
        deltas = {
            name: (
                float(ph["pooled_kw_retention_sensitivity"])
                - float(metrics[name]["pooled_kw_retention_sensitivity"])
            )
            for name in metrics
            if name != "phicte"
        }
        primary_by_feeder[feeder] = {
            "planned_n": len(indices),
            "eligible_n": sum(_is_analysis_eligible(replication_rows[index]) for index in indices),
            "active_n": int(ph["active_n"]),
            "policies": metrics,
            "phicte_pareto": _pareto_status(metrics),
            "phicte_kw_retention_delta_vs": deltas,
        }

    descriptive_by_duration: dict[str, Any] = {}
    for duration in config["durations_min"]:
        indices = [
            index for index, row in enumerate(replication_rows)
            if int(row["duration_min"]) == int(duration)
        ]
        descriptive_by_duration[str(duration)] = _metrics(
            replication_rows, factor_maps, indices
        )

    primary_rows, primary_factor_maps = _subset(
        replication_rows, factor_maps, primary_indices
    )
    bootstrap = _bootstrap_primary_deltas(
        primary_rows,
        primary_factor_maps["phicte"],
        primary_factor_maps["feeder_only"],
        seed=int(config["bootstrap"]["seed"]),
        resamples=int(config["bootstrap"]["resamples"]),
    )
    scenario_risk = {
        name: _scenario_risk_summary(primary_rows, values)
        for name, values in primary_factor_maps.items()
    }
    numerical_failure_count = _numerical_failure_audits(primary_rows)
    repairability = _repairability_summary(replication_rows)
    primary_noneligible = _noneligible_summary(primary_rows)
    performance = {
        "three_phase_replay": _performance_summary(primary_rows),
        "phicte_inference": _benchmark_phicte_inference(
            primary_rows,
            model=final_model,
            correction=correction,
            feeder_kva=feeder_kva,
        ),
    }

    rules = config["primary_evidence_rules"]
    p_metrics = primary_metrics["phicte"]
    criteria = {
        "minimum_active_primary_n": int(p_metrics["active_n"])
        >= int(rules["minimum_active_primary_n"]),
        "minimum_primary_risk_denominator_n": int(p_metrics["risk_denominator_n"])
        >= int(rules["minimum_primary_risk_denominator_n"]),
        "minimum_primary_risk_denominator_n_each_feeder": all(
            int(primary_by_feeder[feeder]["policies"]["phicte"]["risk_denominator_n"])
            >= int(rules["minimum_primary_risk_denominator_n_per_feeder"])
            for feeder in config["feeders"]
        ),
        "phicte_empirical_material_risk": (
            p_metrics["material_false_safe_rate"] is not None
            and float(p_metrics["material_false_safe_rate"])
            <= float(rules["phicte_empirical_material_false_safe_rate_max"]) + 1e-12
        ),
        "phicte_empirical_material_risk_each_feeder": all(
            primary_by_feeder[feeder]["policies"]["phicte"]["material_false_safe_rate"] is not None
            and float(primary_by_feeder[feeder]["policies"]["phicte"]["material_false_safe_rate"])
            <= float(rules["phicte_empirical_material_false_safe_rate_max_each_feeder"]) + 1e-12
            for feeder in config["feeders"]
        ),
        "zero_phicte_strict_bound_exceedance": int(
            p_metrics["exceeds_verified_bound_n"]
        ) == 0,
        "zero_phicte_strict_bound_exceedance_each_feeder": all(
            int(primary_by_feeder[feeder]["policies"]["phicte"]["exceeds_verified_bound_n"]) == 0
            for feeder in config["feeders"]
        ),
        "no_numerical_failure_audits": (
            numerical_failure_count == 0
            and int(primary_noneligible["baseline_numerical_invalid_n"]) == 0
        ),
        "phicte_pareto_nondominated_each_feeder": all(
            primary_by_feeder[feeder]["phicte_pareto"]["status"] == "NONDOMINATED"
            for feeder in config["feeders"]
        ),
        "positive_kw_delta_vs_global_each_feeder": all(
            primary_by_feeder[feeder]["phicte_kw_retention_delta_vs"]["global_derating"]
            > 1e-12
            for feeder in config["feeders"]
        ),
        "positive_kw_delta_vs_direction_only_each_feeder": all(
            primary_by_feeder[feeder]["phicte_kw_retention_delta_vs"]["direction_only"]
            > 1e-12
            for feeder in config["feeders"]
        ),
        "positive_lv906_kw_delta_vs_feeder_only": (
            primary_by_feeder["lv906"]["phicte_kw_retention_delta_vs"]["feeder_only"]
            > 1e-12
        ),
    }
    evidence_sufficient = all(criteria.values())
    decision_status = (
        "EVIDENCE_SUFFICIENT_FOR_CONFERENCE_DRAFT_WITH_LIMITATIONS"
        if evidence_sufficient
        else "EXPERIMENT_REVIEW_REQUIRED_BEFORE_PAPER_DRAFT"
    )

    predictions: list[dict[str, Any]] = []
    for index, row in enumerate(replication_rows):
        predictions.append(
            {
                "evaluation_id": row["evaluation_id"],
                "scenario_id": row["scenario_id"],
                "feeder": row["feeder"],
                "call_time": row["call_time"],
                "direction": row["direction"],
                "duration_min": row["duration_min"],
                "active_offer": row["active_offer"],
                "f_bal_kw": row["f_bal_kw"],
                "alpha_transfer": row.get("alpha_transfer"),
                "alpha_transfer_tied": row.get("alpha_transfer_tied"),
                "phase_repair_gain": (
                    float(row["alpha_transfer_tied"]) - float(row["alpha_transfer"])
                    if isinstance(row.get("alpha_transfer_tied"), (int, float))
                    and not isinstance(row.get("alpha_transfer_tied"), bool)
                    and isinstance(row.get("alpha_transfer"), (int, float))
                    and not isinstance(row.get("alpha_transfer"), bool)
                    else None
                ),
                "phicte_quantile_prediction": quantile_predictions[index],
                "phicte_factor": factor_maps["phicte"][index],
                "raw_balanced_offer_factor": factor_maps["raw_balanced_offer"][index],
                "global_derating_factor": factor_maps["global_derating"][index],
                "feeder_only_factor": factor_maps["feeder_only"][index],
                "direction_only_factor": factor_maps["direction_only"][index],
                "local_feeder_direction_duration_factor": factor_maps[
                    "local_feeder_direction_duration"
                ][index],
            }
        )

    summary = {
        "analysis_version": PROTOCOL_VERSION,
        "analysis_role": "expanded_retrospective_replication",
        "protocol_amendment": deepcopy(dict(config["protocol_amendment"])),
        "generated_at_utc": generated_at_utc,
        "blind_holdout_claim": False,
        "confirmatory_claim": False,
        "decision": {
            "status": decision_status,
            "evidence_sufficient_for_conference_draft_with_limitations": evidence_sufficient,
            "criteria": criteria,
            "paper_claim_boundary": (
                "V2.5B can strengthen retrospective replication and feeder-specific risk-retention claims, "
                "but it cannot establish a blind confirmatory or deployable 5% risk guarantee."
            ),
        },
        "scope": {
            "planned_scenarios": 48,
            "planned_work_units": 96,
            "planned_evaluations": 288,
            "primary_duration_min": primary_duration,
            "primary_planned_n": 96,
            "analysis_eligible_evaluations": len(analysis_rows),
            "noneligible_evaluations": noneligible,
            "source_selection": config["selection_rule"],
        },
        "frozen_phicte": {
            "selected_penalty": float(fitted_phicte["selected_penalty"]),
            "correction": correction,
            "quantile": DEFAULT_QUANTILE,
            "target_risk": DEFAULT_TARGET_RISK,
            "external_outcomes_used_for_fitting_or_tuning": False,
        },
        "primary_15min": {
            "policies": primary_metrics,
            "by_feeder": primary_by_feeder,
            "numerical_failure_audits": numerical_failure_count,
            "noneligible": primary_noneligible,
            "phase_aware_schedule_repair": repairability,
            "scenario_cluster_risk": scenario_risk,
            "bootstrap": bootstrap,
            "performance": performance,
        },
        "descriptive_by_duration_min": descriptive_by_duration,
        "provenance": {
            "code_commit": code_commit,
            "config_sha256": config["_config_sha256"],
            "source_manifest_sha256": config["source_manifest_sha256"],
            "development": development_provenance,
            "v2_4_source_module_git_blob_sha": frozen["source_module_git_blob_sha"],
            "v2_4_summary_git_blob_sha": frozen["source_result_summary_git_blob_sha"],
            "v2_4_predictions_git_blob_sha": frozen["source_predictions_git_blob_sha"],
        },
        "limitations": [
            "The 48 scenarios come from the previously opened V2.0 holdout pool and therefore are not a blind holdout.",
            "The PHiCTE implementation, features, penalty rule, and correction are frozen from V2.4 and use V2.2 development outcomes only.",
            "The 5% threshold remains an empirical screening target; Wilson intervals are uncertainty summaries and are not a deployment guarantee.",
            "Line thermal constraints remain outside the formal audited constraint set because traceable line ampacity is unavailable.",
            "Pooled-kW superiority is not required; feeder-specific and feeder-macro results must be reported separately.",
            "Planned cases with a physically infeasible baseline are retained and reported as coverage outcomes but excluded from transferability denominators because alpha=0 is not feasible.",
            "Phase-aware tie-break repair is a constrained redispatch diagnostic that preserves bus-time aggregate schedules; it is not full three-phase reoptimization.",
        ],
        "evaluations": deepcopy(list(replication_rows)),
    }
    return summary, predictions


def _write_outputs(
    repo_root: Path,
    summary: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Path]:
    output = repo_root / OUTPUT_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    predictions_path = output / "predictions.csv"
    if summary_path.exists() or predictions_path.exists():
        raise FileExistsError("V2.5B output artifacts already exist")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    with predictions_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PREDICTION_FIELDS, extrasaction="raise")
        writer.writeheader()
        for row in predictions:
            writer.writerow({name: row.get(name) for name in PREDICTION_FIELDS})
    return {"summary": summary_path, "predictions": predictions_path}


def _checkpoint_payload(
    *,
    config: Mapping[str, Any],
    code_commit: str,
    unit_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "config_sha256": config["_config_sha256"],
        "code_commit": code_commit,
        "blind_holdout_claim": False,
        "confirmatory_claim": False,
        "unit_results": list(unit_results),
    }


def _load_checkpoint(
    path: Path,
    *,
    config: Mapping[str, Any],
    code_commit: str,
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("protocol_version") != PROTOCOL_VERSION
        or payload.get("config_sha256") != config["_config_sha256"]
        or payload.get("code_commit") != code_commit
        or payload.get("blind_holdout_claim") is not False
        or payload.get("confirmatory_claim") is not False
        or not isinstance(payload.get("unit_results"), list)
    ):
        raise ValueError("V2.5B checkpoint identity differs")
    return [deepcopy(dict(item)) for item in payload["unit_results"]]


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    from evflex.runner import atomic_write_json

    atomic_write_json(path, payload)


def run_all_replication(
    repo_root: str | Path,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    _require_clean_worktree(root)
    config, frame = load_replication_design(root)
    units = _records(frame)
    code_commit = _git_commit(root)
    output = root / OUTPUT_DIRECTORY
    if (output / "summary.json").exists() or (output / "predictions.csv").exists():
        raise FileExistsError("V2.5B outputs already exist")
    checkpoint = root / CHECKPOINT_PATH
    if checkpoint.exists():
        if not resume:
            raise FileExistsError("V2.5B checkpoint exists; rerun with --resume")
        unit_results = _load_checkpoint(checkpoint, config=config, code_commit=code_commit)
    else:
        unit_results = []
    by_id = {str(item.get("work_unit_id")): item for item in unit_results}
    expected_ids = {str(unit["work_unit_id"]) for unit in units}
    if len(by_id) != len(unit_results) or not set(by_id).issubset(expected_ids):
        raise ValueError("V2.5B checkpoint contains unexpected work units")

    environment = {**os.environ, **THREAD_ENVIRONMENT}
    for index, unit in enumerate(units, start=1):
        unit_id = str(unit["work_unit_id"])
        if unit_id in by_id:
            print(f"[{index:03d}/096] {unit_id} RESUMED", flush=True)
            continue
        print(f"[{index:03d}/096] {unit_id}", flush=True)
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "evflex.transferability_replication_v2_5b",
                "--workers",
                "1",
                "--unit-id",
                unit_id,
            ],
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if child.returncode != 0:
            detail = "\n".join((child.stderr or child.stdout).splitlines()[-40:])
            raise RuntimeError(f"V2.5B child {unit_id} failed:\n{detail}")
        lines = [
            line.removeprefix("V25B_REPLICATION_UNIT_JSON=")
            for line in child.stdout.splitlines()
            if line.startswith("V25B_REPLICATION_UNIT_JSON=")
        ]
        if len(lines) != 1:
            raise ValueError(f"V2.5B child {unit_id} emitted no unique result")
        result = json.loads(lines[0])
        if result.get("work_unit_id") != unit_id or result.get("status") != "SUCCESS":
            raise ValueError(f"V2.5B child {unit_id} result is invalid")
        unit_results.append(result)
        by_id[unit_id] = result
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            checkpoint,
            _checkpoint_payload(
                config=config,
                code_commit=code_commit,
                unit_results=unit_results,
            ),
        )
        print("  SUCCESS", flush=True)

    ordered = [by_id[str(unit["work_unit_id"])] for unit in units]
    rows = [
        deepcopy(evaluation)
        for unit_result in ordered
        for evaluation in unit_result["evaluations"]
    ]
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary, predictions = build_replication_analysis(
        root,
        rows,
        config=config,
        code_commit=code_commit,
        generated_at_utc=generated,
    )
    paths = _write_outputs(root, summary, predictions)
    checkpoint.unlink(missing_ok=True)
    print(f"WROTE {paths['summary'].relative_to(root)}", flush=True)
    print(f"WROTE {paths['predictions'].relative_to(root)}", flush=True)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the V2.5B expanded retrospective PHiCTE replication."
    )
    parser.add_argument("--workers", type=int, default=1)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--unit-id")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: str | Path | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.workers != 1:
        raise SystemExit("--workers must be exactly 1")
    if args.resume and args.unit_id:
        raise SystemExit("--resume is only valid with --all")
    root = (
        Path(repo_root).resolve(strict=False)
        if repo_root is not None
        else Path(__file__).resolve().parents[2]
    )
    if args.unit_id:
        config, frame = load_replication_design(root)
        matches = [
            unit for unit in _records(frame)
            if unit["work_unit_id"] == args.unit_id
        ]
        if len(matches) != 1:
            raise SystemExit(f"unknown V2.5B work unit: {args.unit_id}")
        result = execute_replication_unit(root, matches[0], config)
        print(
            "V25B_REPLICATION_UNIT_JSON="
            + json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            flush=True,
        )
        return 0
    summary = run_all_replication(root, resume=bool(args.resume))
    print(
        json.dumps(
            {
                "status": summary["decision"]["status"],
                "blind_holdout_claim": False,
                "confirmatory_claim": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
