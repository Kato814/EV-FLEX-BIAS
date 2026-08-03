from __future__ import annotations

import csv
from copy import deepcopy
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from evflex import pilot
from evflex.mechanism_diagnostic_d1r_lite import (
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
        "load_scales": np.asarray([0.75, 1.25], dtype=float),
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
