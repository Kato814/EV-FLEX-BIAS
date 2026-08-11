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


_OBSERVATION_KEYS = {
    "setting_label",
    "requested_solver_settings",
    "observed_solver_settings",
    "selected_slot",
    "load_scale",
    "audited_schedule_sha256",
    "power_vector_sha256",
    "metric_id",
    "metric_value",
    "limit",
    "direction",
    "exceedance",
    "physical_violation",
    "physical_violation_metrics",
    "converged",
    "numerical_failure",
    "iterations",
    "vmin",
    "vmax",
    "line_thermal_in_scope",
    "independent_context",
}
_OBSERVED_SETTING_KEYS = {
    "convergence_tolerance",
    "max_iterations",
    "max_control_iterations",
}
_CASE_ARTIFACT_KEYS = {
    "protocol_version",
    "status",
    "pair_id",
    "scenario_cluster",
    "selection",
    "source_evidence_commit",
    "source_n0_commit",
    "runtime_version",
    "target_replay_evaluations",
    "observations",
    "assessment",
    "formal_v2_1_run_started",
    "formal_v2_1_run_authorized",
    "line_thermal_in_scope",
    "resource_policy",
}


def _validate_finite_tree(value: Any, label: str) -> None:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            _fail(f"{label} mapping keys must be strings")
        for key, item in value.items():
            _validate_finite_tree(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_finite_tree(item, f"{label}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        _fail(f"{label} contains a non-finite number")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a mapping")
    return value


def _json_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be a finite JSON number")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{label} must be a finite JSON number")
    return number


def _json_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _frozen_selection(
    selection: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(selection, Mapping):
        _fail("selection must be a mapping")
    matches = [
        item
        for item in config["selected_cases"]
        if item["pair_id"] == selection.get("pair_id")
    ]
    if len(matches) != 1 or dict(selection) != matches[0]:
        _fail("selection differs from the frozen representative case")
    return matches[0]


def _validate_observation(
    observation: Mapping[str, Any],
    *,
    selection: Mapping[str, Any],
    setting: Mapping[str, Any],
    physical_margin: float,
) -> dict[str, Any]:
    row = _mapping(observation, "replay observation")
    if set(row) != _OBSERVATION_KEYS:
        _fail("replay observation has unexpected or missing fields")
    if row.get("setting_label") != setting["label"]:
        _fail("replay observation setting order or label differs")
    requested = _mapping(
        row.get("requested_solver_settings"), "requested solver settings"
    )
    if dict(requested) != dict(setting):
        _fail("requested solver settings differ from the frozen setting")
    observed = _mapping(
        row.get("observed_solver_settings"), "observed solver settings"
    )
    if set(observed) != _OBSERVED_SETTING_KEYS:
        _fail("observed solver settings have unexpected or missing fields")
    observed_tolerance = _json_number(
        observed.get("convergence_tolerance"), "observed convergence tolerance"
    )
    observed_max_iterations = _json_int(
        observed.get("max_iterations"), "observed maximum iterations", minimum=1
    )
    observed_max_control_iterations = _json_int(
        observed.get("max_control_iterations"),
        "observed maximum control iterations",
        minimum=1,
    )
    if observed_tolerance <= 0.0:
        _fail("observed convergence tolerance must be positive")

    if row.get("selected_slot") != selection["selected_slot"]:
        _fail("replay observation selected slot differs")
    load_scale = _json_number(row.get("load_scale"), "replay load scale")
    if load_scale <= 0.0:
        _fail("replay load scale must be positive")
    if row.get("audited_schedule_sha256") != selection["audited_schedule_sha256"]:
        _fail("replay observation schedule hash differs")
    power_hash = row.get("power_vector_sha256")
    if not isinstance(power_hash, str) or _SHA256_RE.fullmatch(power_hash) is None:
        _fail("replay power-vector hash is invalid")

    metric_id = row.get("metric_id")
    if not isinstance(metric_id, str) or re.fullmatch(r"V:[^;\s]+", metric_id) is None:
        _fail("replay metric ID is invalid")
    direction = row.get("direction")
    if direction not in {"hi", "lo"}:
        _fail("replay direction must be hi or lo")
    value = _json_number(row.get("metric_value"), "replay metric value")
    limit = _json_number(row.get("limit"), "replay metric limit")
    exceedance = _json_number(row.get("exceedance"), "replay exceedance")
    if exceedance < 0.0:
        _fail("replay exceedance must be nonnegative")
    expected_exceedance = max(
        0.0, value - limit if direction == "hi" else limit - value
    )
    if not math.isclose(exceedance, expected_exceedance, rel_tol=0.0, abs_tol=1e-12):
        _fail("replay exceedance is inconsistent with value, limit, and direction")
    physical = row.get("physical_violation")
    if not isinstance(physical, bool):
        _fail("replay physical-violation flag must be Boolean")
    expected_physical = bool(
        value > limit + physical_margin
        if direction == "hi"
        else value < limit - physical_margin
    )
    if physical is not expected_physical:
        _fail("replay physical-violation flag is inconsistent")
    metrics = row.get("physical_violation_metrics")
    if (
        not isinstance(metrics, list)
        or not all(isinstance(item, str) and item for item in metrics)
        or len(metrics) != len(set(metrics))
    ):
        _fail("replay physical-violation metrics are invalid")
    if (metric_id in metrics) is not physical:
        _fail("selected replay metric presence contradicts its physical flag")

    for name in ("converged", "numerical_failure", "independent_context"):
        if not isinstance(row.get(name), bool):
            _fail(f"replay {name} must be Boolean")
    if row.get("independent_context") is not True:
        _fail("replay setting was not evaluated in an independent context")
    if row.get("line_thermal_in_scope") is not False:
        _fail("replay observation expands the frozen scope")
    iterations = _json_int(row.get("iterations"), "replay iterations")
    vmin = _json_number(row.get("vmin"), "replay minimum voltage")
    vmax = _json_number(row.get("vmax"), "replay maximum voltage")
    if vmin > vmax:
        _fail("replay voltage extrema are inconsistent")

    settings_ok = bool(
        observed_tolerance == float(setting["convergence_tolerance"])
        and observed_max_iterations == setting["max_iterations"]
        and observed_max_control_iterations == setting["max_control_iterations"]
    )
    return {
        "value": value,
        "limit": limit,
        "metric_id": metric_id,
        "direction": direction,
        "physical": physical,
        "physical_metrics": list(metrics),
        "settings_ok": settings_ok,
        "converged": row["converged"],
        "numerical_failure_free": row["numerical_failure"] is False,
        "iterations": iterations,
    }


def assess_case_replay(
    selection: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the frozen N1 identity, persistence, and drift rules to one case."""

    if dict(config) != _expected_config():
        _fail("case assessment requires the frozen replay config")
    frozen = _frozen_selection(selection, config)
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        _fail("replay observations must be a sequence")
    retained = list(observations)
    settings = config["solver_settings"]
    if len(retained) != len(settings):
        _fail("case replay requires exactly three observations")
    threshold = config["thresholds"]
    normalized = [
        _validate_observation(
            observation,
            selection=frozen,
            setting=setting,
            physical_margin=float(threshold["physical_violation_margin_pu"]),
        )
        for observation, setting in zip(retained, settings, strict=True)
    ]
    labels = [str(setting["label"]) for setting in settings]
    solver_settings_ok = {
        label: item["settings_ok"] for label, item in zip(labels, normalized, strict=True)
    }
    convergence_ok = {
        label: item["converged"] for label, item in zip(labels, normalized, strict=True)
    }
    numerical_failure_free = {
        label: item["numerical_failure_free"]
        for label, item in zip(labels, normalized, strict=True)
    }
    solver_failure = not (
        all(solver_settings_ok.values())
        and all(convergence_ok.values())
        and all(numerical_failure_free.values())
    )

    native = normalized[0]
    native_abs_diff = abs(native["value"] - float(frozen["value"]))
    native_identity = bool(
        native["metric_id"] == frozen["metric_id"]
        and native["direction"] == frozen["direction"]
        and native["limit"] == float(frozen["limit"])
        and native["physical"]
        and frozen["metric_id"] in native["physical_metrics"]
        and native_abs_diff <= float(threshold["native_replay_identity_pu"])
    )

    tight_labels = labels[1:]
    witness_persists: dict[str, bool] = {}
    native_to_tight_drift: dict[str, float] = {}
    native_to_tight_ok: dict[str, bool] = {}
    for label, item in zip(tight_labels, normalized[1:], strict=True):
        witness_persists[label] = bool(
            item["metric_id"] == frozen["metric_id"]
            and item["direction"] == frozen["direction"]
            and item["limit"] == float(frozen["limit"])
            and item["physical"]
            and frozen["metric_id"] in item["physical_metrics"]
        )
        drift = abs(item["value"] - native["value"])
        native_to_tight_drift[label] = drift
        native_to_tight_ok[label] = bool(
            drift <= float(threshold["native_to_tight_drift_pu"])
        )
    plateau_drift = abs(normalized[2]["value"] - normalized[1]["value"])
    plateau_ok = bool(
        plateau_drift <= float(threshold["tight_plateau_drift_pu"])
    )

    if solver_failure:
        decision = "STOP_SOLVER_FAILURE"
    elif not native_identity:
        decision = "STOP_REPLAY_IDENTITY_MISMATCH"
    elif (
        all(witness_persists.values())
        and all(native_to_tight_ok.values())
        and plateau_ok
    ):
        decision = "NUMERICALLY_STABLE_WITNESS"
    else:
        decision = "NUMERICAL_SENSITIVITY_DETECTED"
    return {
        "case_decision": decision,
        "native_replay_abs_diff_pu": native_abs_diff,
        "native_replay_identity_ok": native_identity,
        "solver_settings_ok": solver_settings_ok,
        "convergence_ok": convergence_ok,
        "numerical_failure_free": numerical_failure_free,
        "witness_persists": witness_persists,
        "native_to_tight_drift_pu": native_to_tight_drift,
        "native_to_tight_drift_ok": native_to_tight_ok,
        "tight_plateau_drift_pu": plateau_drift,
        "tight_plateau_ok": plateau_ok,
        "all_solver_settings_ok": all(solver_settings_ok.values()),
        "all_converged": all(convergence_ok.values()),
        "all_numerical_failure_free": all(numerical_failure_free.values()),
    }


def validate_replay_case_artifact(
    artifact: Mapping[str, Any],
    selection: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    """Strictly validate one terminal N1 case artifact and rederive its result."""

    if not isinstance(artifact, Mapping):
        _fail("case artifact must be a mapping")
    _validate_finite_tree(artifact, "case artifact")
    if dict(config) != _expected_config():
        _fail("case validation requires the frozen replay config")
    frozen = _frozen_selection(selection, config)
    if set(artifact) != _CASE_ARTIFACT_KEYS:
        _fail("case artifact has unexpected or missing fields")
    status = artifact.get("status")
    if status not in {"SUCCESS", "STOP_REPLAY"}:
        _fail("case artifact status is not terminal")
    identity = {
        "protocol_version": config["protocol_version"],
        "pair_id": frozen["pair_id"],
        "scenario_cluster": frozen["scenario_cluster"],
        "selection": dict(frozen),
        "source_evidence_commit": config["source_evidence_commit"],
        "source_n0_commit": config["source_n0_commit"],
        "runtime_version": config["runtime_requirement"]["version"],
        "target_replay_evaluations": len(config["solver_settings"]),
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
        "resource_policy": config["resource_policy"],
    }
    if any(artifact.get(name) != value for name, value in identity.items()):
        _fail("case identity, provenance, resource policy, or scope differs")
    observations = artifact.get("observations")
    if (
        not isinstance(observations, list)
        or not all(isinstance(item, Mapping) for item in observations)
    ):
        _fail("case observations must be a mapping list")
    expected_assessment = assess_case_replay(frozen, observations, config)
    if artifact.get("assessment") != expected_assessment:
        _fail("case assessment differs from the rederived result")
    expected_status = (
        "STOP_REPLAY"
        if expected_assessment["case_decision"].startswith("STOP_")
        else "SUCCESS"
    )
    if status != expected_status:
        _fail("case status contradicts the rederived result")


def assess_replay_gate(
    case_artifacts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate an ordered terminal prefix of the four N1 replay cases."""

    if dict(config) != _expected_config():
        _fail("replay gate requires the frozen replay config")
    if isinstance(case_artifacts, (str, bytes)) or not isinstance(
        case_artifacts, Sequence
    ):
        _fail("replay case artifacts must be a sequence")
    retained = list(case_artifacts)
    selected = config["selected_cases"]
    if not retained or len(retained) > len(selected):
        _fail("replay gate requires a nonempty ordered case prefix")
    for index, (artifact, selection) in enumerate(
        zip(retained, selected, strict=False)
    ):
        validate_replay_case_artifact(artifact, selection, config)
        is_stop = artifact["assessment"]["case_decision"].startswith("STOP_")
        if is_stop and index != len(retained) - 1:
            _fail("a stopped replay case must terminate the artifact prefix")
    decisions = [artifact["assessment"]["case_decision"] for artifact in retained]
    stops = [decision for decision in decisions if decision.startswith("STOP_")]
    if len(stops) > 1:
        _fail("replay prefix contains more than one terminal stop")
    if stops:
        decision = stops[0]
    elif len(retained) != len(selected):
        _fail("a non-stopped replay gate requires all four cases")
    elif all(decision == "NUMERICALLY_STABLE_WITNESS" for decision in decisions):
        decision = "NUMERICALLY_STABLE_SELECTED_WITNESSES"
    else:
        decision = "NUMERICAL_SENSITIVITY_DETECTED"
    return {
        "protocol_version": config["protocol_version"],
        "decision": decision,
        "completed_case_count": len(retained),
        "stable_case_count": decisions.count("NUMERICALLY_STABLE_WITNESS"),
        "sensitive_case_count": decisions.count("NUMERICAL_SENSITIVITY_DETECTED"),
        "pair_ids": [str(artifact["pair_id"]) for artifact in retained],
        "target_replay_evaluations": sum(
            int(artifact["target_replay_evaluations"]) for artifact in retained
        ),
        "formal_v2_1_run_authorized": False,
    }
