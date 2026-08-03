from __future__ import annotations

import csv
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from evflex import pilot
from evflex.mechanism_diagnostic_d1r_lite import (
    LiteAuditStop,
    execute_lite_case,
    load_lite_config,
    load_lite_manifest,
    stage_a_case_ids,
    stage_b_case_ids,
    validate_raw_audit_identity,
    verify_lite_sources,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_RELATIVE = Path("config/mechanism_diagnostic_v2_1_d1r_lite.json")
MANIFEST_RELATIVE = Path(
    "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv"
)
SOURCE_MANIFEST_RELATIVE = Path(
    "manifests/mechanism_diagnostic_pairs_v2_1.csv"
)


def _copy_manifest_inputs(tmp_path: Path) -> None:
    for relative in (CONFIG_RELATIVE, MANIFEST_RELATIVE, SOURCE_MANIFEST_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)


def test_lite_config_has_exact_contract_and_independent_paths() -> None:
    config = load_lite_config(REPO_ROOT)

    assert config["protocol_version"] == "EV-FLEX-BIAS-V2.1-D1R-LITE"
    assert config["source_commit"] == "e1740f912a351b1822b5ee019f9e4f05b6b71c6f"
    assert config["expected_counts"] == {
        "stage_a_cases": 4,
        "stage_a_audits": 8,
        "stage_b_cases": 8,
        "maximum_cases": 12,
        "maximum_audits": 16,
        "scenario_clusters": 4,
    }
    assert config["adapter_identity"] == {
        "adapter_schema": "evflex.pilot.network-audit",
        "adapter_version": 2,
    }
    assert config["selection"] == {
        "rule": "CLOSEST_TO_CLUSTER_MEDIAN_ALPHA_THEN_PAIR_ID",
        "stage_a_pair_ids": ["01", "04", "07", "10"],
        "stage_b_pair_ids": ["02", "03", "05", "06", "08", "09", "11", "12"],
        "execution_order": [
            "01",
            "04",
            "07",
            "10",
            "02",
            "03",
            "05",
            "06",
            "08",
            "09",
            "11",
            "12",
        ],
    }
    assert config["resource_policy"]["workers"] == 1
    assert set(config["resource_policy"]["numeric_threads"].values()) == {1}
    assert config["line_thermal_in_scope"] is False
    assert config["formal_v2_1_run_authorized"] is False

    old_paths = {
        "results/mechanism_diagnostic_v2_1",
        "reports/mechanism_diagnostic_audits_v2_1.csv",
        "reports/mechanism_diagnostic_v2_1.json",
        "reports/mechanism_diagnostic_v2_1.md",
        "reports/mechanism_diagnostic_hashes_v2_1.csv",
    }
    materialized = set(config["artifact_names"].values())
    assert materialized.isdisjoint(old_paths)
    assert all("d1r_lite" in path for path in materialized)


def test_lite_manifest_contains_exact_12_bad_cases() -> None:
    cases = load_lite_manifest(REPO_ROOT)

    assert len(cases) == 12
    assert [case["pair_id"] for case in cases] == [
        "01",
        "04",
        "07",
        "10",
        "02",
        "03",
        "05",
        "06",
        "08",
        "09",
        "11",
        "12",
    ]
    assert [case["execution_order"] for case in cases] == list(range(1, 13))
    assert [case["stage"] for case in cases[:4]] == ["A"] * 4
    assert [case["stage"] for case in cases[4:]] == ["B"] * 8
    assert {case["feeder"] for case in cases} == {"lv906"}
    assert len({case["evaluation_id"] for case in cases}) == 12
    assert all(case["evaluation_id"].startswith("v20_core_lv906_") for case in cases)


def test_representatives_are_01_04_07_10_by_frozen_median_rule() -> None:
    config = load_lite_config(REPO_ROOT)
    cases = load_lite_manifest(REPO_ROOT)

    assert stage_a_case_ids(cases) == ["01", "04", "07", "10"]
    assert stage_b_case_ids(cases) == [
        "02",
        "03",
        "05",
        "06",
        "08",
        "09",
        "11",
        "12",
    ]
    assert stage_a_case_ids(cases) == config["selection"]["stage_a_pair_ids"]
    assert stage_b_case_ids(cases) == config["selection"]["stage_b_pair_ids"]


@pytest.mark.parametrize("mutation", ["control_member", "duplicate_pair"])
def test_manifest_rejects_control_member_duplicate_or_source_drift(
    tmp_path: Path, mutation: str
) -> None:
    _copy_manifest_inputs(tmp_path)
    manifest_path = tmp_path / MANIFEST_RELATIVE
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])

    if mutation == "control_member":
        rows[0]["evaluation_id"] = "v20_core_ieee13_1900_17__dec__15m"
    else:
        rows[1]["pair_id"] = rows[0]["pair_id"]

    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError):
        load_lite_manifest(tmp_path)


def test_lite_sources_pin_old_helper_and_pilot_hashes() -> None:
    config = load_lite_config(REPO_ROOT)
    frozen = {item["path"]: item["sha256"] for item in config["frozen_sources"]}

    assert frozen["src/evflex/pilot.py"] == (
        "37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b"
    )
    assert frozen["src/evflex/mechanism_diagnostic.py"] == (
        "c455679f9f2595830a3db347c01eaaf0998b443ce3087457dc7544a94ecb1eaa"
    )
    assert frozen["config/mechanism_diagnostic_v2_1.json"] == (
        "8ee0ea969d26e8a2bc55a065c89fdf382346c90904d15432e7694af64ec781b1"
    )
    assert frozen["manifests/mechanism_diagnostic_pairs_v2_1.csv"] == (
        "5b7fc6dc5121a0e1ff42bec62710085fce07865ffc5a58008d05a1e2900d53f1"
    )
    verify_lite_sources(REPO_ROOT, config)


def test_config_rejects_json_duplicate_keys(tmp_path: Path) -> None:
    target = tmp_path / CONFIG_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"protocol_version":"a","protocol_version":"b"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        load_lite_config(tmp_path)


def test_config_is_strict_json_without_nonfinite_values() -> None:
    raw = json.loads((REPO_ROOT / CONFIG_RELATIVE).read_text(encoding="utf-8"))
    assert raw == load_lite_config(REPO_ROOT)


FORMAL_CONSTRAINTS = {
    "vmin_pu": 0.95,
    "vmax_pu": 1.06,
    "vuf_limit_pct": 2.0,
    "transformer_loading_limit_pu": 1.0,
    "feeder_loading_limit_pu": 1.0,
    "line_thermal_in_scope": False,
}


class _AuditNetwork:
    def __init__(self, load_scale: float) -> None:
        self.load_scale = load_scale
        self.groups: list[object] = []

    def audit_context(self) -> dict[str, object]:
        return {
            "adapter_schema": pilot._PILOT_ADAPTER_SCHEMA,
            "adapter_version": pilot._PILOT_ADAPTER_VERSION,
            "feeder": "lv906",
            "model": "3ph",
            "load_scale": self.load_scale,
            **FORMAL_CONSTRAINTS,
            "feeder_kva": 1000.0,
            "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
            "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
            "transformer_rating_multiplier": 1.0,
        }


def _identity_fixture() -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, object]
]:
    records: list[dict[str, object]] = []
    for slot, scale in enumerate((0.75, 1.25)):
        context = pilot._capture_network_audit_context(
            _AuditNetwork(scale),
            feeder="lv906",
            model="3ph",
            load_scale=scale,
        )
        records.append(
            {
                "slot": slot,
                "verified": True,
                "load_scale": scale,
                "feeder": "lv906",
                "model": "3ph",
                "source": "power_flow",
                "audit_context": context,
            }
        )
    raw: dict[str, object] = {"slot_results": records}
    case: dict[str, object] = {
        "member": {"feeder": "lv906"},
        "load_scales": np.asarray([0.75, 1.25] + [1.0] * 94, dtype=float),
    }
    config = load_lite_config(REPO_ROOT)
    return raw, case, FORMAL_CONSTRAINTS, config["adapter_identity"]


def test_audit_identity_accepts_context_produced_by_frozen_pilot() -> None:
    raw, case, formal_constraints, adapter_identity = _identity_fixture()

    validate_raw_audit_identity(
        raw,
        case=case,
        formal_constraints=formal_constraints,
        adapter_identity=adapter_identity,
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("record_scale", "AUDIT_RECORD_SCALE_MISMATCH"),
        ("context_scale", "AUDIT_CONTEXT_SCALE_MISMATCH"),
        ("schema", "AUDIT_SCHEMA_MISMATCH"),
        ("version", "AUDIT_VERSION_MISMATCH"),
        ("feeder", "AUDIT_FEEDER_MISMATCH"),
        ("model", "AUDIT_MODEL_MISMATCH"),
        ("formal_constraint", "AUDIT_FORMAL_CONSTRAINT_MISMATCH"),
    ],
)
def test_audit_identity_reports_field_level_failure_codes(
    mutation: str, expected_code: str
) -> None:
    raw, case, formal_constraints, adapter_identity = _identity_fixture()
    changed = deepcopy(raw)
    record = changed["slot_results"][0]
    context = record["audit_context"]
    if mutation == "record_scale":
        record["load_scale"] = 0.76
    elif mutation == "context_scale":
        context["load_scale"] = 0.76
    elif mutation == "schema":
        context["adapter_schema"] = "EV-FLEX-BIAS-PILOT-NETWORK-AUDIT"
    elif mutation == "version":
        context["adapter_version"] = "2"
    elif mutation == "feeder":
        context["feeder"] = "ieee13"
    elif mutation == "model":
        context["model"] = "balanced"
    else:
        context["vmin_pu"] = 0.94

    with pytest.raises(ValueError, match=expected_code):
        validate_raw_audit_identity(
            changed,
            case=case,
            formal_constraints=formal_constraints,
            adapter_identity=adapter_identity,
        )


def _formal_coverage() -> dict[str, object]:
    return {
        "all_bus_count": 2,
        "monitored_bus_count": 2,
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
        "transformer_ratings_kva": {"t1": 100.0},
        "transformer_raw_ratings_kva": {"t1": 100.0},
        "transformer_rating_multiplier": 1.0,
        "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
        "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
    }


def _runtime_metrics(*, physical: bool = False) -> dict[str, float]:
    values = {
        "V:bus1.1": 1.0,
        "V:bus2.2": 1.0,
        "V:bus3.3": 1.0,
        "U:bus1": 0.5,
        "S:transformer:t1": 0.5,
        "S:feeder": 0.5,
    }
    if physical:
        values["V:bus1.1"] = 0.94
        values["U:bus1"] = 2.2
    return values


def _runtime_violations(*, physical: bool = False) -> list[dict[str, object]]:
    if not physical:
        return []
    return [
        {
            "kind": "physical_constraint",
            "metric": "V:bus1.1",
            "value": 0.94,
            "limit": 0.95,
            "direction": "lo",
        },
        {
            "kind": "physical_constraint",
            "metric": "U:bus1",
            "value": 2.2,
            "limit": 2.0,
            "direction": "hi",
        },
    ]


def _runtime_slot(
    slot: int, *, physical: bool = False, numerical: bool = False
) -> dict[str, object]:
    metrics = _runtime_metrics(physical=physical)
    violations = _runtime_violations(physical=physical)
    coverage = _formal_coverage()
    result = {
        "metrics": metrics,
        "feasible": not numerical and not violations,
        "converged": not numerical,
        "numerical_failure": numerical,
        "violations": violations,
        "vmin": min(v for k, v in metrics.items() if k.startswith("V:")),
        "vmax": max(v for k, v in metrics.items() if k.startswith("V:")),
        "vufmax": max(v for k, v in metrics.items() if k.startswith("U:")),
        "transformer_loading_max": max(
            v for k, v in metrics.items() if k.startswith("S:transformer:")
        ),
        "feeder_loading": metrics["S:feeder"],
        "line_thermal_in_scope": False,
        "coverage": deepcopy(coverage),
        "formal_integrity": {
            "validated": True,
            "result_schema_valid": True,
            "metrics_finite": True,
            "summary_finite": True,
            "coverage_complete": True,
            "summary_consistent": True,
        },
    }
    return {
        "slot": slot,
        "verified": True,
        "baseline_exact": False,
        "baseline_schedule": None,
        "load_scale": 1.0,
        "feeder": "lv906",
        "model": "3ph",
        "source": "power_flow",
        "audit_context": {
            "adapter_schema": pilot._PILOT_ADAPTER_SCHEMA,
            "adapter_version": pilot._PILOT_ADAPTER_VERSION,
            "network_class": "tests.FakeNetwork",
            "network_instance_id": 1,
            "feeder": "lv906",
            "model": "3ph",
            "load_scale": 1.0,
            **FORMAL_CONSTRAINTS,
            "feeder_kva": 1000.0,
            "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
            "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
            "transformer_rating_multiplier": 1.0,
            "groups": [],
        },
        "group_power": [0.0],
        "coverage": deepcopy(coverage),
        "formal_integrity": deepcopy(result["formal_integrity"]),
        "result": result,
    }


def _runtime_raw(slots: list[dict[str, object]]) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    trace: list[dict[str, object]] = []
    numerical_checks = 0
    physical_checks = 0
    for record in slots:
        result = record["result"]
        violations = result["violations"]
        numerical = bool(result["numerical_failure"])
        physical = any(item.get("kind") == "physical_constraint" for item in violations)
        numerical_checks += int(numerical)
        physical_checks += int(physical)
        failure_class = (
            "NUMERICAL_INVALID"
            if numerical
            else "PHYSICAL_CONSTRAINT"
            if physical
            else "NONE"
        )
        if numerical or violations:
            failures.append(
                {
                    "slot": record["slot"],
                    "converged": bool(result["converged"]),
                    "numerical_failure": numerical,
                    "failure_class": failure_class,
                    "physical_witness": physical,
                    "violations": deepcopy(violations),
                }
            )
        trace.append(
            {
                "slot": record["slot"],
                "feasible": bool(result["feasible"]),
                "converged": bool(result["converged"]),
                "numerical_failure": numerical,
                "failure_class": failure_class,
                "physical_witness": physical,
            }
        )
    checked = len(slots)
    complete = checked == 96
    feasible = complete and not failures
    failure_class = (
        "NUMERICAL_INVALID"
        if numerical_checks
        else "PHYSICAL_CONSTRAINT"
        if physical_checks
        else "NONE"
    )
    return {
        "feasible": feasible,
        "checked_intervals": checked,
        "coverage_ratio": checked / 96.0,
        "complete_coverage": complete,
        "eligible_for_v01_pass": feasible,
        "power_flow_evaluations": checked,
        "reused_baseline_intervals": 0,
        "converged_checks": checked - numerical_checks,
        "nonconverged_checks": numerical_checks,
        "numerical_failure_checks": numerical_checks,
        "physical_violation_checks": physical_checks,
        "failure_class": failure_class,
        "nonconverged_slots": [
            item["slot"] for item in failures if not item["converged"]
        ],
        "violations": failures,
        "slot_results": slots,
        "slot_audit_trace": trace,
        "coverage_counts": deepcopy(_formal_coverage()),
        "vmin": min(item["result"]["vmin"] for item in slots),
        "vmax": max(item["result"]["vmax"] for item in slots),
        "vufmax": max(item["result"]["vufmax"] for item in slots),
        "transformer_loading_max": max(
            item["result"]["transformer_loading_max"] for item in slots
        ),
        "feeder_loading_max": max(
            item["result"]["feeder_loading"] for item in slots
        ),
    }


def _fake_ev() -> SimpleNamespace:
    return SimpleNamespace(
        ev_id=1,
        capacity=10.0,
        initial=0.0,
        target=1.0,
        reserve=0.0,
        arrival=0,
        departure=96,
        pch=2.0,
        pdis=0.0,
        eta_c=1.0,
        eta_d=1.0,
        v2g=False,
        max_discharge=0.0,
        bus="bus",
        phase=1,
        kv_ln=0.24,
    )


class _LiteFakeRuntime:
    def __init__(self, stage: str, failure_mode: str | None = None) -> None:
        self.stage = stage
        self.failure_mode = failure_mode
        self.fleet = [_fake_ev()]
        self.baseline = np.zeros((1, 96), dtype=float)
        self.schedule = self.baseline.copy()
        self.schedule[0, :4] = 1.0
        self.load_scales = np.ones(96, dtype=float)
        self.generate_calls: list[tuple[int, str]] = []
        self.cache_calls = 0
        self.audit_calls: list[dict[str, object]] = []
        self.forbidden_calls: list[str] = []
        self._cache = object()
        self._targeted_count = 0

    def generate_balanced_raw(self, duration: int, model: str) -> dict[str, object]:
        self.generate_calls.append((duration, model))
        return {
            "success": True,
            "physical_feasible": True,
            "schedule": self.schedule.copy(),
            "flex_kw": 1.0,
            "max_departure_error_kwh": 0.0,
            "max_reserve_violation_kwh": 0.0,
            "max_capacity_violation_kwh": 0.0,
            "simultaneous_slots": 0,
            "model_network_check": {"feasible": True},
        }

    def create_corrected_truth_cache(self) -> object:
        self.cache_calls += 1
        return self._cache

    def audit_corrected(
        self,
        schedule: object,
        cache: object,
        *,
        baseline_slot_results: object,
        stop_on_violation: bool,
        retain_slot_results: bool,
    ) -> dict[str, object]:
        assert cache is self._cache
        self.audit_calls.append(
            {
                "schedule": np.asarray(schedule, dtype=float).copy(),
                "baseline_slot_count": (
                    None
                    if baseline_slot_results is None
                    else len(baseline_slot_results)
                ),
                "stop_on_violation": stop_on_violation,
                "retain_slot_results": retain_slot_results,
            }
        )
        if baseline_slot_results is None:
            return _runtime_raw([_runtime_slot(slot) for slot in range(96)])

        self._targeted_count += 1
        boundary_infeasible = self.stage == "B" or self._targeted_count == 2
        if self.failure_mode == "feasible_drift" and not boundary_infeasible:
            return _runtime_raw(
                [*[_runtime_slot(slot) for slot in range(5)], _runtime_slot(5, physical=True)]
            )
        if not boundary_infeasible:
            return _runtime_raw([_runtime_slot(slot) for slot in range(96)])
        if self.failure_mode == "numerical":
            return _runtime_raw([_runtime_slot(0, numerical=True)])
        if self.failure_mode == "missing_witness":
            return _runtime_raw([_runtime_slot(slot) for slot in range(96)])
        raw = _runtime_raw(
            [*[_runtime_slot(slot) for slot in range(5)], _runtime_slot(5, physical=True)]
        )
        if self.failure_mode == "schema_drift":
            raw["slot_results"][-1]["audit_context"]["adapter_schema"] = "wrong"
        return raw

    def alpha_legacy_verifier(self, *_args: object, **_kwargs: object) -> None:
        self.forbidden_calls.append("alpha_legacy_verifier")
        raise AssertionError("alpha search is forbidden")

    def phase_tie_break(self, *_args: object, **_kwargs: object) -> None:
        self.forbidden_calls.append("phase_tie_break")
        raise AssertionError("tie-break is forbidden")

    def timing_replay(self, *_args: object, **_kwargs: object) -> None:
        self.forbidden_calls.append("timing_replay")
        raise AssertionError("timing is forbidden")


def _lite_case_and_factory(
    stage: str, *, failure_mode: str | None = None
) -> tuple[dict[str, object], _LiteFakeRuntime, object]:
    cases = load_lite_manifest(REPO_ROOT)
    pair_id = "04" if stage == "A" else "03"
    case = deepcopy(next(item for item in cases if item["pair_id"] == pair_id))
    runtime = _LiteFakeRuntime(stage, failure_mode=failure_mode)
    case["schedule_sha256"] = pilot.canonical_schedule_sha256(
        runtime.fleet, runtime.schedule
    )
    case["bus_phase_time_sha256"] = pilot._canonical_bus_phase_time_sha256(
        runtime.fleet, runtime.schedule
    )
    case["baseline_schedule_sha256"] = pilot.canonical_schedule_sha256(
        runtime.fleet, runtime.baseline
    )

    def factory(
        _repo_root: Path,
        work_unit: dict[str, object],
        _pilot_config: dict[str, object],
    ) -> _LiteFakeRuntime:
        assert work_unit["feeder"] == "lv906"
        return runtime

    return case, runtime, factory


def test_stage_a_executes_only_boundary_feasible_and_infeasible() -> None:
    case, runtime, factory = _lite_case_and_factory("A")
    config = load_lite_config(REPO_ROOT)

    artifact = execute_lite_case(
        REPO_ROOT, case, config, runtime_factory=factory
    )

    assert artifact["status"] == "SUCCESS"
    assert [audit["audit_point"] for audit in artifact["audits"]] == [
        "BOUNDARY_FEASIBLE",
        "BOUNDARY_INFEASIBLE",
    ]
    assert len(runtime.audit_calls) == 3
    expected_alphas = [case["alpha_transfer"], case["alpha_transfer"] + 0.002]
    for call, alpha in zip(runtime.audit_calls[1:], expected_alphas, strict=True):
        expected = runtime.baseline + alpha * (runtime.schedule - runtime.baseline)
        np.testing.assert_allclose(call["schedule"], expected, rtol=0.0, atol=0.0)
    assert [call["stop_on_violation"] for call in runtime.audit_calls] == [
        False,
        False,
        True,
    ]


def test_stage_b_executes_only_boundary_infeasible() -> None:
    case, runtime, factory = _lite_case_and_factory("B")

    artifact = execute_lite_case(
        REPO_ROOT, case, load_lite_config(REPO_ROOT), runtime_factory=factory
    )

    assert [audit["audit_point"] for audit in artifact["audits"]] == [
        "BOUNDARY_INFEASIBLE"
    ]
    assert len(runtime.audit_calls) == 2
    assert runtime.audit_calls[1]["stop_on_violation"] is True


def test_case_reconstructs_once_and_reuses_one_baseline_audit() -> None:
    case, runtime, factory = _lite_case_and_factory("A")

    execute_lite_case(
        REPO_ROOT, case, load_lite_config(REPO_ROOT), runtime_factory=factory
    )

    assert runtime.generate_calls == [(case["source_duration_min"], "balanced")]
    assert runtime.cache_calls == 1
    assert runtime.audit_calls[0]["baseline_slot_count"] is None
    assert [call["baseline_slot_count"] for call in runtime.audit_calls[1:]] == [
        96,
        96,
    ]


def test_case_never_uses_control_full_offer_search_optimizer_or_tie_break() -> None:
    case, runtime, factory = _lite_case_and_factory("A")

    artifact = execute_lite_case(
        REPO_ROOT, case, load_lite_config(REPO_ROOT), runtime_factory=factory
    )

    assert artifact["member"]["feeder"] == "lv906"
    assert all(audit["audit_point"] != "FULL_OFFER" for audit in artifact["audits"])
    assert runtime.forbidden_calls == []


def test_case_preserves_all_simultaneous_first_slot_witnesses() -> None:
    case, _, factory = _lite_case_and_factory("A")

    artifact = execute_lite_case(
        REPO_ROOT, case, load_lite_config(REPO_ROOT), runtime_factory=factory
    )

    selected = artifact["audits"][1]["selected_slot"]
    assert selected["slot"] == 5
    assert {
        row["constraint_family"] for row in selected["simultaneous_violations"]
    } == {"VMIN", "VUF"}
    assert all(
        row["is_physical_violation"] is True
        for row in selected["constraint_rows"]
    )


@pytest.mark.parametrize(
    ("failure_mode", "expected_code"),
    [
        ("feasible_drift", "BOUNDARY_FEASIBLE_REQUIRED"),
        ("numerical", "AUDIT_EVIDENCE_INVALID"),
        ("missing_witness", "BOUNDARY_INFEASIBLE_REQUIRED"),
        ("schema_drift", "AUDIT_SCHEMA_MISMATCH"),
    ],
)
def test_case_stops_on_boundary_drift_numerical_failure_or_missing_witness(
    failure_mode: str, expected_code: str
) -> None:
    case, _, factory = _lite_case_and_factory("A", failure_mode=failure_mode)

    with pytest.raises(LiteAuditStop) as caught:
        execute_lite_case(
            REPO_ROOT,
            case,
            load_lite_config(REPO_ROOT),
            runtime_factory=factory,
        )

    assert caught.value.rule_code == expected_code
