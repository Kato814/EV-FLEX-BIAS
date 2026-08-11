from __future__ import annotations

from pathlib import Path
import csv
import json

import pytest

from evflex.transferability_witness_v2_2 import (
    build_representative_witness_summary,
    build_witness_summary,
    execute_representative_witness_case,
    execute_witness_pair,
    flatten_representative_summary_csv_rows,
    flatten_summary_csv_rows,
    load_archived_evaluations,
    main,
    select_representative_witnesses,
    select_tightest_constraint,
    select_witness_pairs,
    write_representative_summary_artifacts,
    write_summary_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _row(
    evaluation_id: str,
    *,
    feeder: str,
    direction: str,
    call_time: str,
    duration_min: int,
    alpha: float,
) -> dict[str, object]:
    trace: list[dict[str, object]] = []
    if alpha < 0.95:
        trace = [
            {
                "alpha": alpha,
                "feasible": True,
                "failure_class": "NONE",
                "first_failure_slot": None,
                "numerical_failure_checks": 0,
            },
            {
                "alpha": round(alpha + 0.002, 3),
                "feasible": False,
                "failure_class": "PHYSICAL_CONSTRAINT",
                "first_failure_slot": 17,
                "numerical_failure_checks": 0,
            },
        ]
    return {
        "evaluation_id": evaluation_id,
        "feeder": feeder,
        "direction": direction,
        "call_time": call_time,
        "duration_min": duration_min,
        "alpha_transfer": alpha,
        "alpha_path_audit": {"alpha_trace": trace},
    }


def test_select_witness_pairs_uses_extreme_failure_and_nearest_safe_control() -> None:
    rows: list[dict[str, object]] = []
    for feeder in ("ieee13", "lv906"):
        for direction in ("dec", "inc"):
            prefix = f"{feeder}_{direction}"
            rows.extend(
                [
                    _row(
                        f"{prefix}_moderate",
                        feeder=feeder,
                        direction=direction,
                        call_time="19:00",
                        duration_min=15,
                        alpha=0.6,
                    ),
                    _row(
                        f"{prefix}_extreme",
                        feeder=feeder,
                        direction=direction,
                        call_time="06:00",
                        duration_min=30,
                        alpha=0.4,
                    ),
                    _row(
                        f"{prefix}_safe_same_duration",
                        feeder=feeder,
                        direction=direction,
                        call_time="02:00",
                        duration_min=30,
                        alpha=1.0,
                    ),
                    _row(
                        f"{prefix}_safe_same_time",
                        feeder=feeder,
                        direction=direction,
                        call_time="06:00",
                        duration_min=60,
                        alpha=1.0,
                    ),
                ]
            )

    pairs = select_witness_pairs(rows)

    assert len(pairs) == 4
    assert {pair["bad"]["evaluation_id"] for pair in pairs} == {
        "ieee13_dec_extreme",
        "ieee13_inc_extreme",
        "lv906_dec_extreme",
        "lv906_inc_extreme",
    }
    assert {pair["control"]["evaluation_id"] for pair in pairs} == {
        "ieee13_dec_safe_same_time",
        "ieee13_inc_safe_same_time",
        "lv906_dec_safe_same_time",
        "lv906_inc_safe_same_time",
    }
    assert {pair["boundary_infeasible_alpha"] for pair in pairs} == {0.402}
    assert {pair["archived_first_failure_slot"] for pair in pairs} == {17}


def test_archived_selection_is_exactly_eight_development_members() -> None:
    rows = load_archived_evaluations(REPO_ROOT)
    pairs = select_witness_pairs(rows)

    assert len(rows) == 96
    assert [pair["stratum_id"] for pair in pairs] == [
        "ieee13__dec",
        "ieee13__inc",
        "lv906__dec",
        "lv906__inc",
    ]
    assert [pair["bad"]["evaluation_id"] for pair in pairs] == [
        "v22_dev_ieee13_0600_05__dec__30m",
        "v22_dev_ieee13_0600_13__inc__15m",
        "v22_dev_lv906_0000_05__dec__60m",
        "v22_dev_lv906_0000_05__inc__15m",
    ]
    assert [pair["control"]["evaluation_id"] for pair in pairs] == [
        "v22_dev_ieee13_0600_13__dec__60m",
        "v22_dev_ieee13_0600_05__inc__60m",
        "v22_dev_lv906_0200_05__dec__60m",
        "v22_dev_lv906_0000_13__inc__15m",
    ]
    assert [pair["boundary_infeasible_alpha"] for pair in pairs] == [
        0.69,
        0.458,
        0.02,
        0.004,
    ]


def test_archived_representatives_freeze_one_median_failure_per_bad_cell() -> None:
    rows = load_archived_evaluations(REPO_ROOT)

    cases = select_representative_witnesses(rows)

    assert len(cases) == 12
    assert [case["cell_id"] for case in cases] == [
        "ieee13__dec__0600",
        "ieee13__inc__0000",
        "ieee13__inc__0600",
        "ieee13__inc__1900",
        "lv906__dec__0000",
        "lv906__dec__0200",
        "lv906__dec__0600",
        "lv906__dec__1900",
        "lv906__inc__0000",
        "lv906__inc__0200",
        "lv906__inc__0600",
        "lv906__inc__1900",
    ]
    assert [case["bad"]["evaluation_id"] for case in cases] == [
        "v22_dev_ieee13_0600_05__dec__60m",
        "v22_dev_ieee13_0000_13__inc__15m",
        "v22_dev_ieee13_0600_13__inc__60m",
        "v22_dev_ieee13_1900_05__inc__30m",
        "v22_dev_lv906_0000_05__dec__30m",
        "v22_dev_lv906_0200_05__dec__30m",
        "v22_dev_lv906_0600_05__dec__30m",
        "v22_dev_lv906_1900_05__dec__30m",
        "v22_dev_lv906_0000_05__inc__30m",
        "v22_dev_lv906_0200_05__inc__30m",
        "v22_dev_lv906_0600_13__inc__30m",
        "v22_dev_lv906_1900_05__inc__30m",
    ]
    assert [case["cell_bad_count"] for case in cases] == [
        5,
        3,
        5,
        4,
        6,
        4,
        6,
        6,
        3,
        2,
        5,
        2,
    ]
    assert [case["boundary_infeasible_alpha"] for case in cases] == [
        0.766,
        0.818,
        0.58,
        0.842,
        0.052,
        0.816,
        0.81,
        0.634,
        0.004,
        0.564,
        0.724,
        0.634,
    ]
    assert all(case["bad"]["alpha_transfer"] < 0.95 for case in cases)


def test_select_tightest_constraint_compares_normalized_headroom() -> None:
    selected = select_tightest_constraint(
        [
            {
                "slot": 8,
                "constraint_family": "VMAX",
                "metric_id": "V:1.1",
                "object_id": "1.1",
                "value": 1.05,
                "limit": 1.06,
                "direction": "hi",
                "signed_headroom": 0.01,
                "exceedance": 0.0,
                "is_physical_violation": False,
            },
            {
                "slot": 9,
                "constraint_family": "VUF",
                "metric_id": "U:1",
                "object_id": "1",
                "value": 1.985,
                "limit": 2.0,
                "direction": "hi",
                "signed_headroom": 0.015,
                "exceedance": 0.0,
                "is_physical_violation": False,
            },
        ]
    )

    assert selected["metric_id"] == "U:1"
    assert selected["relative_headroom"] == pytest.approx(0.0075)


def test_select_witness_pairs_rejects_numerical_boundary_failure() -> None:
    rows: list[dict[str, object]] = []
    for feeder in ("ieee13", "lv906"):
        for direction in ("dec", "inc"):
            bad = _row(
                f"{feeder}_{direction}_bad",
                feeder=feeder,
                direction=direction,
                call_time="00:00",
                duration_min=15,
                alpha=0.5,
            )
            rows.append(bad)
            rows.append(
                _row(
                    f"{feeder}_{direction}_safe",
                    feeder=feeder,
                    direction=direction,
                    call_time="00:00",
                    duration_min=15,
                    alpha=1.0,
                )
            )
    rows[0]["alpha_path_audit"]["alpha_trace"][1][
        "numerical_failure_checks"
    ] = 1

    with pytest.raises(ValueError, match="physical and numerically clean"):
        select_witness_pairs(rows)


def test_execute_ieee13_witness_pair_replays_exact_archived_boundary() -> None:
    rows = load_archived_evaluations(REPO_ROOT)
    pair = select_witness_pairs(rows)[0]

    result = execute_witness_pair(REPO_ROOT, pair)

    assert result["status"] == "SUCCESS"
    assert result["stratum_id"] == "ieee13__dec"
    assert len(result["audits"]) == 3
    feasible, infeasible, control = result["audits"]
    assert (feasible["role"], feasible["audit_point"], feasible["feasible"]) == (
        "bad",
        "BOUNDARY_FEASIBLE",
        True,
    )
    assert infeasible["alpha"] == 0.69
    assert infeasible["first_failure_slot"] == 73
    assert infeasible["failure_class"] == "PHYSICAL_CONSTRAINT"
    assert infeasible["numerical_failure_checks"] == 0
    assert infeasible["simultaneous_violations"]
    assert (control["role"], control["audit_point"], control["feasible"]) == (
        "control",
        "FULL_OFFER",
        True,
    )
    assert feasible["tightest_constraint"]["relative_headroom"] >= 0.0
    assert control["tightest_constraint"]["relative_headroom"] >= 0.0


def test_execute_ieee13_representative_replays_only_two_boundary_points() -> None:
    rows = load_archived_evaluations(REPO_ROOT)
    case = select_representative_witnesses(rows)[0]

    result = execute_representative_witness_case(REPO_ROOT, case)

    assert result["status"] == "SUCCESS"
    assert result["cell_id"] == "ieee13__dec__0600"
    assert result["safe_control_evaluated"] is False
    assert len(result["audits"]) == 2
    feasible, infeasible = result["audits"]
    assert (feasible["audit_point"], feasible["alpha"], feasible["feasible"]) == (
        "BOUNDARY_FEASIBLE",
        0.764,
        True,
    )
    assert (
        infeasible["audit_point"],
        infeasible["alpha"],
        infeasible["feasible"],
    ) == ("BOUNDARY_INFEASIBLE", 0.766, False)
    assert infeasible["first_failure_slot"] == 75
    assert infeasible["failure_class"] == "PHYSICAL_CONSTRAINT"
    assert infeasible["numerical_failure_checks"] == 0
    assert infeasible["simultaneous_violations"]
    assert feasible["tightest_constraint"]["relative_headroom"] >= 0.0


def test_build_witness_summary_counts_only_exact_physical_boundaries(
    tmp_path: Path,
) -> None:
    def constraint(family: str, *, violation: bool) -> dict[str, object]:
        return {
            "slot": 12,
            "constraint_family": family,
            "metric_id": "V:1.1",
            "object_id": "1.1",
            "value": 1.061 if violation else 1.05,
            "limit": 1.06,
            "direction": "hi",
            "signed_headroom": -0.001 if violation else 0.01,
            "exceedance": 0.001 if violation else 0.0,
            "is_physical_violation": violation,
            **(
                {"relative_exceedance": 0.001 / 1.06}
                if violation
                else {"relative_headroom": 0.01 / 1.06}
            ),
        }

    pairs: list[dict[str, object]] = []
    for index, stratum in enumerate(
        ("ieee13__dec", "ieee13__inc", "lv906__dec", "lv906__inc"),
        start=1,
    ):
        pairs.append(
            {
                "protocol_version": (
                    "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-WITNESS-DEV"
                ),
                "status": "SUCCESS",
                "pair_id": f"{index:02d}",
                "stratum_id": stratum,
                "control_is_causal_match": False,
                "line_thermal_in_scope": False,
                "members": {"bad": {}, "control": {}},
                "audits": [
                    {
                        "role": "bad",
                        "source_evaluation_id": f"bad_{index}",
                        "audit_point": "BOUNDARY_FEASIBLE",
                        "alpha": 0.5,
                        "feasible": True,
                        "checked_intervals": 96,
                        "complete_coverage": True,
                        "failure_class": "NONE",
                        "first_failure_slot": None,
                        "numerical_failure_checks": 0,
                        "nonconverged_checks": 0,
                        "physical_violation_checks": 0,
                        "tightest_constraint": constraint(
                            "VMAX", violation=False
                        ),
                        "simultaneous_violations": [],
                    },
                    {
                        "role": "bad",
                        "source_evaluation_id": f"bad_{index}",
                        "audit_point": "BOUNDARY_INFEASIBLE",
                        "alpha": 0.502,
                        "feasible": False,
                        "checked_intervals": 13,
                        "complete_coverage": False,
                        "failure_class": "PHYSICAL_CONSTRAINT",
                        "first_failure_slot": 12,
                        "numerical_failure_checks": 0,
                        "nonconverged_checks": 0,
                        "physical_violation_checks": 1,
                        "tightest_constraint": None,
                        "simultaneous_violations": [
                            constraint("VMAX", violation=True)
                        ],
                    },
                    {
                        "role": "control",
                        "source_evaluation_id": f"control_{index}",
                        "audit_point": "FULL_OFFER",
                        "alpha": 1.0,
                        "feasible": True,
                        "checked_intervals": 96,
                        "complete_coverage": True,
                        "failure_class": "NONE",
                        "first_failure_slot": None,
                        "numerical_failure_checks": 0,
                        "nonconverged_checks": 0,
                        "physical_violation_checks": 0,
                        "tightest_constraint": constraint(
                            "VMAX", violation=False
                        ),
                        "simultaneous_violations": [],
                    },
                ],
            }
        )

    summary = build_witness_summary(
        pairs,
        code_commit="1" * 40,
        config_sha256="2" * 64,
        source_run_code_commit="3" * 40,
        source_result_hash_aggregate="4" * 64,
        generated_at_utc="2026-08-11T00:00:00Z",
    )
    csv_rows = flatten_summary_csv_rows(summary)

    assert summary["status"] == "SUCCESS"
    assert summary["formal_holdout_opened"] is False
    assert summary["resource_policy"]["gpu_used"] is False
    assert summary["counts"] == {
        "pairs": 4,
        "selected_members": 8,
        "audits": 12,
        "exact_boundary_witnesses": 4,
        "numerical_failure_checks": 0,
    }
    assert summary["boundary_constraint_family_counts"] == {"VMAX": 4}
    assert len(csv_rows) == 12
    assert csv_rows[1]["constraint_family"] == "VMAX"
    assert csv_rows[1]["relative_margin"] == pytest.approx(-(0.001 / 1.06))

    paths = write_summary_artifacts(tmp_path, summary)
    loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
    with paths["csv"].open("r", encoding="utf-8", newline="") as stream:
        csv_payload = list(csv.DictReader(stream))
    assert loaded["counts"]["exact_boundary_witnesses"] == 4
    assert len(csv_payload) == 12


def test_representative_summary_retains_only_12_cases_and_24_audits(
    tmp_path: Path,
) -> None:
    cases: list[dict[str, object]] = []
    for index in range(1, 13):
        family = "VMAX" if index <= 8 else "VUF"
        limit = 1.06 if family == "VMAX" else 2.0
        violation = {
            "slot": index,
            "constraint_family": family,
            "metric_id": f"{family}:{index}",
            "object_id": str(index),
            "value": limit + 0.001,
            "limit": limit,
            "direction": "hi",
            "signed_headroom": -0.001,
            "exceedance": 0.001,
            "is_physical_violation": True,
            "relative_exceedance": 0.001 / limit,
        }
        tightest = {
            **violation,
            "value": limit - 0.001,
            "signed_headroom": 0.001,
            "exceedance": 0.0,
            "is_physical_violation": False,
            "relative_headroom": 0.001 / limit,
        }
        cases.append(
            {
                "protocol_version": (
                    "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-"
                    "REPRESENTATIVE-WITNESS-DEV"
                ),
                "status": "SUCCESS",
                "case_id": f"{index:02d}",
                "cell_id": f"cell_{index:02d}",
                "safe_control_evaluated": False,
                "line_thermal_in_scope": False,
                "selection": {
                    "rule": "frozen median rule",
                    "cell_bad_count": 4 if index <= 9 else 5,
                    "cell_median_alpha": 0.5,
                    "distance_to_median": 0.0,
                },
                "member": {
                    "evaluation_id": f"evaluation_{index:02d}",
                    "feeder": "ieee13" if index <= 4 else "lv906",
                    "direction": "dec" if index % 2 else "inc",
                    "call_time": "06:00",
                    "duration_min": 30,
                },
                "audits": [
                    {
                        "role": "bad",
                        "source_evaluation_id": f"evaluation_{index:02d}",
                        "audit_point": "BOUNDARY_FEASIBLE",
                        "alpha": 0.5,
                        "feasible": True,
                        "checked_intervals": 96,
                        "complete_coverage": True,
                        "failure_class": "NONE",
                        "first_failure_slot": None,
                        "numerical_failure_checks": 0,
                        "nonconverged_checks": 0,
                        "physical_violation_checks": 0,
                        "tightest_constraint": tightest,
                        "simultaneous_violations": [],
                    },
                    {
                        "role": "bad",
                        "source_evaluation_id": f"evaluation_{index:02d}",
                        "audit_point": "BOUNDARY_INFEASIBLE",
                        "alpha": 0.502,
                        "feasible": False,
                        "checked_intervals": index + 1,
                        "complete_coverage": False,
                        "failure_class": "PHYSICAL_CONSTRAINT",
                        "first_failure_slot": index,
                        "numerical_failure_checks": 0,
                        "nonconverged_checks": 0,
                        "physical_violation_checks": 1,
                        "tightest_constraint": None,
                        "simultaneous_violations": [violation],
                    },
                ],
            }
        )

    summary = build_representative_witness_summary(
        cases,
        code_commit="1" * 40,
        config_sha256="2" * 64,
        source_run_code_commit="3" * 40,
        source_result_hash_aggregate="4" * 64,
        generated_at_utc="2026-08-11T00:00:00Z",
    )
    csv_rows = flatten_representative_summary_csv_rows(summary)

    assert summary["formal_holdout_opened"] is False
    assert summary["scientific_scope"]["safe_controls_evaluated"] is False
    assert summary["counts"] == {
        "cases": 12,
        "selected_members": 12,
        "source_failing_rows_covered_by_cells": 51,
        "audits": 24,
        "exact_boundary_witnesses": 12,
        "numerical_failure_checks": 0,
        "nonconverged_checks": 0,
    }
    assert summary["primary_boundary_constraint_family_counts"] == {
        "VMAX": 8,
        "VUF": 4,
    }
    assert len(csv_rows) == 24
    assert csv_rows[1]["constraint_family"] == "VMAX"

    paths = write_representative_summary_artifacts(tmp_path, summary)
    assert paths["json"].parent.name == (
        "transferability_representative_witness_v2_2"
    )
    assert not (tmp_path / "results" / "transferability_witness_v2_2").exists()
    loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
    with paths["csv"].open("r", encoding="utf-8", newline="") as stream:
        csv_payload = list(csv.DictReader(stream))
    assert loaded["counts"]["exact_boundary_witnesses"] == 12
    assert len(csv_payload) == 24


def test_cli_identifies_unknown_representative_case() -> None:
    with pytest.raises(SystemExit, match="unknown representative witness case: 99"):
        main(["--representative-case-id", "99", "--workers", "1"])
