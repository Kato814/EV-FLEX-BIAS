from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence


_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)
THREAD_ENVIRONMENT = {name: "1" for name in _THREAD_VARIABLES}
for _name, _value in THREAD_ENVIRONMENT.items():
    os.environ[_name] = _value

import pandas as pd


PROTOCOL_VERSION = (
    "EV-FLEX-BIAS-V2.3A-TRANSFERABILITY-LOCKED-EXTERNAL-VALIDATION"
)
CONFIG_RELATIVE_PATH = Path(
    "config/transferability_external_validation_v2_3.json"
)
OUTPUT_DIRECTORY = Path("results/transferability_external_validation_v2_3")
CHECKPOINT_PATH = Path(
    "state/runtime/transferability_external_validation_v2_3/checkpoint.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("external-validation protocol version is not frozen")
    if config.get("source_protocol_version") != "EV-FLEX-BIAS-V2.0":
        raise ValueError("external-validation source protocol is not frozen")
    if config.get("source_manifest") != "manifests/core_work_units_v2_0.csv":
        raise ValueError("external-validation source manifest is not frozen")
    if config.get("source_data_role") != "holdout":
        raise ValueError("external-validation source role must be the prior holdout")
    if config.get("blind_holdout_claim") is not False:
        raise ValueError("external validation must not claim a blind holdout")
    if config.get("prior_v2_0_holdout_open_count") != 1:
        raise ValueError("prior V2.0 holdout opening must be acknowledged")
    if config.get("design_role") != "locked_external_validation":
        raise ValueError("external-validation design role is not frozen")
    if config.get("workers") != 1 or config.get("numeric_threads") != 1:
        raise ValueError("external validation must use one worker and one thread")
    if config.get("directions") != ["inc", "dec"]:
        raise ValueError("external-validation directions are not frozen")
    if config.get("durations_min") != [15, 30, 60]:
        raise ValueError("external-validation durations are not frozen")
    if config.get("primary_duration_min") != 15:
        raise ValueError("external-validation primary duration must remain 15 minutes")
    if config.get("longer_duration_policy") != (
        "descriptive_offer_coverage_only"
    ):
        raise ValueError("external-validation longer-duration policy differs")
    amendment = config.get("protocol_amendment")
    if (
        not isinstance(amendment, dict)
        or amendment.get("previous_stopped_commit")
        != "994ca668e32815b24c0db62a08e7341d74648313"
        or amendment.get("previous_completed_units") != 16
        or amendment.get("observed_status") != "INACTIVE_OFFER"
        or amendment.get("selection_changed") is not False
        or amendment.get("scientific_thresholds_changed") is not False
        or amendment.get("restart_from_zero") is not True
    ):
        raise ValueError("external-validation protocol amendment is not frozen")
    if config.get("feeders") != ["ieee13", "lv906"]:
        raise ValueError("external-validation feeders are not frozen")
    if config.get("call_times") != ["19:00", "00:00", "02:00", "06:00"]:
        raise ValueError("external-validation call times are not frozen")
    scenarios = config.get("scenario_ids")
    if (
        not isinstance(scenarios, list)
        or len(scenarios) != 16
        or len(set(scenarios)) != 16
    ):
        raise ValueError("external validation requires 16 unique scenarios")
    suffixes = {int(str(value).rsplit("_", 1)[1]) for value in scenarios}
    if suffixes != {25, 32}:
        raise ValueError("external validation must use the frozen ID extremes")
    constraints = config.get("formal_constraints")
    if not isinstance(constraints, dict) or constraints.get(
        "line_thermal_in_scope"
    ) is not False:
        raise ValueError("external-validation line thermal scope must remain false")
    if config.get("scientific_validation_thresholds") != {
        "cell_failure_status_agreement_min": 0.75,
        "cell_median_spearman_rho_min": 0.6,
        "cell_median_alpha_mae_max": 0.15,
        "require_safe_and_bad_each_feeder": True,
    }:
        raise ValueError("external-validation scientific thresholds are not frozen")


def load_external_validation_design(
    repo_root: str | Path,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Load identities only for the locked retrospective validation cohort."""

    root = Path(repo_root).resolve(strict=True)
    config_path = root / CONFIG_RELATIVE_PATH
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)

    unlock_path = root / str(config["prior_v2_0_holdout_open_record"])
    if _sha256(unlock_path) != config["prior_v2_0_holdout_open_record_sha256"]:
        raise ValueError("prior V2.0 holdout-open record hash differs")
    unlock = json.loads(unlock_path.read_text(encoding="utf-8"))
    if unlock.get("status") != "UNLOCKED" or unlock.get("holdout_open_count") != 1:
        raise ValueError("prior V2.0 holdout-open record is inconsistent")

    source_path = root / str(config["source_manifest"])
    if _sha256(source_path) != config["source_manifest_sha256"]:
        raise ValueError("external-validation source manifest hash differs")
    source = pd.read_csv(source_path)
    scenario_ids = list(config["scenario_ids"])
    selected = source[source["scenario_id"].isin(scenario_ids)].copy()
    if len(selected) != 32 or set(selected["scenario_id"]) != set(scenario_ids):
        raise ValueError("external-validation source identities are incomplete")
    if set(selected["protocol_version"]) != {config["source_protocol_version"]}:
        raise ValueError("external-validation source protocol differs")
    if set(selected["data_role"]) != {config["source_data_role"]}:
        raise ValueError("external-validation source rows are not prior holdout rows")
    if set(selected["holdout_access"]) != {"sealed"}:
        raise ValueError("external-validation source access labels differ")

    source_by_key = {
        (str(row.scenario_id), str(row.direction)): row
        for row in selected.itertuples(index=False)
    }
    if len(source_by_key) != 32:
        raise ValueError("external-validation source identities are not unique")

    durations = [int(value) for value in config["durations_min"]]
    records: list[dict[str, Any]] = []
    for scenario_id in scenario_ids:
        for direction in config["directions"]:
            source_row = source_by_key[(scenario_id, direction)]
            unit_id = f"v23_external_{scenario_id}__{direction}"
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
                            f"v23_external_{scenario_id}__{direction}__{duration}m"
                            for duration in durations
                        ],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "status": "PENDING",
                }
            )
    frame = pd.DataFrame.from_records(records)
    if len(frame) != 32 or frame["work_unit_id"].duplicated().any():
        raise ValueError("external-validation design construction failed")
    config["_config_sha256"] = _sha256(config_path)
    return config, frame


def _validated_evaluations(
    evaluations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    role: str,
    allow_inactive: bool = False,
) -> list[dict[str, Any]]:
    rows = [deepcopy(dict(row)) for row in evaluations]
    ids = [str(row.get("evaluation_id")) for row in rows]
    if len(rows) != 96 or len(set(ids)) != 96:
        raise ValueError(f"{role} comparison source must contain 96 unique rows")
    for row in rows:
        alpha = row.get("alpha_transfer")
        audit = row.get("alpha_path_audit")
        valid_active = bool(
            row.get("data_role") == role
            and row.get("status") == "SUCCESS"
            and row.get("scientific_status") == "VALID"
            and row.get("alpha_path_scientific_valid") is True
            and row.get("alpha_path_status") == "VALID"
            and not isinstance(alpha, bool)
            and isinstance(alpha, (int, float))
            and math.isfinite(float(alpha))
            and 0.0 <= float(alpha) <= 1.0
            and isinstance(audit, dict)
            and audit.get("numerical_failure_audits") == 0
        )
        valid_inactive = bool(
            allow_inactive
            and row.get("data_role") == role
            and row.get("status") == "INACTIVE_OFFER"
            and row.get("scientific_status") == "NOT_APPLICABLE_INACTIVE"
            and row.get("active_offer") is False
            and row.get("eligible_for_scientific_denominator") is False
            and alpha is None
            and row.get("alpha_path_scientific_valid") is None
            and row.get("alpha_path_status") is None
            and audit is None
        )
        if not valid_active and not valid_inactive:
            raise ValueError(f"{role} comparison row is invalid: {row.get('evaluation_id')}")
        row["_comparison_eligible"] = valid_active
        if valid_active:
            row["alpha_transfer"] = float(alpha)
    cell_counts = pd.DataFrame(rows).groupby(
        ["feeder", "direction", "call_time"]
    )["evaluation_id"].count()
    if len(cell_counts) != 16 or set(int(value) for value in cell_counts) != {6}:
        raise ValueError(f"{role} comparison source must cover 16 six-row cells")
    return rows


def build_external_validation_summary(
    development_evaluations: list[dict[str, Any]],
    external_evaluations: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    code_commit: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Compare the locked external cohort with development at the 16-cell level."""

    _validate_config(config)
    development = _validated_evaluations(
        development_evaluations, role="development_transferability"
    )
    external = _validated_evaluations(
        external_evaluations,
        role="locked_external_validation",
        allow_inactive=True,
    )
    if len(code_commit) != 40 or any(
        character not in "0123456789abcdef" for character in code_commit
    ):
        raise ValueError("external-validation code commit is invalid")

    def cells(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
        grouped: dict[tuple[str, str, str], list[float]] = {}
        for row in rows:
            key = (
                str(row["feeder"]),
                str(row["direction"]),
                str(row["call_time"]),
            )
            grouped.setdefault(key, []).append(float(row["alpha_transfer"]))
        return {
            key: {
                "n": len(values),
                "bad_count": sum(value < 0.95 for value in values),
                "safe_count": sum(
                    math.isclose(value, 1.0, rel_tol=0.0, abs_tol=1e-12)
                    for value in values
                ),
                "median_alpha": float(statistics.median(values)),
                "has_bad": any(value < 0.95 for value in values),
            }
            for key, values in grouped.items()
        }

    primary_duration = int(config["primary_duration_min"])
    development_primary = [
        row
        for row in development
        if int(row["duration_min"]) == primary_duration
        and row["_comparison_eligible"]
    ]
    external_primary = [
        row
        for row in external
        if int(row["duration_min"]) == primary_duration
        and row["_comparison_eligible"]
    ]
    development_cells = cells(development_primary)
    external_cells = cells(external_primary)
    primary_coverage_complete = bool(
        len(development_primary) == 32
        and len(external_primary) == 32
        and len(development_cells) == 16
        and len(external_cells) == 16
        and set(development_cells) == set(external_cells)
        and {value["n"] for value in development_cells.values()} == {2}
        and {value["n"] for value in external_cells.values()} == {2}
    )
    keys = sorted(development_cells)
    if primary_coverage_complete:
        development_medians = [
            development_cells[key]["median_alpha"] for key in keys
        ]
        external_medians = [external_cells[key]["median_alpha"] for key in keys]
        agreement = sum(
            development_cells[key]["has_bad"]
            == external_cells[key]["has_bad"]
            for key in keys
        ) / len(keys)
        development_ranks = pd.Series(development_medians).rank(method="average")
        external_ranks = pd.Series(external_medians).rank(method="average")
        if development_ranks.nunique() < 2 or external_ranks.nunique() < 2:
            rho = 0.0
        else:
            raw_rho = development_ranks.corr(external_ranks)
            rho = float(raw_rho) if pd.notna(raw_rho) else 0.0
        median_alpha_mae = sum(
            abs(
                development_cells[key]["median_alpha"]
                - external_cells[key]["median_alpha"]
            )
            for key in keys
        ) / len(keys)
    else:
        agreement = None
        rho = None
        median_alpha_mae = None
    safe_and_bad_each_feeder = all(
        any(
            row["feeder"] == feeder and float(row["alpha_transfer"]) < 0.95
            for row in external_primary
        )
        and any(
            row["feeder"] == feeder
            and math.isclose(
                float(row["alpha_transfer"]), 1.0, rel_tol=0.0, abs_tol=1e-12
            )
            for row in external_primary
        )
        for feeder in ("ieee13", "lv906")
    ) if primary_coverage_complete else False

    thresholds = config["scientific_validation_thresholds"]
    threshold_checks = {
        "cell_failure_status_agreement": (
            primary_coverage_complete
            and agreement is not None
            and agreement >= thresholds["cell_failure_status_agreement_min"]
        ),
        "cell_median_spearman_rho": (
            primary_coverage_complete
            and rho is not None
            and rho >= thresholds["cell_median_spearman_rho_min"]
        ),
        "cell_median_alpha_mae": (
            primary_coverage_complete
            and median_alpha_mae is not None
            and median_alpha_mae <= thresholds["cell_median_alpha_mae_max"]
        ),
        "safe_and_bad_present_each_feeder": (
            primary_coverage_complete
            and (
                safe_and_bad_each_feeder
                if thresholds["require_safe_and_bad_each_feeder"]
                else True
            )
        ),
    }
    cell_rows = [
        {
            "cell_id": f"{key[0]}__{key[1]}__{key[2].replace(':', '')}",
            "feeder": key[0],
            "direction": key[1],
            "call_time": key[2],
            "development": development_cells[key],
            "external": external_cells.get(key),
            "failure_status_agrees": (
                development_cells[key]["has_bad"]
                == external_cells[key]["has_bad"]
                if key in external_cells
                else None
            ),
            "median_alpha_absolute_difference": (
                abs(
                    development_cells[key]["median_alpha"]
                    - external_cells[key]["median_alpha"]
                )
                if key in external_cells
                else None
            ),
        }
        for key in keys
    ]
    support = (
        "NOT_EVALUABLE_PRIMARY_COVERAGE"
        if not primary_coverage_complete
        else (
            "SUPPORTED_ON_LOCKED_RETROSPECTIVE_EXTERNAL_COHORT"
            if all(threshold_checks.values())
            else "NOT_FULLY_SUPPORTED"
        )
    )
    numerical_failures = sum(
        int(row["alpha_path_audit"]["numerical_failure_audits"])
        for row in external
        if row["_comparison_eligible"]
    )
    coverage_by_duration: dict[str, dict[str, Any]] = {}
    for duration in config["durations_min"]:
        duration_rows = [
            row for row in external if int(row["duration_min"]) == int(duration)
        ]
        active_count = sum(row["_comparison_eligible"] for row in duration_rows)
        inactive_count = sum(
            row["status"] == "INACTIVE_OFFER" for row in duration_rows
        )
        coverage_by_duration[str(duration)] = {
            "planned": len(duration_rows),
            "active": active_count,
            "inactive": inactive_count,
            "active_fraction": active_count / len(duration_rows),
        }
    external_output = deepcopy(external)
    for row in external_output:
        row.pop("_comparison_eligible", None)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": "SUCCESS",
        "machine_execution_gate": "PASS",
        "scientific_support_status": support,
        "generated_at_utc": generated_at_utc,
        "blind_holdout_claim": False,
        "validation_type": "locked_retrospective_external_validation",
        "limitations": [
            "The source cohort belonged to the previously opened V2.0 holdout.",
            "This is independent of V2.2 development selection but is not an untouched blind holdout.",
            "After the first legitimate inactive longer-duration offer stopped V2.3, V2.3A restarted from zero and restricted the primary comparison to 15 minutes.",
            "The unchanged thresholds apply only to the complete 15-minute primary comparison; 30- and 60-minute offers are descriptive coverage only.",
            "Mechanism-family prevalence is outside this validation stage.",
        ],
        "protocol_amendment": deepcopy(config["protocol_amendment"]),
        "selection_design": {
            "rule": config["selection_rule"],
            "source_outcome_fields_used": False,
            "scenario_suffixes": [25, 32],
        },
        "primary_estimand": {
            "duration_min": primary_duration,
            "planned_evaluations": 32,
            "planned_rows_per_cell": 2,
            "coverage_complete": primary_coverage_complete,
            "longer_duration_policy": config["longer_duration_policy"],
        },
        "offer_coverage": {
            "planned": len(external),
            "active": sum(row["_comparison_eligible"] for row in external),
            "inactive": sum(
                row["status"] == "INACTIVE_OFFER" for row in external
            ),
            "by_duration_min": coverage_by_duration,
        },
        "scientific_validation_thresholds": deepcopy(thresholds),
        "cell_pattern_comparison": {
            "failure_status_agreement": agreement,
            "median_alpha_spearman_rho": rho,
            "median_alpha_mae": median_alpha_mae,
            "safe_and_bad_present_each_feeder": safe_and_bad_each_feeder,
            "threshold_checks": threshold_checks,
        },
        "counts": {
            "development_evaluations": len(development),
            "external_evaluations": len(external),
            "development_primary_evaluations": len(development_primary),
            "external_primary_evaluations": len(external_primary),
            "external_active_evaluations": sum(
                row["_comparison_eligible"] for row in external
            ),
            "external_inactive_offers": sum(
                row["status"] == "INACTIVE_OFFER" for row in external
            ),
            "comparison_cells": len(keys),
            "development_failing_cells": sum(
                bool(value["has_bad"]) for value in development_cells.values()
            ),
            "external_failing_cells": sum(
                bool(value["has_bad"]) for value in external_cells.values()
            ),
            "external_numerical_failure_audits": numerical_failures,
        },
        "provenance": {
            "code_commit": code_commit,
            "config_sha256": config["_config_sha256"],
            "source_manifest_sha256": config["source_manifest_sha256"],
            "prior_v2_0_holdout_open_record_sha256": config[
                "prior_v2_0_holdout_open_record_sha256"
            ],
            "prior_v2_0_holdout_open_count": 1,
        },
        "resource_policy": {
            "workers": 1,
            "numeric_threads": 1,
            "gpu_used": False,
            "gpu_reason": "OpenDSS three-phase power flow uses the CPU path",
        },
        "cells": cell_rows,
        "evaluations": external_output,
    }


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    commit = completed.stdout.strip()
    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ValueError("external-validation Git commit is invalid")
    return commit


def _require_clean_worktree(repo_root: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.stdout.strip():
        raise ValueError("external validation requires a clean committed worktree")


def execute_external_validation_unit(
    repo_root: str | Path,
    unit: Mapping[str, Any],
    config: dict[str, Any],
    *,
    evaluator: Callable[..., list[dict[str, Any]]] | None = None,
    code_commit: str | None = None,
) -> dict[str, Any]:
    """Evaluate one locked external work unit entirely in memory."""

    root = Path(repo_root).resolve(strict=True)
    expected_ids = json.loads(str(unit["evaluation_ids"]))
    if not isinstance(expected_ids, list) or len(expected_ids) != 3:
        raise ValueError("external-validation unit must contain three evaluation IDs")
    if evaluator is None:
        from evflex.pilot import evaluate_pilot_work_unit

        evaluator = evaluate_pilot_work_unit
    evaluations = evaluator(root, unit, config=config)
    if (
        not isinstance(evaluations, list)
        or len(evaluations) != 3
        or [row.get("evaluation_id") for row in evaluations] != expected_ids
    ):
        raise ValueError("external-validation evaluator returned different identities")
    status_counts: dict[str, int] = {}
    for row in evaluations:
        identity_valid = bool(
            row.get("work_unit_id") == unit["work_unit_id"]
            and row.get("protocol_version") == config["protocol_version"]
            and row.get("data_role") == config["design_role"]
        )
        status = str(row.get("status"))
        valid_active = bool(
            status == "SUCCESS"
            and row.get("scientific_status") == "VALID"
            and row.get("alpha_path_scientific_valid") is True
            and row.get("alpha_path_status") == "VALID"
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
        if not identity_valid or (not valid_active and not valid_inactive):
            raise ValueError(
                "external-validation evaluation is invalid: "
                f"{row.get('evaluation_id')}"
            )
        status_counts[status] = status_counts.get(status, 0) + 1
    commit = code_commit or _git_commit(root)
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
            "code_commit": commit,
            "config_sha256": config["_config_sha256"],
            "source_manifest_sha256": config["source_manifest_sha256"],
            "prior_v2_0_holdout_open_count": 1,
            "blind_holdout_claim": False,
            "source_outcomes_used_for_selection": False,
            "output_namespace": OUTPUT_DIRECTORY.as_posix(),
        },
        "evaluations": deepcopy(evaluations),
    }


def _csv_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    evaluations = summary.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != 96:
        raise ValueError("external summary must contain 96 evaluations")
    rows: list[dict[str, Any]] = []
    for evaluation in evaluations:
        if not isinstance(evaluation, Mapping):
            raise ValueError("external summary evaluation is invalid")
        audit = evaluation.get("alpha_path_audit")
        alpha_value = evaluation.get("alpha_transfer")
        alpha = (
            float(alpha_value)
            if isinstance(alpha_value, (int, float))
            and not isinstance(alpha_value, bool)
            else None
        )
        rows.append(
            {
                "evaluation_id": evaluation.get("evaluation_id"),
                "work_unit_id": evaluation.get("work_unit_id"),
                "scenario_id": evaluation.get("scenario_id"),
                "scenario_seed": evaluation.get("scenario_seed"),
                "feeder": evaluation.get("feeder"),
                "direction": evaluation.get("direction"),
                "call_time": evaluation.get("call_time"),
                "duration_min": evaluation.get("duration_min"),
                "source_duration_min": evaluation.get("source_duration_min"),
                "alpha_transfer": alpha,
                "bad_alpha_lt_0_95": (
                    alpha < 0.95 if alpha is not None else None
                ),
                "full_transfer_alpha_eq_1": (
                    math.isclose(
                        alpha, 1.0, rel_tol=0.0, abs_tol=1e-12
                    )
                    if alpha is not None
                    else None
                ),
                "active_offer": evaluation.get("active_offer"),
                "status": evaluation.get("status"),
                "scientific_status": evaluation.get("scientific_status"),
                "alpha_path_status": evaluation.get("alpha_path_status"),
                "numerical_failure_audits": (
                    audit.get("numerical_failure_audits")
                    if isinstance(audit, Mapping)
                    else None
                ),
                "schedule_sha256": evaluation.get("schedule_sha256"),
                "bus_phase_time_sha256": evaluation.get(
                    "bus_phase_time_sha256"
                ),
                "baseline_schedule_sha256": evaluation.get(
                    "baseline_schedule_sha256"
                ),
                "blind_holdout_claim": False,
            }
        )
    return rows


def write_external_validation_artifacts(
    repo_root: str | Path, summary: Mapping[str, Any]
) -> dict[str, Path]:
    """Atomically retain only one JSON and one CSV external-validation result."""

    from evflex.runner import atomic_write_json

    root = Path(repo_root).resolve(strict=False)
    output = root / OUTPUT_DIRECTORY
    json_path = output / "summary.json"
    csv_path = output / "summary.csv"
    if json_path.exists() or csv_path.exists():
        raise FileExistsError(
            "external-validation summary artifacts already exist"
        )
    rows = _csv_rows(summary)
    atomic_write_json(json_path, summary)
    output.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=csv_path.name, suffix=".tmp", dir=output
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, csv_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"json": json_path, "csv": csv_path}


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        unit = {
            key: (None if pd.isna(value) else value) for key, value in raw.items()
        }
        unit["scenario_seed"] = int(unit["scenario_seed"])
        unit["prior_holdout_open_acknowledged"] = bool(
            unit["prior_holdout_open_acknowledged"]
        )
        records.append(unit)
    return records


def _checkpoint_payload(
    *,
    config: Mapping[str, Any],
    code_commit: str,
    unit_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "config_sha256": config["_config_sha256"],
        "code_commit": code_commit,
        "blind_holdout_claim": False,
        "unit_results": unit_results,
    }


def _load_checkpoint(
    path: Path, *, config: Mapping[str, Any], code_commit: str
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("protocol_version") != PROTOCOL_VERSION
        or payload.get("config_sha256") != config["_config_sha256"]
        or payload.get("code_commit") != code_commit
        or payload.get("blind_holdout_claim") is not False
        or not isinstance(payload.get("unit_results"), list)
    ):
        raise ValueError("external-validation checkpoint identity differs")
    unit_results = payload["unit_results"]
    for item in unit_results:
        if not isinstance(item, Mapping):
            raise ValueError(
                "external-validation checkpoint unit provenance differs"
            )
        provenance = item.get("run_provenance")
        if (
            item.get("status") != "SUCCESS"
            or not isinstance(provenance, Mapping)
            or provenance.get("code_commit") != code_commit
            or provenance.get("config_sha256") != config["_config_sha256"]
            or provenance.get("blind_holdout_claim") is not False
            or not isinstance(item.get("evaluations"), list)
        ):
            raise ValueError(
                "external-validation checkpoint unit provenance differs"
            )
    return [deepcopy(dict(item)) for item in unit_results]


def run_all_external_validation(
    repo_root: str | Path, *, resume: bool = False
) -> dict[str, Any]:
    """Run 32 isolated units and compare their 96 evaluations with development."""

    from evflex.runner import atomic_write_json
    from evflex.transferability_witness_v2_2 import load_archived_evaluations

    root = Path(repo_root).resolve(strict=True)
    _require_clean_worktree(root)
    output = root / OUTPUT_DIRECTORY
    if (output / "summary.json").exists() or (output / "summary.csv").exists():
        raise FileExistsError("external-validation summary artifacts already exist")
    config, frame = load_external_validation_design(root)
    units = _records(frame)
    code_commit = _git_commit(root)
    checkpoint = root / CHECKPOINT_PATH
    if checkpoint.exists():
        if not resume:
            raise FileExistsError("external-validation checkpoint requires --resume")
        unit_results = _load_checkpoint(
            checkpoint, config=config, code_commit=code_commit
        )
    else:
        unit_results = []
    by_id = {str(item.get("work_unit_id")): item for item in unit_results}
    expected_ids = {str(unit["work_unit_id"]) for unit in units}
    if len(by_id) != len(unit_results) or not set(by_id).issubset(expected_ids):
        raise ValueError("external-validation checkpoint contains unexpected units")

    environment = {**os.environ, **THREAD_ENVIRONMENT}
    for index, unit in enumerate(units, start=1):
        unit_id = str(unit["work_unit_id"])
        if unit_id in by_id:
            print(f"[{index:02d}/32] {unit_id} RESUMED", flush=True)
            continue
        print(f"[{index:02d}/32] {unit_id}", flush=True)
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "evflex.transferability_external_validation_v2_3",
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
            detail = "\n".join((child.stderr or child.stdout).splitlines()[-30:])
            raise RuntimeError(f"external-validation child {unit_id} failed:\n{detail}")
        lines = [
            line.removeprefix("EXTERNAL_VALIDATION_UNIT_JSON=")
            for line in child.stdout.splitlines()
            if line.startswith("EXTERNAL_VALIDATION_UNIT_JSON=")
        ]
        if len(lines) != 1:
            raise ValueError(f"external-validation child {unit_id} emitted no result")
        result = json.loads(lines[0])
        if result.get("work_unit_id") != unit_id or result.get("status") != "SUCCESS":
            raise ValueError(f"external-validation child {unit_id} result is invalid")
        unit_results.append(result)
        by_id[unit_id] = result
        atomic_write_json(
            checkpoint,
            _checkpoint_payload(
                config=config,
                code_commit=code_commit,
                unit_results=unit_results,
            ),
        )
        print("  SUCCESS", flush=True)

    ordered_results = [by_id[str(unit["work_unit_id"])] for unit in units]
    external = [
        deepcopy(evaluation)
        for result in ordered_results
        for evaluation in result["evaluations"]
    ]
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = build_external_validation_summary(
        load_archived_evaluations(root),
        external,
        config=config,
        code_commit=code_commit,
        generated_at_utc=generated,
    )
    paths = write_external_validation_artifacts(root, summary)
    checkpoint.unlink(missing_ok=True)
    print(f"WROTE {paths['json'].relative_to(root)}", flush=True)
    print(f"WROTE {paths['csv'].relative_to(root)}", flush=True)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run locked retrospective V2.3 external validation."
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
        config, frame = load_external_validation_design(root)
        units = _records(frame)
        matches = [
            unit for unit in units if unit["work_unit_id"] == args.unit_id
        ]
        if len(matches) != 1:
            raise SystemExit(f"unknown external-validation unit: {args.unit_id}")
        result = execute_external_validation_unit(root, matches[0], config)
        print(
            "EXTERNAL_VALIDATION_UNIT_JSON="
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
    summary = run_all_external_validation(root, resume=bool(args.resume))
    print(
        json.dumps(
            {
                "machine_execution_gate": summary["machine_execution_gate"],
                "scientific_support_status": summary[
                    "scientific_support_status"
                ],
                "blind_holdout_claim": summary["blind_holdout_claim"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
