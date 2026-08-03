"""Artifact-only margin sensitivity for the archived D1-R-Lite screen."""

from __future__ import annotations

import csv
from copy import deepcopy
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from evflex.mechanism_diagnostic import strict_json_file
from evflex.mechanism_diagnostic_d1r_lite import (
    load_lite_config,
    load_lite_manifest,
    validate_lite_case_artifact,
)


_CONFIG_RELATIVE = Path(
    "config/mechanism_margin_sensitivity_v2_1_d1r_lite.json"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_HASH_FIELDS = ("pair_id", "stage", "status", "path", "sha256")


def _fail(detail: str) -> None:
    raise ValueError(f"D1-R-Lite N0 margin sensitivity: {detail}")


def _expected_config() -> dict[str, Any]:
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.1-D1R-LITE-N0-MARGIN",
        "source_protocol_version": "EV-FLEX-BIAS-V2.1-D1R-LITE",
        "source_evidence_commit": "5421ec6c5b6333ba9e8426d4909b4942403b55e7",
        "source_report_decision": "COMMON_CANDIDATE_CONFOUNDED",
        "candidate_family": "VMAX",
        "family_order": ["VMIN", "VMAX", "VUF", "TRANSFORMER", "FEEDER"],
        "voltage_families": ["VMIN", "VMAX"],
        "voltage_guard_bands_pu": [0.0, 1e-6, 1e-5, 1e-4],
        "decisive_guard_band_pu": 1e-5,
        "minimum_cases": 8,
        "total_cases": 12,
        "minimum_clusters": 3,
        "total_clusters": 4,
        "source_pair_order": [
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
        "new_power_flow_solves": 0,
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
        "interpretation": {
            "post_result_sensitivity_only": True,
            "independent_confirmation": False,
            "engineering_safety_margin": False,
            "original_decision_unchanged": True,
        },
        "artifact_names": {
            "config": "config/mechanism_margin_sensitivity_v2_1_d1r_lite.json",
            "source_report_json": "reports/mechanism_diagnostic_v2_1_d1r_lite.json",
            "source_audit_csv": "reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv",
            "source_hashes_csv": "reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv",
            "source_config": "config/mechanism_diagnostic_v2_1_d1r_lite.json",
            "source_manifest": "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv",
            "source_module": "src/evflex/mechanism_diagnostic_d1r_lite.py",
            "source_case_artifact_pattern": (
                "results/mechanism_diagnostic_v2_1_d1r_lite/"
                "cases/case_{pair_id}.json"
            ),
            "report_json": "reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json",
            "report_markdown": "reports/mechanism_margin_sensitivity_v2_1_d1r_lite.md",
            "report_csv": "reports/mechanism_margin_sensitivity_v2_1_d1r_lite.csv",
            "hashes_csv": "reports/mechanism_margin_sensitivity_hashes_v2_1_d1r_lite.csv",
        },
        "frozen_sources": [
            {
                "path": "reports/mechanism_diagnostic_v2_1_d1r_lite.json",
                "sha256": "86f7c0d3498da45d01e7008eeca42b6b8265a67bf1337ea5ea569a80d5c71275",
            },
            {
                "path": "reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv",
                "sha256": "ed58ded0d3581d5b7afcafa23f02b53471d4866c8a1fa9becfeb90060dd1ce94",
            },
            {
                "path": "reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv",
                "sha256": "b936cb7d1697a0888165afc81e688fdb830e00b7236e81215c8db86b1851b46a",
            },
            {
                "path": "config/mechanism_diagnostic_v2_1_d1r_lite.json",
                "sha256": "ec69c26761de716ace3b65aa3ad11ff2f5afcdb39d25754a62d98fec8ccd778a",
            },
            {
                "path": "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv",
                "sha256": "c150a56e7535c09fe1cf361a32f7fd86b424912a8ad286ed8ad8b469047196de",
            },
            {
                "path": "src/evflex/mechanism_diagnostic_d1r_lite.py",
                "sha256": "8efaa90990225cf1ae7ac99eb2becd7df9bbae0b4271fb544038a405f6ad8fd5",
            },
        ],
        "resource_policy": {
            "workers": 1,
            "numeric_threads": {
                "OMP_NUM_THREADS": 1,
                "OPENBLAS_NUM_THREADS": 1,
                "MKL_NUM_THREADS": 1,
                "NUMEXPR_NUM_THREADS": 1,
                "VECLIB_MAXIMUM_THREADS": 1,
                "BLIS_NUM_THREADS": 1,
            },
        },
    }


def _rooted(root: Path, relative: str | Path, label: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        _fail(f"{label} must be relative")
    target = (root / path).resolve(strict=False)
    if target != root and root not in target.parents:
        _fail(f"{label} escapes the repository")
    return target


def _sha256(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        _fail(f"cannot read {label} ({exc})")


def load_margin_config(repo_root: str | Path) -> dict[str, Any]:
    """Load the exact frozen N0 contract."""

    root = Path(repo_root).resolve(strict=True)
    path = _rooted(root, _CONFIG_RELATIVE, "config path")
    config = strict_json_file(path)
    if config != _expected_config():
        _fail("config differs from the frozen contract")
    for name, relative in config["artifact_names"].items():
        if not isinstance(relative, str):
            _fail(f"artifact_names.{name} must be a string")
        _rooted(root, relative.replace("{pair_id}", "01"), f"artifact_names.{name}")
    return config


def _read_hash_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != _HASH_FIELDS:
                _fail("source case-hash CSV columns differ from the frozen contract")
            rows = list(reader)
    except OSError as exc:
        _fail(f"cannot read source case-hash CSV ({exc})")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        _fail("source case-hash CSV contains malformed rows")
    return rows


def _validate_source_report(
    report: Mapping[str, Any], config: Mapping[str, Any]
) -> None:
    expected = {
        "artifact": "EV-FLEX-BIAS-V2.1-D1R-LITE-REPORT",
        "protocol_version": config["source_protocol_version"],
        "decision": config["source_report_decision"],
        "diagnostic_completed": True,
        "actual_cases": config["total_cases"],
        "actual_target_audits": 16,
        "qualifying_families": [config["candidate_family"]],
        "successful_case_ids": config["source_pair_order"],
        "terminal_case_ids": config["source_pair_order"],
        "missing_pair_ids": [],
        "terminal_failure": None,
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
    }
    for name, value in expected.items():
        if report.get(name) != value:
            _fail(f"source report {name} differs from the completed D1-R-Lite evidence")
    threshold = report.get("threshold")
    if threshold != {
        "minimum_cases": config["minimum_cases"],
        "total_cases": config["total_cases"],
        "minimum_scenario_clusters": config["minimum_clusters"],
        "total_scenario_clusters": config["total_clusters"],
    }:
        _fail("source report threshold differs from the frozen D1-R-Lite gate")
    support = report.get("family_support")
    if not isinstance(support, list):
        _fail("source report family support is missing")
    candidate_rows = [
        row
        for row in support
        if isinstance(row, Mapping)
        and row.get("constraint_family") == config["candidate_family"]
    ]
    if len(candidate_rows) != 1 or candidate_rows[0].get("qualifies") is not True:
        _fail("source report does not retain one qualifying VMAX candidate")


def load_margin_source(
    repo_root: str | Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the strictly validated frozen report, cases, and artifacts."""

    root = Path(repo_root).resolve(strict=True)
    if dict(config) != _expected_config():
        _fail("source loading requires the frozen margin config")
    for item in config["frozen_sources"]:
        path = _rooted(root, item["path"], f"frozen source {item['path']}")
        if _sha256(path, str(item["path"])) != item["sha256"]:
            _fail(f"frozen source hash drift: {item['path']}")

    report_path = _rooted(
        root, config["artifact_names"]["source_report_json"], "source report"
    )
    report = strict_json_file(report_path)
    _validate_source_report(report, config)

    lite_config = load_lite_config(root)
    cases = load_lite_manifest(root)
    if [case["pair_id"] for case in cases] != config["source_pair_order"]:
        _fail("source manifest pair order differs from the frozen margin contract")

    hash_path = _rooted(
        root, config["artifact_names"]["source_hashes_csv"], "source case hashes"
    )
    hash_rows = _read_hash_rows(hash_path)
    if [row["pair_id"] for row in hash_rows] != config["source_pair_order"]:
        _fail("source case-hash rows differ from the frozen pair order")
    if len(hash_rows) != config["total_cases"]:
        _fail("source case-hash CSV must contain exactly 12 rows")

    artifacts: list[dict[str, Any]] = []
    for case, row in zip(cases, hash_rows, strict=True):
        pair_id = str(case["pair_id"])
        expected_relative = config["artifact_names"][
            "source_case_artifact_pattern"
        ].format(pair_id=pair_id)
        if (
            row["stage"] != case["stage"]
            or row["status"] != "SUCCESS"
            or row["path"] != expected_relative
            or _SHA256_RE.fullmatch(row["sha256"]) is None
        ):
            _fail(f"source case-hash identity differs for pair {pair_id}")
        case_path = _rooted(root, expected_relative, f"source case {pair_id}")
        if _sha256(case_path, f"source case {pair_id}") != row["sha256"]:
            _fail(f"case artifact hash drift: pair {pair_id}")
        artifact = strict_json_file(case_path)
        validate_lite_case_artifact(artifact, case, lite_config)
        if artifact.get("status") != "SUCCESS":
            _fail(f"source case {pair_id} is not successful")
        witnesses = [
            audit
            for audit in artifact["audits"]
            if audit.get("audit_point") == "BOUNDARY_INFEASIBLE"
            and audit.get("feasible") is False
            and audit.get("explicit_physical_witness") is True
        ]
        if len(witnesses) != 1:
            _fail(f"source case {pair_id} lacks one boundary-infeasible witness")
        artifacts.append(artifact)

    return {
        "report": deepcopy(report),
        "cases": deepcopy(cases),
        "artifacts": artifacts,
        "hash_rows": deepcopy(hash_rows),
        "frozen_source_hashes": {
            item["path"]: item["sha256"] for item in config["frozen_sources"]
        },
    }
