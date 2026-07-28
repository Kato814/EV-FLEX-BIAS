from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _gate_api():
    try:
        from evflex.pilot import assess_pilot_gate
    except ImportError:
        pytest.fail("assess_pilot_gate is not implemented", pytrace=False)
    return assess_pilot_gate


@pytest.fixture
def pilot_config() -> dict[str, Any]:
    return json.loads(
        (ROOT / "config" / "pilot_gate_v2_1.json").read_text(encoding="utf-8")
    )


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _baseline_audit(*, valid: bool = True) -> dict[str, Any]:
    slot_trace = [
        {
            "slot": slot,
            "feasible": valid or slot != 40,
            "converged": True,
            "numerical_failure": False,
            "failure_class": (
                "NONE" if valid or slot != 40 else "PHYSICAL_CONSTRAINT"
            ),
            "physical_witness": not valid and slot == 40,
        }
        for slot in range(96)
    ]
    return {
        "feasible": valid,
        "checked_intervals": 96,
        "coverage_ratio": 1.0,
        "complete_coverage": True,
        "power_flow_evaluations": 96,
        "reused_baseline_intervals": 0,
        "converged_checks": 96,
        "nonconverged_checks": 0,
        "numerical_failure_checks": 0,
        "physical_violation_checks": 0 if valid else 1,
        "failure_class": "NONE" if valid else "PHYSICAL_CONSTRAINT",
        "explicit_physical_witness": not valid,
        "violation_count": 0 if valid else 1,
        "first_failure_slot": None if valid else 40,
        "slot_trace": slot_trace,
        "vmin": 0.97 if valid else 0.94,
        "vmax": 1.03,
        "vufmax": 0.5,
        "transformer_loading_max": 0.8,
        "feeder_loading_max": 0.8,
        "coverage_counts": {
            "all_bus_count": 3,
            "monitored_bus_count": 3,
            "energized_voltage_node_count": 9,
            "monitored_voltage_node_count": 9,
            "three_phase_bus_count": 3,
            "monitored_vuf_bus_count": 3,
            "enabled_transformer_count": 1,
            "rated_transformer_count": 1,
            "line_count": 2,
            "transformer_rating_coverage": 1.0,
            "line_thermal_in_scope": False,
            "feeder_rating_multiplier": 1.0,
            "transformer_rating_multiplier": 1.0,
            "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
            "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
        },
    }


def _path_audit(alpha: float) -> dict[str, Any]:
    trace = [
        {
            "alpha": 0.0,
            "feasible": True,
            "checked_intervals": 96,
            "complete_coverage": True,
            "failure_class": "NONE",
            "numerical_failure_checks": 0,
            "nonconverged_checks": 0,
            "physical_violation_checks": 0,
            "first_failure_slot": None,
        }
    ]
    if alpha < 1.0:
        trace.extend(
            [
                {
                    "alpha": alpha,
                    "feasible": True,
                    "checked_intervals": 96,
                    "complete_coverage": True,
                    "failure_class": "NONE",
                    "numerical_failure_checks": 0,
                    "nonconverged_checks": 0,
                    "physical_violation_checks": 0,
                    "first_failure_slot": None,
                },
                {
                    "alpha": 1.0,
                    "feasible": False,
                    "checked_intervals": 40,
                    "complete_coverage": False,
                    "failure_class": "PHYSICAL_CONSTRAINT",
                    "numerical_failure_checks": 0,
                    "nonconverged_checks": 0,
                    "physical_violation_checks": 1,
                    "first_failure_slot": 39,
                },
            ]
        )
    else:
        trace.append(
            {
                "alpha": 1.0,
                "feasible": True,
                "checked_intervals": 96,
                "complete_coverage": True,
                "failure_class": "NONE",
                "numerical_failure_checks": 0,
                "nonconverged_checks": 0,
                "physical_violation_checks": 0,
                "first_failure_slot": None,
            }
        )
    return {
        "audit_calls": len(trace),
        "power_flow_evaluations": sum(item["checked_intervals"] for item in trace),
        "reused_baseline_intervals": 0,
        "complete_audits": sum(item["complete_coverage"] for item in trace),
        "early_stopped_audits": sum(
            not item["complete_coverage"] for item in trace
        ),
        "numerical_failure_audits": 0,
        "physical_boundary_audits": sum(
            item["physical_violation_checks"] > 0 for item in trace
        ),
        "minimum_checked_intervals": min(
            item["checked_intervals"] for item in trace
        ),
        "maximum_checked_intervals": max(
            item["checked_intervals"] for item in trace
        ),
        "alpha_trace": trace,
    }


def _set_corrected_alpha(row: dict[str, Any], alpha: float) -> None:
    row["alpha_transfer"] = alpha
    row["alpha_prefix"] = alpha
    row["alpha_sup"] = alpha
    row["alpha_path_audit"] = _path_audit(alpha)


def _set_tied_alpha(row: dict[str, Any], alpha: float) -> None:
    row["alpha_transfer_tied"] = alpha
    row["alpha_tie_prefix"] = alpha
    row["alpha_tie_sup"] = alpha
    row["alpha_tie_path_audit"] = _path_audit(alpha)


def _set_warm_timing(row: dict[str, Any], warm_s: list[float]) -> None:
    mean = sum(warm_s) / len(warm_s)
    row["alpha1_warm_timing_s"] = list(warm_s)
    row["alpha1_warm_p95_s"] = sorted(warm_s)[math.ceil(0.95 * len(warm_s)) - 1]
    row["alpha1_warm_cv"] = (
        math.sqrt(sum((value - mean) ** 2 for value in warm_s) / len(warm_s))
        / mean
        if mean > 0
        else None
    )


def _canonical_evidence(config: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    wrappers: list[dict[str, Any]] = []
    bad_cells = {
        (config["scenario_ids"][0], "inc", 15),
        (config["scenario_ids"][0], "dec", 15),
        (config["scenario_ids"][1], "inc", 15),
        (config["scenario_ids"][1], "dec", 15),
        (config["scenario_ids"][4], "inc", 15),
        (config["scenario_ids"][4], "dec", 15),
        (config["scenario_ids"][5], "inc", 15),
        (config["scenario_ids"][5], "dec", 15),
    }
    for scenario_id in config["scenario_ids"]:
        design = config["scenario_design"][scenario_id]
        baseline_hash = _sha256(f"baseline:{scenario_id}")
        for direction in config["directions"]:
            work_unit_id = f"v20_work_{scenario_id}__{direction}"
            unit_rows: list[dict[str, Any]] = []
            for duration in config["durations_min"]:
                evaluation_id = (
                    f"v20_core_{scenario_id}__{direction}__{duration}m"
                )
                alpha = (
                    0.94
                    if (scenario_id, direction, duration) in bad_cells
                    else 1.0
                )
                schedule_hash = _sha256(f"schedule:{evaluation_id}")
                feeder = design["feeder"]
                threshold = max(
                    float(config["active_offer"]["minimum_kw"]),
                    float(config["active_offer"]["feeder_fraction"])
                    * float(config["feeder_kva"][feeder]),
                )
                row = {
                    "evaluation_id": evaluation_id,
                    "work_unit_id": work_unit_id,
                    "protocol_version": config["protocol_version"],
                    "scenario_id": scenario_id,
                    "scenario_seed": design["scenario_seed"],
                    "data_role": "development_pilot",
                    "feeder": feeder,
                    "call_time": design["call_time"],
                    "direction": direction,
                    "duration_min": duration,
                    "requested_duration_min": duration,
                    "source_duration_min": duration,
                    "baseline_status": "VALID",
                    "baseline_audit": _baseline_audit(),
                    "baseline_schedule_sha256": baseline_hash,
                    "active_offer_threshold_kw": threshold,
                    "f_bal_kw": threshold + 1.0,
                    "active_offer": True,
                    "eligible_for_scientific_denominator": True,
                    "schedule_sha256": schedule_hash,
                    "bus_phase_time_sha256": _sha256(
                        f"bus-phase:{evaluation_id}"
                    ),
                    "monotonic_closure_promoted": False,
                    "canonical_schedule_reused": False,
                    "reuse_source_requested_duration_min": None,
                    "max_departure_error_kwh": 0.0,
                    "max_reserve_violation_kwh": 0.0,
                    "max_capacity_violation_kwh": 0.0,
                    "max_discharge_budget_violation_kwh": 0.0,
                    "max_availability_violation_kw": 0.0,
                    "max_charge_limit_violation_kw": 0.0,
                    "max_discharge_limit_violation_kw": 0.0,
                    "max_schedule_identity_error_kw": 0.0,
                    "max_ev_invariant_error": 0.0,
                    "simultaneous_slots": 0,
                    "ev_invariant_errors": {
                        "max_departure_error_kwh": 0.0,
                        "max_reserve_violation_kwh": 0.0,
                        "max_capacity_violation_kwh": 0.0,
                        "max_discharge_budget_violation_kwh": 0.0,
                        "max_availability_violation_kw": 0.0,
                        "max_charge_limit_violation_kw": 0.0,
                        "max_discharge_limit_violation_kw": 0.0,
                        "max_schedule_identity_error_kw": 0.0,
                        "max_ev_invariant_error": 0.0,
                        "simultaneous_slots": 0,
                    },
                    "reported_ev_invariant_errors": {
                        "max_departure_error_kwh": 0.0,
                        "max_reserve_violation_kwh": 0.0,
                        "max_capacity_violation_kwh": 0.0,
                        "max_ev_invariant_error": 0.0,
                        "simultaneous_slots": 0,
                    },
                    "derived_ev_invariant_errors": {
                        "max_departure_error_kwh": 0.0,
                        "max_reserve_violation_kwh": 0.0,
                        "max_capacity_violation_kwh": 0.0,
                        "max_discharge_budget_violation_kwh": 0.0,
                        "max_availability_violation_kw": 0.0,
                        "max_charge_limit_violation_kw": 0.0,
                        "max_discharge_limit_violation_kw": 0.0,
                        "max_schedule_identity_error_kw": 0.0,
                        "max_ev_invariant_error": 0.0,
                        "simultaneous_slots": 0,
                    },
                    "alpha_legacy_verifier": alpha,
                    "alpha_legacy_verifier_status": "SUCCESS",
                    "alpha_legacy_verifier_detail": None,
                    "alpha_nonmonotone": False,
                    "alpha_path_status": "VALID",
                    "alpha_path_valid_baseline": True,
                    "alpha_path_scientific_valid": True,
                    "alpha1_timing_status": "SUCCESS",
                    "alpha1_timing_detail": None,
                    "alpha1_cold_timing_s": 2.1,
                    "alpha1_cold_timing_scope": (
                        "FIRST_SCHEDULE_REPLAY_AFTER_COMMON_BASELINE_WITH_PREBUILT_TRUTH_CACHE"
                    ),
                    "alpha1_first_replay_timing_s": 2.1,
                    "alpha1_first_replay_scope": (
                        "FIRST_SCHEDULE_REPLAY_AFTER_COMMON_BASELINE_WITH_PREBUILT_TRUTH_CACHE"
                    ),
                    "alpha1_warm_timing_s": [2.0, 2.0, 2.0],
                    "alpha1_warm_p95_s": 2.0,
                    "alpha1_warm_cv": 0.0,
                    "alpha1_timing_checked_intervals": [96, 96, 96, 96],
                    "alpha1_timing_power_flow_evaluations": [96, 96, 96, 96],
                    "alpha1_timing_numerical_failure_checks": [0, 0, 0, 0],
                    "alpha1_timing_nonconverged_checks": [0, 0, 0, 0],
                    "alpha1_timing_physical_violation_checks": [0, 0, 0, 0],
                    "alpha1_timing_failure_class": [
                        "NONE",
                        "NONE",
                        "NONE",
                        "NONE",
                    ],
                    "tie_comparator_valid": True,
                    "tie_break_status": "SUCCESS",
                    "tie_original_schedule_sha256": schedule_hash,
                    "tie_schedule_sha256": _sha256(f"tie:{evaluation_id}"),
                    "tie_offer_retention": 1.0,
                    "alpha_tie_nonmonotone": False,
                    "alpha_tie_path_status": "VALID",
                    "scientific_status": "VALID",
                    "status": "SUCCESS",
                }
                _set_corrected_alpha(row, alpha)
                _set_tied_alpha(row, alpha)
                rows.append(row)
                unit_rows.append(row)
            wrappers.append(
                {
                    "protocol_version": config["protocol_version"],
                    "work_unit_id": work_unit_id,
                    "scenario_seed": design["scenario_seed"],
                    "data_role": "development_pilot",
                    "status": "SUCCESS",
                    "attempt_count": 1,
                    "evaluations": unit_rows,
                }
            )
    work_unit_ids = [unit["work_unit_id"] for unit in wrappers]
    evaluation_ids = [row["evaluation_id"] for row in rows]
    raw_hash_rows = [
        {
            "work_unit_id": work_unit_id,
            "relative_path": (
                f"results/pilot_v2_1/work_units/{work_unit_id}.json"
            ),
            "sha256": _sha256(f"raw:{work_unit_id}"),
        }
        for work_unit_id in work_unit_ids
    ]
    return {
        "work_units": wrappers,
        "evaluations": rows,
        "raw_hash_rows": raw_hash_rows,
        "loader_validation": {"status": "VALID", "errors": []},
        "expected_work_unit_ids": work_unit_ids,
        "actual_work_unit_ids": list(work_unit_ids),
        "expected_evaluation_ids": evaluation_ids,
        "actual_evaluation_ids": list(evaluation_ids),
        "active_lock_files": [],
        "attempt_state_files": [],
        "unexpected_raw_files": [],
    }


def _assess(evidence: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return _gate_api()(copy.deepcopy(evidence), copy.deepcopy(config))


def _sync_wrapper_statuses(evidence: dict[str, Any]) -> None:
    for wrapper in evidence["work_units"]:
        wrapper["status"] = (
            "SUCCESS"
            if all(row["status"] == "SUCCESS" for row in wrapper["evaluations"])
            else "SCIENTIFIC_TERMINAL"
        )


def _clear_non_denominator_diagnostics(row: dict[str, Any]) -> None:
    for field in (
        "alpha_legacy_verifier_status",
        "alpha_legacy_verifier_detail",
        "alpha_path_status",
        "alpha_path_valid_baseline",
        "alpha_path_scientific_valid",
        "alpha_path_audit",
        "alpha1_timing_status",
        "alpha1_timing_detail",
        "alpha1_timing_checked_intervals",
        "alpha1_timing_power_flow_evaluations",
        "alpha1_timing_numerical_failure_checks",
        "alpha1_timing_nonconverged_checks",
        "alpha1_timing_physical_violation_checks",
        "alpha1_timing_failure_class",
        "tie_original_schedule_sha256",
        "tie_schedule_sha256",
        "tie_offer_retention",
        "alpha_tie_prefix",
        "alpha_tie_sup",
        "alpha_tie_nonmonotone",
        "alpha_tie_path_status",
        "alpha_tie_path_audit",
    ):
        row.pop(field, None)


def _make_inactive(row: dict[str, Any]) -> None:
    row["f_bal_kw"] = row["active_offer_threshold_kw"] - 0.1
    row["active_offer"] = False
    row["eligible_for_scientific_denominator"] = False
    for field in (
        "alpha_legacy_verifier",
        "alpha_transfer",
        "alpha_prefix",
        "alpha_sup",
        "alpha_nonmonotone",
        "alpha_transfer_tied",
        "tie_comparator_valid",
        "alpha1_cold_timing_s",
        "alpha1_first_replay_timing_s",
        "alpha1_warm_p95_s",
        "alpha1_warm_cv",
    ):
        row[field] = None
    row["alpha1_warm_timing_s"] = []
    row["alpha1_cold_timing_scope"] = None
    row["alpha1_first_replay_scope"] = None
    _clear_non_denominator_diagnostics(row)
    row["tie_break_status"] = "NOT_APPLICABLE_INACTIVE"
    row["scientific_status"] = "NOT_APPLICABLE_INACTIVE"
    row["status"] = "INACTIVE_OFFER"


def _set_active_count(evidence: dict[str, Any], count: int) -> None:
    for row in evidence["evaluations"][count:]:
        _make_inactive(row)
    _sync_wrapper_statuses(evidence)


def _make_physical_baseline(
    evidence: dict[str, Any], scenario_ids: list[str]
) -> None:
    for row in evidence["evaluations"]:
        if row["scenario_id"] not in scenario_ids:
            continue
        row["baseline_status"] = "BASELINE_PHYSICAL_INVALID"
        row["baseline_audit"] = _baseline_audit(valid=False)
        row["eligible_for_scientific_denominator"] = False
        for field in (
            "alpha_legacy_verifier",
            "alpha_transfer",
            "alpha_prefix",
            "alpha_sup",
            "alpha_nonmonotone",
            "alpha_transfer_tied",
            "tie_comparator_valid",
            "alpha1_cold_timing_s",
            "alpha1_first_replay_timing_s",
            "alpha1_warm_p95_s",
            "alpha1_warm_cv",
        ):
            row[field] = None
        row["alpha1_warm_timing_s"] = []
        row["alpha1_cold_timing_scope"] = None
        row["alpha1_first_replay_scope"] = None
        _clear_non_denominator_diagnostics(row)
        row["tie_break_status"] = "NOT_RUN_BASELINE_INVALID"
        row["scientific_status"] = "INVALID_BASELINE"
        row["status"] = "BASELINE_PHYSICAL_INVALID"
    _sync_wrapper_statuses(evidence)


def _set_bad_rows(
    evidence: dict[str, Any],
    bad_evaluation_ids: set[str],
) -> None:
    for row in evidence["evaluations"]:
        if row["active_offer"] is not True or row["baseline_status"] != "VALID":
            continue
        alpha = 0.94 if row["evaluation_id"] in bad_evaluation_ids else 1.0
        _set_corrected_alpha(row, alpha)
        row["alpha_legacy_verifier"] = alpha
        row["alpha_legacy_verifier_status"] = "SUCCESS"
        _set_tied_alpha(row, alpha)


def _scenario_ids(evidence: dict[str, Any], scenario: int) -> list[str]:
    ordered = list(dict.fromkeys(row["scenario_id"] for row in evidence["evaluations"]))
    return [
        row["evaluation_id"]
        for row in evidence["evaluations"]
        if row["scenario_id"] == ordered[scenario]
    ]


def _set_tie_outcome(
    evidence: dict[str, Any],
    *,
    unresolved_bad: int = 0,
    newly_unsafe: int = 0,
    retention: float = 1.0,
) -> None:
    bad = [
        row
        for row in evidence["evaluations"]
        if isinstance(row.get("alpha_transfer"), (int, float))
        and row["alpha_transfer"] < 0.95
    ]
    safe = [
        row for row in evidence["evaluations"] if row.get("alpha_transfer") == 1.0
    ]
    for index, row in enumerate(bad):
        _set_tied_alpha(row, 0.94 if index < unresolved_bad else 1.0)
        row["tie_offer_retention"] = retention
    for index, row in enumerate(safe):
        _set_tied_alpha(row, 0.94 if index < newly_unsafe else 1.0)
        row["tie_offer_retention"] = retention


def test_validity_failure_stops_before_scientific_decision(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    evidence["evaluations"].pop()

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert gate["overall_action"] == "STOP_FIX_AND_REPEAT_16_WU_AUDIT"
    assert gate["decision_class"] == "VALIDITY_STOP"
    assert gate["core_topic_status"] == "NOT_EVALUATED_VALIDITY_STOP"
    assert gate["baseline_status"] == "NOT_EVALUATED_VALIDITY_STOP"
    assert gate["formal_v2_1_run_started"] is False


def test_core_signal_can_pass_while_direction_claim_is_dropped(pilot_config):
    gate = _assess(_canonical_evidence(pilot_config), pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["baseline_status"] == "PASS_ALL_BASELINES"
    assert gate["active_offer_status"] == "PASS_ACTIVE_COVERAGE"
    assert gate["core_topic_status"] == "GO"
    assert gate["scenario_dominance_status"] == "DISTRIBUTED"
    assert gate["direction_claim_status"] == "DROP_CLAIM"
    assert gate["duration_claim_status"] == "KEEP_CLAIM"
    assert gate["feeder_replication_status"] == "REPLICATED"
    assert gate["tie_break_route_status"] == "KEEP_ORIGINAL_ROUTE"
    assert gate["screening_compute_status"] == "KEEP_SCREENING_MATERIAL"
    assert gate["v2_0_reuse_status"] == "DIAGNOSTIC_ONLY_NO_FLIP"
    assert gate["overall_action"] == "GO_TO_FORMAL_V2_1_WITH_REPORTED_SCOPE"
    assert gate["decision_class"] == "GO"
    assert gate["repeat_scope"] == "NONE"
    assert "DROP_DIRECTION_CLAIM" in gate["mandatory_scope_actions"]
    assert "REPORT_V2_0_REUSE_AS_DIAGNOSTIC_ONLY" in gate[
        "mandatory_scope_actions"
    ]
    assert gate["metrics"]["core_bad_alpha"] == {
        "numerator": 8,
        "denominator": 48,
        "rate": pytest.approx(8 / 48),
        "unique_bad_scenarios": 4,
    }


def test_fast_direct_audit_drops_screening_not_core_topic(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    for row in evidence["evaluations"]:
        _set_warm_timing(row, [0.5, 0.5, 0.5])

    gate = _assess(evidence, pilot_config)

    assert gate["screening_compute_status"] == "DROP_SCREENING"
    assert gate["core_topic_status"] == "GO"
    assert gate["overall_action"] == "GO_TO_FORMAL_V2_1_WITH_REPORTED_SCOPE"
    assert "DROP_ONLINE_SCREENING" in gate["mandatory_scope_actions"]


def test_corrected_alpha_equal_to_threshold_is_not_bad(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    for row in evidence["evaluations"]:
        if row["alpha_transfer"] < 0.95:
            _set_corrected_alpha(row, 0.95)
            row["alpha_legacy_verifier"] = 0.95
            _set_tied_alpha(row, 0.95)

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["core_bad_alpha"]["numerator"] == 0
    assert gate["core_topic_status"] == "NO_GO"
    assert gate["scenario_dominance_status"] == "NOT_APPLICABLE_NO_BAD_ALPHA"
    assert gate["tie_break_route_status"] == "NOT_APPLICABLE_NO_BAD_ALPHA"


def test_offer_equal_to_active_threshold_is_active(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][0]
    row["f_bal_kw"] = row["active_offer_threshold_kw"]

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["metrics"]["active_offer_coverage"]["numerator"] == 48


@pytest.mark.parametrize(
    ("valid_scenarios", "expected"),
    [
        (8, "PASS_ALL_BASELINES"),
        (7, "WARN_REPEAT_BASELINE_COVERAGE"),
        (6, "HARD_STOP_BASELINE_COVERAGE"),
    ],
)
def test_baseline_scenario_count_boundaries(
    pilot_config, valid_scenarios, expected
):
    evidence = _canonical_evidence(pilot_config)
    invalid_scenarios = pilot_config["scenario_ids"][valid_scenarios:]
    _make_physical_baseline(evidence, invalid_scenarios)

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["baseline_status"] == expected
    assert gate["metrics"]["baseline_coverage"]["numerator"] == valid_scenarios


@pytest.mark.parametrize(
    ("active_count", "expected"),
    [
        (36, "PASS_ACTIVE_COVERAGE"),
        (24, "WARN_REPEAT_ACTIVE_COVERAGE"),
        (23, "NO_GO_LOW_ACTIVE_COVERAGE"),
    ],
)
def test_active_offer_boundaries(pilot_config, active_count, expected):
    evidence = _canonical_evidence(pilot_config)
    _set_active_count(evidence, active_count)

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["active_offer_status"] == expected
    assert gate["metrics"]["active_offer_coverage"] == {
        "numerator": active_count,
        "denominator": 48,
        "rate": active_count / 48,
    }


def test_core_go_accepts_exact_ten_percent_boundary(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    _set_active_count(evidence, 40)
    bad = {
        _scenario_ids(evidence, 0)[0],
        _scenario_ids(evidence, 1)[0],
        _scenario_ids(evidence, 4)[0],
        _scenario_ids(evidence, 5)[0],
    }
    _set_bad_rows(evidence, bad)

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["core_bad_alpha"]["rate"] == pytest.approx(0.10)
    assert gate["metrics"]["core_bad_alpha"]["unique_bad_scenarios"] == 4
    assert gate["core_topic_status"] == "GO"


@pytest.mark.parametrize(
    ("bad_count", "expected"),
    [
        (1, "NO_GO"),
        (2, "NO_GO"),
        (3, "REPEAT_PILOT"),
    ],
)
def test_core_hard_no_go_or_boundaries(pilot_config, bad_count, expected):
    evidence = _canonical_evidence(pilot_config)
    candidates = [
        _scenario_ids(evidence, scenario)[0]
        for scenario in range(bad_count)
    ]
    _set_bad_rows(evidence, set(candidates))

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["core_bad_alpha"]["numerator"] == bad_count
    assert gate["core_topic_status"] == expected


@pytest.mark.parametrize(
    ("scenario_distribution", "expected"),
    [
        ([4, 2, 2], "DISTRIBUTED"),
        ([5, 2, 1], "DOMINANCE_REPEAT"),
        ([6, 1, 1], "NO_GO_SCENARIO_DOMINATED"),
    ],
)
def test_scenario_dominance_boundaries(
    pilot_config, scenario_distribution, expected
):
    evidence = _canonical_evidence(pilot_config)
    bad: set[str] = set()
    for scenario, count in zip((0, 1, 4), scenario_distribution, strict=True):
        bad.update(_scenario_ids(evidence, scenario)[:count])
    _set_bad_rows(evidence, bad)

    gate = _assess(evidence, pilot_config)

    assert gate["scenario_dominance_status"] == expected


@pytest.mark.parametrize(
    ("ieee_bad", "expected"),
    [
        (4, "REPLICATED"),
        (5, "WEAK_REPLICATION_REPEAT"),
        (6, "NO_GO_SINGLE_FEEDER_DOMINATED"),
    ],
)
def test_feeder_replication_boundaries(pilot_config, ieee_bad, expected):
    evidence = _canonical_evidence(pilot_config)
    by_feeder: dict[str, list[list[str]]] = {"ieee13": [], "lv906": []}
    for scenario in range(8):
        scenario_rows = _scenario_ids(evidence, scenario)
        feeder = next(
            row["feeder"]
            for row in evidence["evaluations"]
            if row["evaluation_id"] == scenario_rows[0]
        )
        by_feeder[feeder].append(scenario_rows)

    def spread(feeder: str, count: int) -> list[str]:
        groups = by_feeder[feeder]
        return [
            groups[index % len(groups)][index // len(groups)]
            for index in range(count)
        ]

    bad = set(spread("ieee13", ieee_bad) + spread("lv906", 8 - ieee_bad))
    _set_bad_rows(evidence, bad)

    gate = _assess(evidence, pilot_config)

    assert gate["scenario_dominance_status"] == "DISTRIBUTED"
    assert gate["feeder_replication_status"] == expected


@pytest.mark.parametrize(
    ("material_pairs", "expected"),
    [
        (6, "KEEP_CLAIM"),
        (3, "INDETERMINATE_REPEAT"),
        (2, "DROP_CLAIM"),
    ],
)
def test_direction_materiality_boundaries(
    pilot_config, material_pairs, expected
):
    evidence = _canonical_evidence(pilot_config)
    bad = {
        row["evaluation_id"]
        for row in evidence["evaluations"]
        if row["direction"] == "inc"
    }
    _set_bad_rows(evidence, set(list(bad)[:material_pairs]))

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["direction_materiality"]["denominator"] == 24
    assert gate["metrics"]["direction_materiality"]["numerator"] == material_pairs
    assert gate["direction_claim_status"] == expected


@pytest.mark.parametrize(
    ("material_triplets", "expected"),
    [
        (4, "KEEP_CLAIM"),
        (2, "INDETERMINATE_REPEAT"),
        (1, "DROP_CLAIM"),
    ],
)
def test_duration_materiality_boundaries(
    pilot_config, material_triplets, expected
):
    evidence = _canonical_evidence(pilot_config)
    bad = {
        row["evaluation_id"]
        for row in evidence["evaluations"]
        if row["duration_min"] == 15
    }
    _set_bad_rows(evidence, set(list(bad)[:material_triplets]))

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["duration_materiality"]["denominator"] == 16
    assert gate["metrics"]["duration_materiality"]["numerator"] == material_triplets
    assert gate["duration_claim_status"] == expected


def test_exact_material_delta_counts_as_material(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    _set_bad_rows(evidence, set())
    row = next(
        row
        for row in evidence["evaluations"]
        if row["direction"] == "inc" and row["duration_min"] == 15
    )
    _set_corrected_alpha(row, 0.95)
    row["alpha_legacy_verifier"] = 0.95
    _set_tied_alpha(row, 0.95)

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["direction_materiality"]["numerator"] == 1
    assert gate["metrics"]["duration_materiality"]["numerator"] == 1


def test_just_below_material_delta_is_not_material(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    _set_bad_rows(evidence, set())
    inc = next(
        row
        for row in evidence["evaluations"]
        if row["direction"] == "inc" and row["duration_min"] == 15
    )
    dec = next(
        row
        for row in evidence["evaluations"]
        if row["scenario_id"] == inc["scenario_id"]
        and row["direction"] == "dec"
        and row["duration_min"] == 15
    )
    below = math.nextafter(0.05, 0.0)
    lower = 0.25
    upper = lower + below
    assert upper - lower < 0.05
    for row, alpha in ((inc, lower), (dec, upper)):
        _set_corrected_alpha(row, alpha)
        row["alpha_legacy_verifier"] = alpha
        _set_tied_alpha(row, alpha)

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["direction_materiality"]["numerator"] == 0


def test_tie_pivot_accepts_exact_rescue_and_retention_boundaries(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    bad = {
        _scenario_ids(evidence, 0)[0],
        _scenario_ids(evidence, 0)[1],
        _scenario_ids(evidence, 1)[0],
        _scenario_ids(evidence, 4)[0],
        _scenario_ids(evidence, 5)[0],
    }
    _set_bad_rows(evidence, bad)
    _set_tie_outcome(evidence, unresolved_bad=1, retention=0.995)

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["tie_rescue"]["rate"] == pytest.approx(0.8)
    assert gate["metrics"]["tie_offer_retention"]["minimum"] == pytest.approx(
        0.995
    )
    assert gate["tie_break_route_status"] == "PIVOT_TO_PHASE_BALANCED"
    assert gate["decision_class"] == "PIVOT"


def test_tie_pivot_accepts_exact_new_unsafe_boundary(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    _set_tie_outcome(evidence, unresolved_bad=0, newly_unsafe=2)

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["tie_new_unsafe"]["rate"] == pytest.approx(0.05)
    assert gate["metrics"]["tie_post_bad"]["rate"] < 0.05
    assert gate["tie_break_route_status"] == "PIVOT_TO_PHASE_BALANCED"


def test_tie_pivot_accepts_exact_total_bad_boundary(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    _set_active_count(evidence, 40)
    bad: set[str] = set()
    for scenario, count in ((0, 2), (1, 2), (2, 1), (4, 2), (5, 2), (6, 1)):
        bad.update(_scenario_ids(evidence, scenario)[:count])
    _set_bad_rows(evidence, bad)
    _set_tie_outcome(evidence, unresolved_bad=2)

    gate = _assess(evidence, pilot_config)

    assert gate["metrics"]["tie_rescue"]["rate"] == pytest.approx(0.8)
    assert gate["metrics"]["tie_post_bad"]["rate"] == pytest.approx(0.05)
    assert gate["tie_break_route_status"] == "PIVOT_TO_PHASE_BALANCED"


def test_invalid_optional_tie_is_repeat_not_validity_stop(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][0]
    row["tie_comparator_valid"] = False
    row["alpha_transfer_tied"] = None
    row["alpha_tie_prefix"] = None
    row["alpha_tie_sup"] = None
    row["alpha_tie_nonmonotone"] = None
    row["alpha_tie_path_status"] = "NOT_RUN_TIE_INVALID"
    row["alpha_tie_path_audit"] = None

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["tie_break_route_status"] == "INDETERMINATE_REPEAT"
    assert gate["overall_action"] == "REPEAT_16_WU_PILOT"


@pytest.mark.parametrize(
    ("cv", "expected"),
    [
        (0.20, "KEEP_SCREENING_MATERIAL"),
        (0.25, "REPEAT_TIMING"),
        (0.31, "INDETERMINATE_TIMING"),
    ],
)
def test_warm_timing_cv_boundaries(pilot_config, cv, expected):
    evidence = _canonical_evidence(pilot_config)
    delta = cv * math.sqrt(3 / 2)
    for row in evidence["evaluations"]:
        _set_warm_timing(row, [1.0 - delta, 1.0, 1.0 + delta])

    gate = _assess(evidence, pilot_config)

    assert gate["screening_compute_status"] == expected
    if expected == "REPEAT_TIMING":
        assert gate["overall_action"] == "REPEAT_TIMING_BENCHMARK_ONLY"
        assert gate["repeat_scope"] == "TIMING_ONLY"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (1.0, "DROP_SCREENING"),
        (5.0, "KEEP_SCREENING_MATERIAL"),
        (5.0001, "KEEP_SCREENING_DIRECT_AUDIT_OVER_BUDGET"),
    ],
)
def test_direct_audit_latency_boundaries(pilot_config, seconds, expected):
    evidence = _canonical_evidence(pilot_config)
    for row in evidence["evaluations"]:
        _set_warm_timing(row, [seconds, seconds, seconds])

    gate = _assess(evidence, pilot_config)

    assert gate["screening_compute_status"] == expected


def test_timing_deduplicates_exact_feeder_schedule_key(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    first, second = evidence["evaluations"][:2]
    second["schedule_sha256"] = first["schedule_sha256"]
    second["tie_original_schedule_sha256"] = first["schedule_sha256"]
    for field in (
        "alpha1_timing_status",
        "alpha1_warm_timing_s",
        "alpha1_warm_p95_s",
        "alpha1_warm_cv",
        "alpha1_timing_checked_intervals",
        "alpha1_timing_power_flow_evaluations",
        "alpha1_timing_numerical_failure_checks",
        "alpha1_timing_nonconverged_checks",
        "alpha1_timing_physical_violation_checks",
        "alpha1_timing_failure_class",
    ):
        second[field] = copy.deepcopy(first[field])

    gate = _assess(evidence, pilot_config)

    assert gate["screening_compute_status"] == "KEEP_SCREENING_MATERIAL"
    assert gate["metrics"]["screening_compute"]["unique_schedule_count"] == 47


def test_mismatched_repeated_schedule_timing_is_axis_local_indeterminate(
    pilot_config,
):
    evidence = _canonical_evidence(pilot_config)
    first, second = evidence["evaluations"][:2]
    second["schedule_sha256"] = first["schedule_sha256"]
    second["tie_original_schedule_sha256"] = first["schedule_sha256"]
    _set_warm_timing(second, [3.0, 3.0, 3.0])

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["screening_compute_status"] == "INDETERMINATE_TIMING"


def test_per_schedule_cv_does_not_pool_between_schedule_speed(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    for index, row in enumerate(evidence["evaluations"]):
        seconds = 1.0 if index % 2 == 0 else 4.0
        _set_warm_timing(row, [seconds, seconds, seconds])

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["screening_compute_status"] == "KEEP_SCREENING_MATERIAL"


def test_repeated_schedule_cold_timing_mismatch_is_indeterminate(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    first, second = evidence["evaluations"][:2]
    second["schedule_sha256"] = first["schedule_sha256"]
    second["tie_original_schedule_sha256"] = first["schedule_sha256"]
    second["alpha1_cold_timing_s"] = first["alpha1_cold_timing_s"] + 1.0
    second["alpha1_first_replay_timing_s"] = (
        first["alpha1_first_replay_timing_s"] + 1.0
    )

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["screening_compute_status"] == "INDETERMINATE_TIMING"


def test_legacy_label_flip_blocks_reuse_but_not_corrected_core(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][0]
    row["alpha_legacy_verifier"] = (
        1.0 if row["alpha_transfer"] < 0.95 else 0.0
    )

    gate = _assess(evidence, pilot_config)

    assert gate["core_topic_status"] == "GO"
    assert gate["v2_0_reuse_status"] == "BLOCKED_LABEL_FLIP"
    assert "BLOCK_V2_0_EVIDENCE_REUSE" in gate["mandatory_scope_actions"]


def test_legacy_error_is_axis_local_and_never_allows_reuse(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][0]
    row["alpha_legacy_verifier"] = None
    row["alpha_legacy_verifier_status"] = "ERROR"

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["v2_0_reuse_status"] == "BLOCKED_LEGACY_DIAGNOSTIC_FAILURE"
    assert gate["overall_action"] == "GO_TO_FORMAL_V2_1_WITH_REPORTED_SCOPE"


@pytest.mark.parametrize(
    "mutation",
    [
        "nan_alpha",
        "prefix_mismatch",
        "numerical_path",
        "bool_seed",
        "baseline_hash_mismatch",
        "unhandled_wrapper",
        "active_lock",
        "null_leakage",
    ],
)
def test_fail_closed_invalid_cases(pilot_config, mutation):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][0]
    if mutation == "nan_alpha":
        row["alpha_transfer"] = float("nan")
    elif mutation == "prefix_mismatch":
        row["alpha_prefix"] = 0.5
    elif mutation == "numerical_path":
        row["alpha_path_audit"]["alpha_trace"][0][
            "numerical_failure_checks"
        ] = 1
    elif mutation == "bool_seed":
        row["scenario_seed"] = True
    elif mutation == "baseline_hash_mismatch":
        row["baseline_schedule_sha256"] = _sha256("different-baseline")
    elif mutation == "unhandled_wrapper":
        evidence["work_units"][0]["status"] = "UNHANDLED_FAILURE"
    elif mutation == "active_lock":
        evidence["active_lock_files"] = ["results/pilot_v2_1/locks/a.lock"]
    elif mutation == "null_leakage":
        _make_inactive(row)
        row["alpha_transfer"] = 0.5
        _sync_wrapper_statuses(evidence)

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert gate["overall_action"] == "STOP_FIX_AND_REPEAT_16_WU_AUDIT"
    assert all(
        gate[field] == "NOT_EVALUATED_VALIDITY_STOP"
        for field in (
            "baseline_status",
            "active_offer_status",
            "core_topic_status",
            "scenario_dominance_status",
            "direction_claim_status",
            "duration_claim_status",
            "feeder_replication_status",
            "tie_break_route_status",
            "screening_compute_status",
            "v2_0_reuse_status",
        )
    )


def test_numerical_baseline_is_validity_stop_not_scientific_terminal(
    pilot_config,
):
    evidence = _canonical_evidence(pilot_config)
    for row in evidence["evaluations"]:
        if row["scenario_id"] == pilot_config["scenario_ids"][0]:
            row["baseline_status"] = "BASELINE_NUMERICAL_INVALID"
            row["baseline_audit"]["feasible"] = False
            row["baseline_audit"]["numerical_failure_checks"] = 1
            row["baseline_audit"]["failure_class"] = "NUMERICAL_INVALID"
            row["status"] = "BASELINE_NUMERICAL_INVALID"
    _sync_wrapper_statuses(evidence)

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "BASELINE_NUMERICAL_EVIDENCE_INVALID" in gate["reason_codes"]


@pytest.mark.parametrize(
    "mutation",
    [
        "path_summary_type",
        "path_accounting",
        "path_duplicate_alpha",
        "path_failure_slot",
        "path_physical_flag_mismatch",
        "feasible_path_early_stop",
        "baseline_witness_mismatch",
    ],
)
def test_nested_audit_schema_is_fail_closed(pilot_config, mutation):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][0]
    if mutation == "path_summary_type":
        row["alpha_path_audit"]["power_flow_evaluations"] = "96"
    elif mutation == "path_accounting":
        row["alpha_path_audit"]["power_flow_evaluations"] -= 1
    elif mutation == "path_duplicate_alpha":
        row["alpha_path_audit"]["alpha_trace"].append(
            copy.deepcopy(row["alpha_path_audit"]["alpha_trace"][0])
        )
        row["alpha_path_audit"]["audit_calls"] += 1
        row["alpha_path_audit"]["complete_audits"] += 1
    elif mutation == "path_failure_slot":
        row["alpha_path_audit"]["alpha_trace"][-1][
            "first_failure_slot"
        ] = None
    elif mutation == "path_physical_flag_mismatch":
        trace = row["alpha_path_audit"]["alpha_trace"][-1]
        trace["feasible"] = False
        trace["failure_class"] = "NONE"
        trace["physical_violation_checks"] = 0
    elif mutation == "feasible_path_early_stop":
        trace = row["alpha_path_audit"]["alpha_trace"][1]
        trace["checked_intervals"] = 95
        trace["complete_coverage"] = False
        row["alpha_path_audit"]["complete_audits"] -= 1
        row["alpha_path_audit"]["early_stopped_audits"] += 1
    else:
        row["baseline_audit"]["explicit_physical_witness"] = True

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"


def test_frozen_threshold_drift_is_validity_stop(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    pilot_config["scientific_gate_thresholds"]["core_bad_alpha"][
        "bad_if_below"
    ] = 0.90

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert gate["reason_codes"] == ["GATE_CONFIG_INVALID"]


def test_sub_epsilon_frozen_threshold_drift_is_validity_stop(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    pilot_config["scientific_gate_thresholds"]["core_bad_alpha"][
        "bad_if_below"
    ] = 0.9500000000005

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"


def test_incomplete_baseline_slot_or_device_coverage_is_validity_stop(
    pilot_config,
):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][0]
    row["baseline_audit"]["slot_trace"].pop()
    row["baseline_audit"]["coverage_counts"]["rated_transformer_count"] = 0

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "BASELINE_EVIDENCE_INVALID" in gate["reason_codes"]


def test_selected_schedule_invariant_violation_is_validity_stop(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    evidence["evaluations"][0]["max_ev_invariant_error"] = 2e-6

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "SCHEDULE_INVARIANT_INVALID" in gate["reason_codes"]


def test_nested_schedule_invariant_must_match_combined_top_level(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    evidence["evaluations"][0]["derived_ev_invariant_errors"][
        "max_departure_error_kwh"
    ] = 100.0

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "SCHEDULE_INVARIANT_INVALID" in gate["reason_codes"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vmin", 0.1),
        ("vmax", 1.2),
        ("vufmax", 3.0),
        ("transformer_loading_max", 1.1),
        ("feeder_loading_max", 1.1),
    ],
)
def test_valid_baseline_extrema_must_satisfy_formal_limits(
    pilot_config, field, value
):
    evidence = _canonical_evidence(pilot_config)
    evidence["evaluations"][0]["baseline_audit"][field] = value

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "BASELINE_EVIDENCE_INVALID" in gate["reason_codes"]


def test_malformed_optional_timing_counter_is_axis_local(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    evidence["evaluations"][0]["alpha1_timing_power_flow_evaluations"] = [
        96,
        96,
        "96",
        96,
    ]

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["screening_compute_status"] == "INDETERMINATE_TIMING"


def test_timing_physical_counter_must_match_failure_class(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    evidence["evaluations"][0][
        "alpha1_timing_physical_violation_checks"
    ] = [5, 5, 5, 5]

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["screening_compute_status"] == "INDETERMINATE_TIMING"


def test_inconsistent_optional_tie_status_is_axis_local(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    evidence["evaluations"][0]["tie_break_status"] = "ERROR"

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["tie_break_route_status"] == "INDETERMINATE_REPEAT"


def test_tie_no_op_cannot_change_alpha_or_rescue_bad_rows(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    for row in evidence["evaluations"]:
        row["tie_break_status"] = "NO_OP"
        row["tie_schedule_sha256"] = row["schedule_sha256"]
    bad = next(row for row in evidence["evaluations"] if row["alpha_transfer"] < 0.95)
    _set_tied_alpha(bad, 1.0)

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALID"
    assert gate["tie_break_route_status"] == "INDETERMINATE_REPEAT"


def test_non_denominator_row_rejects_stale_optional_evidence(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    row = evidence["evaluations"][-1]
    _make_inactive(row)
    row["alpha_path_audit"] = _path_audit(1.0)
    row["alpha1_timing_status"] = "SUCCESS"
    _sync_wrapper_statuses(evidence)

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "NULL_SEMANTICS_INVALID" in gate["reason_codes"]


def test_wrapper_row_must_not_have_fields_missing_from_flattened_row(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    wrapped = copy.deepcopy(evidence["work_units"][0]["evaluations"][0])
    evidence["work_units"][0]["evaluations"][0] = wrapped
    evidence["evaluations"][0].pop("alpha_legacy_verifier")

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "WORK_UNIT_EVALUATION_LINK_INVALID" in gate["reason_codes"]


def test_wrapper_attempt_count_above_three_is_validity_stop(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    evidence["work_units"][0]["attempt_count"] = 4

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "WORK_UNIT_SCHEMA_INVALID" in gate["reason_codes"]


@pytest.mark.parametrize("mutation", ["empty", "missing", "duplicate", "extra"])
def test_raw_hash_rows_must_close_exact_sixteen_file_set(
    pilot_config, mutation
):
    evidence = _canonical_evidence(pilot_config)
    if mutation == "empty":
        evidence["raw_hash_rows"] = []
    elif mutation == "missing":
        evidence["raw_hash_rows"].pop()
    elif mutation == "duplicate":
        evidence["raw_hash_rows"][-1] = copy.deepcopy(
            evidence["raw_hash_rows"][0]
        )
    else:
        evidence["raw_hash_rows"].append(
            {
                "work_unit_id": "unexpected",
                "relative_path": "results/pilot_v2_1/work_units/unexpected.json",
                "sha256": _sha256("raw:unexpected"),
            }
        )

    gate = _assess(evidence, pilot_config)

    assert gate["validator_status"] == "VALIDITY_STOP"
    assert "RAW_HASH_ROWS_INVALID" in gate["reason_codes"]


def test_overall_priority_hard_no_go_beats_tie_pivot(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    _set_tie_outcome(evidence)
    _make_physical_baseline(
        evidence, pilot_config["scenario_ids"][2:]
    )

    gate = _assess(evidence, pilot_config)

    assert gate["tie_break_route_status"] == "PIVOT_TO_PHASE_BALANCED"
    assert gate["decision_class"] == "NO_GO"
    assert gate["overall_action"] == "NO_GO_REASSESS_BROAD_TOPIC"


def test_overall_priority_pivot_beats_nonhard_warning(pilot_config):
    evidence = _canonical_evidence(pilot_config)
    _set_tie_outcome(evidence)
    _make_physical_baseline(evidence, [pilot_config["scenario_ids"][7]])

    gate = _assess(evidence, pilot_config)

    assert gate["baseline_status"] == "WARN_REPEAT_BASELINE_COVERAGE"
    assert gate["tie_break_route_status"] == "PIVOT_TO_PHASE_BALANCED"
    assert gate["decision_class"] == "PIVOT"
