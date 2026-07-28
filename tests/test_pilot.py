from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _pilot_api():
    try:
        from evflex.pilot import load_pilot_config, validate_pilot_manifest
    except ModuleNotFoundError:
        pytest.fail("pilot validator is not implemented", pytrace=False)
    return load_pilot_config, validate_pilot_manifest


def _alpha_api():
    try:
        from evflex.pilot import evaluate_alpha_path
    except ImportError:
        pytest.fail("alpha-path evaluation is not implemented", pytrace=False)
    return evaluate_alpha_path


def _full_network_api():
    try:
        from evflex.pilot import full_network_check
    except ImportError:
        pytest.fail("full-network audit is not implemented", pytrace=False)
    return full_network_check


def _network_api():
    try:
        from evflex.pilot import build_pilot_network_class, configure_pilot_core
    except ImportError:
        pytest.fail("corrected pilot network is not implemented", pytrace=False)
    return build_pilot_network_class, configure_pilot_core


def _tie_break_api():
    try:
        from evflex.pilot import (
            canonical_schedule_sha256,
            phase_balanced_tie_break,
        )
    except ImportError:
        pytest.fail("phase-balanced tie-break is not implemented", pytrace=False)
    return canonical_schedule_sha256, phase_balanced_tie_break


def _work_unit_api():
    try:
        from evflex.pilot import evaluate_pilot_work_unit
    except ImportError:
        pytest.fail("pilot work-unit evaluator is not implemented", pytrace=False)
    return evaluate_pilot_work_unit


def _toy_ev(
    ev_id,
    phase,
    *,
    initial=0.0,
    target=0.5,
    reserve=0.0,
    arrival=0,
    departure=2,
    pch=2.0,
    pdis=0.0,
    v2g=False,
    max_discharge=0.0,
):
    return SimpleNamespace(
        ev_id=ev_id,
        capacity=10.0,
        initial=initial,
        target=target,
        reserve=reserve,
        arrival=arrival,
        departure=departure,
        pch=pch,
        pdis=pdis,
        eta_c=1.0,
        eta_d=1.0,
        v2g=v2g,
        max_discharge=max_discharge,
        bus="bus",
        phase=phase,
        kv_ln=0.24,
    )


def _toy_phase_case():
    fleet = [_toy_ev(1, 1), _toy_ev(2, 2), _toy_ev(3, 3)]
    baseline = np.zeros((3, 96), dtype=float)
    original = baseline.copy()
    original[:, 0] = [2.0, 0.0, 1.0]
    original[:, 1] = [0.0, 2.0, 1.0]
    return fleet, baseline, original


def _valid_frame() -> pd.DataFrame:
    return pd.read_csv(REPO_ROOT / "manifests" / "audit_pilot_work_units_v2_1.csv")


def test_exact_pilot_manifest_passes():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()

    report = validate_pilot_manifest(frame, config)

    assert report == {
        "work_units": 16,
        "unique_scenarios": 8,
        "evaluations": 48,
        "call_times": ["00:00", "02:00", "06:00", "19:00"],
        "feeders": ["ieee13", "lv906"],
        "directions": ["dec", "inc"],
        "durations": [15, 30, 60],
    }
    assert config["protocol_version"] == "EV-FLEX-BIAS-V2.1-PILOT"
    assert config["workers"] == 1
    assert config["numeric_threads"] == 1
    assert config["scientific_gate_thresholds"]["warm_timing"] == {
        "repeats": 3,
        "cv_pass_max": 0.2,
        "cv_indeterminate_above": 0.3,
    }


def test_core_manifest_head_is_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = pd.read_csv(REPO_ROOT / "manifests" / "core_work_units_v2_0.csv").head(16)

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_duplicate_work_unit_id_is_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    frame.loc[frame.index[1], "work_unit_id"] = frame.loc[frame.index[0], "work_unit_id"]

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_unique_work_unit_id_that_differs_from_v2_source_is_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    frame.loc[frame.index[0], "work_unit_id"] = "v20_work_unique_but_not_from_source"

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_format_valid_evaluation_ids_that_differ_from_v2_source_are_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    for index in frame.index:
        evaluation_ids = json.loads(frame.loc[index, "evaluation_ids"])
        evaluation_ids[0], evaluation_ids[1] = evaluation_ids[1], evaluation_ids[0]
        frame.loc[index, "evaluation_ids"] = json.dumps(evaluation_ids)
    config["durations_min"] = [30, 15, 60]

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_seed_that_differs_from_v2_manifest_is_rejected():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    frame.loc[frame.index[0], "scenario_seed"] += 1

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_fractional_pilot_seed_is_rejected_without_truncation():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    frame["scenario_seed"] = frame["scenario_seed"].astype(object)
    frame.loc[frame.index[0], "scenario_seed"] = 2026071616.5

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


def test_fractional_config_duration_is_rejected_without_truncation():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    config["durations_min"][0] = 15.9

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(_valid_frame(), config)


def test_fractional_v2_source_seed_is_rejected_without_truncation(tmp_path):
    load_pilot_config, _ = _pilot_api()
    (tmp_path / "config").mkdir()
    (tmp_path / "manifests").mkdir()
    shutil.copy2(
        REPO_ROOT / "config" / "pilot_gate_v2_1.json",
        tmp_path / "config" / "pilot_gate_v2_1.json",
    )
    source = pd.read_csv(REPO_ROOT / "manifests" / "core_work_units_v2_0.csv")
    source["scenario_seed"] = source["scenario_seed"].astype(object)
    source.loc[source["scenario_id"] == "ieee13_1900_17", "scenario_seed"] = (
        2026071616.5
    )
    source.to_csv(
        tmp_path / "manifests" / "core_work_units_v2_0.csv",
        index=False,
    )

    with pytest.raises(ValueError, match="pilot design"):
        load_pilot_config(tmp_path)


@pytest.mark.parametrize(
    "seed",
    [float("nan"), float("inf"), float("-inf"), True],
    ids=["nan", "positive-inf", "negative-inf", "bool"],
)
def test_non_finite_and_boolean_pilot_seeds_are_rejected(seed):
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    frame["scenario_seed"] = frame["scenario_seed"].astype(object)
    frame.loc[frame.index[0], "scenario_seed"] = seed

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)


@pytest.mark.parametrize(
    "duration",
    [float("nan"), float("inf"), float("-inf"), True],
    ids=["nan", "positive-inf", "negative-inf", "bool"],
)
def test_non_finite_and_boolean_config_durations_are_rejected(duration):
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    config["durations_min"][0] = duration

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(_valid_frame(), config)


def test_lossless_integer_like_numeric_values_are_accepted():
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    config["durations_min"] = ["15.0", 30.0, "60"]
    frame = _valid_frame()
    frame["scenario_seed"] = frame["scenario_seed"].map(lambda value: f"{value}.0")

    report = validate_pilot_manifest(frame, config)

    assert report["durations"] == [15, 30, 60]


def test_alpha_path_all_feasible_reaches_one():
    evaluate_alpha_path = _alpha_api()

    result = evaluate_alpha_path(lambda alpha: {"feasible": True, "alpha": alpha})

    assert result["valid_baseline"] is True
    assert result["alpha_prefix"] == 1.0
    assert result["scientific_alpha"] == 1.0
    assert result["alpha_sup"] == 1.0
    assert result["nonmonotone"] is False
    assert result["prefix_resolution"] == 0.0
    assert result["audit_calls"] == 51
    assert len(result["coarse_results"]) == 51
    assert result["refinement_results"] == []


def test_alpha_path_refines_first_monotone_failure_to_requested_tolerance():
    evaluate_alpha_path = _alpha_api()

    result = evaluate_alpha_path(lambda alpha: alpha <= 0.37)

    assert result["valid_baseline"] is True
    assert 0.368 <= result["alpha_prefix"] <= 0.37
    assert result["scientific_alpha"] == result["alpha_prefix"]
    assert result["alpha_sup"] == pytest.approx(0.37)
    assert result["nonmonotone"] is False
    assert result["prefix_resolution"] <= 0.002
    assert result["audit_calls"] == 51 + len(result["refinement_results"])


def test_alpha_path_reports_nonmonotone_feasible_island_without_crossing_it():
    evaluate_alpha_path = _alpha_api()

    result = evaluate_alpha_path(
        lambda alpha: alpha < 0.40 or 0.60 <= alpha < 0.70
    )

    assert result["valid_baseline"] is True
    assert result["nonmonotone"] is True
    assert 0.398 <= result["alpha_prefix"] < 0.40
    assert result["scientific_alpha"] == result["alpha_prefix"]
    assert result["alpha_sup"] >= 0.68
    assert all(
        item["alpha"] <= 0.40 for item in result["refinement_results"]
    )


def test_alpha_path_rejects_infeasible_baseline_as_a_scientific_alpha():
    evaluate_alpha_path = _alpha_api()

    result = evaluate_alpha_path(lambda alpha: alpha >= 0.50)

    assert result["valid_baseline"] is False
    assert result["alpha_prefix"] is None
    assert result["scientific_alpha"] is None
    assert result["alpha_sup"] == 1.0
    assert result["prefix_resolution"] is None
    assert result["audit_calls"] == 51


def test_alpha_path_default_coarse_grid_contains_exactly_51_ordered_points():
    evaluate_alpha_path = _alpha_api()
    seen = []

    result = evaluate_alpha_path(lambda alpha: seen.append(alpha) is None)

    assert seen == pytest.approx(
        [index / 50 for index in range(51)], rel=0.0, abs=1e-15
    )
    assert [item["alpha"] for item in result["coarse_results"]] == seen


def test_alpha_path_fine_scan_detects_hidden_island_in_first_coarse_interval():
    evaluate_alpha_path = _alpha_api()

    result = evaluate_alpha_path(
        lambda alpha: alpha < 0.385 or 0.390 <= alpha < 0.400
    )

    assert result["nonmonotone"] is True
    assert 0.383 <= result["alpha_prefix"] < 0.385
    assert result["alpha_sup"] >= 0.398
    assert result["prefix_resolution"] <= 0.002
    assert any(
        not item["feasible"] and 0.385 <= item["alpha"] < 0.390
        for item in result["refinement_results"]
    )
    assert any(
        item["feasible"] and 0.390 <= item["alpha"] < 0.400
        for item in result["refinement_results"]
    )


@pytest.mark.parametrize("feasible", ["false", 1, None])
def test_alpha_path_requires_boolean_feasibility(feasible):
    evaluate_alpha_path = _alpha_api()

    with pytest.raises(TypeError, match="boolean"):
        evaluate_alpha_path(lambda alpha: {"feasible": feasible})


def test_phase_tie_break_improves_phase_l1_and_preserves_every_bus_slot():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, original = _toy_phase_case()

    tied = phase_balanced_tie_break(
        engine,
        fleet,
        baseline,
        original,
        direction="inc",
        call_slots=[0],
    )

    assert tied["success"] is True
    assert tied["comparator_valid"] is True
    assert tied["status"] == "SUCCESS"
    assert tied["schedule"].shape == (3, 96)
    np.testing.assert_allclose(
        tied["bus_time_schedule"],
        tied["original_bus_time_schedule"],
        rtol=0.0,
        atol=1e-7,
    )
    # Slot 1 is outside the declared call but is part of energy recovery.
    np.testing.assert_allclose(
        tied["bus_time_schedule"][:, 1],
        tied["original_bus_time_schedule"][:, 1],
        rtol=0.0,
        atol=1e-7,
    )
    assert tied["max_bus_time_error_kw"] <= 1e-7
    assert tied["offer_relative_difference"] <= 0.005
    assert tied["primary_objective_relative_gap"] <= 1e-6
    assert (
        tied["phase_imbalance_objective"]
        <= tied["original_phase_imbalance_objective"] + 1e-8
    )
    assert tied["phase_imbalance_objective"] == pytest.approx(0.0, abs=1e-7)
    assert tied["simultaneous_slots"] == 0
    assert tied["max_ev_invariant_error"] <= 1e-6
    assert np.count_nonzero(tied["discharge"]) == 0


def test_phase_tie_break_preserves_dec_reserve_and_v2g_budget():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet = [
        _toy_ev(
            ev_id,
            phase,
            initial=1.0,
            target=1.0,
            reserve=0.5,
            pch=2.0,
            pdis=2.0,
            v2g=True,
            max_discharge=0.25,
        )
        for ev_id, phase in ((1, 1), (2, 2), (3, 3))
    ]
    baseline = np.zeros((3, 96), dtype=float)
    original = baseline.copy()
    original[:, 0] = -1.0
    original[:, 1] = 1.0

    tied = phase_balanced_tie_break(
        engine,
        fleet,
        baseline,
        original,
        direction="dec",
    )

    assert tied["success"] is True
    assert tied["comparator_valid"] is True
    assert tied["max_reserve_violation_kwh"] <= 1e-6
    assert tied["max_capacity_violation_kwh"] <= 1e-6
    assert tied["max_departure_error_kwh"] <= 1e-6
    assert tied["max_discharge_budget_violation_kwh"] <= 1e-6
    assert tied["simultaneous_slots"] == 0


def test_phase_tie_break_accepts_an_already_balanced_noop():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, _ = _toy_phase_case()
    balanced = baseline.copy()
    balanced[:, :2] = 1.0

    tied = phase_balanced_tie_break(
        engine,
        fleet,
        baseline,
        balanced,
        direction="inc",
    )

    assert tied["success"] is True
    assert tied["comparator_valid"] is True
    assert tied["status"] in {"SUCCESS", "NO_OP"}
    assert tied["phase_imbalance_objective"] == pytest.approx(
        tied["original_phase_imbalance_objective"], abs=1e-7
    )
    assert tied["original_schedule_sha256"] == tied["tied_schedule_sha256"]


def test_phase_tie_break_is_ev_id_canonical_and_hashes_exact_float64():
    canonical_schedule_sha256, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, original = _toy_phase_case()
    order = [2, 0, 1]
    shuffled_fleet = [fleet[index] for index in order]
    shuffled_baseline = baseline[order]
    shuffled_original = original[order]

    first = phase_balanced_tie_break(
        engine, fleet, baseline, original, direction="inc"
    )
    second = phase_balanced_tie_break(
        engine,
        shuffled_fleet,
        shuffled_baseline,
        shuffled_original,
        direction="inc",
    )

    assert first["original_schedule_sha256"] == second["original_schedule_sha256"]
    assert first["tied_schedule_sha256"] == second["tied_schedule_sha256"]
    assert first["vehicle_identity_sha256"] == second["vehicle_identity_sha256"]
    signed_zero = original.copy()
    signed_zero[0, 20] = -0.0
    assert canonical_schedule_sha256(fleet, signed_zero) == (
        canonical_schedule_sha256(fleet, original)
    )
    nearby = original.copy()
    nearby[0, 0] = np.nextafter(nearby[0, 0], np.inf)
    assert canonical_schedule_sha256(fleet, nearby) != (
        canonical_schedule_sha256(fleet, original)
    )


def test_schedule_hash_preserves_large_integer_ev_ids_without_float_rounding():
    canonical_schedule_sha256, _ = _tie_break_api()
    first_id = 2**53
    second_id = first_id + 1
    fleet = [_toy_ev(first_id, 1), _toy_ev(second_id, 2)]
    schedule = np.zeros((2, 96), dtype=float)
    schedule[0, 0] = 1.0
    schedule[1, 0] = 2.0

    first = canonical_schedule_sha256(fleet, schedule)
    second = canonical_schedule_sha256(
        [fleet[1], fleet[0]], schedule[[1, 0]]
    )

    assert first == second


def test_phase_tie_break_rejects_duplicate_identity_and_nonfinite_schedule():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, original = _toy_phase_case()
    duplicate = [fleet[0], _toy_ev(1, 2), fleet[2]]
    with pytest.raises(ValueError, match="ev_id"):
        phase_balanced_tie_break(
            engine, duplicate, baseline, original, direction="inc"
        )

    nonfinite = original.copy()
    nonfinite[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        phase_balanced_tie_break(
            engine, fleet, baseline, nonfinite, direction="inc"
        )


def test_phase_tie_break_rejects_conflicting_direction_and_mode():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, original = _toy_phase_case()

    with pytest.raises(ValueError, match="conflict"):
        phase_balanced_tie_break(
            engine,
            fleet,
            baseline,
            original,
            direction="inc",
            mode="v2g",
        )


def test_phase_tie_break_derives_offer_and_rejects_false_declared_identity():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, original = _toy_phase_case()

    tied = phase_balanced_tie_break(
        engine,
        fleet,
        baseline,
        original,
        direction="inc",
        call_slots=[0],
        offer_kw=999.0,
    )

    assert tied["success"] is True
    assert tied["original_offer_kw"] == pytest.approx(3.0)
    assert tied["declared_offer_kw"] == pytest.approx(999.0)
    assert tied["declared_offer_absolute_gap_kw"] == pytest.approx(996.0)
    assert tied["declared_offer_identity"] is False
    assert tied["comparator_valid"] is False
    assert tied["status"] == "COMPARATOR_INVALID"


def test_phase_tie_break_requires_original_primary_objective_identity():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet = [
        _toy_ev(1, 1, target=0.5),
        _toy_ev(2, 1, target=0.5),
    ]
    baseline = np.zeros((2, 96), dtype=float)
    baseline[0, :2] = [2.0, 0.0]
    baseline[1, :2] = [0.0, 2.0]
    original = baseline[[1, 0]].copy()

    tied = phase_balanced_tie_break(
        engine, fleet, baseline, original, direction="inc"
    )

    assert tied["success"] is True
    assert tied["primary_objective_original_relative_gap"] > 1e-6
    assert tied["primary_objective_tied_relative_gap"] <= 1e-6
    assert tied["comparator_valid"] is False
    assert tied["status"] == "COMPARATOR_INVALID"


def test_phase_tie_break_fails_closed_for_an_invalid_original_comparator():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, original = _toy_phase_case()
    original[:, 0] = [3.0, 0.0, 0.0]
    original[:, 1] = [-1.0, 2.0, 2.0]

    tied = phase_balanced_tie_break(
        engine, fleet, baseline, original, direction="inc"
    )

    assert tied["success"] is True
    assert tied["original_ev_invariants"]["max_ev_invariant_error"] > 1e-6
    assert tied["comparator_valid"] is False
    assert tied["status"] == "COMPARATOR_INVALID"


def test_phase_tie_break_returns_explicit_nulls_when_lp_is_infeasible():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet, baseline, original = _toy_phase_case()
    original[:, 0] = [7.0, 0.0, 0.0]
    original[:, 1] = [-5.0, 2.0, 2.0]

    tied = phase_balanced_tie_break(
        engine, fleet, baseline, original, direction="inc"
    )

    assert tied["success"] is False
    assert tied["comparator_valid"] is False
    assert tied["status"] == "PRIMARY_INFEASIBLE"
    assert tied["schedule"] is None
    assert tied["charge"] is None
    assert tied["discharge"] is None
    assert tied["tied_schedule_sha256"] is None
    assert tied["max_bus_time_error_kw"] is None


def test_phase_tie_break_never_moves_power_between_buses():
    _, phase_balanced_tie_break = _tie_break_api()
    from evflex.engine import load_archived_engine

    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    fleet = []
    for bus_offset, bus in enumerate(("a", "b")):
        for phase in (1, 2, 3):
            ev = _toy_ev(3 * bus_offset + phase, phase)
            ev.bus = bus
            fleet.append(ev)
    baseline = np.zeros((6, 96), dtype=float)
    original = baseline.copy()
    original[:3, 0] = [2.0, 0.0, 1.0]
    original[:3, 1] = [0.0, 2.0, 1.0]
    original[3:, 0] = [0.0, 2.0, 1.0]
    original[3:, 1] = [2.0, 0.0, 1.0]

    tied = phase_balanced_tie_break(
        engine, fleet, baseline, original, direction="inc"
    )

    assert tied["comparator_valid"] is True
    assert tied["bus_labels"] == ["a", "b"]
    assert tied["bus_time_schedule"].shape == (2, 96)
    np.testing.assert_allclose(
        tied["bus_time_schedule"],
        tied["original_bus_time_schedule"],
        rtol=0.0,
        atol=1e-7,
    )


class _FakePilotRuntime:
    def __init__(
        self,
        *,
        baseline_feasible=True,
        flex_by_duration=None,
        schedule_marker_by_duration=None,
        fail_durations=(),
        tie_comparator_valid=True,
    ):
        self.fleet = [_toy_ev(1, 1, departure=3)]
        self.baseline = np.zeros((1, 96), dtype=float)
        self.load_scales = np.ones(96, dtype=float)
        self.raw_calls = []
        self.cache_builds = 0
        self.baseline_calls = 0
        self.legacy_calls = 0
        self.tie_calls = 0
        self.timing_calls = 0
        self.audit_events = []
        self.retain_slot_results_calls = []
        self.baseline_feasible = baseline_feasible
        self.flex_by_duration = flex_by_duration or {
            15: 12.0,
            30: 11.0,
            60: 10.0,
        }
        self.schedule_marker_by_duration = schedule_marker_by_duration or {
            15: 0.15,
            30: 0.30,
            60: 0.60,
        }
        self.fail_durations = set(fail_durations)
        self.tie_comparator_valid = tie_comparator_valid

    def generate_balanced_raw(self, duration, model):
        self.raw_calls.append((duration, model))
        if duration in self.fail_durations:
            raise RuntimeError(f"solver failed for {duration}")
        schedule = self.baseline.copy()
        schedule[0, 0] = 1.0
        schedule[0, 1] = self.schedule_marker_by_duration[duration]
        schedule[0, 2] = 1.0 - self.schedule_marker_by_duration[duration]
        return {
            "success": True,
            "duration_min": duration,
            "call_slots": [0],
            "flex_kw": self.flex_by_duration[duration],
            "schedule": schedule,
            "physical_feasible": True,
            "max_departure_error_kwh": 0.0,
            "max_reserve_violation_kwh": 0.0,
            "max_capacity_violation_kwh": 0.0,
            "simultaneous_slots": 0,
        }

    def create_corrected_truth_cache(self):
        self.cache_builds += 1
        return object()

    def audit_corrected(
        self,
        schedule,
        cache,
        *,
        baseline_slot_results,
        stop_on_violation,
        retain_slot_results=True,
    ):
        assert cache is not None
        self.retain_slot_results_calls.append(retain_slot_results)
        alpha = float(np.asarray(schedule)[0, 0])
        baseline_call = baseline_slot_results is None
        if baseline_call:
            self.baseline_calls += 1
            self.audit_events.append("baseline")
            feasible = self.baseline_feasible
        else:
            feasible = alpha < 0.40 or 0.60 <= alpha < 0.70
            if not stop_on_violation:
                self.timing_calls += 1
                self.audit_events.append("timing")
            else:
                self.audit_events.append("path")
        checked = 96 if feasible or not stop_on_violation else 1
        return {
            "feasible": feasible,
            "checked_intervals": checked,
            "coverage_ratio": checked / 96.0,
            "complete_coverage": checked == 96,
            "eligible_for_v01_pass": feasible and checked == 96,
            "power_flow_evaluations": checked,
            "reused_baseline_intervals": 0,
            "converged_checks": checked,
            "nonconverged_checks": 0,
            "numerical_failure_checks": 0,
            "violations": [] if feasible else [{"slot": 0}],
            "slot_results": (
                [{"slot": slot} for slot in range(96)] if baseline_call else []
            ),
            "slot_audit_trace": [
                {
                    "slot": slot,
                    "feasible": feasible,
                    "failure_class": "NONE" if feasible else "PHYSICAL_CONSTRAINT",
                    "converged": True,
                    "numerical_failure": False,
                }
                for slot in range(checked)
            ],
            "physical_violation_checks": 0 if feasible else 1,
            "vmin": 0.99,
            "vmax": 1.01,
            "vufmax": 0.2,
            "transformer_loading_max": 0.5,
            "feeder_loading_max": 0.4,
            "coverage_counts": {
                "all_bus_count": 1,
                "monitored_bus_count": 1,
            },
        }

    def alpha_legacy_verifier(self, schedule):
        self.legacy_calls += 1
        return 0.73

    def phase_tie_break(self, schedule, *, direction, call_slots, offer_kw):
        from evflex.pilot import canonical_schedule_sha256

        self.tie_calls += 1
        schedule = np.asarray(schedule, dtype=float).copy()
        schedule_hash = canonical_schedule_sha256(self.fleet, schedule)
        return {
            "success": True,
            "comparator_valid": self.tie_comparator_valid,
            "status": (
                "NO_OP" if self.tie_comparator_valid else "COMPARATOR_INVALID"
            ),
            "schedule": schedule,
            "charge": np.maximum(schedule, 0.0),
            "discharge": np.maximum(-schedule, 0.0),
            "original_schedule_sha256": schedule_hash,
            "tied_schedule_sha256": schedule_hash,
            "vehicle_identity_sha256": "vehicle-hash",
            "original_bus_phase_time_sha256": "phase-hash",
            "tied_bus_phase_time_sha256": "phase-hash",
            "max_bus_time_error_kw": 0.0,
            "offer_relative_difference": 0.0,
            "offer_retention": 1.0,
            "primary_objective_original": 1.0,
            "primary_objective_optimum": 1.0,
            "primary_objective_tied": 1.0,
            "primary_objective_relative_gap": 0.0,
            "original_phase_imbalance_objective": 1.0,
            "phase_imbalance_objective": 1.0,
            "max_departure_error_kwh": 0.0,
            "max_reserve_violation_kwh": 0.0,
            "max_capacity_violation_kwh": 0.0,
            "max_discharge_budget_violation_kwh": 0.0,
            "max_ev_invariant_error": 0.0,
            "simultaneous_slots": 0,
        }


class _StepClock:
    def __init__(self, increment=0.01):
        self.value = 0.0
        self.increment = increment

    def __call__(self):
        self.value += self.increment
        return self.value


def _fake_work_unit():
    return {
        "work_unit_id": "fake_work",
        "scenario_id": "fake_scenario",
        "scenario_seed": 123,
        "data_role": "development_pilot",
        "feeder": "fake",
        "call_time": "19:00",
        "direction": "inc",
        "evaluation_ids": [
            "fake__inc__15m",
            "fake__inc__30m",
            "fake__inc__60m",
        ],
    }


def _fake_pilot_config(runtime):
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.1-PILOT",
        "durations_min": [15, 30, 60],
        "feeder_kva": {"fake": 100.0},
        "formal_constraints": {"vmax_pu": 1.06},
        "active_offer": {"minimum_kw": 7.2, "feeder_fraction": 0.005},
        "alpha_search": {"coarse_step": 0.02, "refine_tolerance": 0.002},
        "scientific_gate_thresholds": {"warm_timing": {"repeats": 3}},
        "_runtime_factory": lambda repo_root, work_unit, config: runtime,
    }


def test_pilot_work_unit_emits_three_compact_balanced_only_evaluations(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()
    runtime = _FakePilotRuntime()

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    assert [row["duration_min"] for row in rows] == [15, 30, 60]
    assert [row["evaluation_id"] for row in rows] == [
        "fake__inc__15m",
        "fake__inc__30m",
        "fake__inc__60m",
    ]
    assert runtime.raw_calls == [
        (15, "balanced"),
        (30, "balanced"),
        (60, "balanced"),
    ]
    assert runtime.cache_builds == 1
    assert runtime.baseline_calls == 1
    assert runtime.audit_events[0] == "baseline"
    assert runtime.audit_events[1] == "path"
    assert runtime.retain_slot_results_calls[0] is True
    assert all(
        retain is False for retain in runtime.retain_slot_results_calls[1:]
    )
    assert all(row["baseline_audit"]["checked_intervals"] == 96 for row in rows)
    assert all(len(row["baseline_audit"]["slot_trace"]) == 96 for row in rows)
    assert len({row["baseline_schedule_sha256"] for row in rows}) == 1
    assert all(row["alpha_transfer"] == row["alpha_prefix"] for row in rows)
    assert all(row["alpha_sup"] >= 0.68 for row in rows)
    assert all(row["alpha_nonmonotone"] is True for row in rows)
    assert all(row["alpha_legacy_verifier"] == 0.73 for row in rows)
    assert all(row["tie_comparator_valid"] is True for row in rows)
    assert all(row["alpha_path_status"] == "VALID" for row in rows)
    assert all(row["alpha_tie_path_status"] == "VALID" for row in rows)
    assert all(
        row["alpha_tie_path_audit"]["numerical_failure_audits"] == 0
        for row in rows
    )
    assert all(len(row["alpha1_warm_timing_s"]) == 3 for row in rows)
    assert all(row["alpha1_timing_status"] == "SUCCESS" for row in rows)
    assert all(
        row["alpha1_first_replay_scope"]
        == "FIRST_IN_PROCESS_REPLAY_NOT_COLD_START"
        for row in rows
    )
    assert all("alpha1_cold_timing_s" not in row for row in rows)
    assert runtime.timing_calls == 12
    assert all(
        row["alpha1_timing_checked_intervals"] == [96, 96, 96, 96]
        for row in rows
    )
    assert all(
        row["alpha1_timing_numerical_failure_checks"] == [0, 0, 0, 0]
        for row in rows
    )
    assert all(
        row["alpha1_timing_nonconverged_checks"] == [0, 0, 0, 0]
        for row in rows
    )
    encoded = json.dumps(rows, allow_nan=False)
    assert "f_3ph_kw" not in encoded
    assert "bias_pct" not in encoded
    assert "ndarray" not in encoded
    forbidden_array_keys = {
        "schedule",
        "charge",
        "discharge",
        "slot_results",
        "coarse_results",
        "refinement_results",
    }
    assert not any(
        key in forbidden_array_keys
        for row in rows
        for key in row
    )


def test_optional_diagnostic_exceptions_preserve_corrected_primary_result(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()

    class FailingDiagnosticsRuntime(_FakePilotRuntime):
        def alpha_legacy_verifier(self, schedule):
            self.legacy_calls += 1
            raise RuntimeError("legacy diagnostic exploded")

        def audit_corrected(self, *args, **kwargs):
            if (
                kwargs["baseline_slot_results"] is not None
                and not kwargs["stop_on_violation"]
            ):
                self.timing_calls += 1
                self.audit_events.append("timing")
                raise RuntimeError("timing diagnostic exploded")
            return super().audit_corrected(*args, **kwargs)

        def phase_tie_break(self, *args, **kwargs):
            self.tie_calls += 1
            raise RuntimeError("tie diagnostic exploded")

    runtime = FailingDiagnosticsRuntime()

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    assert len(rows) == 3
    assert runtime.audit_events[0] == "baseline"
    assert runtime.audit_events[1] == "path"
    assert all(row["status"] == "SUCCESS" for row in rows)
    assert all(row["scientific_status"] == "VALID" for row in rows)
    assert all(row["alpha_transfer"] is not None for row in rows)
    assert all(row["alpha_legacy_verifier"] is None for row in rows)
    assert all(row["alpha_legacy_verifier_status"] == "ERROR" for row in rows)
    assert all(
        "legacy diagnostic exploded"
        in row["alpha_legacy_verifier_detail"]
        for row in rows
    )
    assert all(row["alpha1_timing_status"] == "ERROR" for row in rows)
    assert all(row["alpha1_first_replay_timing_s"] is None for row in rows)
    assert all(row["alpha1_warm_timing_s"] == [] for row in rows)
    assert all("timing diagnostic exploded" in row["alpha1_timing_detail"] for row in rows)
    assert all(row["tie_comparator_valid"] is False for row in rows)
    assert all(row["tie_break_status"] == "ERROR" for row in rows)
    assert all("tie diagnostic exploded" in row["tie_break_detail"] for row in rows)


def test_numerical_candidate_invalidates_scientific_alpha_without_physical_boundary(
    tmp_path,
):
    evaluate_pilot_work_unit = _work_unit_api()

    class NumericalCandidateRuntime(_FakePilotRuntime):
        def audit_corrected(self, schedule, cache, **kwargs):
            result = super().audit_corrected(schedule, cache, **kwargs)
            alpha = float(np.asarray(schedule)[0, 0])
            if kwargs["stop_on_violation"] and alpha == pytest.approx(0.2):
                result.update(
                    {
                        "feasible": False,
                        "checked_intervals": 96,
                        "coverage_ratio": 1.0,
                        "complete_coverage": True,
                        "converged_checks": 95,
                        "nonconverged_checks": 1,
                        "numerical_failure_checks": 1,
                        "physical_violation_checks": 0,
                        "violations": [
                            {
                                "slot": 17,
                                "converged": False,
                                "numerical_failure": True,
                                "failure_class": "NUMERICAL_INVALID",
                                "violations": [
                                    {
                                        "kind": "numerical_failure",
                                        "reason": "nonconverged",
                                    }
                                ],
                            }
                        ],
                        "slot_audit_trace": [
                            {
                                "slot": slot,
                                "feasible": slot != 17,
                                "failure_class": (
                                    "NUMERICAL_INVALID" if slot == 17 else "NONE"
                                ),
                                "converged": slot != 17,
                                "numerical_failure": slot == 17,
                            }
                            for slot in range(96)
                        ],
                    }
                )
            return result

    runtime = NumericalCandidateRuntime()

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    assert all(row["alpha_transfer"] is None for row in rows)
    assert all(row["alpha_prefix"] is None for row in rows)
    assert all(row["alpha_sup"] is None for row in rows)
    assert all(row["alpha_nonmonotone"] is None for row in rows)
    assert all(
        row["scientific_status"] == "NUMERICAL_INVALID_ALPHA_PATH"
        for row in rows
    )
    assert all(row["status"] == "ALPHA_PATH_NUMERICAL_INVALID" for row in rows)
    trace = rows[0]["alpha_path_audit"]["alpha_trace"]
    numerical = next(item for item in trace if item["alpha"] == pytest.approx(0.2))
    assert numerical["failure_class"] == "NUMERICAL_INVALID"
    assert numerical["nonconverged_checks"] == 1
    assert numerical["checked_intervals"] == 96


def test_timing_and_tie_paths_expose_numerical_status_without_erasing_original(
    tmp_path,
):
    evaluate_pilot_work_unit = _work_unit_api()

    class DiagnosticNumericalRuntime(_FakePilotRuntime):
        def audit_corrected(self, schedule, cache, **kwargs):
            result = super().audit_corrected(schedule, cache, **kwargs)
            values = np.asarray(schedule, dtype=float)
            timing = (
                kwargs["baseline_slot_results"] is not None
                and not kwargs["stop_on_violation"]
            )
            tied_path = (
                kwargs["stop_on_violation"]
                and values[0, 3] > 0
                and values[0, 0] == pytest.approx(0.2)
            )
            if timing or tied_path:
                result.update(
                    {
                        "feasible": False,
                        "checked_intervals": 96,
                        "coverage_ratio": 1.0,
                        "complete_coverage": True,
                        "converged_checks": 95,
                        "nonconverged_checks": 1,
                        "numerical_failure_checks": 1,
                        "physical_violation_checks": 0,
                        "violations": [
                            {
                                "slot": 21,
                                "converged": False,
                                "numerical_failure": True,
                                "failure_class": "NUMERICAL_INVALID",
                                "physical_witness": False,
                                "violations": [
                                    {
                                        "kind": "numerical_failure",
                                        "reason": "nonconverged",
                                    }
                                ],
                            }
                        ],
                    }
                )
            return result

        def phase_tie_break(self, schedule, **kwargs):
            result = super().phase_tie_break(schedule, **kwargs)
            result["schedule"] = result["schedule"].copy()
            result["schedule"][0, 3] = 0.1
            return result

    runtime = DiagnosticNumericalRuntime()

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    assert all(row["alpha_path_status"] == "VALID" for row in rows)
    assert all(row["alpha_transfer"] is not None for row in rows)
    assert all(row["alpha1_timing_status"] == "NUMERICAL_INVALID" for row in rows)
    assert all(
        row["alpha1_timing_nonconverged_checks"] == [1, 1, 1, 1]
        for row in rows
    )
    assert all(
        row["alpha_tie_path_status"] == "NUMERICAL_INVALID"
        for row in rows
    )
    assert all(row["alpha_transfer_tied"] is None for row in rows)
    assert all(
        row["alpha_tie_path_audit"]["numerical_failure_audits"] > 0
        for row in rows
    )


def test_real_runtime_separates_corrected_scheduler_from_legacy_verifier(
    tmp_path, monkeypatch
):
    import evflex.engine as engine_module
    import evflex.fleet as fleet_module
    import evflex.network as network_module
    import evflex.pilot as pilot_module

    changed_cwd = tmp_path / "legacy-cwd"
    changed_cwd.mkdir()
    calls = {"duration": [], "cache": [], "safe": []}

    class FakeArchivedEngine:
        CALL_SLOTS = {"19:00": 28}

        def duration_result(
            self,
            core,
            feeder,
            fleet,
            baseline,
            tau,
            duration,
            direction,
            load_scales,
            model,
        ):
            calls["duration"].append((core, duration, model))
            return {
                "success": True,
                "duration_min": duration,
                "call_slots": [tau],
                "flex_kw": 8.0,
                "schedule": baseline.copy(),
                "max_departure_error_kwh": 0.0,
                "max_reserve_violation_kwh": 0.0,
                "max_capacity_violation_kwh": 0.0,
                "simultaneous_slots": 0,
                "model_network_check": {"feasible": True},
            }

        def network_cache(self, core, feeder, fleet, load_scales, model):
            calls["cache"].append((core, model))
            return {"core": core, "model": model}

        def safe_schedule_alpha(
            self,
            core,
            feeder,
            fleet,
            schedule,
            baseline,
            load_scales,
            model,
            cache,
        ):
            calls["safe"].append((core, model, cache))
            os.chdir(changed_cwd)
            return 0.81, {"feasible": True}

    class BaseNetwork:
        pass

    cores = [
        SimpleNamespace(Network=BaseNetwork, name="core-a"),
        SimpleNamespace(Network=BaseNetwork, name="core-b"),
    ]
    archived = FakeArchivedEngine()
    bundle = SimpleNamespace(
        scenario={"feeder": "fake", "call_time": "19:00"},
        fleet=[_toy_ev(1, 1)],
        baseline=np.zeros((1, 96), dtype=float),
        load_scales=np.ones(96, dtype=float),
    )
    configured = []
    corrected = []

    monkeypatch.setattr(
        engine_module, "load_archived_engine", lambda path: archived
    )
    monkeypatch.setattr(
        network_module, "load_legacy_core", lambda path: cores.pop(0)
    )
    monkeypatch.setattr(
        network_module,
        "configure_core",
        lambda core, repo: configured.append(core),
    )
    monkeypatch.setattr(
        fleet_module,
        "load_fleet_bundle",
        lambda repo, scenario_id, archived_engine, core: bundle,
    )

    def fake_configure_pilot_core(core, config):
        corrected.append(core)
        core.Network = type("CorrectedNetwork", (core.Network,), {})
        return core

    monkeypatch.setattr(
        pilot_module, "configure_pilot_core", fake_configure_pilot_core
    )

    runtime = pilot_module._create_real_pilot_runtime(
        tmp_path,
        _fake_work_unit(),
        _fake_pilot_config(_FakePilotRuntime()),
    )

    raw = runtime.generate_balanced_raw(15, "balanced")
    assert raw["physical_feasible"] is True
    assert calls["duration"] == [(runtime.corrected_core, 15, "balanced")]
    with pytest.raises(ValueError, match="balanced"):
        runtime.generate_balanced_raw(15, "3ph")
    runtime.create_corrected_truth_cache()
    assert calls["cache"][0] == (runtime.corrected_core, "3ph")
    original_cwd = os.getcwd()
    alpha = runtime.alpha_legacy_verifier(bundle.baseline)
    assert os.getcwd() == original_cwd
    assert alpha["alpha"] == 0.81
    assert calls["safe"][0][0] is runtime.legacy_core
    assert calls["safe"][0][0] is not runtime.corrected_core
    assert corrected == [runtime.corrected_core]
    assert configured == [runtime.corrected_core, runtime.legacy_core]
    assert runtime.legacy_core.Network._pilot_legacy_verifier_vmax == 1.06


def test_invalid_common_baseline_returns_three_scientific_terminal_rows(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()
    runtime = _FakePilotRuntime(baseline_feasible=False)

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    assert len(rows) == 3
    assert runtime.baseline_calls == 1
    assert runtime.legacy_calls == 0
    assert runtime.tie_calls == 0
    assert runtime.timing_calls == 0
    assert all(row["baseline_audit"]["checked_intervals"] == 96 for row in rows)
    assert all(row["baseline_audit"]["violation_count"] == 1 for row in rows)
    assert all(row["status"] == "BASELINE_PHYSICAL_INVALID" for row in rows)
    assert all(row["scientific_status"] == "INVALID_BASELINE" for row in rows)
    assert all(row["alpha_transfer"] is None for row in rows)
    assert all(row["alpha_legacy_verifier"] is None for row in rows)
    assert all(row["alpha_transfer_tied"] is None for row in rows)
    assert all(row["tie_comparator_valid"] is None for row in rows)
    assert all(
        row["eligible_for_scientific_denominator"] is False for row in rows
    )
    json.dumps(rows, allow_nan=False)


def test_active_threshold_is_inclusive_and_inactive_alpha_is_null(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()
    runtime = _FakePilotRuntime(
        flex_by_duration={15: 7.2, 30: 7.2, 60: 7.19}
    )

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    by_duration = {row["duration_min"]: row for row in rows}
    assert by_duration[15]["f_bal_kw"] == 7.2
    assert by_duration[15]["active_offer"] is True
    assert by_duration[30]["active_offer"] is True
    assert by_duration[60]["active_offer"] is False
    assert by_duration[60]["alpha_transfer"] is None
    assert by_duration[60]["alpha_legacy_verifier"] is None
    assert by_duration[60]["alpha_transfer_tied"] is None
    assert by_duration[60]["tie_comparator_valid"] is None
    assert by_duration[60]["eligible_for_scientific_denominator"] is False
    assert by_duration[60]["status"] == "INACTIVE_OFFER"
    assert runtime.legacy_calls == 2
    assert runtime.tie_calls == 2
    assert runtime.timing_calls == 8


def test_exact_schedule_hash_deduplicates_every_expensive_operation(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()
    runtime = _FakePilotRuntime(
        flex_by_duration={15: 10.0, 30: 12.0, 60: 9.0}
    )

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    by_duration = {row["duration_min"]: row for row in rows}
    assert by_duration[15]["source_duration_min"] == 30
    assert by_duration[30]["source_duration_min"] == 30
    assert by_duration[15]["schedule_sha256"] == by_duration[30][
        "schedule_sha256"
    ]
    assert by_duration[30]["canonical_schedule_reused"] is True
    assert by_duration[30]["reuse_source_requested_duration_min"] == 15
    assert by_duration[30]["legacy_verifier_reused"] is True
    assert (
        by_duration[30]["legacy_verifier_source_requested_duration_min"]
        == 15
    )
    assert by_duration[30]["tie_break_reused"] is True
    assert by_duration[30]["tie_break_source_requested_duration_min"] == 15
    assert by_duration[30]["timing_reused"] is True
    assert by_duration[30]["timing_source_requested_duration_min"] == 15
    assert by_duration[30]["timing_independent_schedule"] is False
    assert runtime.legacy_calls == 2
    assert runtime.tie_calls == 2
    assert runtime.timing_calls == 8


def test_nearby_but_distinct_float64_schedules_are_not_deduplicated(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()
    runtime = _FakePilotRuntime(
        schedule_marker_by_duration={
            15: 0.30,
            30: np.nextafter(0.30, np.inf),
            60: 0.60,
        }
    )

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    assert len({row["schedule_sha256"] for row in rows}) == 3
    assert all(row["canonical_schedule_reused"] is False for row in rows)
    assert all(row["legacy_verifier_reused"] is False for row in rows)
    assert all(row["tie_break_reused"] is False for row in rows)
    assert all(row["timing_reused"] is False for row in rows)
    assert runtime.legacy_calls == 3
    assert runtime.tie_calls == 3
    assert runtime.timing_calls == 12


def test_solver_invalid_duration_has_explicit_null_not_run_semantics(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()
    runtime = _FakePilotRuntime(fail_durations={60})

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    failed = next(row for row in rows if row["duration_min"] == 60)
    assert failed["status"] == "SCHEDULE_SOLVER_INVALID"
    assert failed["scientific_status"] == "INVALID_SCHEDULE"
    assert isinstance(failed["baseline_schedule_sha256"], str)
    assert len(failed["baseline_schedule_sha256"]) == 64
    assert failed["source_duration_min"] is None
    assert failed["alpha_transfer"] is None
    assert failed["alpha_legacy_verifier"] is None
    assert failed["alpha_transfer_tied"] is None
    assert failed["tie_comparator_valid"] is None
    assert failed["tie_break_status"] == "NOT_RUN_SCHEDULE_SOLVER_INVALID"
    assert failed["alpha1_first_replay_timing_s"] is None
    assert failed["alpha1_warm_timing_s"] == []
    assert failed["eligible_for_scientific_denominator"] is False
    json.dumps(rows, allow_nan=False)


def test_invalid_tie_comparator_cannot_supply_scientific_tie_alpha(tmp_path):
    evaluate_pilot_work_unit = _work_unit_api()
    runtime = _FakePilotRuntime(tie_comparator_valid=False)

    rows = evaluate_pilot_work_unit(
        tmp_path,
        _fake_work_unit(),
        config=_fake_pilot_config(runtime),
        perf_counter=_StepClock(),
    )

    assert all(row["status"] == "SUCCESS" for row in rows)
    assert all(row["alpha_transfer"] is not None for row in rows)
    assert all(row["tie_comparator_valid"] is False for row in rows)
    assert all(row["tie_break_status"] == "COMPARATOR_INVALID" for row in rows)
    assert all(row["alpha_transfer_tied"] is None for row in rows)
    assert all(row["alpha_tie_prefix"] is None for row in rows)
    assert all(row["alpha_tie_sup"] is None for row in rows)


def test_raw_balanced_schedule_recomputes_all_ev_invariants_without_defaults():
    import evflex.pilot as pilot_module

    fleet = [
        _toy_ev(
            1,
            1,
            initial=1.0,
            target=1.0,
            reserve=0.5,
            arrival=2,
            departure=4,
            pch=1.0,
            pdis=1.0,
            v2g=False,
            max_discharge=0.0,
        )
    ]
    baseline = np.zeros((1, 96), dtype=float)
    schedule = baseline.copy()
    schedule[0, 0] = 3.0
    schedule[0, 2] = -3.0
    raw = {
        "success": True,
        "physical_feasible": True,
        "flex_kw": 8.0,
        "schedule": schedule,
    }

    result = pilot_module._normalize_raw_balanced_result(
        raw,
        15,
        fleet,
        baseline,
        direction="dec",
    )

    assert result["physical_feasible"] is False
    assert result["max_availability_violation_kw"] == pytest.approx(3.0)
    assert result["max_discharge_limit_violation_kw"] == pytest.approx(3.0)
    assert result["max_discharge_budget_violation_kwh"] == pytest.approx(0.75)
    assert result["max_reserve_violation_kwh"] > 0
    assert result["max_ev_invariant_error"] >= 3.0
    assert set(result["ev_invariant_errors"]) == {
        "max_departure_error_kwh",
        "max_reserve_violation_kwh",
        "max_capacity_violation_kwh",
        "max_discharge_budget_violation_kwh",
        "max_availability_violation_kw",
        "max_charge_limit_violation_kw",
        "max_discharge_limit_violation_kw",
        "max_schedule_identity_error_kw",
        "simultaneous_slots",
        "max_ev_invariant_error",
    }


class _FakeAuditEngine:
    @staticmethod
    def group_vector(fleet, power, groups, model):
        assert groups == [("test", 1)]
        assert model == "3ph"
        return np.asarray(power, dtype=float)


def _fake_formal_coverage():
    return {
        "all_bus_count": 1,
        "monitored_bus_count": 1,
        "energized_voltage_node_count": 3,
        "monitored_voltage_node_count": 3,
        "three_phase_bus_count": 1,
        "monitored_vuf_bus_count": 1,
        "enabled_transformer_count": 1,
        "rated_transformer_count": 1,
        "transformer_rating_coverage": 1.0,
        "line_count": 1,
        "line_thermal_in_scope": False,
        "feeder_rating_multiplier": 1.0,
        "transformer_ratings_kva": {"tx1": 100.0},
        "transformer_raw_ratings_kva": {"tx1": 100.0},
        "transformer_rating_multiplier": 1.0,
        "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
        "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
    }


class _FakeAuditNetwork:
    def __init__(self, result_for_call=None, *, vmax=1.06):
        self.groups = [("test", 1)]
        self.feeder = "fake"
        self.model = "3ph"
        self.load_scale = 1.0
        self.vmin = 0.95
        self.vmax = float(vmax)
        self.vuf = 2.0
        self.feeder_kva = 100.0
        self.calls = []
        self._result_for_call = result_for_call

    def audit_context(self):
        return {
            "adapter_schema": "evflex.pilot.network-audit",
            "adapter_version": 2,
            "feeder": self.feeder,
            "model": self.model,
            "load_scale": self.load_scale,
            "vmin_pu": self.vmin,
            "vmax_pu": self.vmax,
            "vuf_limit_pct": self.vuf,
            "transformer_loading_limit_pu": 1.0,
            "feeder_loading_limit_pu": 1.0,
            "feeder_kva": self.feeder_kva,
            "line_thermal_in_scope": False,
            "transformer_rating_multiplier": 1.0,
            "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
            "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
        }

    def evaluate(self, power):
        call_index = len(self.calls)
        self.calls.append(np.asarray(power, dtype=float).copy())
        result = {
            "feasible": True,
            "converged": True,
            "numerical_failure": False,
            "violations": [],
            "metrics": {
                "V:test.1": 0.99,
                "V:test.2": 1.01,
                "V:test.3": 1.0,
                "U:test": 0.2,
                "S:transformer:tx1": 0.5,
                "S:feeder": 0.4,
            },
            "vmin": 0.99,
            "vmax": 1.01,
            "vufmax": 0.2,
            "transformer_loading_max": 0.5,
            "feeder_loading": 0.4,
            "coverage": _fake_formal_coverage(),
        }
        if self._result_for_call is not None:
            result.update(self._result_for_call(call_index))
        return result


def _audit_inputs(network):
    baseline = np.zeros((1, 96), dtype=float)
    return {
        "engine": _FakeAuditEngine,
        "feeder": "fake",
        "fleet": [object()],
        "schedule": baseline.copy(),
        "baseline": baseline,
        "load_scales": np.ones(96, dtype=float),
        "model": "3ph",
        "cache": {1.0: network},
    }


def test_full_network_check_audits_all_baseline_slots_without_cache():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()

    result = full_network_check(**_audit_inputs(network))

    assert result["feasible"] is True
    assert result["checked_intervals"] == 96
    assert result["coverage_ratio"] == 1.0
    assert result["complete_coverage"] is True
    assert result["power_flow_evaluations"] == 96
    assert result["reused_baseline_intervals"] == 0
    assert result["converged_checks"] == 96
    assert result["nonconverged_checks"] == 0
    assert len(result["slot_results"]) == 96
    assert len(network.calls) == 96


def test_full_network_check_reuses_only_exact_verified_baseline_slots():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()
    inputs = _audit_inputs(network)
    baseline_result = full_network_check(**inputs)
    network.calls.clear()

    result = full_network_check(
        **inputs,
        baseline_slot_results=baseline_result["slot_results"],
    )

    assert result["feasible"] is True
    assert result["checked_intervals"] == 96
    assert result["coverage_ratio"] == 1.0
    assert result["power_flow_evaluations"] == 0
    assert result["reused_baseline_intervals"] == 96
    assert result["converged_checks"] == 96
    assert network.calls == []


def test_full_network_cache_records_carry_validated_formal_integrity():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()

    result = full_network_check(**_audit_inputs(network))
    record = result["slot_results"][0]

    assert "coverage" in record
    assert "formal_integrity" in record
    assert record["formal_integrity"]["validated"] is True
    assert record["formal_integrity"]["metrics_finite"] is True
    assert record["formal_integrity"]["coverage_complete"] is True
    assert record["result"]["formal_integrity"] == record["formal_integrity"]
    assert record["result"]["coverage"] == record["coverage"]


def test_full_network_cache_does_not_cross_stricter_network_context():
    full_network_check = _full_network_api()
    baseline_network = _FakeAuditNetwork(vmax=1.06)
    inputs = _audit_inputs(baseline_network)
    baseline_result = full_network_check(**inputs)
    stricter_network = _FakeAuditNetwork(vmax=1.02)

    result = full_network_check(
        **{**inputs, "cache": {1.0: stricter_network}},
        baseline_slot_results=baseline_result["slot_results"],
    )

    assert result["power_flow_evaluations"] == 96
    assert result["reused_baseline_intervals"] == 0
    assert len(stricter_network.calls) == 96


def test_full_network_cache_binds_exact_current_group_power_vector():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()
    inputs = _audit_inputs(network)
    baseline_result = full_network_check(**inputs)
    network.calls.clear()

    class OffsetAuditEngine:
        @staticmethod
        def group_vector(fleet, power, groups, model):
            return np.asarray(power, dtype=float) + 0.25

    result = full_network_check(
        **{**inputs, "engine": OffsetAuditEngine},
        baseline_slot_results=baseline_result["slot_results"],
    )

    assert result["power_flow_evaluations"] == 96
    assert result["reused_baseline_intervals"] == 0
    assert len(network.calls) == 96


@pytest.mark.parametrize(
    "field",
    ["feasible", "converged", "numerical_failure"],
)
def test_full_network_invalid_boolean_result_fails_closed(field):
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork(
        lambda call_index: {field: "false"}
    )

    result = full_network_check(**_audit_inputs(network))

    assert result["feasible"] is False
    assert result["power_flow_evaluations"] == 96
    assert result["numerical_failure_checks"] == 96


@pytest.mark.parametrize(
    "field",
    ["feasible", "converged", "numerical_failure"],
)
def test_full_network_cache_rechecks_invalid_boolean_result(field):
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()
    inputs = _audit_inputs(network)
    baseline_result = full_network_check(**inputs)
    baseline_result["slot_results"][31]["result"][field] = "false"
    network.calls.clear()

    result = full_network_check(
        **inputs,
        baseline_slot_results=baseline_result["slot_results"],
    )

    assert result["feasible"] is True
    assert result["power_flow_evaluations"] == 1
    assert result["reused_baseline_intervals"] == 95
    assert len(network.calls) == 1


def test_full_network_invalid_violations_type_is_numerical_failure():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork(
        lambda call_index: {"violations": "none"}
    )

    result = full_network_check(**_audit_inputs(network))

    assert result["feasible"] is False
    assert result["numerical_failure_checks"] == 96
    assert all(
        item["numerical_failure"] is True for item in result["violations"]
    )


def test_full_network_cache_rechecks_nonfinite_metric_before_reuse():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()
    inputs = _audit_inputs(network)
    baseline_result = full_network_check(**inputs)
    baseline_result["slot_results"][17]["result"]["metrics"]["V:test.1"] = float(
        "nan"
    )
    network.calls.clear()

    result = full_network_check(
        **inputs,
        baseline_slot_results=baseline_result["slot_results"],
    )

    assert result["feasible"] is True
    assert result["power_flow_evaluations"] == 1
    assert result["reused_baseline_intervals"] == 95
    assert len(network.calls) == 1


def test_full_network_cache_does_not_reuse_record_without_coverage():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()
    inputs = _audit_inputs(network)
    baseline_result = full_network_check(**inputs)
    record = baseline_result["slot_results"][23]
    record.pop("coverage", None)
    record["result"].pop("coverage", None)
    network.calls.clear()

    result = full_network_check(
        **inputs,
        baseline_slot_results=baseline_result["slot_results"],
    )

    assert result["feasible"] is True
    assert result["power_flow_evaluations"] == 1
    assert result["reused_baseline_intervals"] == 95
    assert len(network.calls) == 1


def test_full_network_check_tiny_nonzero_change_still_triggers_power_flow():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()
    inputs = _audit_inputs(network)
    baseline_result = full_network_check(**inputs)
    network.calls.clear()
    schedule = inputs["baseline"].copy()
    schedule[0, 37] = 0.001

    result = full_network_check(
        **{**inputs, "schedule": schedule},
        baseline_slot_results=baseline_result["slot_results"],
    )

    assert result["checked_intervals"] == 96
    assert result["power_flow_evaluations"] == 1
    assert result["reused_baseline_intervals"] == 95
    assert len(network.calls) == 1
    assert network.calls[0][0] == pytest.approx(0.001)


def test_full_network_check_records_nonconvergence_separately():
    full_network_check = _full_network_api()

    def result_for_call(call_index):
        if call_index == 9:
            return {
                "feasible": False,
                "converged": False,
                "numerical_failure": True,
                "violations": [],
            }
        return {}

    network = _FakeAuditNetwork(result_for_call)

    result = full_network_check(**_audit_inputs(network))

    assert result["feasible"] is False
    assert result["checked_intervals"] == 96
    assert result["converged_checks"] == 95
    assert result["nonconverged_checks"] == 1
    assert result["violations"][0]["slot"] == 9
    assert result["violations"][0]["converged"] is False
    assert result["violations"][0]["numerical_failure"] is True


def test_full_network_check_early_stop_cannot_claim_complete_coverage():
    full_network_check = _full_network_api()

    def result_for_call(call_index):
        if call_index == 0:
            return {
                "feasible": False,
                "violations": [
                    {
                        "kind": "physical_constraint",
                        "metric": "V:test.1",
                        "value": 0.90,
                        "limit": 0.95,
                        "direction": "lo",
                    }
                ],
            }
        return {}

    network = _FakeAuditNetwork(result_for_call)

    result = full_network_check(
        **_audit_inputs(network),
        stop_on_violation=True,
    )

    assert result["feasible"] is False
    assert result["checked_intervals"] == 1
    assert result["coverage_ratio"] == pytest.approx(1 / 96)
    assert result["complete_coverage"] is False
    assert result["eligible_for_v01_pass"] is False
    assert result["power_flow_evaluations"] == 1
    assert result["violations"][0]["failure_class"] == "PHYSICAL_CONSTRAINT"
    assert result["violations"][0]["physical_witness"] is True


def test_full_network_check_compact_mode_does_not_retain_full_metric_records():
    full_network_check = _full_network_api()
    network = _FakeAuditNetwork()
    inputs = _audit_inputs(network)
    baseline_result = full_network_check(**inputs)
    network.calls.clear()

    compact = full_network_check(
        **inputs,
        baseline_slot_results=baseline_result["slot_results"],
        retain_slot_results=False,
    )

    assert compact["feasible"] is True
    assert compact["checked_intervals"] == 96
    assert compact["slot_results"] == []
    assert len(compact["slot_audit_trace"]) == 96
    assert all(
        set(item)
        <= {
            "slot",
            "feasible",
            "converged",
            "numerical_failure",
            "failure_class",
            "physical_witness",
        }
        for item in compact["slot_audit_trace"]
    )
    assert compact["coverage_counts"]["all_bus_count"] == 1
    assert compact["reused_baseline_intervals"] == 96
    assert network.calls == []


def test_full_network_check_never_early_stops_on_numerical_failure():
    full_network_check = _full_network_api()

    def result_for_call(call_index):
        if call_index == 0:
            return {
                "feasible": False,
                "converged": False,
                "numerical_failure": True,
                "violations": [
                    {
                        "kind": "numerical_failure",
                        "reason": "nonconverged",
                        "metric": "power_flow",
                    }
                ],
            }
        return {}

    network = _FakeAuditNetwork(result_for_call)

    result = full_network_check(
        **_audit_inputs(network),
        stop_on_violation=True,
        retain_slot_results=False,
    )

    assert result["feasible"] is False
    assert result["checked_intervals"] == 96
    assert result["nonconverged_checks"] == 1
    assert result["numerical_failure_checks"] == 1
    assert result["physical_violation_checks"] == 0
    assert result["violations"][0]["failure_class"] == "NUMERICAL_INVALID"
    assert result["violations"][0]["physical_witness"] is False


class _FakeSolution:
    def __init__(self, context):
        self.context = context

    def Solve(self):
        self.context.solve_calls += 1

    def Converged(self):
        return self.context.load_scale != 0.0


class _FakeCircuit:
    def __init__(self, context):
        self.context = context

    def AllNodeNames(self):
        return ["bus.1", "bus.2", "bus.3"]

    def AllBusMagPu(self):
        if self.context.load_scale < 0.0:
            return [1.0, float("nan"), 1.0]
        if self.context.load_scale == 2.0:
            return [0.94, 1.07, 1.0]
        return [0.99, 1.01, 1.0]

    def AllBusNames(self):
        return ["bus"]

    def SetActiveBus(self, name):
        self.context.active_bus = name

    def SetActiveElement(self, name):
        self.context.active_element = name

    def TotalPower(self):
        return [150.0, 0.0] if self.context.load_scale == 2.0 else [40.0, 0.0]


class _FakeBus:
    def __init__(self, context):
        self.context = context

    def Nodes(self):
        return [1, 2, 3]

    def puVmagAngle(self):
        magnitudes = self.context.Circuit.AllBusMagPu()
        return [
            magnitudes[0],
            0.0,
            magnitudes[1],
            -120.0,
            magnitudes[2],
            120.0,
        ]

    def SeqVoltages(self):
        if self.context.load_scale == 2.0:
            return [0.0, 1.0, 0.03]
        return [0.0, 1.0, 0.01]


class _FakeTransformers:
    def __init__(self, context):
        self.context = context

    def AllNames(self):
        return ["tx1"]

    def Name(self, name):
        self.context.active_transformer = name

    def Wdg(self, winding):
        self.context.active_winding = winding

    def kVA(self):
        return 100.0


class _FakeCktElement:
    def __init__(self, context):
        self.context = context

    def Enabled(self):
        return True

    def TotalPowers(self):
        power = 120.0 if self.context.load_scale == 2.0 else 50.0
        return [power, 0.0, -power, 0.0]

    def NumTerminals(self):
        return 2

    def NumPhases(self):
        return 1


class _FakeLines:
    @staticmethod
    def AllNames():
        return ["line1", "line2"]


class _FakePilotContext:
    def __init__(self, load_scale):
        self.load_scale = float(load_scale)
        self.solve_calls = 0
        self.active_bus = None
        self.active_element = None
        self.active_transformer = None
        self.active_winding = None
        self.Solution = _FakeSolution(self)
        self.Circuit = _FakeCircuit(self)
        self.Bus = _FakeBus(self)
        self.Transformers = _FakeTransformers(self)
        self.CktElement = _FakeCktElement(self)
        self.Lines = _FakeLines()


class _DynamicDispatchNetwork:
    def __init__(
        self,
        feeder,
        fleet_frame,
        model,
        load_scale,
        vmin=0.95,
        vmax=1.05,
        vuf=2.0,
    ):
        self.feeder = feeder
        self.model = model
        self.load_scale = float(load_scale)
        self.vmin = vmin
        self.vmax = vmax
        self.vuf = vuf
        self.groups = [("bus", 1)]
        self.labels = None
        self.ctx = _FakePilotContext(load_scale)
        self.legacy_evaluate_calls = 0
        self._prepare()

    def _prepare(self):
        self.base = self.evaluate(np.zeros(1))

    def evaluate(self, power):
        self.legacy_evaluate_calls += 1
        return {
            "feasible": True,
            "converged": True,
            "violations": [],
            "metrics": {},
        }

    def setp(self, power):
        self.last_power = np.asarray(power, dtype=float)


def _minimal_network_config():
    return {
        "formal_constraints": {
            "vmin_pu": 0.95,
            "vmax_pu": 1.06,
            "vuf_limit_pct": 2.0,
            "transformer_loading_limit_pu": 1.0,
            "feeder_loading_limit_pu": 1.0,
            "line_thermal_in_scope": False,
        },
        "feeder_kva": {"fake": 100.0},
    }


def test_pilot_network_handles_legacy_prepare_dynamic_dispatch():
    build_pilot_network_class, _ = _network_api()
    pilot_class = build_pilot_network_class(
        _DynamicDispatchNetwork, _minimal_network_config()
    )

    network = pilot_class("fake", object(), "3ph", 1.0)

    assert network.legacy_evaluate_calls == 1
    assert network.vmin == 0.95
    assert network.vmax == 1.06
    assert network.vuf == 2.0
    assert network.base["feasible"] is True
    assert network.base["converged"] is True
    assert network.base["numerical_failure"] is False
    assert network.base["transformer_loading_max"] == pytest.approx(0.5)
    assert network.base["feeder_loading"] == pytest.approx(0.4)
    coverage = network.coverage_report()
    assert coverage["all_bus_count"] == 1
    assert coverage["monitored_bus_count"] == 1
    assert coverage["energized_voltage_node_count"] == 3
    assert coverage["monitored_voltage_node_count"] == 3
    assert coverage["three_phase_bus_count"] == 1
    assert coverage["monitored_vuf_bus_count"] == 1
    assert coverage["enabled_transformer_count"] == 1
    assert coverage["rated_transformer_count"] == 1
    assert coverage["transformer_rating_coverage"] == 1.0
    assert coverage["line_count"] == 2
    assert coverage["line_thermal_in_scope"] is False
    assert coverage["feeder_rating_multiplier"] == 1.0
    assert coverage["transformer_ratings_kva"] == {"tx1": 100.0}
    assert coverage["transformer_raw_ratings_kva"] == {"tx1": 100.0}
    assert coverage["transformer_rating_basis"] == "NATIVE_SYSTEM_TOTAL_KVA"
    assert coverage["transformer_rating_multiplier"] == 1.0


def test_balanced_positive_sequence_transformer_rating_is_normalized_to_system_total():
    build_pilot_network_class, _ = _network_api()
    config = _minimal_network_config()
    config["feeder_kva"]["ieee13"] = 5000.0
    pilot_class = build_pilot_network_class(_DynamicDispatchNetwork, config)

    network = pilot_class("ieee13", object(), "balanced", 1.0)
    coverage = network.coverage_report()

    assert network.base["transformer_loading_max"] == pytest.approx(50.0 / 300.0)
    assert coverage["transformer_raw_ratings_kva"] == {"tx1": 100.0}
    assert coverage["transformer_ratings_kva"] == {"tx1": 300.0}
    assert (
        coverage["transformer_rating_basis"]
        == "MAKEPOSSEQ_PER_PHASE_KVA_NORMALIZED_TO_SYSTEM_TOTAL"
    )
    assert coverage["transformer_power_basis"] == "SYSTEM_TOTAL_TERMINAL_POWER"
    assert coverage["transformer_rating_multiplier"] == 3.0


def test_pilot_network_restores_cwd_after_legacy_construction(tmp_path):
    build_pilot_network_class, _ = _network_api()
    original_cwd = os.getcwd()
    changed_cwd = tmp_path / "compiled_feeder"
    changed_cwd.mkdir()

    class CwdChangingNetwork(_DynamicDispatchNetwork):
        def __init__(self, *args, **kwargs):
            os.chdir(changed_cwd)
            super().__init__(*args, **kwargs)

    pilot_class = build_pilot_network_class(
        CwdChangingNetwork, _minimal_network_config()
    )
    try:
        pilot_class("fake", object(), "3ph", 1.0)

        assert os.getcwd() == original_cwd
    finally:
        os.chdir(original_cwd)


def test_pilot_network_restores_cwd_when_legacy_construction_raises(tmp_path):
    build_pilot_network_class, _ = _network_api()
    original_cwd = os.getcwd()
    changed_cwd = tmp_path / "failed_compile"
    changed_cwd.mkdir()

    class FailingCwdNetwork:
        def __init__(self, *args, **kwargs):
            os.chdir(changed_cwd)
            raise RuntimeError("compile failed")

    pilot_class = build_pilot_network_class(
        FailingCwdNetwork, _minimal_network_config()
    )
    try:
        with pytest.raises(RuntimeError, match="compile failed"):
            pilot_class("fake", object(), "3ph", 1.0)

        assert os.getcwd() == original_cwd
    finally:
        os.chdir(original_cwd)


def test_configure_pilot_core_replaces_only_the_in_memory_network_class():
    _, configure_pilot_core = _network_api()

    class Core:
        Network = _DynamicDispatchNetwork

    original = Core.Network
    returned = configure_pilot_core(Core, _minimal_network_config())

    assert returned is Core
    assert Core.Network is not original
    assert issubclass(Core.Network, original)


def test_pilot_network_enforces_all_formal_constraints_without_line_thermal():
    build_pilot_network_class, _ = _network_api()
    pilot_class = build_pilot_network_class(
        _DynamicDispatchNetwork, _minimal_network_config()
    )

    result = pilot_class("fake", object(), "3ph", 2.0).base
    violation_metrics = {
        violation["metric"]
        for violation in result["violations"]
        if violation["kind"] == "physical_constraint"
    }

    assert result["feasible"] is False
    assert result["converged"] is True
    assert result["numerical_failure"] is False
    assert {
        "V:bus.1",
        "V:bus.2",
        "U:bus",
        "S:transformer:tx1",
        "S:feeder",
    } <= violation_metrics
    assert not any(metric.startswith("I:") for metric in result["metrics"])
    assert result["line_thermal_in_scope"] is False


@pytest.mark.parametrize(
    ("load_scale", "expected_reason"),
    [(0.0, "nonconverged"), (-1.0, "formal_metric_unavailable")],
)
def test_pilot_network_marks_numerical_and_missing_metric_failures(
    load_scale, expected_reason
):
    build_pilot_network_class, _ = _network_api()
    pilot_class = build_pilot_network_class(
        _DynamicDispatchNetwork, _minimal_network_config()
    )

    result = pilot_class("fake", object(), "3ph", load_scale).base

    assert result["feasible"] is False
    assert result["numerical_failure"] is True
    assert any(
        violation["kind"] == "numerical_failure"
        and violation["reason"] == expected_reason
        for violation in result["violations"]
    )


@pytest.mark.parametrize(
    ("scenario_id", "feeder", "call_time", "expected_buses", "expected_transformers"),
    [
        ("ieee13_1900_17", "ieee13", "19:00", 16, 5),
        ("lv906_1900_18", "lv906", "19:00", 907, 1),
    ],
)
def test_real_three_phase_pilot_network_has_complete_formal_coverage(
    scenario_id,
    feeder,
    call_time,
    expected_buses,
    expected_transformers,
):
    load_pilot_config, _ = _pilot_api()
    _, configure_pilot_core = _network_api()
    from evflex.engine import load_archived_engine
    from evflex.fleet import load_fleet_bundle
    from evflex.network import configure_core, load_legacy_core

    config = load_pilot_config(REPO_ROOT)
    archived_engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    core = load_legacy_core(
        REPO_ROOT / "legacy" / "d5_v1_2" / "network_core_v1_2.py"
    )
    configure_core(core, REPO_ROOT)
    configure_pilot_core(core, config)
    bundle = load_fleet_bundle(REPO_ROOT, scenario_id, archived_engine, core)
    static_fleet = archived_engine.static_fleet_frame(bundle.fleet)
    slot = archived_engine.CALL_SLOTS[call_time]

    network = core.Network(
        feeder,
        static_fleet,
        "3ph",
        float(bundle.load_scales[slot]),
    )
    result = network.base
    coverage = network.coverage_report()

    assert result["converged"] is True
    assert result["numerical_failure"] is False
    assert coverage["all_bus_count"] == expected_buses
    assert coverage["monitored_bus_count"] == expected_buses
    assert coverage["energized_voltage_node_count"] > 0
    assert (
        coverage["monitored_voltage_node_count"]
        == coverage["energized_voltage_node_count"]
    )
    assert coverage["three_phase_bus_count"] > 0
    assert (
        coverage["monitored_vuf_bus_count"]
        == coverage["three_phase_bus_count"]
    )
    assert coverage["enabled_transformer_count"] == expected_transformers
    assert coverage["rated_transformer_count"] == expected_transformers
    assert coverage["transformer_rating_coverage"] == 1.0
    assert len(coverage["transformer_ratings_kva"]) == expected_transformers
    assert all(
        np.isfinite(rating) and rating > 0
        for rating in coverage["transformer_ratings_kva"].values()
    )
    assert coverage["line_count"] > 0
    assert coverage["line_thermal_in_scope"] is False
    assert coverage["feeder_rating_multiplier"] == 1.0
    assert not any(metric.startswith("I:") for metric in result["metrics"])
    transformer_metrics = [
        value
        for name, value in result["metrics"].items()
        if name.startswith("S:transformer:")
    ]
    assert len(transformer_metrics) == expected_transformers
    assert np.isfinite(transformer_metrics).all()
    total_power = network.ctx.Circuit.TotalPower()
    expected_feeder_loading = np.hypot(total_power[0], total_power[1]) / config[
        "feeder_kva"
    ][feeder]
    assert result["feeder_loading"] == pytest.approx(expected_feeder_loading)


def test_real_ieee13_balanced_transformer_rating_basis_smoke():
    load_pilot_config, _ = _pilot_api()
    _, configure_pilot_core = _network_api()
    from evflex.engine import load_archived_engine
    from evflex.fleet import load_fleet_bundle
    from evflex.network import configure_core, load_legacy_core

    config = load_pilot_config(REPO_ROOT)
    engine = load_archived_engine(
        REPO_ROOT / "legacy" / "d5_v1_2" / "duration_aware_engine_v1_2.py"
    )
    core = load_legacy_core(
        REPO_ROOT / "legacy" / "d5_v1_2" / "network_core_v1_2.py"
    )
    configure_core(core, REPO_ROOT)
    configure_pilot_core(core, config)
    bundle = load_fleet_bundle(
        REPO_ROOT, "ieee13_1900_17", engine, core
    )
    static_fleet = engine.static_fleet_frame(bundle.fleet)
    network = core.Network(
        "ieee13",
        static_fleet,
        "balanced",
        float(bundle.load_scales[engine.CALL_SLOTS["19:00"]]),
    )
    coverage = network.coverage_report()

    assert network.base["converged"] is True
    assert network.base["numerical_failure"] is False
    assert coverage["transformer_rating_multiplier"] == 3.0
    assert (
        coverage["transformer_rating_basis"]
        == "MAKEPOSSEQ_PER_PHASE_KVA_NORMALIZED_TO_SYSTEM_TOTAL"
    )
    assert coverage["transformer_raw_ratings_kva"]["sub"] == pytest.approx(
        5000.0 / 3.0
    )
    assert coverage["transformer_ratings_kva"]["sub"] == pytest.approx(5000.0)
    assert coverage["transformer_ratings_kva"]["reg1"] == pytest.approx(4998.0)
    assert coverage["transformer_ratings_kva"]["xfm1"] == pytest.approx(500.0)
    transformer_loadings = [
        value
        for name, value in network.base["metrics"].items()
        if name.startswith("S:transformer:")
    ]
    assert max(transformer_loadings) < 1.0


def _drop_one_direction(frame: pd.DataFrame) -> None:
    frame.drop(index=frame.index[1], inplace=True)


def _change_scenario_feeder(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "feeder"] = "lv906"


def _change_scenario_call_time(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "call_time"] = "00:00"


def _change_protocol(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "protocol_version"] = "EV-FLEX-BIAS-V2.0"


def _change_role(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "data_role"] = "development"


def _change_holdout_access(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "holdout_access"] = "development_only"


def _change_status(frame: pd.DataFrame) -> None:
    frame.loc[frame.index[0], "status"] = "SUCCESS"


def _change_evaluation_durations(frame: pd.DataFrame) -> None:
    evaluation_ids = json.loads(frame.loc[frame.index[0], "evaluation_ids"])
    evaluation_ids[-1] = evaluation_ids[-1].replace("__60m", "__45m")
    frame.loc[frame.index[0], "evaluation_ids"] = json.dumps(evaluation_ids)


def _change_evaluation_direction(frame: pd.DataFrame) -> None:
    evaluation_ids = json.loads(frame.loc[frame.index[0], "evaluation_ids"])
    evaluation_ids[0] = evaluation_ids[0].replace("__inc__", "__dec__")
    frame.loc[frame.index[0], "evaluation_ids"] = json.dumps(evaluation_ids)


@pytest.mark.parametrize(
    "mutate",
    [
        _drop_one_direction,
        _change_scenario_feeder,
        _change_scenario_call_time,
        _change_protocol,
        _change_role,
        _change_holdout_access,
        _change_status,
        _change_evaluation_durations,
        _change_evaluation_direction,
    ],
    ids=[
        "paired-directions",
        "scenario-feeder",
        "scenario-call-time",
        "protocol",
        "role",
        "holdout-access",
        "status",
        "durations",
        "evaluation-direction",
    ],
)
def test_invalid_pilot_design_is_rejected(mutate):
    load_pilot_config, validate_pilot_manifest = _pilot_api()
    config = load_pilot_config(REPO_ROOT)
    frame = _valid_frame()
    mutate(frame)

    with pytest.raises(ValueError, match="pilot design"):
        validate_pilot_manifest(frame, config)
