from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

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
            "adapter_version": 1,
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
                "violations": [("V:test.1", 0.90, 0.95, "lo")],
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
