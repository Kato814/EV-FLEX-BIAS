"""Strict inputs and pure rules for the D1-R-Lite N1 numerical replay."""

from __future__ import annotations

import csv
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
from importlib.metadata import PackageNotFoundError, version
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from evflex.mechanism_diagnostic import strict_json_file
from evflex.mechanism_margin_sensitivity_d1r_lite import (
    load_margin_config,
    load_margin_source,
)


_CONFIG_RELATIVE = Path(
    "config/numerical_certainty_replay_v2_1_d1r_lite.json"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_AUDIT_FIELDS = (
    "pair_id",
    "stage",
    "execution_order",
    "scenario_cluster",
    "sequence_index",
    "audit_point",
    "source_evaluation_id",
    "alpha_label",
    "feasible",
    "checked_intervals",
    "complete_coverage",
    "failure_class",
    "first_failure_slot",
    "explicit_physical_witness",
    "physical_violation_checks",
    "numerical_failure_checks",
    "vmin",
    "vmax",
    "vufmax",
    "transformer_loading_max",
    "feeder_loading_max",
    "selected_slot",
    "simultaneous_violation_families",
    "simultaneous_violation_objects",
    "simultaneous_violation_values",
    "simultaneous_violation_limits",
    "simultaneous_violation_exceedances",
    "audited_schedule_sha256",
)


def _fail(detail: str) -> None:
    raise ValueError(f"D1-R-Lite N1 numerical replay: {detail}")


def _expected_config() -> dict[str, Any]:
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.1-D1R-LITE-N1-NUMERICAL",
        "source_protocol_version": "EV-FLEX-BIAS-V2.1-D1R-LITE",
        "source_n0_protocol_version": "EV-FLEX-BIAS-V2.1-D1R-LITE-N0-MARGIN",
        "source_evidence_commit": "5421ec6c5b6333ba9e8426d4909b4942403b55e7",
        "source_n0_commit": "73518d928d973d420d4f5f8807f846b1f6c549cd",
        "source_pair_order": [
            "01", "04", "07", "10", "02", "03", "05", "06", "08", "09", "11", "12"
        ],
        "scenario_cluster_order": [
            "lv906_1900_18",
            "lv906_0000_11",
            "lv906_0200_03",
            "lv906_0600_02",
        ],
        "selected_pair_ids": ["01", "05", "08", "12"],
        "selection": {
            "rule": "CLOSEST_VMAX_EXCEEDANCE_TO_1E5_WITHIN_CLUSTER_THEN_PAIR_ID",
            "candidate_family": "VMAX",
            "guard_band_pu": 1e-5,
        },
        "selected_cases": [
            {
                "pair_id": "01",
                "stage": "A",
                "execution_order": 1,
                "scenario_cluster": "lv906_1900_18",
                "source_evaluation_id": "v20_core_lv906_1900_18__dec__15m",
                "alpha": 0.942,
                "alpha_label": "0.942",
                "selected_slot": 28,
                "constraint_family": "VMAX",
                "metric_id": "V:860.1",
                "object_id": "860.1",
                "direction": "hi",
                "value": 1.0600621154646155,
                "limit": 1.06,
                "exceedance": 6.211546461543094e-05,
                "audited_schedule_sha256": "393fc65082668ec8cab01344c1db8493cce7b2cd748370be0f3940a529a35c85",
            },
            {
                "pair_id": "05",
                "stage": "B",
                "execution_order": 7,
                "scenario_cluster": "lv906_0000_11",
                "source_evaluation_id": "v20_core_lv906_0000_11__dec__15m",
                "alpha": 0.708,
                "alpha_label": "0.708",
                "selected_slot": 48,
                "constraint_family": "VMAX",
                "metric_id": "V:563.1",
                "object_id": "563.1",
                "direction": "hi",
                "value": 1.0600027494562219,
                "limit": 1.06,
                "exceedance": 2.7494562218066676e-06,
                "audited_schedule_sha256": "2773415e90c8b54c33ec60cf92556eba925edaed008ab8725796b61d571d2518",
            },
            {
                "pair_id": "08",
                "stage": "B",
                "execution_order": 9,
                "scenario_cluster": "lv906_0200_03",
                "source_evaluation_id": "v20_core_lv906_0200_03__dec__30m",
                "alpha": 0.688,
                "alpha_label": "0.688",
                "selected_slot": 56,
                "constraint_family": "VMAX",
                "metric_id": "V:900.1",
                "object_id": "900.1",
                "direction": "hi",
                "value": 1.0600063998269251,
                "limit": 1.06,
                "exceedance": 6.399826925074237e-06,
                "audited_schedule_sha256": "05b27d55a66da22385f9f854bd8df0b797bf7e0d8f667aad789c21eb48f88b9e",
            },
            {
                "pair_id": "12",
                "stage": "B",
                "execution_order": 12,
                "scenario_cluster": "lv906_0600_02",
                "source_evaluation_id": "v20_core_lv906_0600_02__dec__60m",
                "alpha": 0.612,
                "alpha_label": "0.612",
                "selected_slot": 75,
                "constraint_family": "VMAX",
                "metric_id": "V:780.3",
                "object_id": "780.3",
                "direction": "hi",
                "value": 1.0600434424802179,
                "limit": 1.06,
                "exceedance": 4.3442480217814605e-05,
                "audited_schedule_sha256": "46aec87fa963d82a218dea0d2a501452e3646e657a41d8aa47006b45655424be",
            },
        ],
        "solver_settings": [
            {
                "label": "NATIVE_1E4",
                "convergence_tolerance": 1e-4,
                "max_iterations": 15,
                "max_control_iterations": 100,
            },
            {
                "label": "TIGHT_1E6",
                "convergence_tolerance": 1e-6,
                "max_iterations": 100,
                "max_control_iterations": 100,
            },
            {
                "label": "ULTRA_1E8",
                "convergence_tolerance": 1e-8,
                "max_iterations": 100,
                "max_control_iterations": 100,
            },
        ],
        "thresholds": {
            "native_replay_identity_pu": 1e-9,
            "native_to_tight_drift_pu": 1e-6,
            "tight_plateau_drift_pu": 1e-7,
            "physical_violation_margin_pu": 1e-7,
        },
        "expected_counts": {
            "selected_cases": 4,
            "solver_settings": 3,
            "target_replay_evaluations": 12,
        },
        "target_replay_evaluations": 12,
        "source_artifact_names": {
            "report_json": "reports/mechanism_diagnostic_v2_1_d1r_lite.json",
            "audit_csv": "reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv",
            "case_hashes_csv": "reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv",
            "config": "config/mechanism_diagnostic_v2_1_d1r_lite.json",
            "manifest": "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv",
            "case_artifact_pattern": "results/mechanism_diagnostic_v2_1_d1r_lite/cases/case_{pair_id}.json",
            "n0_report_json": "reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json",
            "n0_config": "config/mechanism_margin_sensitivity_v2_1_d1r_lite.json",
        },
        "artifact_names": {
            "config": "config/numerical_certainty_replay_v2_1_d1r_lite.json",
            "result_root": "results/numerical_certainty_replay_v2_1_d1r_lite",
            "case_artifact_pattern": "results/numerical_certainty_replay_v2_1_d1r_lite/cases/case_{pair_id}.json",
            "attempt_pattern": "results/numerical_certainty_replay_v2_1_d1r_lite/.attempts/case_{pair_id}.json",
            "run_lock": "results/numerical_certainty_replay_v2_1_d1r_lite/.run.lock",
            "report_json": "reports/numerical_certainty_replay_v2_1_d1r_lite.json",
            "report_markdown": "reports/numerical_certainty_replay_v2_1_d1r_lite.md",
            "report_csv": "reports/numerical_certainty_replay_v2_1_d1r_lite.csv",
            "hashes_csv": "reports/numerical_certainty_replay_hashes_v2_1_d1r_lite.csv",
        },
        "frozen_sources": [
            {"path": "reports/mechanism_diagnostic_v2_1_d1r_lite.json", "sha256": "86f7c0d3498da45d01e7008eeca42b6b8265a67bf1337ea5ea569a80d5c71275"},
            {"path": "reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv", "sha256": "ed58ded0d3581d5b7afcafa23f02b53471d4866c8a1fa9becfeb90060dd1ce94"},
            {"path": "reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv", "sha256": "b936cb7d1697a0888165afc81e688fdb830e00b7236e81215c8db86b1851b46a"},
            {"path": "config/mechanism_diagnostic_v2_1_d1r_lite.json", "sha256": "ec69c26761de716ace3b65aa3ad11ff2f5afcdb39d25754a62d98fec8ccd778a"},
            {"path": "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv", "sha256": "c150a56e7535c09fe1cf361a32f7fd86b424912a8ad286ed8ad8b469047196de"},
            {"path": "src/evflex/mechanism_diagnostic_d1r_lite.py", "sha256": "8efaa90990225cf1ae7ac99eb2becd7df9bbae0b4271fb544038a405f6ad8fd5"},
            {"path": "reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json", "sha256": "d7da6a5d00c6d44cc994300844be0b69bfeef47e43d45549f32961778e93dfff"},
            {"path": "config/mechanism_margin_sensitivity_v2_1_d1r_lite.json", "sha256": "5f188613783ae10d5d53ff5b06a62ce57b52a9c61d66bef56f16b19aedf84d31"},
        ],
        "runtime_requirement": {"distribution": "opendssdirect.py", "version": "0.9.4"},
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
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


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        _fail(f"{label} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(f"{label} must be finite")
    if not math.isfinite(number) or (positive and number <= 0.0):
        _fail(f"{label} must be finite{' and positive' if positive else ''}")
    return number


def load_replay_config(repo_root: str | Path) -> dict[str, Any]:
    """Load the exact frozen N1 replay contract."""

    root = Path(repo_root).resolve(strict=True)
    config = strict_json_file(_rooted(root, _CONFIG_RELATIVE, "config path"))
    if config != _expected_config():
        _fail("config differs from the frozen contract")
    for owner in ("source_artifact_names", "artifact_names"):
        for name, relative in config[owner].items():
            if not isinstance(relative, str):
                _fail(f"{owner}.{name} must be a string")
            _rooted(root, relative.replace("{pair_id}", "01"), f"{owner}.{name}")
    return config


def select_replay_cases(
    audit_rows: Sequence[Mapping[str, Any]],
    cluster_order: Sequence[str],
    *,
    guard_band: float,
) -> list[dict[str, Any]]:
    """Select the closest VMAX exceedance in each ordered cluster."""

    if isinstance(audit_rows, (str, bytes)) or not isinstance(audit_rows, Sequence):
        _fail("selection rows must be a sequence")
    if isinstance(cluster_order, (str, bytes)) or not isinstance(cluster_order, Sequence):
        _fail("cluster order must be a sequence")
    clusters = list(cluster_order)
    if not clusters or len(set(clusters)) != len(clusters) or not all(
        isinstance(item, str) and item for item in clusters
    ):
        _fail("cluster order must contain unique nonempty strings")
    try:
        target = Decimal(str(guard_band))
    except InvalidOperation:
        _fail("selection guard band is invalid")
    if not target.is_finite() or target <= 0:
        _fail("selection guard band must be finite and positive")
    selected: list[dict[str, Any]] = []
    for cluster in clusters:
        candidates: list[tuple[Decimal, str, dict[str, Any]]] = []
        for raw in audit_rows:
            if not isinstance(raw, Mapping):
                _fail("selection row must be a mapping")
            if raw.get("scenario_cluster") != cluster or raw.get("constraint_family") != "VMAX":
                continue
            pair_id = raw.get("pair_id")
            if not isinstance(pair_id, str) or re.fullmatch(r"[0-9]{2}", pair_id) is None:
                _fail("selection pair ID must be two digits")
            exceedance = _finite(raw.get("exceedance"), "selection exceedance", positive=True)
            distance = abs(Decimal(str(exceedance)) - target)
            candidates.append((distance, pair_id, deepcopy(dict(raw))))
        if not candidates:
            _fail(f"cluster {cluster} has no archived VMAX witness")
        selected.append(min(candidates, key=lambda item: (item[0], item[1]))[2])
    return selected


def _read_audit_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != _AUDIT_FIELDS:
                _fail("source audit CSV columns differ from the frozen contract")
            rows = list(reader)
    except OSError as exc:
        _fail(f"cannot read source audit CSV ({exc})")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        _fail("source audit CSV contains malformed rows")
    return rows


def _normalized_vmax_rows(rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        if row["audit_point"] != "BOUNDARY_INFEASIBLE":
            continue
        if (
            row["feasible"] != "false"
            or row["failure_class"] != "PHYSICAL_CONSTRAINT"
            or row["explicit_physical_witness"] != "true"
            or row["numerical_failure_checks"] != "0"
        ):
            _fail(f"source boundary row {row['pair_id']} is not a clean physical witness")
        families = row["simultaneous_violation_families"].split(";")
        objects = row["simultaneous_violation_objects"].split(";")
        values = row["simultaneous_violation_values"].split(";")
        limits = row["simultaneous_violation_limits"].split(";")
        exceedances = row["simultaneous_violation_exceedances"].split(";")
        if len({len(families), len(objects), len(values), len(limits), len(exceedances)}) != 1:
            _fail(f"source boundary row {row['pair_id']} witness vectors differ")
        for family, object_id, value, limit, exceedance in zip(
            families, objects, values, limits, exceedances, strict=True
        ):
            if family != "VMAX":
                continue
            try:
                execution_order = int(row["execution_order"])
                selected_slot = int(row["selected_slot"])
            except ValueError:
                _fail(f"source boundary row {row['pair_id']} integer fields are invalid")
            normalized = {
                "pair_id": row["pair_id"],
                "stage": row["stage"],
                "execution_order": execution_order,
                "scenario_cluster": row["scenario_cluster"],
                "source_evaluation_id": row["source_evaluation_id"],
                "alpha": _finite(row["alpha_label"], "source boundary alpha"),
                "alpha_label": row["alpha_label"],
                "selected_slot": selected_slot,
                "constraint_family": "VMAX",
                "metric_id": f"V:{object_id}",
                "object_id": object_id,
                "direction": "hi",
                "value": _finite(value, "source VMAX value"),
                "limit": _finite(limit, "source VMAX limit"),
                "exceedance": _finite(exceedance, "source VMAX exceedance", positive=True),
                "audited_schedule_sha256": row["audited_schedule_sha256"],
            }
            if (
                not 0 <= selected_slot <= 95
                or _SHA256_RE.fullmatch(normalized["audited_schedule_sha256"]) is None
                or not math.isclose(
                    normalized["value"] - normalized["limit"],
                    normalized["exceedance"],
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                _fail(f"source boundary row {row['pair_id']} VMAX evidence is inconsistent")
            output.append(normalized)
    return output


def load_replay_source(
    repo_root: str | Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate archived D1-R-Lite/N0 evidence and rederive the four cases."""

    root = Path(repo_root).resolve(strict=True)
    if dict(config) != _expected_config():
        _fail("source loading requires the frozen replay config")
    for item in config["frozen_sources"]:
        path = _rooted(root, item["path"], f"frozen source {item['path']}")
        if _sha256(path, str(item["path"])) != item["sha256"]:
            _fail(f"frozen source hash drift: {item['path']}")
    requirement = config["runtime_requirement"]
    try:
        installed = version(requirement["distribution"])
    except PackageNotFoundError:
        _fail(f"required runtime distribution is missing: {requirement['distribution']}")
    if installed != requirement["version"]:
        _fail(f"runtime version differs: {installed} != {requirement['version']}")

    margin_config = load_margin_config(root)
    margin_source = load_margin_source(root, margin_config)
    n0_path = _rooted(
        root, config["source_artifact_names"]["n0_report_json"], "N0 report"
    )
    n0 = strict_json_file(n0_path)
    if (
        n0.get("protocol_version") != config["source_n0_protocol_version"]
        or n0.get("decision") != "HOLD_MARGIN_FRAGILE_AT_1E5"
        or n0.get("source_report_decision") != "COMMON_CANDIDATE_CONFOUNDED"
        or n0.get("new_power_flow_solves") != 0
        or n0.get("formal_v2_1_run_started") is not False
        or n0.get("formal_v2_1_run_authorized") is not False
        or n0.get("line_thermal_in_scope") is not False
        or n0.get("decisive_support", {}).get("case_count") != 6
        or n0.get("decisive_support", {}).get("scenario_cluster_count") != 3
    ):
        _fail("N0 source is not the frozen completed HOLD result")

    cases = margin_source["cases"]
    artifacts = margin_source["artifacts"]
    if [case["pair_id"] for case in cases] != config["source_pair_order"]:
        _fail("source case order differs from the frozen replay contract")
    cluster_order: list[str] = []
    for case in cases:
        cluster = str(case["scenario_cluster"])
        if cluster not in cluster_order:
            cluster_order.append(cluster)
    if cluster_order != config["scenario_cluster_order"]:
        _fail("source scenario-cluster order differs from the frozen replay contract")

    audit_path = _rooted(
        root, config["source_artifact_names"]["audit_csv"], "source audit CSV"
    )
    normalized = _normalized_vmax_rows(_read_audit_rows(audit_path))
    selected = select_replay_cases(
        normalized,
        cluster_order,
        guard_band=config["selection"]["guard_band_pu"],
    )
    if selected != config["selected_cases"]:
        _fail("derived representative cases differ from the frozen selection")
    if [item["pair_id"] for item in selected] != config["selected_pair_ids"]:
        _fail("derived representative pair order differs")
    case_by_pair = {str(case["pair_id"]): deepcopy(case) for case in cases}
    artifact_by_pair = {
        str(artifact["pair_id"]): deepcopy(artifact) for artifact in artifacts
    }
    return {
        "selected": deepcopy(selected),
        "selected_cases": [
            {
                "selection": deepcopy(item),
                "case": case_by_pair[item["pair_id"]],
                "source_artifact": artifact_by_pair[item["pair_id"]],
            }
            for item in selected
        ],
        "cases": deepcopy(cases),
        "source_artifacts": deepcopy(artifacts),
        "source_case_hash_rows": deepcopy(margin_source["hash_rows"]),
        "n0_report": deepcopy(n0),
        "runtime_version": installed,
        "frozen_source_hashes": {
            item["path"]: item["sha256"] for item in config["frozen_sources"]
        },
    }
