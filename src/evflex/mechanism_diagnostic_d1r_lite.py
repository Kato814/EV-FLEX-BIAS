"""Strict inputs and execution primitives for the bounded D1-R-Lite screen."""

from __future__ import annotations

import csv
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Callable, Mapping, Sequence


_CONFIG_RELATIVE = Path("config/mechanism_diagnostic_v2_1_d1r_lite.json")
_MANIFEST_RELATIVE = Path(
    "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv"
)
_SOURCE_MANIFEST_RELATIVE = Path(
    "manifests/mechanism_diagnostic_pairs_v2_1.csv"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MANIFEST_FIELDS = (
    "pair_id",
    "stage",
    "execution_order",
    "scenario_cluster",
    "evaluation_id",
    "work_unit_id",
    "scenario_id",
    "scenario_seed",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "alpha_transfer",
    "source_duration_min",
    "schedule_sha256",
    "bus_phase_time_sha256",
    "baseline_schedule_sha256",
)


def _fail(detail: str) -> None:
    raise ValueError(f"D1-R-Lite: {detail}")


def _reject_json_constant(value: str) -> None:
    _fail(f"non-finite JSON constant {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key {key}")
        result[key] = value
    return result


def _expected_config() -> dict[str, Any]:
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.1-D1R-LITE",
        "source_protocol_version": "EV-FLEX-BIAS-V2.1-D1-MECHANISM",
        "source_commit": "e1740f912a351b1822b5ee019f9e4f05b6b71c6f",
        "artifact_names": {
            "config": "config/mechanism_diagnostic_v2_1_d1r_lite.json",
            "case_manifest": (
                "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv"
            ),
            "result_root": "results/mechanism_diagnostic_v2_1_d1r_lite",
            "case_artifact_pattern": (
                "results/mechanism_diagnostic_v2_1_d1r_lite/"
                "cases/case_{pair_id}.json"
            ),
            "run_lock": (
                "results/mechanism_diagnostic_v2_1_d1r_lite/.run.lock"
            ),
            "attempt_pattern": (
                "results/mechanism_diagnostic_v2_1_d1r_lite/"
                ".attempts/case_{pair_id}.json"
            ),
            "audit_csv": (
                "reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv"
            ),
            "report_json": (
                "reports/mechanism_diagnostic_v2_1_d1r_lite.json"
            ),
            "report_markdown": (
                "reports/mechanism_diagnostic_v2_1_d1r_lite.md"
            ),
            "hashes_csv": (
                "reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv"
            ),
        },
        "expected_counts": {
            "stage_a_cases": 4,
            "stage_a_audits": 8,
            "stage_b_cases": 8,
            "maximum_cases": 12,
            "maximum_audits": 16,
            "scenario_clusters": 4,
        },
        "adapter_identity": {
            "adapter_schema": "evflex.pilot.network-audit",
            "adapter_version": 2,
        },
        "selection": {
            "rule": "CLOSEST_TO_CLUSTER_MEDIAN_ALPHA_THEN_PAIR_ID",
            "stage_a_pair_ids": ["01", "04", "07", "10"],
            "stage_b_pair_ids": [
                "02",
                "03",
                "05",
                "06",
                "08",
                "09",
                "11",
                "12",
            ],
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
        },
        "audit": {
            "delta": 0.002,
            "stage_a_point_order": [
                "BOUNDARY_FEASIBLE",
                "BOUNDARY_INFEASIBLE",
            ],
            "stage_b_point_order": ["BOUNDARY_INFEASIBLE"],
            "family_order": [
                "VMIN",
                "VMAX",
                "VUF",
                "TRANSFORMER",
                "FEEDER",
            ],
        },
        "gates": {
            "stage_a_minimum_cases": 3,
            "stage_a_total_cases": 4,
            "final_minimum_cases": 8,
            "final_total_cases": 12,
            "final_minimum_scenario_clusters": 3,
            "final_total_scenario_clusters": 4,
        },
        "frozen_sources": [
            {
                "path": "src/evflex/pilot.py",
                "sha256": (
                    "37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b"
                ),
            },
            {
                "path": "src/evflex/mechanism_diagnostic.py",
                "sha256": (
                    "c455679f9f2595830a3db347c01eaaf0998b443ce3087457dc7544a94ecb1eaa"
                ),
            },
            {
                "path": "config/mechanism_diagnostic_v2_1.json",
                "sha256": (
                    "8ee0ea969d26e8a2bc55a065c89fdf382346c90904d15432e7694af64ec781b1"
                ),
            },
            {
                "path": "manifests/mechanism_diagnostic_pairs_v2_1.csv",
                "sha256": (
                    "5b7fc6dc5121a0e1ff42bec62710085fce07865ffc5a58008d05a1e2900d53f1"
                ),
            },
        ],
        "line_thermal_in_scope": False,
        "formal_v2_1_run_authorized": False,
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
    resolved = (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        _fail(f"{label} escapes the repository")
    return resolved


def load_lite_config(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=True)
    path = _rooted(root, _CONFIG_RELATIVE, "config path")
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(
                handle,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
    except OSError as exc:
        _fail(f"cannot read config ({exc})")
    except json.JSONDecodeError as exc:
        _fail(f"invalid config JSON ({exc})")
    if value != _expected_config():
        _fail("config differs from the frozen contract")
    for name, relative in value["artifact_names"].items():
        if not isinstance(relative, str) or "d1r_lite" not in relative:
            _fail(f"artifact_names.{name} is not an independent lite path")
        _rooted(root, relative, f"artifact_names.{name}")
    return value


def _read_csv(path: Path, expected_fields: Sequence[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or len(reader.fieldnames) != len(
                set(reader.fieldnames)
            ):
                _fail(f"{path.name} has duplicate or missing headers")
            if tuple(reader.fieldnames) != tuple(expected_fields):
                _fail(f"{path.name} columns differ from the frozen contract")
            rows = list(reader)
    except OSError as exc:
        _fail(f"cannot read {path.name} ({exc})")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        _fail(f"{path.name} contains malformed rows")
    return rows


def _source_bad_rows(root: Path) -> dict[str, dict[str, str]]:
    path = _rooted(root, _SOURCE_MANIFEST_RELATIVE, "source manifest")
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or len(reader.fieldnames) != len(
                set(reader.fieldnames)
            ):
                _fail("source manifest has duplicate or missing headers")
            rows = list(reader)
    except OSError as exc:
        _fail(f"cannot read source manifest ({exc})")
    if len(rows) != 12 or len({row.get("pair_id") for row in rows}) != 12:
        _fail("source manifest must contain 12 unique pairs")
    return {str(row["pair_id"]): row for row in rows}


def _parse_int(value: str, label: str, *, minimum: int = 0) -> int:
    if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        _fail(f"{label} must be a canonical integer")
    parsed = int(value)
    if parsed < minimum:
        _fail(f"{label} is below its minimum")
    return parsed


def _parse_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(f"{label} must be numeric")
    if not math.isfinite(parsed):
        _fail(f"{label} must be finite")
    return parsed


def _normalized_case(row: Mapping[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = dict(row)
    pair_id = normalized["pair_id"]
    if re.fullmatch(r"[0-9]{2}", pair_id) is None:
        _fail("pair_id must be two digits")
    if normalized["stage"] not in {"A", "B"}:
        _fail(f"case {pair_id} stage must be A or B")
    normalized["execution_order"] = _parse_int(
        normalized["execution_order"], f"case {pair_id} execution_order", minimum=1
    )
    normalized["scenario_seed"] = _parse_int(
        normalized["scenario_seed"], f"case {pair_id} scenario_seed"
    )
    for name in ("duration_min", "source_duration_min"):
        normalized[name] = _parse_int(
            normalized[name], f"case {pair_id} {name}", minimum=1
        )
    normalized["alpha_transfer"] = _parse_float(
        normalized["alpha_transfer"], f"case {pair_id} alpha_transfer"
    )
    if not 0.0 <= normalized["alpha_transfer"] < 0.95:
        _fail(f"case {pair_id} alpha is outside the archived bad range")
    if normalized["duration_min"] != normalized["source_duration_min"]:
        _fail(f"case {pair_id} source duration differs")
    if normalized["feeder"] != "lv906":
        _fail(f"case {pair_id} is not an LV906 bad member")
    if normalized["direction"] not in {"inc", "dec"}:
        _fail(f"case {pair_id} direction is invalid")
    for name in (
        "schedule_sha256",
        "bus_phase_time_sha256",
        "baseline_schedule_sha256",
    ):
        if _SHA256_RE.fullmatch(normalized[name]) is None:
            _fail(f"case {pair_id} {name} is not a lowercase SHA-256")
    return normalized


def stage_a_case_ids(cases: Sequence[Mapping[str, Any]]) -> list[str]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        groups.setdefault(str(case["scenario_cluster"]), []).append(case)
    ordered_groups = sorted(
        groups.values(), key=lambda group: min(int(str(item["pair_id"])) for item in group)
    )
    selected: list[str] = []
    for group in ordered_groups:
        median = statistics.median(float(item["alpha_transfer"]) for item in group)
        representative = min(
            group,
            key=lambda item: (
                abs(float(item["alpha_transfer"]) - median),
                str(item["pair_id"]),
            ),
        )
        selected.append(str(representative["pair_id"]))
    return selected


def stage_b_case_ids(cases: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(case["pair_id"])
        for case in sorted(cases, key=lambda item: int(item["execution_order"]))
        if case["stage"] == "B"
    ]


def load_lite_manifest(repo_root: str | Path) -> list[dict[str, Any]]:
    root = Path(repo_root).resolve(strict=True)
    config = load_lite_config(root)
    rows = _read_csv(
        _rooted(root, _MANIFEST_RELATIVE, "case manifest"), _MANIFEST_FIELDS
    )
    if len(rows) != config["expected_counts"]["maximum_cases"]:
        _fail("case manifest must contain exactly 12 rows")
    cases = [_normalized_case(row) for row in rows]
    pair_ids = [case["pair_id"] for case in cases]
    if len(set(pair_ids)) != len(pair_ids):
        _fail("case manifest contains duplicate pair IDs")
    if [case["execution_order"] for case in cases] != list(range(1, 13)):
        _fail("case execution order must be continuous from 1 through 12")
    if pair_ids != config["selection"]["execution_order"]:
        _fail("case rows differ from the frozen execution order")
    if stage_a_case_ids(cases) != config["selection"]["stage_a_pair_ids"]:
        _fail("Stage A representatives differ from the frozen median rule")
    if stage_b_case_ids(cases) != config["selection"]["stage_b_pair_ids"]:
        _fail("Stage B cases differ from the frozen selection")
    if [case["stage"] for case in cases[:4]] != ["A"] * 4 or [
        case["stage"] for case in cases[4:]
    ] != ["B"] * 8:
        _fail("case stages differ from the frozen 4-plus-8 design")

    source_rows = _source_bad_rows(root)
    comparison = {
        "scenario_cluster": "scenario_cluster",
        "evaluation_id": "bad_evaluation_id",
        "work_unit_id": "bad_work_unit_id",
        "scenario_id": "bad_scenario_id",
        "scenario_seed": "bad_scenario_seed",
        "feeder": "bad_feeder",
        "call_time": "bad_call_time",
        "direction": "bad_direction",
        "duration_min": "duration_min",
        "alpha_transfer": "bad_alpha_transfer",
        "source_duration_min": "bad_source_duration_min",
        "schedule_sha256": "bad_schedule_sha256",
        "bus_phase_time_sha256": "bad_bus_phase_time_sha256",
        "baseline_schedule_sha256": "bad_baseline_schedule_sha256",
    }
    for case in cases:
        source = source_rows.get(case["pair_id"])
        if source is None:
            _fail(f"case {case['pair_id']} is absent from the source manifest")
        for target_name, source_name in comparison.items():
            expected: Any = source[source_name]
            if target_name in {"scenario_seed", "duration_min", "source_duration_min"}:
                expected = int(expected)
            elif target_name == "alpha_transfer":
                expected = float(expected)
            if case[target_name] != expected:
                _fail(
                    f"case {case['pair_id']} {target_name} differs from the archived bad member"
                )
    return cases


def verify_lite_sources(
    repo_root: str | Path, config: Mapping[str, Any]
) -> None:
    root = Path(repo_root).resolve(strict=True)
    if dict(config) != _expected_config():
        _fail("source verification requires the frozen config")
    for item in config["frozen_sources"]:
        path = _rooted(root, item["path"], f"frozen source {item['path']}")
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            _fail(f"cannot read frozen source {item['path']} ({exc})")
        if digest != item["sha256"]:
            _fail(f"frozen source hash drift: {item['path']}")

    from evflex.mechanism_diagnostic import (
        load_mechanism_config,
        verify_frozen_sources,
    )

    old_config = load_mechanism_config(root)
    verify_frozen_sources(root, old_config)


def _identity_fail(code: str, detail: str) -> None:
    raise ValueError(f"{code}: {detail}")


def _finite_number(value: Any, code: str, detail: str) -> float:
    if isinstance(value, bool):
        _identity_fail(code, detail)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        _identity_fail(code, detail)
    if not math.isfinite(number):
        _identity_fail(code, detail)
    return number


def validate_raw_audit_identity(
    raw: Mapping[str, Any],
    *,
    case: Mapping[str, Any],
    formal_constraints: Mapping[str, Any],
    adapter_identity: Mapping[str, Any],
) -> None:
    """Validate audit provenance with one explicit failure code per field."""

    import numpy as np

    if not isinstance(raw, Mapping):
        _identity_fail("AUDIT_STRUCTURE_INVALID", "raw audit must be a mapping")
    records = raw.get("slot_results")
    if not isinstance(records, list) or not records:
        _identity_fail(
            "AUDIT_STRUCTURE_INVALID", "raw audit must retain slot results"
        )
    if not isinstance(case, Mapping):
        _identity_fail("AUDIT_STRUCTURE_INVALID", "case must be a mapping")
    member = case.get("member")
    if not isinstance(member, Mapping):
        _identity_fail("AUDIT_STRUCTURE_INVALID", "case member is missing")
    expected_feeder = member.get("feeder")
    if not isinstance(expected_feeder, str) or not expected_feeder:
        _identity_fail("AUDIT_STRUCTURE_INVALID", "case feeder is missing")
    try:
        expected_scales = np.asarray(case.get("load_scales"), dtype=float)
    except (TypeError, ValueError, OverflowError):
        _identity_fail("AUDIT_STRUCTURE_INVALID", "case load scales are invalid")
    if expected_scales.shape != (96,) or len(records) > 96 or not np.isfinite(
        expected_scales
    ).all():
        _identity_fail(
            "AUDIT_STRUCTURE_INVALID",
            "case load scales must cover the fixed 96-slot horizon",
        )

    if set(adapter_identity) != {"adapter_schema", "adapter_version"}:
        _identity_fail(
            "AUDIT_STRUCTURE_INVALID", "adapter identity fields are invalid"
        )
    expected_schema = adapter_identity["adapter_schema"]
    expected_version = adapter_identity["adapter_version"]
    if not isinstance(expected_schema, str) or type(expected_version) is not int:
        _identity_fail(
            "AUDIT_STRUCTURE_INVALID", "adapter identity types are invalid"
        )
    constraint_names = (
        "vmin_pu",
        "vmax_pu",
        "vuf_limit_pct",
        "transformer_loading_limit_pu",
        "feeder_loading_limit_pu",
    )
    expected_constraints = {
        name: _finite_number(
            formal_constraints.get(name),
            "AUDIT_STRUCTURE_INVALID",
            f"formal constraint {name} is invalid",
        )
        for name in constraint_names
    }
    if formal_constraints.get("line_thermal_in_scope") is not False:
        _identity_fail(
            "AUDIT_STRUCTURE_INVALID", "line thermal scope must remain false"
        )

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            _identity_fail(
                "AUDIT_STRUCTURE_INVALID", f"slot {index} record is not a mapping"
            )
        if (
            record.get("slot") != index
            or record.get("verified") is not True
            or record.get("source") not in {"power_flow", "baseline_reuse"}
        ):
            _identity_fail(
                "AUDIT_SLOT_IDENTITY_MISMATCH",
                f"slot {index} index, verification, or source differs",
            )
        if record.get("feeder") != expected_feeder:
            _identity_fail(
                "AUDIT_FEEDER_MISMATCH", f"slot {index} record feeder differs"
            )
        if record.get("model") != "3ph":
            _identity_fail(
                "AUDIT_MODEL_MISMATCH", f"slot {index} record model differs"
            )
        expected_scale = float(expected_scales[index])
        record_scale = _finite_number(
            record.get("load_scale"),
            "AUDIT_RECORD_SCALE_MISMATCH",
            f"slot {index} record scale is invalid",
        )
        if record_scale != expected_scale:
            _identity_fail(
                "AUDIT_RECORD_SCALE_MISMATCH",
                f"slot {index} record scale differs",
            )
        context = record.get("audit_context")
        if not isinstance(context, Mapping):
            _identity_fail(
                "AUDIT_STRUCTURE_INVALID", f"slot {index} context is missing"
            )
        context_scale = _finite_number(
            context.get("load_scale"),
            "AUDIT_CONTEXT_SCALE_MISMATCH",
            f"slot {index} context scale is invalid",
        )
        if context_scale != expected_scale:
            _identity_fail(
                "AUDIT_CONTEXT_SCALE_MISMATCH",
                f"slot {index} context scale differs",
            )
        observed_schema = context.get("adapter_schema")
        if type(observed_schema) is not type(expected_schema) or (
            observed_schema != expected_schema
        ):
            _identity_fail(
                "AUDIT_SCHEMA_MISMATCH", f"slot {index} adapter schema differs"
            )
        observed_version = context.get("adapter_version")
        if type(observed_version) is not type(expected_version) or (
            observed_version != expected_version
        ):
            _identity_fail(
                "AUDIT_VERSION_MISMATCH", f"slot {index} adapter version differs"
            )
        if context.get("feeder") != expected_feeder:
            _identity_fail(
                "AUDIT_FEEDER_MISMATCH", f"slot {index} context feeder differs"
            )
        if context.get("model") != "3ph":
            _identity_fail(
                "AUDIT_MODEL_MISMATCH", f"slot {index} context model differs"
            )
        for name, expected in expected_constraints.items():
            observed = _finite_number(
                context.get(name),
                "AUDIT_FORMAL_CONSTRAINT_MISMATCH",
                f"slot {index} formal constraint {name} is invalid",
            )
            if observed != expected:
                _identity_fail(
                    "AUDIT_FORMAL_CONSTRAINT_MISMATCH",
                    f"slot {index} formal constraint {name} differs",
                )
        if context.get("line_thermal_in_scope") is not False:
            _identity_fail(
                "AUDIT_FORMAL_CONSTRAINT_MISMATCH",
                f"slot {index} line thermal scope differs",
            )


def _case_as_d1_member(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pair_id": case["pair_id"],
        "scenario_cluster": case["scenario_cluster"],
        "role": "bad",
        "evaluation_id": case["evaluation_id"],
        "work_unit_id": case["work_unit_id"],
        "scenario_id": case["scenario_id"],
        "scenario_seed": case["scenario_seed"],
        "feeder": case["feeder"],
        "call_time": case["call_time"],
        "direction": case["direction"],
        "duration_min": case["duration_min"],
        "requested_duration_min": case["duration_min"],
        "source_duration_min": case["source_duration_min"],
        "alpha_transfer": case["alpha_transfer"],
        "schedule_sha256": case["schedule_sha256"],
        "bus_phase_time_sha256": case["bus_phase_time_sha256"],
        "baseline_schedule_sha256": case["baseline_schedule_sha256"],
    }


def real_runtime_preflight(
    repo_root: str | Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    """Run one real pair-01 baseline audit in memory before production."""

    from evflex import pilot
    from evflex.mechanism_diagnostic import (
        compact_targeted_audit,
        reconstruct_case,
    )

    root = Path(repo_root).resolve(strict=True)
    if dict(config) != _expected_config():
        _fail("real preflight requires the frozen config")
    verify_lite_sources(root, config)
    cases = load_lite_manifest(root)
    case = next(item for item in cases if item["pair_id"] == "01")
    pilot_config = pilot.load_pilot_config(root)
    reconstructed = reconstruct_case(
        root,
        _case_as_d1_member(case),
        pilot_config=pilot_config,
    )
    runtime = reconstructed["runtime"]
    cache = runtime.create_corrected_truth_cache()
    raw = runtime.audit_corrected(
        reconstructed["baseline"],
        cache,
        baseline_slot_results=None,
        stop_on_violation=False,
        retain_slot_results=True,
    )
    validate_raw_audit_identity(
        raw,
        case=reconstructed,
        formal_constraints=pilot_config["formal_constraints"],
        adapter_identity=config["adapter_identity"],
    )
    compact = compact_targeted_audit(
        raw,
        audit_point="BOUNDARY_FEASIBLE",
        alpha=0.0,
    )
    records = raw.get("slot_results")
    if (
        compact.get("feasible") is not True
        or compact.get("complete_coverage") is not True
        or not isinstance(records, list)
        or len(records) != 96
    ):
        _fail("real preflight baseline is not feasible with 96-slot coverage")
    return {
        "status": "PREFLIGHT_OK",
        "pair_id": "01",
        "record_count": len(records),
        "adapter_schema": config["adapter_identity"]["adapter_schema"],
        "adapter_version": config["adapter_identity"]["adapter_version"],
        "identity_mismatch_count": 0,
        "writes_performed": False,
        "formal_v2_1_run_started": False,
    }


class LiteAuditStop(ValueError):
    """Controlled immutable case stop with the retained target-audit prefix."""

    def __init__(
        self,
        rule_code: str,
        detail: str,
        *,
        audits: Sequence[Mapping[str, Any]] = (),
        sequence_index: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.rule_code = rule_code
        self.detail = detail
        self.audits = [deepcopy(dict(audit)) for audit in audits]
        self.sequence_index = sequence_index


def _identity_error_code(exc: ValueError) -> str | None:
    prefix = str(exc).partition(":")[0]
    if re.fullmatch(r"AUDIT_[A-Z0-9_]+", prefix):
        return prefix
    return None


def _audit_points(case: Mapping[str, Any], config: Mapping[str, Any]) -> list[tuple[str, float, str]]:
    try:
        base = Decimal(str(case["alpha_transfer"]))
        delta = Decimal(str(config["audit"]["delta"]))
    except (InvalidOperation, KeyError, TypeError) as exc:
        _fail(f"case audit alpha is invalid ({exc})")
    if delta != Decimal("0.002") or not Decimal("0") <= base < Decimal("0.950"):
        _fail("case audit alpha differs from the frozen boundary rule")
    values = {
        "BOUNDARY_FEASIBLE": base,
        "BOUNDARY_INFEASIBLE": base + delta,
    }
    order = (
        config["audit"]["stage_a_point_order"]
        if case["stage"] == "A"
        else config["audit"]["stage_b_point_order"]
    )
    return [
        (name, float(values[name]), format(values[name], ".3f")) for name in order
    ]


def _prune_lite_evidence(compact: Mapping[str, Any]) -> dict[str, Any]:
    output = deepcopy(dict(compact))
    selected = output.get("selected_slot")
    if selected is None:
        return output
    if not isinstance(selected, Mapping):
        _fail("selected audit evidence must be a mapping")
    mutable = dict(selected)
    rows = mutable.get("constraint_rows")
    if not isinstance(rows, list):
        _fail("selected audit constraint rows must be a list")
    retained = [deepcopy(row) for row in rows if row.get("is_physical_violation") is True]
    mutable["constraint_rows"] = retained
    mutable["simultaneous_violations"] = deepcopy(retained)
    output["selected_slot"] = mutable
    return output


def execute_lite_case(
    repo_root: str | Path,
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    runtime_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute one fixed-trajectory LV906 case under the compact protocol."""

    import numpy as np
    from evflex import pilot
    from evflex.mechanism_diagnostic import (
        compact_targeted_audit,
        reconstruct_case,
    )

    root = Path(repo_root).resolve(strict=True)
    if dict(config) != _expected_config():
        _fail("case execution requires the frozen config")
    if not isinstance(case, Mapping) or case.get("stage") not in {"A", "B"}:
        _fail("case execution requires a Stage A or Stage B mapping")
    if case.get("feeder") != "lv906":
        _fail("D1-R-Lite executes LV906 cases only")
    pilot_config = pilot.load_pilot_config(root)
    reconstructed = reconstruct_case(
        root,
        _case_as_d1_member(case),
        pilot_config=pilot_config,
        runtime_factory=runtime_factory,
    )
    runtime = reconstructed["runtime"]
    try:
        cache = runtime.create_corrected_truth_cache()
        baseline_raw = runtime.audit_corrected(
            reconstructed["baseline"],
            cache,
            baseline_slot_results=None,
            stop_on_violation=False,
            retain_slot_results=True,
        )
        validate_raw_audit_identity(
            baseline_raw,
            case=reconstructed,
            formal_constraints=pilot_config["formal_constraints"],
            adapter_identity=config["adapter_identity"],
        )
        baseline_compact = compact_targeted_audit(
            baseline_raw,
            audit_point="BOUNDARY_FEASIBLE",
            alpha=0.0,
        )
    except ValueError as exc:
        code = _identity_error_code(exc) or "PRE_AUDIT_IMPLEMENTATION_INVALID"
        raise LiteAuditStop(code, str(exc), sequence_index=None) from exc
    baseline_slots = baseline_raw.get("slot_results")
    if (
        baseline_compact.get("feasible") is not True
        or baseline_compact.get("complete_coverage") is not True
        or not isinstance(baseline_slots, list)
        or len(baseline_slots) != 96
    ):
        raise LiteAuditStop(
            "PRE_AUDIT_IMPLEMENTATION_INVALID",
            "D1-R-Lite baseline must be feasible with complete 96-slot coverage",
            sequence_index=None,
        )

    audits: list[dict[str, Any]] = []
    for sequence_index, (audit_point, alpha, alpha_label) in enumerate(
        _audit_points(case, config)
    ):
        audited_schedule = reconstructed["baseline"] + alpha * (
            reconstructed["schedule"] - reconstructed["baseline"]
        )
        if not np.isfinite(audited_schedule).all():
            raise LiteAuditStop(
                "AUDIT_EVIDENCE_INVALID",
                "audited schedule contains a non-finite value",
                audits=audits,
                sequence_index=sequence_index,
            )
        try:
            raw = runtime.audit_corrected(
                audited_schedule,
                cache,
                baseline_slot_results=baseline_slots,
                stop_on_violation=audit_point == "BOUNDARY_INFEASIBLE",
                retain_slot_results=True,
            )
            validate_raw_audit_identity(
                raw,
                case=reconstructed,
                formal_constraints=pilot_config["formal_constraints"],
                adapter_identity=config["adapter_identity"],
            )
            compact = compact_targeted_audit(
                raw,
                audit_point=audit_point,
                alpha=alpha,
            )
            compact = _prune_lite_evidence(compact)
        except ValueError as exc:
            code = _identity_error_code(exc) or "AUDIT_EVIDENCE_INVALID"
            raise LiteAuditStop(
                code,
                str(exc),
                audits=audits,
                sequence_index=sequence_index,
            ) from exc
        audit_record = {
            "sequence_index": sequence_index,
            "audit_point": audit_point,
            "alpha": alpha,
            "alpha_label": alpha_label,
            "source_evaluation_id": case["evaluation_id"],
            "audited_schedule_sha256": pilot.canonical_schedule_sha256(
                reconstructed["fleet"], audited_schedule
            ),
            "formal_constraints": deepcopy(pilot_config["formal_constraints"]),
            "line_thermal_in_scope": False,
            **compact,
        }
        audits.append(audit_record)
        if audit_point == "BOUNDARY_FEASIBLE":
            valid = bool(
                compact.get("feasible") is True
                and compact.get("complete_coverage") is True
                and compact.get("explicit_physical_witness") is False
            )
            if not valid:
                raise LiteAuditStop(
                    "BOUNDARY_FEASIBLE_REQUIRED",
                    "archived boundary point must remain feasible",
                    audits=audits,
                    sequence_index=sequence_index,
                )
        else:
            valid = bool(
                compact.get("feasible") is False
                and compact.get("explicit_physical_witness") is True
                and compact.get("failure_class") == "PHYSICAL_CONSTRAINT"
                and compact.get("numerical_failure_checks") == 0
            )
            if not valid:
                raise LiteAuditStop(
                    "BOUNDARY_INFEASIBLE_REQUIRED",
                    "alpha plus 0.002 must have an explicit physical witness",
                    audits=audits,
                    sequence_index=sequence_index,
                )

    return {
        "protocol_version": config["protocol_version"],
        "status": "SUCCESS",
        "pair_id": case["pair_id"],
        "stage": case["stage"],
        "execution_order": case["execution_order"],
        "scenario_cluster": case["scenario_cluster"],
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "formal_v2_1_run_authorized": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "member": deepcopy(dict(case)),
        "audits": audits,
    }


_LITE_COMMON_ARTIFACT_KEYS = {
    "protocol_version",
    "status",
    "pair_id",
    "stage",
    "execution_order",
    "scenario_cluster",
    "source_commit",
    "line_thermal_in_scope",
    "formal_v2_1_run_authorized",
    "resource_policy",
    "member",
    "audits",
}
_LITE_AUDIT_KEYS = {
    "sequence_index",
    "audit_point",
    "alpha",
    "alpha_label",
    "source_evaluation_id",
    "audited_schedule_sha256",
    "formal_constraints",
    "line_thermal_in_scope",
    "feasible",
    "checked_intervals",
    "coverage_ratio",
    "complete_coverage",
    "converged_checks",
    "nonconverged_checks",
    "numerical_failure_checks",
    "physical_violation_checks",
    "failure_class",
    "first_failure_slot",
    "explicit_physical_witness",
    "selected_slot",
    "coverage_counts",
    "vmin",
    "vmax",
    "vufmax",
    "transformer_loading_max",
    "feeder_loading_max",
}
_LITE_SELECTED_KEYS = {"slot", "constraint_rows", "simultaneous_violations"}
_LITE_CONSTRAINT_ROW_KEYS = {
    "slot",
    "constraint_family",
    "metric_id",
    "object_id",
    "value",
    "limit",
    "direction",
    "signed_headroom",
    "exceedance",
    "is_physical_violation",
}
_LITE_COVERAGE_KEYS = {
    "all_bus_count",
    "monitored_bus_count",
    "energized_voltage_node_count",
    "monitored_voltage_node_count",
    "three_phase_bus_count",
    "monitored_vuf_bus_count",
    "enabled_transformer_count",
    "rated_transformer_count",
    "transformer_rating_coverage",
    "line_count",
    "line_thermal_in_scope",
    "feeder_rating_multiplier",
    "transformer_ratings_kva",
    "transformer_raw_ratings_kva",
    "transformer_rating_multiplier",
    "transformer_rating_basis",
    "transformer_power_basis",
}
_LITE_FORMAL_CONSTRAINTS = {
    "vmin_pu": 0.95,
    "vmax_pu": 1.06,
    "vuf_limit_pct": 2.0,
    "transformer_loading_limit_pu": 1.0,
    "feeder_loading_limit_pu": 1.0,
    "line_thermal_in_scope": False,
}


def _validate_finite_artifact_tree(value: Any, label: str) -> None:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            _fail(f"{label} mapping keys must be strings")
        for key, item in value.items():
            _validate_finite_artifact_tree(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_finite_artifact_tree(item, f"{label}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        _fail(f"{label} contains a non-finite number")


def _artifact_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a mapping")
    return value


def _artifact_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _artifact_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be a finite JSON number")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{label} must be a finite JSON number")
    return number


def _validate_lite_coverage(value: Any, label: str) -> None:
    coverage = _artifact_mapping(value, label)
    if set(coverage) != _LITE_COVERAGE_KEYS:
        _fail(f"{label} has unexpected or missing fields")
    count_names = (
        "all_bus_count",
        "monitored_bus_count",
        "energized_voltage_node_count",
        "monitored_voltage_node_count",
        "three_phase_bus_count",
        "monitored_vuf_bus_count",
        "enabled_transformer_count",
        "rated_transformer_count",
        "line_count",
    )
    counts = {
        name: _artifact_int(coverage.get(name), f"{label}.{name}")
        for name in count_names
    }
    ratings = _artifact_mapping(
        coverage.get("transformer_ratings_kva"),
        f"{label}.transformer_ratings_kva",
    )
    raw_ratings = _artifact_mapping(
        coverage.get("transformer_raw_ratings_kva"),
        f"{label}.transformer_raw_ratings_kva",
    )
    multiplier = _artifact_number(
        coverage.get("transformer_rating_multiplier"),
        f"{label}.transformer_rating_multiplier",
    )
    expected_basis = (
        "MAKEPOSSEQ_PER_PHASE_KVA_NORMALIZED_TO_SYSTEM_TOTAL"
        if multiplier == 3.0
        else "NATIVE_SYSTEM_TOTAL_KVA"
    )
    if (
        counts["all_bus_count"] <= 0
        or counts["all_bus_count"] != counts["monitored_bus_count"]
        or counts["energized_voltage_node_count"] <= 0
        or counts["energized_voltage_node_count"]
        != counts["monitored_voltage_node_count"]
        or counts["three_phase_bus_count"]
        != counts["monitored_vuf_bus_count"]
        or counts["enabled_transformer_count"]
        != counts["rated_transformer_count"]
        or counts["rated_transformer_count"] != len(ratings)
        or set(map(str.lower, map(str, ratings)))
        != set(map(str.lower, map(str, raw_ratings)))
        or coverage.get("line_thermal_in_scope") is not False
        or _artifact_number(
            coverage.get("transformer_rating_coverage"),
            f"{label}.transformer_rating_coverage",
        )
        != 1.0
        or _artifact_number(
            coverage.get("feeder_rating_multiplier"),
            f"{label}.feeder_rating_multiplier",
        )
        != 1.0
        or multiplier not in {1.0, 3.0}
        or coverage.get("transformer_rating_basis") != expected_basis
        or coverage.get("transformer_power_basis")
        != "SYSTEM_TOTAL_TERMINAL_POWER"
    ):
        _fail(f"{label} is not complete formal coverage")
    for name, rating in ratings.items():
        observed = _artifact_number(rating, f"{label}.rating.{name}")
        raw = _artifact_number(
            raw_ratings.get(name), f"{label}.raw_rating.{name}"
        )
        if observed <= 0.0 or raw <= 0.0 or not math.isclose(
            observed, raw * multiplier, rel_tol=1e-12, abs_tol=1e-12
        ):
            _fail(f"{label} contains inconsistent transformer ratings")


def _validate_lite_constraint_rows(
    selected: Mapping[str, Any], config: Mapping[str, Any]
) -> tuple[set[str], int]:
    if set(selected) != _LITE_SELECTED_KEYS:
        _fail("selected audit evidence has unexpected or missing fields")
    slot = _artifact_int(selected.get("slot"), "selected slot")
    if slot > 95:
        _fail("selected slot must be between zero and 95")
    rows = selected.get("constraint_rows")
    simultaneous = selected.get("simultaneous_violations")
    if not isinstance(rows, list) or not rows or not isinstance(simultaneous, list):
        _fail("selected physical evidence must contain nonempty row lists")
    family_order = list(config["audit"]["family_order"])
    family_index = {family: index for index, family in enumerate(family_order)}
    previous: tuple[int, str, str] | None = None
    seen_objects: set[tuple[str, str]] = set()
    retained: list[dict[str, Any]] = []
    families: set[str] = set()
    limits = {
        "VMIN": _LITE_FORMAL_CONSTRAINTS["vmin_pu"],
        "VMAX": _LITE_FORMAL_CONSTRAINTS["vmax_pu"],
        "VUF": _LITE_FORMAL_CONSTRAINTS["vuf_limit_pct"],
        "TRANSFORMER": _LITE_FORMAL_CONSTRAINTS[
            "transformer_loading_limit_pu"
        ],
        "FEEDER": _LITE_FORMAL_CONSTRAINTS["feeder_loading_limit_pu"],
    }
    for row_index, value in enumerate(rows):
        row = _artifact_mapping(value, f"constraint row {row_index}")
        if set(row) != _LITE_CONSTRAINT_ROW_KEYS or row.get("slot") != slot:
            _fail("constraint row fields or slot are invalid")
        family = row.get("constraint_family")
        metric_id = row.get("metric_id")
        object_id = row.get("object_id")
        direction = row.get("direction")
        if (
            family not in family_index
            or not isinstance(metric_id, str)
            or not metric_id
            or not isinstance(object_id, str)
            or not object_id
            or direction not in {"lo", "hi"}
            or row.get("is_physical_violation") is not True
        ):
            _fail("constraint row identity is invalid")
        object_key = (str(family), object_id)
        if object_key in seen_objects:
            _fail("duplicate constraint object within a family")
        seen_objects.add(object_key)
        expected_direction = "lo" if family == "VMIN" else "hi"
        prefix_valid = bool(
            (family in {"VMIN", "VMAX"} and metric_id == f"V:{object_id}")
            or (family == "VUF" and metric_id == f"U:{object_id}")
            or (
                family == "TRANSFORMER"
                and metric_id == f"S:transformer:{object_id}"
            )
            or (
                family == "FEEDER"
                and metric_id == "S:feeder"
                and object_id == "feeder"
            )
        )
        numeric = {
            name: _artifact_number(row.get(name), f"constraint row {name}")
            for name in ("value", "limit", "signed_headroom", "exceedance")
        }
        expected_headroom = (
            numeric["value"] - numeric["limit"]
            if direction == "lo"
            else numeric["limit"] - numeric["value"]
        )
        if (
            direction != expected_direction
            or not prefix_valid
            or numeric["limit"] != limits[str(family)]
            or not math.isclose(
                numeric["signed_headroom"],
                expected_headroom,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not math.isclose(
                numeric["exceedance"],
                max(0.0, -expected_headroom),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or numeric["exceedance"] <= 0.0
        ):
            _fail("constraint row value, limit, or margin is inconsistent")
        order_key = (family_index[str(family)], metric_id, str(direction))
        if previous is not None and order_key < previous:
            _fail("constraint rows are not in frozen order")
        previous = order_key
        families.add(str(family))
        retained.append(dict(row))
    if [dict(row) for row in simultaneous] != retained:
        _fail("simultaneous violations differ from retained physical rows")
    return families, len(retained)


def _validate_lite_audit(
    audit: Mapping[str, Any],
    *,
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    index: int,
) -> bool:
    if set(audit) != _LITE_AUDIT_KEYS:
        _fail("audit artifact has unexpected or missing fields")
    expected_points = (
        config["audit"]["stage_a_point_order"]
        if case["stage"] == "A"
        else config["audit"]["stage_b_point_order"]
    )
    if index >= len(expected_points):
        _fail("audit artifact exceeds the frozen stage sequence")
    expected_point = expected_points[index]
    expected_alpha = Decimal(str(case["alpha_transfer"]))
    if expected_point == "BOUNDARY_INFEASIBLE":
        expected_alpha += Decimal(str(config["audit"]["delta"]))
    identity_valid = bool(
        audit.get("sequence_index") == index
        and audit.get("audit_point") == expected_point
        and audit.get("source_evaluation_id") == case["evaluation_id"]
        and audit.get("alpha_label") == format(expected_alpha, ".3f")
        and _artifact_number(audit.get("alpha"), "audit alpha")
        == float(expected_alpha)
        and audit.get("formal_constraints") == _LITE_FORMAL_CONSTRAINTS
        and audit.get("line_thermal_in_scope") is False
    )
    if not identity_valid:
        _fail("audit identity, alpha, or formal constraints differ")
    schedule_hash = audit.get("audited_schedule_sha256")
    if not isinstance(schedule_hash, str) or _SHA256_RE.fullmatch(schedule_hash) is None:
        _fail("audited schedule hash must be a lowercase SHA-256")
    flags = (
        audit.get("feasible"),
        audit.get("complete_coverage"),
        audit.get("explicit_physical_witness"),
    )
    if not all(isinstance(value, bool) for value in flags):
        _fail("audit feasibility flags must be boolean")
    checked = _artifact_int(
        audit.get("checked_intervals"), "audit checked intervals", minimum=1
    )
    converged = _artifact_int(audit.get("converged_checks"), "audit convergence")
    nonconverged = _artifact_int(
        audit.get("nonconverged_checks"), "audit nonconvergence"
    )
    numerical = _artifact_int(
        audit.get("numerical_failure_checks"), "audit numerical failures"
    )
    physical = _artifact_int(
        audit.get("physical_violation_checks"), "audit physical failures"
    )
    ratio = _artifact_number(audit.get("coverage_ratio"), "audit coverage ratio")
    complete = bool(audit["complete_coverage"])
    if (
        checked > 96
        or converged != checked
        or nonconverged != 0
        or numerical != 0
        or complete is not (checked == 96)
        or not math.isclose(ratio, checked / 96.0, rel_tol=0.0, abs_tol=1e-15)
    ):
        _fail("audit coverage or convergence counters are inconsistent")
    _validate_lite_coverage(audit.get("coverage_counts"), "audit formal coverage")
    for name in (
        "vmin",
        "vmax",
        "vufmax",
        "transformer_loading_max",
        "feeder_loading_max",
    ):
        _artifact_number(audit.get(name), f"audit {name}")
    feasible = bool(audit["feasible"])
    selected = audit.get("selected_slot")
    if feasible:
        structurally_valid = bool(
            checked == 96
            and physical == 0
            and audit.get("failure_class") == "NONE"
            and audit.get("first_failure_slot") is None
            and audit.get("explicit_physical_witness") is False
            and selected is None
        )
    else:
        first = _artifact_int(
            audit.get("first_failure_slot"), "audit first failure slot"
        )
        selected_mapping = _artifact_mapping(selected, "selected audit evidence")
        _validate_lite_constraint_rows(selected_mapping, config)
        structurally_valid = bool(
            first <= 95
            and checked == first + 1
            and physical == 1
            and audit.get("failure_class") == "PHYSICAL_CONSTRAINT"
            and audit.get("explicit_physical_witness") is True
            and selected_mapping.get("slot") == first
        )
    if not structurally_valid:
        _fail("audit feasibility and physical witness evidence are inconsistent")
    return feasible is (expected_point == "BOUNDARY_FEASIBLE")


def validate_lite_case_artifact(
    artifact: Mapping[str, Any],
    case: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    """Strictly validate one terminal D1-R-Lite case artifact."""

    if not isinstance(artifact, Mapping):
        _fail("case artifact must be a mapping")
    _validate_finite_artifact_tree(artifact, "case artifact")
    if dict(config) != _expected_config():
        _fail("case validation requires the frozen config")
    status = artifact.get("status")
    if status not in {"SUCCESS", "STOP_IMPLEMENTATION", "UNHANDLED_FAILURE"}:
        _fail("case artifact status is not terminal")
    expected_keys = set(_LITE_COMMON_ARTIFACT_KEYS)
    if status != "SUCCESS":
        expected_keys.add("failure")
    if set(artifact) != expected_keys:
        _fail("case artifact has unexpected or missing fields")
    identity = {
        "protocol_version": config["protocol_version"],
        "pair_id": case.get("pair_id"),
        "stage": case.get("stage"),
        "execution_order": case.get("execution_order"),
        "scenario_cluster": case.get("scenario_cluster"),
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "formal_v2_1_run_authorized": False,
        "resource_policy": config["resource_policy"],
        "member": dict(case),
    }
    if any(artifact.get(name) != value for name, value in identity.items()):
        _fail("case identity, provenance, resource policy, or scope differs")
    audits = artifact.get("audits")
    if not isinstance(audits, list) or not all(
        isinstance(audit, Mapping) for audit in audits
    ):
        _fail("case audits must be a mapping list")
    expected_count = 2 if case.get("stage") == "A" else 1
    if status == "SUCCESS" and len(audits) != expected_count:
        label = "two" if expected_count == 2 else "one"
        _fail(f"successful Stage {case.get('stage')} case must contain exactly {label} audits")
    if status != "SUCCESS" and len(audits) > expected_count:
        _fail("failure case exceeds its continuous audit prefix")
    matches = [
        _validate_lite_audit(
            audit,
            case=case,
            config=config,
            index=index,
        )
        for index, audit in enumerate(audits)
    ]
    if status == "SUCCESS":
        if not all(matches):
            _fail("successful case contradicts a frozen boundary rule")
        return
    failure = _artifact_mapping(artifact.get("failure"), "terminal failure")
    if status == "STOP_IMPLEMENTATION":
        if set(failure) != {"kind", "rule_code", "detail", "sequence_index"}:
            _fail("STOP_IMPLEMENTATION failure fields are invalid")
        sequence_index = failure.get("sequence_index")
        rule_code = failure.get("rule_code")
        if (
            failure.get("kind") != "FROZEN_RULE_CONTRADICTION"
            or not isinstance(rule_code, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", rule_code) is None
            or not isinstance(failure.get("detail"), str)
            or not failure.get("detail")
            or (
                sequence_index is not None
                and (
                    isinstance(sequence_index, bool)
                    or not isinstance(sequence_index, int)
                    or sequence_index < 0
                )
            )
        ):
            _fail("STOP_IMPLEMENTATION failure identity is invalid")
        valid_stop = bool(
            (not audits and sequence_index is None)
            or (
                sequence_index == len(audits)
                and all(matches)
                and len(audits) < expected_count
            )
            or (
                audits
                and sequence_index == len(audits) - 1
                and all(matches[:-1])
                and not matches[-1]
            )
        )
        if not valid_stop:
            _fail("STOP_IMPLEMENTATION is not the first failed frozen rule")
    else:
        if set(failure) != {
            "kind",
            "exception_type",
            "message",
            "sequence_index",
        }:
            _fail("UNHANDLED_FAILURE fields are invalid")
        if (
            failure.get("kind") != "UNHANDLED_EXCEPTION"
            or failure.get("sequence_index") != len(audits)
            or not all(matches)
            or not isinstance(failure.get("exception_type"), str)
            or not failure.get("exception_type")
            or not isinstance(failure.get("message"), str)
        ):
            _fail("UNHANDLED_FAILURE is not a valid continuous audit prefix")


def _ordered_cases(
    cases: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        _fail("cases must be a sequence")
    ordered = list(cases)
    pair_ids = [
        case.get("pair_id") if isinstance(case, Mapping) else None
        for case in ordered
    ]
    if pair_ids != config["selection"]["execution_order"]:
        _fail("case order differs from the frozen manifest")
    if len(ordered) != config["expected_counts"]["maximum_cases"]:
        _fail("case count differs from the frozen manifest")
    return ordered


def _family_support(
    artifacts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    minimum_cases: int,
    minimum_clusters: int,
) -> list[dict[str, Any]]:
    family_order = list(config["audit"]["family_order"])
    pair_support = {family: [] for family in family_order}
    cluster_support = {family: [] for family in family_order}
    metric_counts = {family: 0 for family in family_order}
    for artifact in artifacts:
        audit = artifact["audits"][-1]
        selected = _artifact_mapping(
            audit.get("selected_slot"), "selected audit evidence"
        )
        rows = selected["simultaneous_violations"]
        present: set[str] = set()
        for row in rows:
            family = str(row["constraint_family"])
            metric_counts[family] += 1
            present.add(family)
        for family in family_order:
            if family not in present:
                continue
            pair_support[family].append(str(artifact["pair_id"]))
            cluster = str(artifact["scenario_cluster"])
            if cluster not in cluster_support[family]:
                cluster_support[family].append(cluster)
    return [
        {
            "constraint_family": family,
            "case_count": len(pair_support[family]),
            "scenario_cluster_count": len(cluster_support[family]),
            "metric_witness_count": metric_counts[family],
            "pair_ids": pair_support[family],
            "scenario_clusters": cluster_support[family],
            "qualifies": bool(
                len(pair_support[family]) >= minimum_cases
                and len(cluster_support[family]) >= minimum_clusters
            ),
        }
        for family in family_order
    ]


def stage_a_gate(
    artifacts: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the frozen four-representative expansion gate."""

    if dict(config) != _expected_config():
        _fail("Stage A gate requires the frozen config")
    ordered_cases = _ordered_cases(cases, config)
    expected_cases = ordered_cases[: config["expected_counts"]["stage_a_cases"]]
    if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
        _fail("Stage A artifacts must be a sequence")
    retained = list(artifacts)
    if len(retained) != len(expected_cases):
        _fail("Stage A gate requires exactly four case artifacts")
    for artifact, case in zip(retained, expected_cases, strict=True):
        validate_lite_case_artifact(artifact, case, config)
        if artifact.get("status") != "SUCCESS":
            _fail("Stage A gate requires four successful cases")
    support = _family_support(
        retained,
        config,
        minimum_cases=config["gates"]["stage_a_minimum_cases"],
        minimum_clusters=1,
    )
    qualifying = [
        item["constraint_family"] for item in support if item["qualifies"]
    ]
    return {
        "protocol_version": config["protocol_version"],
        "stage": "A",
        "decision": (
            "EXPAND_STAGE_B" if qualifying else "STOP_HETEROGENEOUS_SCREEN"
        ),
        "evaluated_case_count": len(retained),
        "evaluated_target_audit_count": sum(
            len(artifact["audits"]) for artifact in retained
        ),
        "threshold": {
            "minimum_cases": config["gates"]["stage_a_minimum_cases"],
            "total_cases": config["gates"]["stage_a_total_cases"],
        },
        "family_support": support,
        "qualifying_families": qualifying,
        "formal_v2_1_run_authorized": False,
    }


def final_gate(
    artifacts: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the frozen 8/12 and 3/4-cluster common-candidate gate."""

    if dict(config) != _expected_config():
        _fail("final gate requires the frozen config")
    ordered_cases = _ordered_cases(cases, config)
    if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
        _fail("final artifacts must be a sequence")
    retained = list(artifacts)
    if len(retained) != len(ordered_cases):
        _fail("final gate requires exactly twelve case artifacts")
    stage_result = stage_a_gate(retained[:4], ordered_cases, config)
    if stage_result["decision"] != "EXPAND_STAGE_B":
        _fail("Stage B artifacts are forbidden before expansion gate")
    for artifact, case in zip(retained, ordered_cases, strict=True):
        validate_lite_case_artifact(artifact, case, config)
        if artifact.get("status") != "SUCCESS":
            _fail("final gate requires twelve successful cases")
    support = _family_support(
        retained,
        config,
        minimum_cases=config["gates"]["final_minimum_cases"],
        minimum_clusters=config["gates"]["final_minimum_scenario_clusters"],
    )
    qualifying = [
        item["constraint_family"] for item in support if item["qualifies"]
    ]
    return {
        "protocol_version": config["protocol_version"],
        "stage": "FINAL",
        "stage_a_decision": stage_result["decision"],
        "decision": (
            "COMMON_CANDIDATE_CONFOUNDED"
            if qualifying
            else "HETEROGENEOUS_12_CASES"
        ),
        "evaluated_case_count": len(retained),
        "evaluated_target_audit_count": sum(
            len(artifact["audits"]) for artifact in retained
        ),
        "threshold": {
            "minimum_cases": config["gates"]["final_minimum_cases"],
            "total_cases": config["gates"]["final_total_cases"],
            "minimum_scenario_clusters": config["gates"][
                "final_minimum_scenario_clusters"
            ],
            "total_scenario_clusters": config["gates"][
                "final_total_scenario_clusters"
            ],
        },
        "family_support": support,
        "qualifying_families": qualifying,
        "formal_v2_1_run_authorized": False,
    }
