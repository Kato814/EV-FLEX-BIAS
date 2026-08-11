from __future__ import annotations

import csv
import json
import math

import pytest


def _row(
    evaluation_id: str,
    *,
    feeder: str = "ieee13",
    direction: str = "inc",
    duration_min: int = 15,
    alpha_transfer: float | None = 1.0,
    f_bal_kw: float = 100.0,
    active_offer: bool = True,
) -> dict[str, object]:
    return {
        "evaluation_id": evaluation_id,
        "feeder": feeder,
        "direction": direction,
        "duration_min": duration_min,
        "alpha_transfer": alpha_transfer,
        "f_bal_kw": f_bal_kw,
        "active_offer": active_offer,
        "eligible_for_scientific_denominator": active_offer,
        "status": "SUCCESS" if active_offer else "INACTIVE_OFFER",
        "scientific_status": (
            "VALID" if active_offer else "NOT_APPLICABLE_INACTIVE"
        ),
        "alpha_path_status": "VALID" if active_offer else None,
    }


def test_factor_is_largest_value_meeting_five_percent_development_risk() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import (
        fit_maximum_retention_factor,
        is_material_false_safe,
    )

    alphas = [0.50, 0.60, *([1.0] * 18)]
    factor = fit_maximum_retention_factor(alphas, maximum_risk=0.05)

    assert factor == pytest.approx(0.60 / 0.95)
    assert sum(is_material_false_safe(alpha, factor) for alpha in alphas) == 1
    assert not is_material_false_safe(0.60, factor)


def test_five_policy_definitions_use_only_declared_grouping_fields() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import (
        POLICY_SPECS,
    )

    assert POLICY_SPECS == {
        "raw_balanced_offer": None,
        "global_derating": (),
        "feeder_only": ("feeder",),
        "direction_only": ("direction",),
        "local_feeder_direction_duration": (
            "feeder",
            "direction",
            "duration_min",
        ),
    }


def test_unseen_group_abstains_instead_of_borrowing_external_outcomes() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import (
        apply_fitted_policy,
        fit_policy,
    )

    development = [
        _row(f"dev_{index}", feeder="ieee13", alpha_transfer=0.8)
        for index in range(8)
    ]
    fitted = fit_policy(
        development,
        grouping_fields=("feeder",),
        maximum_risk=0.05,
    )

    factor, matched = apply_fitted_policy(
        _row("external", feeder="lv906"), fitted
    )

    assert factor == 0.0
    assert matched is False


def test_policy_evaluation_excludes_inactive_offers_and_reports_two_risks() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import evaluate_policy

    rows = [
        _row("active_bad", alpha_transfer=0.50, f_bal_kw=100.0),
        _row("active_safe", alpha_transfer=1.00, f_bal_kw=300.0),
        _row(
            "inactive",
            alpha_transfer=None,
            f_bal_kw=0.0,
            active_offer=False,
        ),
    ]
    fitted = {"grouping_fields": (), "factors": {(): 0.60}}

    metrics = evaluate_policy(rows, fitted)

    assert metrics["planned_n"] == 3
    assert metrics["active_n"] == 2
    assert metrics["inactive_n"] == 1
    assert metrics["offer_coverage"] == pytest.approx(2 / 3)
    assert metrics["prescribed_n"] == 2
    assert metrics["decision_coverage"] == pytest.approx(1.0)
    assert metrics["mean_retained_fraction"] == pytest.approx(0.60)
    assert metrics["kw_weighted_retained_fraction"] == pytest.approx(0.60)
    assert metrics["material_false_safe_n"] == 1
    assert metrics["material_false_safe_rate"] == pytest.approx(0.50)
    assert metrics["exceeds_verified_bound_n"] == 1
    assert metrics["exceeds_verified_bound_rate"] == pytest.approx(0.50)
    assert 0.0 <= metrics["material_false_safe_wilson95_low"] <= 0.50
    assert 0.50 <= metrics["material_false_safe_wilson95_high"] <= 1.0


def test_evaluation_validation_rejects_duplicate_and_broken_inactive_rows() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import (
        validate_evaluation_rows,
    )

    duplicate = [_row("same"), _row("same")]
    with pytest.raises(ValueError, match="duplicate evaluation_id"):
        validate_evaluation_rows(duplicate, dataset_name="duplicate")

    broken = [_row("inactive", active_offer=False, alpha_transfer=0.5)]
    with pytest.raises(ValueError, match="inactive offer has alpha_transfer"):
        validate_evaluation_rows(broken, dataset_name="broken")


def test_local_value_decision_uses_risk_and_pareto_dominance_without_margin() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import (
        assess_local_policy_value,
    )

    failing = assess_local_policy_value(
        {"material_false_safe_rate": 0.10, "kw_weighted_retained_fraction": 0.8},
        {},
        maximum_risk=0.05,
    )
    assert failing["status"] == "FAILS_EMPIRICAL_RISK_TARGET"

    dominated = assess_local_policy_value(
        {"material_false_safe_rate": 0.02, "kw_weighted_retained_fraction": 0.5},
        {
            "global_derating": {
                "material_false_safe_rate": 0.02,
                "kw_weighted_retained_fraction": 0.6,
            }
        },
        maximum_risk=0.05,
    )
    assert dominated["status"] == "DOMINATED_BY_SIMPLE_BASELINE"
    assert dominated["dominated_by"] == ["global_derating"]

    nondominated = assess_local_policy_value(
        {"material_false_safe_rate": 0.02, "kw_weighted_retained_fraction": 0.7},
        {
            "global_derating": {
                "material_false_safe_rate": 0.02,
                "kw_weighted_retained_fraction": 0.6,
            }
        },
        maximum_risk=0.05,
    )
    assert nondominated["status"] == "NONDOMINATED_EXPLORATORY"
    assert nondominated["dominated_by"] == []


def test_wilson_interval_for_zero_of_91_is_below_five_percent() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import wilson_interval

    low, high = wilson_interval(0, 91)

    assert low == 0.0
    assert high < 0.05
    assert math.isclose(high, 0.0405047, rel_tol=2e-4)


def test_summary_fits_on_development_and_only_evaluates_external_outcomes() -> None:
    from evflex.transferability_baseline_comparison_v2_3 import (
        ANALYSIS_VERSION,
        build_baseline_comparison,
    )

    development = []
    external = []
    index = 0
    for feeder in ("ieee13", "lv906"):
        for direction in ("inc", "dec"):
            for duration_min in (15, 30, 60):
                development.append(
                    _row(
                        f"dev_{index}",
                        feeder=feeder,
                        direction=direction,
                        duration_min=duration_min,
                        alpha_transfer=0.76,
                    )
                )
                external.append(
                    _row(
                        f"external_{index}",
                        feeder=feeder,
                        direction=direction,
                        duration_min=duration_min,
                        alpha_transfer=0.20,
                    )
                )
                index += 1

    summary = build_baseline_comparison(
        development,
        external,
        code_commit="1" * 40,
        generated_at_utc="2026-08-11T00:00:00Z",
        provenance={"development": "synthetic", "external": "synthetic"},
    )

    assert summary["analysis_version"] == ANALYSIS_VERSION
    assert summary["analysis_role"] == "retrospective_exploratory_go_no_go"
    assert summary["blind_holdout_claim"] is False
    global_groups = summary["fitted_policies"]["global_derating"]["groups"]
    assert len(global_groups) == 1
    assert global_groups[0]["factor"] == pytest.approx(0.80)
    assert summary["external_scopes"]["primary_15min"]["planned_n"] == 4
    local = summary["external_scopes"]["primary_15min"]["policies"][
        "local_feeder_direction_duration"
    ]
    assert local["material_false_safe_rate"] == pytest.approx(1.0)
    assert summary["decision"]["status"] == "STOP_LOCAL_COMPLEXITY_CLAIM"
    assert summary["decision"]["confirmatory_claim_supported"] is False


def test_result_writer_emits_one_json_and_one_compact_csv(tmp_path) -> None:
    from evflex.transferability_baseline_comparison_v2_3 import write_results

    summary = {
        "analysis_version": "test",
        "external_scopes": {
            "primary_15min": {
                "planned_n": 1,
                "active_n": 1,
                "inactive_n": 0,
                "policies": {
                    "raw_balanced_offer": {
                        "planned_n": 1,
                        "active_n": 1,
                        "inactive_n": 0,
                        "offer_coverage": 1.0,
                        "prescribed_n": 1,
                        "decision_coverage": 1.0,
                        "mean_retained_fraction": 1.0,
                        "kw_weighted_retained_fraction": 1.0,
                        "material_false_safe_n": 0,
                        "material_false_safe_rate": 0.0,
                        "material_false_safe_wilson95_low": 0.0,
                        "material_false_safe_wilson95_high": 0.8,
                        "exceeds_verified_bound_n": 0,
                        "exceeds_verified_bound_rate": 0.0,
                    }
                },
                "local_policy_value": {
                    "status": "NOT_EVALUABLE",
                    "dominated_by": [],
                },
            }
        },
    }

    paths = write_results(summary, tmp_path)

    assert {path.name for path in paths} == {"summary.json", "summary.csv"}
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))[
        "analysis_version"
    ] == "test"
    with (tmp_path / "summary.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["scope"] == "primary_15min"
    assert rows[0]["policy"] == "raw_balanced_offer"
