from __future__ import annotations

import json
from pathlib import Path

from evflex.transferability_replication_v2_5b import (
    _expected_scenario_ids,
    _validate_config,
    load_replication_design,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v25b_config_is_frozen_and_selects_48_scenarios() -> None:
    config = json.loads(
        (REPO_ROOT / "config/transferability_replication_v2_5b.json").read_text(
            encoding="utf-8"
        )
    )
    _validate_config(config)
    scenarios = _expected_scenario_ids(config)
    assert len(scenarios) == 48
    assert len(set(scenarios)) == 48
    assert all(int(value.rsplit("_", 1)[1]) in {26, 27, 28, 29, 30, 31} for value in scenarios)
    assert all(not value.endswith("_25") and not value.endswith("_32") for value in scenarios)
    rules = config["primary_evidence_rules"]
    assert rules["minimum_primary_risk_denominator_n"] == 73
    assert rules["minimum_primary_risk_denominator_n_per_feeder"] == 24
    assert rules["phicte_empirical_material_false_safe_rate_max_each_feeder"] == 0.05
    assert rules["require_zero_phicte_strict_bound_exceedance"] is True
    assert rules["require_zero_phicte_strict_bound_exceedance_each_feeder"] is True
    amendment = config["protocol_amendment"]
    assert amendment["execution_started_before_amendment"] is False
    assert amendment["v2_5b_outcomes_observed_before_amendment"] is False


def test_v25b_design_resolves_exactly_96_paired_work_units() -> None:
    config, frame = load_replication_design(REPO_ROOT)
    assert config["blind_holdout_claim"] is False
    assert config["confirmatory_claim"] is False
    assert len(frame) == 96
    assert frame["work_unit_id"].is_unique
    assert frame["scenario_id"].nunique() == 48
    assert set(frame["direction"]) == {"inc", "dec"}
    assert set(frame.groupby("scenario_id")["direction"].nunique()) == {2}
    assert set(frame["source_data_role"]) == {"holdout"}
    assert set(frame["source_holdout_access"]) == {"sealed"}
    for value in frame["evaluation_ids"]:
        ids = json.loads(value)
        assert len(ids) == 3
        assert ids[0].endswith("__15m")
        assert ids[1].endswith("__30m")
        assert ids[2].endswith("__60m")


def _synthetic_replication_rows() -> list[dict[str, object]]:
    from copy import deepcopy

    from evflex.transferability_baseline_comparison_v2_3 import load_project_evaluations

    development, _external, _provenance = load_project_evaluations(REPO_ROOT)
    by_scenario: dict[str, list[dict[str, object]]] = {}
    for row in development:
        by_scenario.setdefault(str(row["scenario_id"]), []).append(deepcopy(row))
    rows: list[dict[str, object]] = []
    for replica in range(3):
        for source_scenario, source_rows in sorted(by_scenario.items()):
            synthetic_scenario = f"synthetic_{replica}_{source_scenario}"
            for source in source_rows:
                row = deepcopy(source)
                row["scenario_id"] = synthetic_scenario
                row["evaluation_id"] = f"synthetic_{replica}_{source['evaluation_id']}"
                row["work_unit_id"] = f"synthetic_{replica}_{source.get('work_unit_id', source_scenario)}"
                rows.append(row)
    return rows


def test_v25b_analysis_pipeline_runs_without_external_outcome_tuning() -> None:
    from evflex.transferability_replication_v2_5b import build_replication_analysis

    config, _frame = load_replication_design(REPO_ROOT)
    rows = _synthetic_replication_rows()
    assert len(rows) == 288
    assert len({row["scenario_id"] for row in rows}) == 48

    summary, predictions = build_replication_analysis(
        REPO_ROOT,
        rows,
        config=config,
        code_commit="1" * 40,
        generated_at_utc="2026-08-12T00:00:00Z",
    )

    assert summary["analysis_version"] == config["protocol_version"]
    assert summary["blind_holdout_claim"] is False
    assert summary["confirmatory_claim"] is False
    assert summary["frozen_phicte"]["external_outcomes_used_for_fitting_or_tuning"] is False
    assert len(predictions) == 288
    primary = [row for row in predictions if row["duration_min"] == 15]
    assert len(primary) == 96
    assert set(summary["primary_15min"]["by_feeder"]) == {"ieee13", "lv906"}
    assert all(
        summary["primary_15min"]["by_feeder"][feeder]["planned_n"] == 48
        for feeder in ("ieee13", "lv906")
    )
    assert set(summary["decision"]["criteria"]) == {
        "minimum_active_primary_n",
        "minimum_primary_risk_denominator_n",
        "minimum_primary_risk_denominator_n_each_feeder",
        "phicte_empirical_material_risk",
        "phicte_empirical_material_risk_each_feeder",
        "zero_phicte_strict_bound_exceedance",
        "zero_phicte_strict_bound_exceedance_each_feeder",
        "no_numerical_failure_audits",
        "phicte_pareto_nondominated_each_feeder",
        "positive_kw_delta_vs_global_each_feeder",
        "positive_kw_delta_vs_direction_only_each_feeder",
        "positive_lv906_kw_delta_vs_feeder_only",
    }


def test_v25b_explicit_baseline_ineligibility_is_retained_not_fatal() -> None:
    from evflex.transferability_replication_v2_5b import _validate_unit_evaluations

    config, frame = load_replication_design(REPO_ROOT)
    unit = frame.iloc[0].to_dict()
    expected_ids = json.loads(unit["evaluation_ids"])
    rows = []
    for duration, evaluation_id in zip((15, 30, 60), expected_ids, strict=True):
        rows.append(
            {
                "evaluation_id": evaluation_id,
                "work_unit_id": unit["work_unit_id"],
                "protocol_version": config["protocol_version"],
                "scenario_id": unit["scenario_id"],
                "data_role": config["design_role"],
                "duration_min": duration,
                "status": "SCHEDULE_SOLVER_INVALID",
                "scientific_status": "INVALID_SCHEDULE",
                "baseline_status": "BASELINE_PHYSICAL_INVALID",
                "active_offer": None,
                "eligible_for_scientific_denominator": False,
                "alpha_transfer": None,
                "alpha_path_scientific_valid": None,
                "alpha_path_status": None,
                "alpha_path_audit": None,
            }
        )
    _validate_unit_evaluations(rows, unit=unit, config=config)
