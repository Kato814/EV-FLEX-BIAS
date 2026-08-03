"""Strict inputs and execution primitives for the bounded D1-R-Lite screen."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Mapping, Sequence


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
