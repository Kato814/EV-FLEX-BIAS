"""Artifact-only margin sensitivity for the archived D1-R-Lite screen."""

from __future__ import annotations

import csv
from copy import deepcopy
import hashlib
import math
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


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(f"{label} must be a sequence")
    return value


def _finite_exceedance(value: Any, label: str) -> float:
    if isinstance(value, bool):
        _fail(f"{label} must be a finite nonnegative number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(f"{label} must be a finite nonnegative number")
    if not math.isfinite(number) or number < 0.0:
        _fail(f"{label} must be a finite nonnegative number")
    return number


def _source_rows(
    source: Mapping[str, Any], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    report = _mapping(source.get("report"), "source report")
    if (
        report.get("decision") != config["source_report_decision"]
        or report.get("actual_cases") != config["total_cases"]
        or report.get("actual_target_audits") != 16
        or report.get("qualifying_families") != [config["candidate_family"]]
    ):
        _fail("source summary differs from the completed D1-R-Lite result")
    cases = list(_sequence(source.get("cases"), "source cases"))
    artifacts = list(_sequence(source.get("artifacts"), "source artifacts"))
    if len(cases) != config["total_cases"] or len(artifacts) != len(cases):
        _fail("source must contain exactly 12 paired cases and artifacts")
    pair_ids = [
        _mapping(case, "source case").get("pair_id") for case in cases
    ]
    artifact_ids = [
        _mapping(artifact, "source artifact").get("pair_id")
        for artifact in artifacts
    ]
    if pair_ids != config["source_pair_order"] or artifact_ids != pair_ids:
        _fail("source case or artifact order differs from the frozen pair order")

    normalized: list[dict[str, Any]] = []
    observed_clusters: list[str] = []
    for case_value, artifact_value in zip(cases, artifacts, strict=True):
        case = _mapping(case_value, "source case")
        artifact = _mapping(artifact_value, "source artifact")
        pair_id = str(case["pair_id"])
        cluster = case.get("scenario_cluster")
        if (
            not isinstance(cluster, str)
            or not cluster
            or artifact.get("scenario_cluster") != cluster
            or artifact.get("status") != "SUCCESS"
        ):
            _fail(f"source pair {pair_id} identity or status differs")
        if cluster not in observed_clusters:
            observed_clusters.append(cluster)
        audits = list(_sequence(artifact.get("audits"), f"source pair {pair_id} audits"))
        witnesses = [
            _mapping(audit, f"source pair {pair_id} audit")
            for audit in audits
            if isinstance(audit, Mapping)
            and audit.get("audit_point") == "BOUNDARY_INFEASIBLE"
        ]
        if len(witnesses) != 1:
            _fail(f"source pair {pair_id} must retain one boundary-infeasible audit")
        selected = _mapping(
            witnesses[0].get("selected_slot"),
            f"source pair {pair_id} selected witness",
        )
        rows = list(
            _sequence(
                selected.get("simultaneous_violations"),
                f"source pair {pair_id} simultaneous violations",
            )
        )
        normalized_rows: list[dict[str, Any]] = []
        for index, row_value in enumerate(rows):
            row = _mapping(row_value, f"source pair {pair_id} row {index}")
            family = row.get("constraint_family")
            if family not in config["family_order"]:
                _fail(f"source pair {pair_id} row {index} family is invalid")
            if row.get("is_physical_violation") is not True:
                _fail(f"source pair {pair_id} row {index} is not a physical violation")
            normalized_rows.append(
                {
                    "constraint_family": family,
                    "exceedance": _finite_exceedance(
                        row.get("exceedance"),
                        f"source pair {pair_id} row {index} exceedance",
                    ),
                }
            )
        normalized.append(
            {
                "pair_id": pair_id,
                "scenario_cluster": cluster,
                "rows": normalized_rows,
            }
        )
    if len(observed_clusters) != config["total_clusters"]:
        _fail("source cases must contain exactly four scenario clusters")
    return normalized


def _support_at_band(
    cases: Sequence[Mapping[str, Any]],
    *,
    family: str,
    guard_band: float,
    guard_band_applied: bool,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    pair_ids: list[str] = []
    clusters: list[str] = []
    metric_count = 0
    for case in cases:
        matching = [
            row
            for row in case["rows"]
            if row["constraint_family"] == family
            and (not guard_band_applied or row["exceedance"] >= guard_band)
        ]
        if not matching:
            continue
        metric_count += len(matching)
        pair_ids.append(str(case["pair_id"]))
        cluster = str(case["scenario_cluster"])
        if cluster not in clusters:
            clusters.append(cluster)
    return {
        "constraint_family": family,
        "guard_band": guard_band,
        "guard_band_unit": "pu" if guard_band_applied else None,
        "guard_band_applied": guard_band_applied,
        "case_count": len(pair_ids),
        "scenario_cluster_count": len(clusters),
        "metric_witness_count": metric_count,
        "pair_ids": pair_ids,
        "scenario_clusters": clusters,
        "qualifies": bool(
            len(pair_ids) >= config["minimum_cases"]
            and len(clusters) >= config["minimum_clusters"]
        ),
    }


def compute_margin_sensitivity(
    source: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Count archived case and cluster support at the frozen guard bands."""

    if dict(config) != _expected_config():
        _fail("margin computation requires the frozen config")
    if not isinstance(source, Mapping):
        _fail("source must be a mapping")
    cases = _source_rows(source, config)
    support: list[dict[str, Any]] = []
    for family in config["family_order"]:
        voltage = family in config["voltage_families"]
        bands = config["voltage_guard_bands_pu"] if voltage else [0.0]
        support.extend(
            _support_at_band(
                cases,
                family=family,
                guard_band=float(band),
                guard_band_applied=voltage,
                config=config,
            )
            for band in bands
        )
    decisive = next(
        row
        for row in support
        if row["constraint_family"] == config["candidate_family"]
        and row["guard_band"] == config["decisive_guard_band_pu"]
    )
    decision = (
        "MARGIN_ROBUST_AT_1E5"
        if decisive["qualifies"]
        else "HOLD_MARGIN_FRAGILE_AT_1E5"
    )
    report = _mapping(source["report"], "source report")
    result = {
        "artifact": "EV-FLEX-BIAS-V2.1-D1R-LITE-N0-MARGIN-REPORT",
        "protocol_version": config["protocol_version"],
        "source_protocol_version": config["source_protocol_version"],
        "source_evidence_commit": config["source_evidence_commit"],
        "source_report_decision": config["source_report_decision"],
        "candidate_family": config["candidate_family"],
        "decision": decision,
        "decisive_guard_band_pu": config["decisive_guard_band_pu"],
        "threshold": {
            "minimum_cases": config["minimum_cases"],
            "total_cases": config["total_cases"],
            "minimum_scenario_clusters": config["minimum_clusters"],
            "total_scenario_clusters": config["total_clusters"],
        },
        "decisive_support": deepcopy(decisive),
        "support": support,
        "source_summary": {
            "actual_cases": report["actual_cases"],
            "actual_target_audits": report["actual_target_audits"],
            "qualifying_families": deepcopy(report["qualifying_families"]),
            "frozen_source_hashes": deepcopy(
                source.get("frozen_source_hashes", {})
            ),
        },
        "interpretation": deepcopy(config["interpretation"]),
        "new_power_flow_solves": config["new_power_flow_solves"],
        "formal_v2_1_run_started": config["formal_v2_1_run_started"],
        "formal_v2_1_run_authorized": config["formal_v2_1_run_authorized"],
        "line_thermal_in_scope": config["line_thermal_in_scope"],
        "resource_policy": deepcopy(config["resource_policy"]),
    }
    validate_margin_result(result, config)
    return result


def validate_margin_result(
    result: Mapping[str, Any], config: Mapping[str, Any]
) -> None:
    """Reject internally inconsistent or scope-expanding N0 results."""

    if dict(config) != _expected_config():
        _fail("result validation requires the frozen config")
    if not isinstance(result, Mapping):
        _fail("result must be a mapping")
    expected_identity = {
        "artifact": "EV-FLEX-BIAS-V2.1-D1R-LITE-N0-MARGIN-REPORT",
        "protocol_version": config["protocol_version"],
        "source_protocol_version": config["source_protocol_version"],
        "source_evidence_commit": config["source_evidence_commit"],
        "source_report_decision": config["source_report_decision"],
        "candidate_family": config["candidate_family"],
        "decisive_guard_band_pu": config["decisive_guard_band_pu"],
        "interpretation": config["interpretation"],
        "new_power_flow_solves": 0,
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
        "resource_policy": config["resource_policy"],
    }
    for name, value in expected_identity.items():
        if result.get(name) != value:
            _fail(f"result {name} differs from the frozen scope")
    if result.get("threshold") != {
        "minimum_cases": config["minimum_cases"],
        "total_cases": config["total_cases"],
        "minimum_scenario_clusters": config["minimum_clusters"],
        "total_scenario_clusters": config["total_clusters"],
    }:
        _fail("result threshold differs from the frozen gate")
    support = list(_sequence(result.get("support"), "result support"))
    expected_keys = {
        "constraint_family",
        "guard_band",
        "guard_band_unit",
        "guard_band_applied",
        "case_count",
        "scenario_cluster_count",
        "metric_witness_count",
        "pair_ids",
        "scenario_clusters",
        "qualifies",
    }
    expected_order = [
        (family, float(band))
        for family in config["family_order"]
        for band in (
            config["voltage_guard_bands_pu"]
            if family in config["voltage_families"]
            else [0.0]
        )
    ]
    observed_order: list[tuple[Any, Any]] = []
    for value in support:
        row = _mapping(value, "result support row")
        if set(row) != expected_keys:
            _fail("result support row has unexpected or missing fields")
        observed_order.append((row["constraint_family"], row["guard_band"]))
        pair_ids = list(_sequence(row["pair_ids"], "support pair IDs"))
        clusters = list(
            _sequence(row["scenario_clusters"], "support scenario clusters")
        )
        if (
            len(pair_ids) != row["case_count"]
            or len(set(pair_ids)) != len(pair_ids)
            or len(clusters) != row["scenario_cluster_count"]
            or len(set(clusters)) != len(clusters)
            or not isinstance(row["metric_witness_count"], int)
            or row["metric_witness_count"] < row["case_count"]
            or row["qualifies"]
            is not (
                row["case_count"] >= config["minimum_cases"]
                and row["scenario_cluster_count"] >= config["minimum_clusters"]
            )
        ):
            _fail("result support counts or qualification are inconsistent")
        voltage = row["constraint_family"] in config["voltage_families"]
        if (
            row["guard_band_applied"] is not voltage
            or row["guard_band_unit"] != ("pu" if voltage else None)
        ):
            _fail("result support guard-band scope is inconsistent")
    if observed_order != expected_order:
        _fail("result support order differs from the frozen family and band order")
    decisive = next(
        row
        for row in support
        if row["constraint_family"] == config["candidate_family"]
        and row["guard_band"] == config["decisive_guard_band_pu"]
    )
    if result.get("decisive_support") != decisive:
        _fail("result decisive support does not match the VMAX 1e-5 row")
    expected_decision = (
        "MARGIN_ROBUST_AT_1E5"
        if decisive["qualifies"]
        else "HOLD_MARGIN_FRAGILE_AT_1E5"
    )
    if result.get("decision") != expected_decision:
        _fail("result decision contradicts the decisive support")
    source_summary = _mapping(result.get("source_summary"), "source summary")
    if (
        source_summary.get("actual_cases") != config["total_cases"]
        or source_summary.get("actual_target_audits") != 16
        or source_summary.get("qualifying_families")
        != [config["candidate_family"]]
        or not isinstance(source_summary.get("frozen_source_hashes"), Mapping)
    ):
        _fail("result source summary differs from the frozen D1-R-Lite evidence")
