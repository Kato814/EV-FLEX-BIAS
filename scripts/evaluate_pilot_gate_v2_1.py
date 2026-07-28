from __future__ import annotations

import os


_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)
for _variable in _THREAD_VARIABLES:
    os.environ[_variable] = "1"


import argparse
from collections.abc import Callable, Mapping, Sequence
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any


sys.dont_write_bytecode = True


PROTOCOL_VERSION = "EV-FLEX-BIAS-V2.1-PILOT"
DATA_ROLE = "development_pilot"
EXPECTED_WORK_UNITS = 16
EXPECTED_EVALUATIONS = 48
ACCEPTED_WRAPPER_STATUSES = {
    "SUCCESS",
    "SCIENTIFIC_TERMINAL",
}

CONFIG_PATH = Path("config/pilot_gate_v2_1.json")
MANIFEST_PATH = Path("manifests/audit_pilot_work_units_v2_1.csv")
PILOT_MODULE_PATH = Path("src/evflex/pilot.py")
RUNNER_PATH = Path("scripts/run_pilot_gate_v2_1.py")
EVALUATOR_PATH = Path("scripts/evaluate_pilot_gate_v2_1.py")
WORK_UNIT_DIRECTORY = Path("results/pilot_v2_1/work_units")
EVALUATION_CSV_PATH = Path(
    "results/pilot_v2_1/pilot_evaluations_v2_1.csv"
)
RAW_HASH_CSV_PATH = Path("reports/pilot_work_unit_hashes_v2_1.csv")
GATE_JSON_PATH = Path("reports/pilot_gate_v2_1.json")
GATE_MARKDOWN_PATH = Path("reports/pilot_gate_v2_1.md")
OUTPUT_PATHS = (
    EVALUATION_CSV_PATH,
    RAW_HASH_CSV_PATH,
    GATE_JSON_PATH,
    GATE_MARKDOWN_PATH,
)

LOCK_DIRECTORIES = (
    Path("state/runtime/locks/pilot_v2_1"),
    Path("state/runtime/locks/pilot_gate_v2_1"),
)
ATTEMPT_DIRECTORIES = (
    WORK_UNIT_DIRECTORY / ".attempts",
    Path("state/runtime/attempts/pilot_v2_1"),
    Path("state/runtime/attempts/pilot_gate_v2_1"),
)

_SCENARIO_DESIGN = (
    ("ieee13_1900_17", "ieee13", "19:00", 2026071616),
    ("ieee13_0000_09", "ieee13", "00:00", 2026071708),
    ("ieee13_0200_17", "ieee13", "02:00", 2026071816),
    ("ieee13_0600_24", "ieee13", "06:00", 2026071923),
    ("lv906_1900_18", "lv906", "19:00", 2026072017),
    ("lv906_0000_11", "lv906", "00:00", 2026072110),
    ("lv906_0200_03", "lv906", "02:00", 2026072202),
    ("lv906_0600_02", "lv906", "06:00", 2026072301),
)
_DIRECTIONS = ("inc", "dec")
_DURATIONS = (15, 30, 60)
_MANIFEST_COLUMNS = (
    "work_unit_id",
    "protocol_version",
    "scenario_id",
    "feeder",
    "call_time",
    "direction",
    "scenario_seed",
    "data_role",
    "evaluation_ids",
    "holdout_access",
    "status",
)
_EVALUATION_IDENTITY_COLUMNS = (
    "evaluation_id",
    "work_unit_id",
    "protocol_version",
    "scenario_id",
    "scenario_seed",
    "data_role",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "requested_duration_min",
    "source_duration_min",
    "work_unit_status",
    "attempt_count",
    "source_result_file",
)
_RAW_HASH_COLUMNS = (
    "relative_path",
    "filename",
    "bytes",
    "sha256",
    "work_unit_id",
    "expected",
    "expected_work_unit_id",
    "parsed_work_unit_id",
    "parse_status",
    "wrapper_status",
    "attempt_count",
    "evaluation_rows",
    "error",
)
_VALIDITY_STOP_AXIS_STATUS = "NOT_EVALUATED_VALIDITY_STOP"
_SCIENTIFIC_AXIS_FIELDS = (
    "baseline_status",
    "active_offer_status",
    "core_topic_status",
    "scenario_dominance_status",
    "direction_claim_status",
    "duration_claim_status",
    "feeder_replication_status",
    "tie_break_route_status",
    "screening_compute_status",
    "v2_0_reuse_status",
)
_DECISION_FIELDS = (
    "validator_status",
    *_SCIENTIFIC_AXIS_FIELDS,
    "overall_action",
    "decision_class",
)
_DECISION_VOCABULARY = {
    "validator_status": {"VALID", "VALIDITY_STOP"},
    "baseline_status": {
        "PASS_ALL_BASELINES",
        "WARN_REPEAT_BASELINE_COVERAGE",
        "HARD_STOP_BASELINE_COVERAGE",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "active_offer_status": {
        "PASS_ACTIVE_COVERAGE",
        "WARN_REPEAT_ACTIVE_COVERAGE",
        "NO_GO_LOW_ACTIVE_COVERAGE",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "core_topic_status": {
        "GO",
        "REPEAT_PILOT",
        "NO_GO",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "scenario_dominance_status": {
        "DISTRIBUTED",
        "DOMINANCE_REPEAT",
        "NO_GO_SCENARIO_DOMINATED",
        "NOT_APPLICABLE_NO_BAD_ALPHA",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "direction_claim_status": {
        "KEEP_CLAIM",
        "DROP_CLAIM",
        "INDETERMINATE_REPEAT",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "duration_claim_status": {
        "KEEP_CLAIM",
        "DROP_CLAIM",
        "INDETERMINATE_REPEAT",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "feeder_replication_status": {
        "REPLICATED",
        "WEAK_REPLICATION_REPEAT",
        "NO_GO_SINGLE_FEEDER_DOMINATED",
        "NOT_ASSESSABLE_CORE_SIGNAL",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "tie_break_route_status": {
        "PIVOT_TO_PHASE_BALANCED",
        "KEEP_ORIGINAL_ROUTE",
        "INDETERMINATE_REPEAT",
        "NOT_APPLICABLE_NO_BAD_ALPHA",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "screening_compute_status": {
        "DROP_SCREENING",
        "KEEP_SCREENING_MATERIAL",
        "KEEP_SCREENING_DIRECT_AUDIT_OVER_BUDGET",
        "REPEAT_TIMING",
        "INDETERMINATE_TIMING",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "v2_0_reuse_status": {
        "BLOCKED_LABEL_FLIP",
        "BLOCKED_LEGACY_DIAGNOSTIC_FAILURE",
        "DIAGNOSTIC_ONLY_NO_FLIP",
        _VALIDITY_STOP_AXIS_STATUS,
    },
    "overall_action": {
        "STOP_FIX_AND_REPEAT_16_WU_AUDIT",
        "NO_GO_REASSESS_BROAD_TOPIC",
        "PIVOT_TO_PHASE_BALANCED_AND_REPEAT_16_WU_AUDIT",
        "REPEAT_16_WU_PILOT",
        "REPEAT_TIMING_BENCHMARK_ONLY",
        "GO_TO_FORMAL_V2_1_WITH_REPORTED_SCOPE",
    },
    "decision_class": {
        "VALIDITY_STOP",
        "NO_GO",
        "PIVOT",
        "REPEAT_PILOT",
        "GO",
    },
}
_ACTION_CONTRACT = {
    "STOP_FIX_AND_REPEAT_16_WU_AUDIT": ("VALIDITY_STOP", "FULL_16_WU_PILOT"),
    "NO_GO_REASSESS_BROAD_TOPIC": ("NO_GO", "NONE"),
    "PIVOT_TO_PHASE_BALANCED_AND_REPEAT_16_WU_AUDIT": (
        "PIVOT",
        "FULL_16_WU_PILOT",
    ),
    "REPEAT_16_WU_PILOT": ("REPEAT_PILOT", "FULL_16_WU_PILOT"),
    "REPEAT_TIMING_BENCHMARK_ONLY": ("REPEAT_PILOT", "TIMING_ONLY"),
    "GO_TO_FORMAL_V2_1_WITH_REPORTED_SCOPE": ("GO", "NONE"),
}
_SCOPE_ACTIONS = {
    "DROP_DIRECTION_CLAIM",
    "DROP_DURATION_CLAIM",
    "DROP_ONLINE_SCREENING",
    "REPORT_DIRECT_AUDIT_OVER_BUDGET",
    "BLOCK_V2_0_EVIDENCE_REUSE",
    "REPORT_V2_0_REUSE_AS_DIAGNOSTIC_ONLY",
}


class StrictJSONError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(token: str) -> None:
    raise StrictJSONError(f"non-finite JSON number: {token}")


def _validate_finite_tree(value: Any, label: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise StrictJSONError(f"{label}: non-finite JSON number")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _validate_finite_tree(nested, f"{label}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_finite_tree(nested, f"{label}[{index}]")


def strict_json_loads(text: str, *, label: str) -> Any:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, StrictJSONError) as exc:
        raise StrictJSONError(f"{label}: {exc}") from exc
    _validate_finite_tree(value, label)
    return value


def _strict_json_file(repo: Path, relative: Path) -> Any:
    path = repo / relative
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise StrictJSONError(
            f"{relative.as_posix()}: unreadable JSON file ({type(exc).__name__})"
        ) from exc
    return strict_json_loads(text, label=relative.as_posix())


def _canonical_json_bytes(value: Any) -> bytes:
    _validate_finite_tree(value, "output")
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_nested_json(value: Any) -> str:
    _validate_finite_tree(value, "CSV nested value")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(repo: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(
        repo.resolve(strict=False)
    ).as_posix()


def _expected_units() -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for scenario_id, feeder, call_time, scenario_seed in _SCENARIO_DESIGN:
        for direction in _DIRECTIONS:
            work_unit_id = f"v20_work_{scenario_id}__{direction}"
            evaluation_ids = [
                f"v20_core_{scenario_id}__{direction}__{duration}m"
                for duration in _DURATIONS
            ]
            units.append(
                {
                    "work_unit_id": work_unit_id,
                    "protocol_version": PROTOCOL_VERSION,
                    "scenario_id": scenario_id,
                    "feeder": feeder,
                    "call_time": call_time,
                    "direction": direction,
                    "scenario_seed": scenario_seed,
                    "data_role": DATA_ROLE,
                    "evaluation_ids": evaluation_ids,
                    "holdout_access": "prohibited",
                    "status": "PENDING",
                }
            )
    return units


def _expected_evaluation_identity(
    unit: Mapping[str, Any],
    evaluation_id: str,
) -> dict[str, Any]:
    suffix = evaluation_id.rsplit("__", 1)[-1]
    duration = int(suffix[:-1])
    return {
        "evaluation_id": evaluation_id,
        "work_unit_id": unit["work_unit_id"],
        "protocol_version": PROTOCOL_VERSION,
        "scenario_id": unit["scenario_id"],
        "scenario_seed": unit["scenario_seed"],
        "data_role": DATA_ROLE,
        "feeder": unit["feeder"],
        "call_time": unit["call_time"],
        "direction": unit["direction"],
        "duration_min": duration,
        "requested_duration_min": duration,
    }


def _validate_fixed_config(config: Any, errors: list[str]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        errors.append("config: top-level JSON must be an object")
        return {}
    checked = dict(config)
    expected_config_values = {
        "protocol_version": PROTOCOL_VERSION,
        "scenario_ids": [item[0] for item in _SCENARIO_DESIGN],
        "feeders": ["ieee13", "lv906"],
        "call_times": ["19:00", "00:00", "02:00", "06:00"],
        "directions": list(_DIRECTIONS),
        "durations_min": list(_DURATIONS),
        "workers": 1,
        "numeric_threads": 1,
    }
    for key, expected in expected_config_values.items():
        if checked.get(key) != expected:
            errors.append(f"config: {key} differs from the frozen pilot")
    expected_design = {
        scenario_id: {
            "feeder": feeder,
            "call_time": call_time,
            "scenario_seed": seed,
        }
        for scenario_id, feeder, call_time, seed in _SCENARIO_DESIGN
    }
    if checked.get("scenario_design") != expected_design:
        errors.append("config: scenario_design differs from the frozen pilot")
    return checked


def _read_manifest(
    repo: Path,
    expected_units: Sequence[Mapping[str, Any]],
    errors: list[str],
) -> list[dict[str, str]]:
    path = repo / MANIFEST_PATH
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        errors.append(
            f"{MANIFEST_PATH.as_posix()}: unreadable manifest "
            f"({type(exc).__name__})"
        )
        return []
    try:
        with stream:
            reader = csv.DictReader(stream)
            fieldnames = tuple(reader.fieldnames or ())
            if len(fieldnames) != len(set(fieldnames)):
                errors.append("manifest: duplicate CSV column names")
            if fieldnames != _MANIFEST_COLUMNS:
                errors.append("manifest: columns differ from the frozen schema")
            rows = [dict(row) for row in reader]
    except UnicodeError as exc:
        errors.append(
            f"{MANIFEST_PATH.as_posix()}: unreadable manifest "
            f"({type(exc).__name__})"
        )
        return []
    except csv.Error as exc:
        errors.append(f"manifest: malformed CSV ({exc})")
        return []

    by_id: dict[str, dict[str, str]] = {}
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            errors.append(f"manifest row {row_number}: unexpected extra columns")
            continue
        unit_id = str(row.get("work_unit_id", ""))
        if unit_id in by_id:
            errors.append(f"manifest: duplicate work_unit_id {unit_id}")
        else:
            by_id[unit_id] = row

    expected_by_id = {
        str(unit["work_unit_id"]): unit for unit in expected_units
    }
    missing = sorted(set(expected_by_id) - set(by_id))
    unexpected = sorted(set(by_id) - set(expected_by_id))
    for unit_id in missing:
        errors.append(f"manifest: missing work unit {unit_id}")
    for unit_id in unexpected:
        errors.append(f"manifest: unexpected work unit {unit_id}")
    if len(rows) != EXPECTED_WORK_UNITS:
        errors.append(
            f"manifest: expected {EXPECTED_WORK_UNITS} rows, got {len(rows)}"
        )

    for unit_id in sorted(set(expected_by_id) & set(by_id)):
        expected = expected_by_id[unit_id]
        actual = by_id[unit_id]
        scalar_fields = (
            "work_unit_id",
            "protocol_version",
            "scenario_id",
            "feeder",
            "call_time",
            "direction",
            "data_role",
            "holdout_access",
            "status",
        )
        for field in scalar_fields:
            if str(actual.get(field, "")) != str(expected[field]):
                errors.append(
                    f"manifest {unit_id}: {field} differs from frozen identity"
                )
        try:
            seed = int(actual.get("scenario_seed", ""))
        except (TypeError, ValueError):
            seed = None
        if seed != expected["scenario_seed"]:
            errors.append(
                f"manifest {unit_id}: scenario_seed differs from frozen identity"
            )
        try:
            evaluation_ids = strict_json_loads(
                str(actual.get("evaluation_ids", "")),
                label=f"manifest {unit_id} evaluation_ids",
            )
        except StrictJSONError as exc:
            errors.append(str(exc))
        else:
            if evaluation_ids != expected["evaluation_ids"]:
                errors.append(
                    f"manifest {unit_id}: evaluation_ids differ from frozen identity"
                )
    return rows


def _identity_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, int):
        return (
            isinstance(actual, int)
            and not isinstance(actual, bool)
            and actual == expected
        )
    return isinstance(actual, str) and actual == expected


def _validate_wrapper(
    payload: Any,
    expected: Mapping[str, Any],
    *,
    relative_path: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        return rows, [f"{relative_path}: wrapper must be a JSON object"]

    for field in (
        "protocol_version",
        "work_unit_id",
        "scenario_seed",
        "data_role",
    ):
        if not _identity_matches(payload.get(field), expected[field]):
            errors.append(
                f"{relative_path}: wrapper {field} differs from manifest identity"
            )
    status = payload.get("status")
    if status not in ACCEPTED_WRAPPER_STATUSES:
        errors.append(
            f"{relative_path}: wrapper status is not an accepted "
            "scientific terminal"
        )
    attempt_count = payload.get("attempt_count")
    if (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or attempt_count < 1
        or attempt_count > 3
    ):
        errors.append(f"{relative_path}: attempt_count must be an integer in 1..3")

    evaluations = payload.get("evaluations")
    if not isinstance(evaluations, list):
        return rows, errors + [
            f"{relative_path}: evaluations must be a three-row list"
        ]
    if len(evaluations) != 3:
        errors.append(
            f"{relative_path}: expected 3 evaluation rows, got {len(evaluations)}"
        )

    expected_ids = list(expected["evaluation_ids"])
    seen_ids: list[str] = []
    for index, value in enumerate(evaluations):
        if not isinstance(value, Mapping):
            errors.append(
                f"{relative_path}: evaluation row {index} must be an object"
            )
            continue
        row = dict(value)
        evaluation_id = row.get("evaluation_id")
        if isinstance(evaluation_id, str):
            seen_ids.append(evaluation_id)
        else:
            errors.append(
                f"{relative_path}: evaluation row {index} lacks a string ID"
            )
            evaluation_id = ""
        if evaluation_id in expected_ids:
            expected_identity = _expected_evaluation_identity(
                expected, evaluation_id
            )
            for field, identity in expected_identity.items():
                if not _identity_matches(row.get(field), identity):
                    errors.append(
                        f"{relative_path}: evaluation {evaluation_id} "
                        f"{field} differs from manifest identity"
                    )
        else:
            errors.append(
                f"{relative_path}: unexpected evaluation ID {evaluation_id!r}"
            )
        if not isinstance(row.get("status"), str) or not row["status"]:
            errors.append(
                f"{relative_path}: evaluation {evaluation_id!r} "
                "has no terminal status"
            )
        row["work_unit_status"] = status
        row["attempt_count"] = attempt_count
        row["source_result_file"] = Path(relative_path).name
        rows.append(row)

    if len(seen_ids) != len(set(seen_ids)):
        errors.append(f"{relative_path}: duplicate evaluation IDs")
    if set(seen_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(seen_ids))
        unexpected = sorted(set(seen_ids) - set(expected_ids))
        if missing:
            errors.append(
                f"{relative_path}: missing evaluation IDs {missing}"
            )
        if unexpected:
            errors.append(
                f"{relative_path}: unexpected evaluation IDs {unexpected}"
            )
    return rows, errors


def _collect_state_files(repo: Path, directories: Sequence[Path]) -> list[str]:
    found: set[str] = set()
    for relative in directories:
        root = repo / relative
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                found.add(_relative(repo, path))
    return sorted(found, key=str.casefold)


def _is_temporary_file(path: Path) -> bool:
    name = path.name.casefold()
    return (
        name.endswith(".tmp")
        or name.endswith(".partial")
        or name.endswith(".part")
        or ".tmp." in name
    )


def _collect_temporary_files(repo: Path) -> list[str]:
    roots = {
        repo / WORK_UNIT_DIRECTORY,
        repo / EVALUATION_CSV_PATH.parent,
        *(repo / relative for relative in ATTEMPT_DIRECTORIES),
    }
    found: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and _is_temporary_file(path):
                found.add(_relative(repo, path))
    for relative in (
        RAW_HASH_CSV_PATH,
        GATE_JSON_PATH,
        GATE_MARKDOWN_PATH,
    ):
        parent = repo / relative.parent
        if not parent.is_dir():
            continue
        owned_prefix = f".{relative.name}."
        for path in parent.iterdir():
            if (
                path.is_file()
                and path.name.startswith(owned_prefix)
                and _is_temporary_file(path)
            ):
                found.add(_relative(repo, path))
    return sorted(found, key=str.casefold)


def _raw_files(repo: Path) -> list[Path]:
    directory = repo / WORK_UNIT_DIRECTORY
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.rglob("*") if path.is_file()),
        key=lambda path: _relative(repo, path).casefold(),
    )


def _collect_raw_evidence(
    repo: Path,
    expected_units: Sequence[Mapping[str, Any]],
    errors: list[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    expected_by_relative_path = {
        (
            WORK_UNIT_DIRECTORY / f"{unit['work_unit_id']}.json"
        ).as_posix(): unit
        for unit in expected_units
    }
    actual_paths = _raw_files(repo)
    if not (repo / WORK_UNIT_DIRECTORY).is_dir():
        errors.append(
            f"{WORK_UNIT_DIRECTORY.as_posix()}: raw work-unit directory is missing"
        )
    actual_relative_paths = {
        _relative(repo, path) for path in actual_paths
    }
    for relative_path in sorted(
        set(expected_by_relative_path) - actual_relative_paths
    ):
        errors.append(f"raw results: missing expected file {relative_path}")
    if len(actual_paths) != EXPECTED_WORK_UNITS:
        errors.append(
            f"raw results: expected {EXPECTED_WORK_UNITS} files, "
            f"got {len(actual_paths)}"
        )

    wrappers: list[dict[str, Any]] = []
    evaluation_rows: list[dict[str, Any]] = []
    raw_hash_rows: list[dict[str, Any]] = []
    unexpected_files: list[str] = []

    for path in actual_paths:
        relative_path = _relative(repo, path)
        expected = expected_by_relative_path.get(relative_path)
        expected_flag = expected is not None
        row_errors: list[str] = []
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            raw_bytes = None
            row_errors.append(
                f"{relative_path}: raw result is unreadable "
                f"({type(exc).__name__})"
            )
        hash_row: dict[str, Any] = {
            "relative_path": relative_path,
            "filename": path.name,
            "bytes": len(raw_bytes) if raw_bytes is not None else None,
            "sha256": (
                _sha256_bytes(raw_bytes) if raw_bytes is not None else None
            ),
            "work_unit_id": (
                expected["work_unit_id"] if expected is not None else None
            ),
            "expected": expected_flag,
            "expected_work_unit_id": (
                expected["work_unit_id"] if expected is not None else None
            ),
            "parsed_work_unit_id": None,
            "parse_status": "NOT_PARSED",
            "wrapper_status": None,
            "attempt_count": None,
            "evaluation_rows": None,
            "error": None,
        }
        if not expected_flag:
            unexpected_files.append(relative_path)
            row_errors.append(f"{relative_path}: unexpected raw result file")
        if raw_bytes is None:
            hash_row["parse_status"] = "ERROR"
        elif path.suffix.casefold() != ".json":
            hash_row["parse_status"] = "NOT_JSON"
            row_errors.append(f"{relative_path}: raw result is not JSON")
        else:
            try:
                text = raw_bytes.decode("utf-8")
                payload = strict_json_loads(
                    text,
                    label=relative_path,
                )
            except (UnicodeError, StrictJSONError) as exc:
                hash_row["parse_status"] = "ERROR"
                row_errors.append(str(exc))
            else:
                hash_row["parse_status"] = "OK"
                if isinstance(payload, Mapping):
                    hash_row["parsed_work_unit_id"] = payload.get(
                        "work_unit_id"
                    )
                    hash_row["wrapper_status"] = payload.get("status")
                    hash_row["attempt_count"] = payload.get("attempt_count")
                    values = payload.get("evaluations")
                    hash_row["evaluation_rows"] = (
                        len(values) if isinstance(values, list) else None
                    )
                    wrappers.append(dict(payload))
                else:
                    row_errors.append(
                        f"{relative_path}: wrapper must be a JSON object"
                    )
                if expected is not None:
                    rows, wrapper_errors = _validate_wrapper(
                        payload,
                        expected,
                        relative_path=relative_path,
                    )
                    evaluation_rows.extend(rows)
                    row_errors.extend(wrapper_errors)
        if row_errors:
            errors.extend(row_errors)
            hash_row["error"] = " | ".join(row_errors)
        raw_hash_rows.append(hash_row)

    return wrappers, evaluation_rows, raw_hash_rows, unexpected_files


def _sort_evaluations(
    rows: Sequence[Mapping[str, Any]],
    expected_units: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    expected_ids = [
        evaluation_id
        for unit in expected_units
        for evaluation_id in unit["evaluation_ids"]
    ]
    order = {
        evaluation_id: index
        for index, evaluation_id in enumerate(expected_ids)
    }
    normalized = [dict(row) for row in rows]
    normalized.sort(
        key=lambda row: (
            order.get(str(row.get("evaluation_id")), len(order)),
            str(row.get("evaluation_id", "")).casefold(),
            str(row.get("source_result_file", "")).casefold(),
        )
    )
    return normalized


def _csv_scalar(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return _canonical_nested_json(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("CSV contains a non-finite number")
    return value


def _csv_bytes(
    rows: Sequence[Mapping[str, Any]],
    *,
    leading_columns: Sequence[str],
) -> bytes:
    discovered = {
        str(key)
        for row in rows
        for key in row
        if str(key) not in leading_columns
    }
    fields = list(leading_columns) + sorted(discovered, key=str.casefold)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fields,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                field: _csv_scalar(row.get(field))
                for field in fields
            }
        )
    return stream.getvalue().encode("utf-8")


def _source_provenance(
    repo: Path,
    *,
    evaluation_csv: bytes,
    raw_hash_csv: bytes,
) -> dict[str, dict[str, str | None]]:
    sources = (
        ("config", CONFIG_PATH),
        ("manifest", MANIFEST_PATH),
        ("pilot_module", PILOT_MODULE_PATH),
        ("runner", RUNNER_PATH),
        ("evaluator", EVALUATOR_PATH),
    )
    provenance: dict[str, dict[str, str | None]] = {}
    for name, relative in sources:
        path = repo / relative
        provenance[name] = {
            "path": relative.as_posix(),
            "sha256": _sha256_file(path) if path.is_file() else None,
        }
    provenance["evaluation_csv"] = {
        "path": EVALUATION_CSV_PATH.as_posix(),
        "sha256": _sha256_bytes(evaluation_csv),
    }
    provenance["raw_hash_csv"] = {
        "path": RAW_HASH_CSV_PATH.as_posix(),
        "sha256": _sha256_bytes(raw_hash_csv),
    }
    return provenance


def _validity_stop_decision(reason: str) -> dict[str, Any]:
    return {
        "validator_status": "VALIDITY_STOP",
        **{
            field: _VALIDITY_STOP_AXIS_STATUS
            for field in _SCIENTIFIC_AXIS_FIELDS
        },
        "overall_action": "STOP_FIX_AND_REPEAT_16_WU_AUDIT",
        "decision_class": "VALIDITY_STOP",
        "formal_v2_1_run_started": False,
        "metrics": {},
        "reason_codes": [reason],
        "mandatory_scope_actions": [],
        "repeat_scope": "FULL_16_WU_PILOT",
    }


def _validate_decision_contract(decision: Mapping[str, Any]) -> None:
    missing = [
        field
        for field in (
            *_DECISION_FIELDS,
            "formal_v2_1_run_started",
            "metrics",
            "reason_codes",
            "mandatory_scope_actions",
            "repeat_scope",
        )
        if field not in decision
    ]
    if missing:
        raise ValueError(f"decision is missing required fields: {missing}")
    for field, vocabulary in _DECISION_VOCABULARY.items():
        value = decision.get(field)
        if value not in vocabulary:
            raise ValueError(
                f"decision {field} has non-frozen value {value!r}"
            )
    if decision.get("formal_v2_1_run_started") is not False:
        raise ValueError("decision must record that the later run has not started")
    if not isinstance(decision.get("metrics"), Mapping):
        raise ValueError("decision metrics must be a mapping")
    for field in ("reason_codes", "mandatory_scope_actions"):
        values = decision.get(field)
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value for value in values)
            or len(values) != len(set(values))
        ):
            raise ValueError(
                f"decision {field} must be a unique nonempty-string list"
            )
    actions = decision["mandatory_scope_actions"]
    if any(action not in _SCOPE_ACTIONS for action in actions):
        raise ValueError("decision contains a non-frozen mandatory scope action")

    overall = str(decision["overall_action"])
    expected_class, expected_repeat_scope = _ACTION_CONTRACT[overall]
    if decision["decision_class"] != expected_class:
        raise ValueError("decision class is inconsistent with overall action")
    if decision["repeat_scope"] != expected_repeat_scope:
        raise ValueError("decision repeat scope is inconsistent with overall action")

    validator = decision["validator_status"]
    axis_values = [decision[field] for field in _SCIENTIFIC_AXIS_FIELDS]
    if validator == "VALIDITY_STOP":
        if overall != "STOP_FIX_AND_REPEAT_16_WU_AUDIT" or any(
            value != _VALIDITY_STOP_AXIS_STATUS for value in axis_values
        ):
            raise ValueError(
                "validity-stop decision must stop and leave every axis unevaluated"
            )
    elif (
        overall == "STOP_FIX_AND_REPEAT_16_WU_AUDIT"
        or any(value == _VALIDITY_STOP_AXIS_STATUS for value in axis_values)
    ):
        raise ValueError(
            "VALID decision cannot contain validity-stop action or axis status"
        )


def _assess(
    assessor: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    evidence: dict[str, Any],
    config: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    try:
        assessed = assessor(evidence, config)
        if not isinstance(assessed, Mapping):
            raise TypeError("assess_pilot_gate must return a mapping")
        decision = dict(assessed)
        _validate_finite_tree(decision, "assess_pilot_gate output")
        _validate_decision_contract(decision)
    except Exception as exc:
        errors.append(
            "assess_pilot_gate failed: "
            f"{type(exc).__name__}: {exc}"
        )
        evidence["loader_validation"] = {
            "status": "INVALID",
            "errors": sorted(set(errors), key=str.casefold),
        }
        return _validity_stop_decision("ASSESSOR_FAILED")
    if errors:
        decision.update(
            {
                "validator_status": "VALIDITY_STOP",
                **{
                    field: _VALIDITY_STOP_AXIS_STATUS
                    for field in _SCIENTIFIC_AXIS_FIELDS
                },
                "overall_action": "STOP_FIX_AND_REPEAT_16_WU_AUDIT",
                "decision_class": "VALIDITY_STOP",
                "formal_v2_1_run_started": False,
                "mandatory_scope_actions": [],
                "repeat_scope": "FULL_16_WU_PILOT",
            }
        )
        reasons = decision.get("reason_codes")
        reason_codes = (
            [str(value) for value in reasons]
            if isinstance(reasons, list)
            else []
        )
        if "EVALUATOR_STRUCTURAL_INVALID" not in reason_codes:
            reason_codes.append("EVALUATOR_STRUCTURAL_INVALID")
        decision["reason_codes"] = reason_codes
    decision["formal_v2_1_run_started"] = False
    return decision


def _render_markdown(report: Mapping[str, Any]) -> bytes:
    lines = [
        "# EV-FLEX-BIAS V2.1 试运行停止门评估",
        "",
        f"- 验证器状态：`{report.get('validator_status', 'UNKNOWN')}`",
        f"- 总体动作：`{report.get('overall_action', 'UNKNOWN')}`",
        (
            f"- 工作单：{report.get('actual_work_units', 0)} / "
            f"{report.get('expected_work_units', EXPECTED_WORK_UNITS)}"
        ),
        (
            f"- 评估行：{report.get('actual_evaluations', 0)} / "
            f"{report.get('expected_evaluations', EXPECTED_EVALUATIONS)}"
        ),
        "- 正式运行状态：未启动正式 V2.1 重跑",
        "",
        "## 分轴结论",
        "",
        "| 评估轴 | 状态 |",
        "|---|---|",
    ]
    for field in _DECISION_FIELDS:
        lines.append(f"| `{field}` | `{report.get(field, 'MISSING')}` |")

    lines.extend(["", "## 结构有效性", ""])
    loader = report.get("loader_validation", {})
    loader_status = (
        loader.get("status", "UNKNOWN")
        if isinstance(loader, Mapping)
        else "UNKNOWN"
    )
    lines.append(f"- 加载状态：`{loader_status}`")
    loader_errors = (
        loader.get("errors", [])
        if isinstance(loader, Mapping)
        else ["loader_validation 不是对象"]
    )
    if loader_errors:
        for error in loader_errors:
            lines.append(f"- {error}")
    else:
        lines.append("- 未发现结构错误。")

    lines.extend(["", "## 指标与原因", ""])
    lines.append(
        "- 指标：`"
        + _canonical_nested_json(report.get("metrics", {}))
        + "`"
    )
    reasons = report.get("reason_codes", [])
    if isinstance(reasons, list) and reasons:
        for reason in reasons:
            lines.append(f"- 原因代码：`{reason}`")
    else:
        lines.append("- 原因代码：无")

    lines.extend(
        [
            "",
            "## 可追溯哈希",
            "",
            "| 证据 | 路径 | SHA-256 |",
            "|---|---|---|",
        ]
    )
    provenance = report.get("provenance", {})
    if isinstance(provenance, Mapping):
        for name in (
            "config",
            "manifest",
            "pilot_module",
            "runner",
            "evaluator",
            "evaluation_csv",
            "raw_hash_csv",
        ):
            item = provenance.get(name, {})
            if isinstance(item, Mapping):
                lines.append(
                    f"| `{name}` | `{item.get('path', '')}` | "
                    f"`{item.get('sha256') or 'MISSING'}` |"
                )
    lines.extend(
        [
            "",
            "> 本评估器只汇总 16 WU 试运行证据，不会启动任何后续重跑。",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _default_assessor(
    evidence: Mapping[str, Any],
    config: Mapping[str, Any],
) -> Mapping[str, Any]:
    from evflex.pilot import assess_pilot_gate

    return assess_pilot_gate(evidence, config)


def _build_artifacts(
    repo: Path,
    *,
    assessor: Callable[
        [Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
    ],
) -> tuple[dict[Path, bytes], dict[str, Any], bool]:
    root = repo.resolve(strict=False)
    errors: list[str] = []
    try:
        config_value = _strict_json_file(root, CONFIG_PATH)
    except StrictJSONError as exc:
        errors.append(str(exc))
        config: dict[str, Any] = {}
    else:
        config = _validate_fixed_config(config_value, errors)

    expected_units = _expected_units()
    _read_manifest(root, expected_units, errors)
    (
        wrappers,
        evaluation_rows,
        raw_hash_rows,
        unexpected_raw_files,
    ) = _collect_raw_evidence(root, expected_units, errors)

    active_locks = _collect_state_files(root, LOCK_DIRECTORIES)
    attempt_states = _collect_state_files(root, ATTEMPT_DIRECTORIES)
    temporary_files = _collect_temporary_files(root)
    for path in active_locks:
        errors.append(f"active lock evidence: {path}")
    for path in attempt_states:
        errors.append(f"attempt state evidence: {path}")
    for path in temporary_files:
        errors.append(f"temporary artifact evidence: {path}")

    expected_work_unit_ids = [
        str(unit["work_unit_id"]) for unit in expected_units
    ]
    expected_evaluation_ids = [
        str(evaluation_id)
        for unit in expected_units
        for evaluation_id in unit["evaluation_ids"]
    ]
    actual_work_unit_ids = sorted(
        {
            str(wrapper.get("work_unit_id"))
            for wrapper in wrappers
            if isinstance(wrapper.get("work_unit_id"), str)
        }
    )
    actual_evaluation_ids = sorted(
        {
            str(row.get("evaluation_id"))
            for row in evaluation_rows
            if isinstance(row.get("evaluation_id"), str)
        }
    )
    if len(wrappers) != EXPECTED_WORK_UNITS:
        errors.append(
            f"parsed wrappers: expected {EXPECTED_WORK_UNITS}, got {len(wrappers)}"
        )
    if len(evaluation_rows) != EXPECTED_EVALUATIONS:
        errors.append(
            f"evaluation rows: expected {EXPECTED_EVALUATIONS}, "
            f"got {len(evaluation_rows)}"
        )
    if actual_work_unit_ids != sorted(expected_work_unit_ids):
        errors.append("actual work-unit identities differ from the fixed manifest")
    if actual_evaluation_ids != sorted(expected_evaluation_ids):
        errors.append("actual evaluation identities differ from the fixed manifest")

    errors = sorted(set(errors), key=str.casefold)
    loader_validation = {
        "status": "INVALID" if errors else "VALID",
        "errors": errors,
    }
    sorted_evaluations = _sort_evaluations(
        evaluation_rows, expected_units
    )
    raw_hash_rows.sort(
        key=lambda row: str(row["relative_path"]).casefold()
    )
    evaluation_csv = _csv_bytes(
        sorted_evaluations,
        leading_columns=_EVALUATION_IDENTITY_COLUMNS,
    )
    raw_hash_csv = _csv_bytes(
        raw_hash_rows,
        leading_columns=_RAW_HASH_COLUMNS,
    )

    evidence = {
        "work_units": wrappers,
        "evaluations": sorted_evaluations,
        "raw_hash_rows": raw_hash_rows,
        "loader_validation": loader_validation,
        "expected_work_unit_ids": expected_work_unit_ids,
        "actual_work_unit_ids": actual_work_unit_ids,
        "expected_evaluation_ids": expected_evaluation_ids,
        "actual_evaluation_ids": actual_evaluation_ids,
        "active_lock_files": active_locks,
        "attempt_state_files": attempt_states,
        "temporary_files": temporary_files,
        "unexpected_raw_files": unexpected_raw_files,
    }
    decision = _assess(assessor, evidence, config, errors)
    errors = list(evidence["loader_validation"]["errors"])
    provenance = _source_provenance(
        root,
        evaluation_csv=evaluation_csv,
        raw_hash_csv=raw_hash_csv,
    )
    report = {
        **decision,
        "artifact": "EV-FLEX-BIAS-V2.1-PILOT-GATE",
        "protocol_version": PROTOCOL_VERSION,
        "expected_work_units": EXPECTED_WORK_UNITS,
        "actual_work_units": len(wrappers),
        "expected_evaluations": EXPECTED_EVALUATIONS,
        "actual_evaluations": len(sorted_evaluations),
        "unique_work_unit_ids": len(actual_work_unit_ids),
        "unique_evaluation_ids": len(actual_evaluation_ids),
        "loader_validation": evidence["loader_validation"],
        "active_lock_files": active_locks,
        "attempt_state_files": attempt_states,
        "temporary_files": temporary_files,
        "unexpected_raw_files": unexpected_raw_files,
        "raw_result_files": len(raw_hash_rows),
        "numeric_threads": 1,
        "workers": 1,
        "formal_v2_1_run_started": False,
        "provenance": provenance,
    }
    gate_json = _canonical_json_bytes(report)
    markdown = _render_markdown(report)
    artifacts = {
        EVALUATION_CSV_PATH: evaluation_csv,
        RAW_HASH_CSV_PATH: raw_hash_csv,
        GATE_JSON_PATH: gate_json,
        GATE_MARKDOWN_PATH: markdown,
    }
    structurally_valid = bool(
        not errors and report.get("validator_status") == "VALID"
    )
    return artifacts, report, structurally_valid


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_artifacts(
    repo: Path,
    artifacts: Mapping[Path, bytes],
    *,
    structural_valid: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(
        prefix="evflex-pilot-gate-verify-"
    ) as directory:
        temporary_root = Path(directory)
        for relative, expected in artifacts.items():
            rebuilt = temporary_root / relative
            rebuilt.parent.mkdir(parents=True, exist_ok=True)
            rebuilt.write_bytes(expected)
            existing = repo / relative
            if not existing.is_file():
                errors.append(f"{relative.as_posix()}: existing artifact is missing")
                continue
            if existing.read_bytes() != rebuilt.read_bytes():
                errors.append(
                    f"{relative.as_posix()}: byte comparison failed"
                )
    if not structural_valid:
        errors.append(
            "current raw/hash/lock/attempt/tmp evidence is structurally invalid"
        )
    errors = sorted(set(errors), key=str.casefold)
    return {
        "mode": "verify-existing",
        "verified": not errors,
        "errors": errors,
        "exit_code": 0 if not errors else 1,
    }


def evaluate_pilot_gate(
    repo: str | Path,
    *,
    assessor: Callable[
        [Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
    ] | None = None,
    verify_existing: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve(strict=False)
    selected_assessor = assessor or _default_assessor
    artifacts, report, structural_valid = _build_artifacts(
        root,
        assessor=selected_assessor,
    )
    if verify_existing:
        return _verify_artifacts(
            root,
            artifacts,
            structural_valid=structural_valid,
        )
    for relative in OUTPUT_PATHS:
        _atomic_write_bytes(root / relative, artifacts[relative])
    return {
        "mode": "write",
        "gate": report,
        "structural_valid": structural_valid,
        "exit_code": 0 if structural_valid else 1,
        "artifacts": [path.as_posix() for path in OUTPUT_PATHS],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the fixed EV-FLEX-BIAS V2.1 16-WU pilot gate."
    )
    parser.add_argument(
        "--verify-existing",
        action="store_true",
        help="rebuild in a system temporary directory and compare read-only",
    )
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    outcome = evaluate_pilot_gate(
        repo,
        verify_existing=args.verify_existing,
    )
    print(
        json.dumps(
            outcome,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )
    return int(outcome["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
