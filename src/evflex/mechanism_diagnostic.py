from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any


_CONFIG_RELATIVE_PATH = "config/mechanism_diagnostic_v2_1.json"
_ARCHIVED_EVALUATIONS_PATH = "results/pilot_v2_1/pilot_evaluations_v2_1.csv"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

_MANIFEST_COLUMNS = (
    "pair_id",
    "scenario_cluster",
    "bad_evaluation_id",
    "bad_work_unit_id",
    "bad_scenario_id",
    "bad_scenario_seed",
    "bad_feeder",
    "bad_call_time",
    "bad_direction",
    "duration_min",
    "bad_alpha_transfer",
    "bad_source_duration_min",
    "bad_schedule_sha256",
    "bad_bus_phase_time_sha256",
    "bad_baseline_schedule_sha256",
    "control_evaluation_id",
    "control_work_unit_id",
    "control_scenario_id",
    "control_scenario_seed",
    "control_feeder",
    "control_call_time",
    "control_direction",
    "control_alpha_transfer",
    "control_source_duration_min",
    "control_schedule_sha256",
    "control_bus_phase_time_sha256",
    "control_baseline_schedule_sha256",
)

_PAIR_IDENTITIES = (
    (
        "01",
        "lv906_1900_18",
        "v20_core_lv906_1900_18__dec__15m",
        "v20_core_ieee13_1900_17__dec__15m",
    ),
    (
        "02",
        "lv906_1900_18",
        "v20_core_lv906_1900_18__dec__30m",
        "v20_core_ieee13_1900_17__dec__30m",
    ),
    (
        "03",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__inc__15m",
        "v20_core_ieee13_0000_09__inc__15m",
    ),
    (
        "04",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__inc__30m",
        "v20_core_ieee13_0000_09__inc__30m",
    ),
    (
        "05",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__dec__15m",
        "v20_core_ieee13_0000_09__dec__15m",
    ),
    (
        "06",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__dec__30m",
        "v20_core_ieee13_0000_09__dec__30m",
    ),
    (
        "07",
        "lv906_0200_03",
        "v20_core_lv906_0200_03__dec__15m",
        "v20_core_ieee13_0200_17__dec__15m",
    ),
    (
        "08",
        "lv906_0200_03",
        "v20_core_lv906_0200_03__dec__30m",
        "v20_core_ieee13_0200_17__dec__30m",
    ),
    (
        "09",
        "lv906_0200_03",
        "v20_core_lv906_0200_03__dec__60m",
        "v20_core_ieee13_0200_17__dec__60m",
    ),
    (
        "10",
        "lv906_0600_02",
        "v20_core_lv906_0600_02__dec__15m",
        "v20_core_ieee13_0600_24__dec__15m",
    ),
    (
        "11",
        "lv906_0600_02",
        "v20_core_lv906_0600_02__dec__30m",
        "v20_core_ieee13_0600_24__dec__30m",
    ),
    (
        "12",
        "lv906_0600_02",
        "v20_core_lv906_0600_02__dec__60m",
        "v20_core_ieee13_0600_24__dec__60m",
    ),
)

_FROZEN_SOURCE_HASHES = (
    (
        "config/pilot_gate_v2_1.json",
        "1ecc530362e5bd51f144c85156e4bae93eb9ec30137238cf7041bf9887cb122b",
    ),
    (
        "manifests/audit_pilot_work_units_v2_1.csv",
        "d7d5d0424935185de2d49bf5b9aa8524ca3abf66cd23e3677b5b70e5e5936615",
    ),
    (
        "manifests/core_work_units_v2_0.csv",
        "856431b21d240010b44f0125de92ab7447bcef924c9d6987cf3caf12c2a6ce69",
    ),
    (
        "reports/pilot_gate_v2_1.json",
        "041b0d3521c3fbb22ee45578936a72c623cb8c7749a0139f6e63238649551751",
    ),
    (
        "reports/pilot_gate_v2_1.md",
        "30f0b639a1a1044ed92bd3ac86af446862d561c4720eda74cad3ac6c7b56e187",
    ),
    (
        "reports/pilot_work_unit_hashes_v2_1.csv",
        "4f801c8a169f1569dee46f3398e505a4556c92096682569095fe1aea33d4131e",
    ),
    (
        _ARCHIVED_EVALUATIONS_PATH,
        "bfb22446390191bcbc39f4de3f9363f211a090e8022f89f91c1ef515a9cf547a",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_ieee13_0000_09__dec.json",
        "3946ac043bfea3091a2e260df29f8d2615519f197512852d9dfbd6e8140a7a98",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_ieee13_0000_09__inc.json",
        "a0613f67395b2c641c12a9018413b5de19a4e01825a3d5f8b9f414a0c3c1a718",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_ieee13_0200_17__dec.json",
        "86f2665a4b7c3a855cf3d63c4d5e65371782264be2afdb232ffc8c3437ff1887",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_ieee13_0600_24__dec.json",
        "c09edf990b50fcb699466f9d6b8d1d1065601969f9d7894a2f552d8288625df4",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_ieee13_1900_17__dec.json",
        "cc482778e32c2f72918ca722ceeb7245d8edcbdc1da7014d36698f7c96ad744c",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_lv906_0000_11__dec.json",
        "1d702bbc729243c8b4ef7ad2c49d275518202841e6320d497e261b178d059f2c",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_lv906_0000_11__inc.json",
        "1e2e852140e3b44a0726323ce2ca0f397897e9dfe4d848b933ef1ffda0cee86c",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_lv906_0200_03__dec.json",
        "c6110985a82d02379c822b84aebf48165fad56f91e9781dab5e338a8a99f1472",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_lv906_0600_02__dec.json",
        "62a2c79561b81ec504558ebd50d4c61c03d432a6f73b4d2b54dc72beac9ac6ca",
    ),
    (
        "results/pilot_v2_1/work_units/v20_work_lv906_1900_18__dec.json",
        "4146541d33ad30924edab28eaaf6546de6e32e2055de3a7b56445194cdaf058a",
    ),
    (
        "scripts/run_pilot_gate_v2_1.py",
        "6489a712bf1a674a7995ad6f240af25647864aa4e1c2ae95db5768770a3212ba",
    ),
    (
        "scripts/evaluate_pilot_gate_v2_1.py",
        "51dea1efb55c093e1fc368102d391c5483afef770ec27b6ad5c81caf747cd491",
    ),
)


def _expected_config() -> dict[str, Any]:
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.1-D1-MECHANISM",
        "source_protocol_version": "EV-FLEX-BIAS-V2.1-PILOT",
        "source_commit": "e1740f912a351b1822b5ee019f9e4f05b6b71c6f",
        "artifact_names": {
            "config": _CONFIG_RELATIVE_PATH,
            "pair_manifest": "manifests/mechanism_diagnostic_pairs_v2_1.csv",
            "result_root": "results/mechanism_diagnostic_v2_1",
            "pair_artifact_pattern": (
                "results/mechanism_diagnostic_v2_1/pairs/pair_{pair_id}.json"
            ),
            "run_lock": "results/mechanism_diagnostic_v2_1/.run.lock",
            "attempt_pattern": (
                "results/mechanism_diagnostic_v2_1/.attempts/pair_{pair_id}.json"
            ),
            "audit_csv": "reports/mechanism_diagnostic_audits_v2_1.csv",
            "report_json": "reports/mechanism_diagnostic_v2_1.json",
            "report_markdown": "reports/mechanism_diagnostic_v2_1.md",
            "hashes_csv": "reports/mechanism_diagnostic_hashes_v2_1.csv",
        },
        "expected_counts": {"pairs": 12, "sources": 24, "audits": 72},
        "frozen_sources": [
            {"path": path, "sha256": sha256}
            for path, sha256 in _FROZEN_SOURCE_HASHES
        ],
        "pilot_py": {
            "path": "src/evflex/pilot.py",
            "sha256": (
                "37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b"
            ),
        },
        "audit": {
            "delta": 0.002,
            "point_order": [
                "BOUNDARY_FEASIBLE",
                "BOUNDARY_INFEASIBLE",
                "FULL_OFFER",
            ],
            "family_order": [
                "VMIN",
                "VMAX",
                "VUF",
                "TRANSFORMER",
                "FEEDER",
            ],
        },
        "candidate_thresholds": {
            "minimum_bad_cases": 8,
            "total_bad_cases": 12,
            "minimum_scenario_clusters": 3,
            "total_scenario_clusters": 4,
        },
        "count_match_thresholds": {
            "high": {"numerator": 4, "denominator": 5},
            "low": {"numerator": 1, "denominator": 5},
            "minimum_eligible_rows": 4,
            "fraction_display_precision": 12,
        },
        "relative_stress": {
            "reason_code": (
                "RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR"
            ),
            "global_ratio": None,
            "phase_ratios": None,
        },
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


def _fail(detail: str) -> None:
    raise ValueError(f"mechanism diagnostic: {detail}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"config has duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json(token: str) -> None:
    _fail(f"config contains non-finite JSON number {token}")


def _validate_finite_tree(value: Any, label: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _fail(f"{label} contains a non-finite number")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _validate_finite_tree(nested, f"{label}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_finite_tree(nested, f"{label}[{index}]")


def _strict_json_file(path: Path, label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except ValueError:
        raise
    except (OSError, UnicodeError) as exc:
        _fail(f"{label} is unreadable ({type(exc).__name__})")
    _validate_finite_tree(value, label)
    return value


def _assert_exact_tree(actual: Any, expected: Any, label: str) -> None:
    if type(actual) is not type(expected):
        _fail(
            f"{label} differs from the frozen contract: expected "
            f"{type(expected).__name__}, got {type(actual).__name__}"
        )
    if isinstance(expected, dict):
        actual_keys = tuple(actual)
        expected_keys = tuple(expected)
        if set(actual_keys) != set(expected_keys):
            missing = sorted(set(expected_keys) - set(actual_keys))
            unexpected = sorted(set(actual_keys) - set(expected_keys))
            _fail(
                f"{label} differs from the frozen contract: "
                f"missing={missing}, unexpected={unexpected}"
            )
        for key, expected_value in expected.items():
            _assert_exact_tree(actual[key], expected_value, f"{label}.{key}")
        return
    if isinstance(expected, list):
        if len(actual) != len(expected):
            _fail(
                f"{label} differs from the frozen contract: expected "
                f"{len(expected)} entries, got {len(actual)}"
            )
        for index, (actual_value, expected_value) in enumerate(
            zip(actual, expected, strict=True)
        ):
            _assert_exact_tree(
                actual_value, expected_value, f"{label}[{index}]"
            )
        return
    if actual != expected:
        _fail(
            f"{label} differs from the frozen contract: "
            f"expected {expected!r}, got {actual!r}"
        )


def _contained_path(root: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        _fail(f"{label} must be a non-empty repository-relative path")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or "\\" in relative
        or ":" in relative
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        _fail(f"{label} is not a contained canonical relative path: {relative!r}")
    repository = root.resolve(strict=False)
    target = (repository / Path(*pure.parts)).resolve(strict=False)
    try:
        target.relative_to(repository)
    except ValueError:
        _fail(f"{label} escapes the repository: {relative!r}")
    return target


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        _fail(f"source hash drift: {path} is unreadable ({type(exc).__name__})")
    return digest.hexdigest()


def load_mechanism_config(repo_root: str | Path) -> dict[str, Any]:
    """Load the D1 protocol only when it matches the frozen contract exactly."""

    root = Path(repo_root)
    path = _contained_path(root, _CONFIG_RELATIVE_PATH, "config path")
    config = _strict_json_file(path, _CONFIG_RELATIVE_PATH)
    if not isinstance(config, dict):
        _fail("config differs from the frozen contract: root must be an object")
    _assert_exact_tree(config, _expected_config(), "config")

    source_paths: set[str] = set()
    for index, source in enumerate(config["frozen_sources"]):
        relative = source["path"]
        if relative in source_paths:
            _fail(f"config differs from the frozen contract: duplicate source {relative}")
        source_paths.add(relative)
        _contained_path(root, relative, f"frozen_sources[{index}].path")
        if not _SHA256_RE.fullmatch(source["sha256"]):
            _fail(
                "config differs from the frozen contract: invalid source SHA-256 "
                f"for {relative}"
            )
    pilot = config["pilot_py"]
    _contained_path(root, pilot["path"], "pilot_py.path")
    if not _SHA256_RE.fullmatch(pilot["sha256"]):
        _fail("config differs from the frozen contract: invalid pilot.py SHA-256")

    for name, relative in config["artifact_names"].items():
        materialized = relative.format(pair_id="01")
        _contained_path(root, materialized, f"artifact_names.{name}")
    return config


def _strict_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"manifest {label} must be a non-empty canonical string")
    return value


def _strict_int(value: Any, label: str) -> int:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"manifest {label} must be a finite lossless integer")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _fail(f"manifest {label} must be a finite lossless integer")
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        _fail(f"manifest {label} must be a finite lossless integer")
    return int(parsed)


def _strict_float(value: Any, label: str) -> float:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"manifest {label} must be a finite float")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _fail(f"manifest {label} must be a finite float")
    if not parsed.is_finite():
        _fail(f"manifest {label} must be a finite float")
    result = float(parsed)
    if not math.isfinite(result):
        _fail(f"manifest {label} must be a finite float")
    return result


def _strict_sha256(value: Any, label: str) -> str:
    text = _strict_text(value, label)
    if not _SHA256_RE.fullmatch(text):
        _fail(f"manifest {label} must be a lowercase SHA-256")
    return text


def _parse_manifest_row(raw: Mapping[str, Any], row_number: int) -> dict[str, Any]:
    prefix = f"row {row_number}"
    parsed = {
        "pair_id": _strict_text(raw["pair_id"], f"{prefix} pair_id"),
        "scenario_cluster": _strict_text(
            raw["scenario_cluster"], f"{prefix} scenario_cluster"
        ),
        "bad_evaluation_id": _strict_text(
            raw["bad_evaluation_id"], f"{prefix} bad_evaluation_id"
        ),
        "bad_work_unit_id": _strict_text(
            raw["bad_work_unit_id"], f"{prefix} bad_work_unit_id"
        ),
        "bad_scenario_id": _strict_text(
            raw["bad_scenario_id"], f"{prefix} bad_scenario_id"
        ),
        "bad_scenario_seed": _strict_int(
            raw["bad_scenario_seed"], f"{prefix} bad_scenario_seed"
        ),
        "bad_feeder": _strict_text(raw["bad_feeder"], f"{prefix} bad_feeder"),
        "bad_call_time": _strict_text(
            raw["bad_call_time"], f"{prefix} bad_call_time"
        ),
        "bad_direction": _strict_text(
            raw["bad_direction"], f"{prefix} bad_direction"
        ),
        "duration_min": _strict_int(raw["duration_min"], f"{prefix} duration_min"),
        "bad_alpha_transfer": _strict_float(
            raw["bad_alpha_transfer"], f"{prefix} bad_alpha_transfer"
        ),
        "bad_source_duration_min": _strict_int(
            raw["bad_source_duration_min"], f"{prefix} bad_source_duration_min"
        ),
        "bad_schedule_sha256": _strict_sha256(
            raw["bad_schedule_sha256"], f"{prefix} bad_schedule_sha256"
        ),
        "bad_bus_phase_time_sha256": _strict_sha256(
            raw["bad_bus_phase_time_sha256"],
            f"{prefix} bad_bus_phase_time_sha256",
        ),
        "bad_baseline_schedule_sha256": _strict_sha256(
            raw["bad_baseline_schedule_sha256"],
            f"{prefix} bad_baseline_schedule_sha256",
        ),
        "control_evaluation_id": _strict_text(
            raw["control_evaluation_id"], f"{prefix} control_evaluation_id"
        ),
        "control_work_unit_id": _strict_text(
            raw["control_work_unit_id"], f"{prefix} control_work_unit_id"
        ),
        "control_scenario_id": _strict_text(
            raw["control_scenario_id"], f"{prefix} control_scenario_id"
        ),
        "control_scenario_seed": _strict_int(
            raw["control_scenario_seed"], f"{prefix} control_scenario_seed"
        ),
        "control_feeder": _strict_text(
            raw["control_feeder"], f"{prefix} control_feeder"
        ),
        "control_call_time": _strict_text(
            raw["control_call_time"], f"{prefix} control_call_time"
        ),
        "control_direction": _strict_text(
            raw["control_direction"], f"{prefix} control_direction"
        ),
        "control_alpha_transfer": _strict_float(
            raw["control_alpha_transfer"], f"{prefix} control_alpha_transfer"
        ),
        "control_source_duration_min": _strict_int(
            raw["control_source_duration_min"],
            f"{prefix} control_source_duration_min",
        ),
        "control_schedule_sha256": _strict_sha256(
            raw["control_schedule_sha256"], f"{prefix} control_schedule_sha256"
        ),
        "control_bus_phase_time_sha256": _strict_sha256(
            raw["control_bus_phase_time_sha256"],
            f"{prefix} control_bus_phase_time_sha256",
        ),
        "control_baseline_schedule_sha256": _strict_sha256(
            raw["control_baseline_schedule_sha256"],
            f"{prefix} control_baseline_schedule_sha256",
        ),
    }
    return parsed


def pair_members(
    pair: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return normalized bad/control source identities from one loaded pair."""

    if set(pair) != set(_MANIFEST_COLUMNS):
        _fail("manifest pair has unexpected or missing keys")

    def member(role: str) -> dict[str, Any]:
        return {
            "pair_id": pair["pair_id"],
            "scenario_cluster": pair["scenario_cluster"],
            "role": role,
            "evaluation_id": pair[f"{role}_evaluation_id"],
            "work_unit_id": pair[f"{role}_work_unit_id"],
            "scenario_id": pair[f"{role}_scenario_id"],
            "scenario_seed": pair[f"{role}_scenario_seed"],
            "feeder": pair[f"{role}_feeder"],
            "call_time": pair[f"{role}_call_time"],
            "direction": pair[f"{role}_direction"],
            "duration_min": pair["duration_min"],
            "requested_duration_min": pair["duration_min"],
            "source_duration_min": pair[f"{role}_source_duration_min"],
            "alpha_transfer": pair[f"{role}_alpha_transfer"],
            "schedule_sha256": pair[f"{role}_schedule_sha256"],
            "bus_phase_time_sha256": pair[f"{role}_bus_phase_time_sha256"],
            "baseline_schedule_sha256": pair[
                f"{role}_baseline_schedule_sha256"
            ],
        }

    return member("bad"), member("control")


def _read_archived_rows(root: Path) -> dict[str, dict[str, str]]:
    path = _contained_path(
        root, _ARCHIVED_EVALUATIONS_PATH, "archived evaluation table"
    )
    required = {
        "evaluation_id",
        "work_unit_id",
        "protocol_version",
        "scenario_id",
        "scenario_seed",
        "feeder",
        "call_time",
        "direction",
        "duration_min",
        "requested_duration_min",
        "source_duration_min",
        "source_result_file",
        "alpha_transfer",
        "schedule_sha256",
        "bus_phase_time_sha256",
        "baseline_schedule_sha256",
    }
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except (OSError, UnicodeError) as exc:
        _fail(
            f"manifest source table is unreadable ({type(exc).__name__})"
        )
    try:
        with stream:
            reader = csv.DictReader(stream)
            fieldnames = tuple(reader.fieldnames or ())
            if len(fieldnames) != len(set(fieldnames)):
                _fail("manifest source table has duplicate CSV headers")
            missing = sorted(required - set(fieldnames))
            if missing:
                _fail(f"manifest source table is missing columns {missing}")
            rows: dict[str, dict[str, str]] = {}
            for row_number, raw in enumerate(reader, start=2):
                if None in raw or any(value is None for value in raw.values()):
                    _fail(
                        f"manifest source table row {row_number} has extra or missing fields"
                    )
                evaluation_id = raw["evaluation_id"]
                if evaluation_id in rows:
                    _fail(
                        "manifest source table duplicates evaluation_id "
                        f"{evaluation_id}"
                    )
                rows[evaluation_id] = dict(raw)
    except csv.Error as exc:
        _fail(f"manifest source table is malformed ({exc})")
    return rows


def _validate_pair_design(
    pairs: list[dict[str, Any]], config: Mapping[str, Any]
) -> None:
    expected_count = config["expected_counts"]["pairs"]
    if len(pairs) != expected_count:
        _fail(f"manifest expected {expected_count} pairs, got {len(pairs)}")

    identities = tuple(
        (
            pair["pair_id"],
            pair["scenario_cluster"],
            pair["bad_evaluation_id"],
            pair["control_evaluation_id"],
        )
        for pair in pairs
    )
    if identities != _PAIR_IDENTITIES:
        _fail("manifest pair identities differ from the frozen D1 design")

    members = [member for pair in pairs for member in pair_members(pair)]
    evaluation_ids = [member["evaluation_id"] for member in members]
    if len(evaluation_ids) != config["expected_counts"]["sources"]:
        _fail("manifest does not contain exactly 24 source members")
    if len(evaluation_ids) != len(set(evaluation_ids)):
        _fail("manifest duplicates a source evaluation identity")
    if len({pair["pair_id"] for pair in pairs}) != len(pairs):
        _fail("manifest duplicates pair_id")
    if {pair["scenario_cluster"] for pair in pairs} != {
        "lv906_1900_18",
        "lv906_0000_11",
        "lv906_0200_03",
        "lv906_0600_02",
    }:
        _fail("manifest scenario clusters differ from the frozen D1 design")

    for pair in pairs:
        bad, control = pair_members(pair)
        if pair["scenario_cluster"] != bad["scenario_id"]:
            _fail(f"manifest pair {pair['pair_id']} has a mutated scenario cluster")
        if bad["feeder"] != "lv906" or control["feeder"] != "ieee13":
            _fail(f"manifest pair {pair['pair_id']} has invalid feeder roles")
        for field in (
            "call_time",
            "direction",
            "duration_min",
            "requested_duration_min",
            "source_duration_min",
        ):
            if bad[field] != control[field]:
                _fail(
                    f"manifest pair {pair['pair_id']} is not matched on {field}"
                )
        if not 0.0 <= bad["alpha_transfer"] < 0.95:
            _fail(f"manifest pair {pair['pair_id']} bad alpha is not frozen-bad")
        if control["alpha_transfer"] != 1.0:
            _fail(f"manifest pair {pair['pair_id']} control alpha is not 1.0")


def _validate_against_archive(
    root: Path,
    pairs: list[dict[str, Any]],
    config: Mapping[str, Any],
) -> None:
    archived = _read_archived_rows(root)
    frozen_paths = {source["path"] for source in config["frozen_sources"]}
    string_fields = (
        "work_unit_id",
        "scenario_id",
        "feeder",
        "call_time",
        "direction",
        "schedule_sha256",
        "bus_phase_time_sha256",
        "baseline_schedule_sha256",
    )
    int_fields = (
        "scenario_seed",
        "duration_min",
        "requested_duration_min",
        "source_duration_min",
    )

    for pair in pairs:
        for member in pair_members(pair):
            evaluation_id = member["evaluation_id"]
            row = archived.get(evaluation_id)
            if row is None:
                _fail(f"manifest source ID is missing from archive: {evaluation_id}")
            if row["protocol_version"] != config["source_protocol_version"]:
                _fail(
                    f"manifest archive protocol mismatch for {evaluation_id}"
                )
            for field in string_fields:
                if row[field] != str(member[field]):
                    _fail(
                        f"manifest {field} mismatch with archive for {evaluation_id}"
                    )
            for field in int_fields:
                archived_value = _strict_int(
                    row[field], f"archive {evaluation_id} {field}"
                )
                if archived_value != member[field]:
                    _fail(
                        f"manifest {field} mismatch with archive for {evaluation_id}"
                    )
            archived_alpha = _strict_float(
                row["alpha_transfer"],
                f"archive {evaluation_id} alpha_transfer",
            )
            if archived_alpha != member["alpha_transfer"]:
                _fail(
                    "manifest alpha_transfer mismatch with archive for "
                    f"{evaluation_id}"
                )
            expected_file = f"{member['work_unit_id']}.json"
            if row["source_result_file"] != expected_file:
                _fail(
                    f"manifest archive source file mismatch for {evaluation_id}"
                )
            relative_file = f"results/pilot_v2_1/work_units/{expected_file}"
            if relative_file not in frozen_paths:
                _fail(
                    f"manifest source work unit is not hash-frozen: {relative_file}"
                )


def load_pair_manifest(repo_root: str | Path) -> list[dict[str, Any]]:
    """Strictly load the immutable ordered 12-pair D1 manifest."""

    root = Path(repo_root)
    config = load_mechanism_config(root)
    relative = config["artifact_names"]["pair_manifest"]
    path = _contained_path(root, relative, "pair manifest")
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except (OSError, UnicodeError) as exc:
        _fail(f"manifest is unreadable ({type(exc).__name__})")
    try:
        with stream:
            reader = csv.DictReader(stream)
            fieldnames = tuple(reader.fieldnames or ())
            if len(fieldnames) != len(set(fieldnames)):
                _fail("manifest has duplicate CSV headers")
            if fieldnames != _MANIFEST_COLUMNS:
                _fail("manifest columns differ from the frozen schema")
            pairs: list[dict[str, Any]] = []
            for row_number, raw in enumerate(reader, start=2):
                if None in raw or any(value is None for value in raw.values()):
                    _fail(
                        f"manifest row {row_number} has unexpected or missing columns"
                    )
                pairs.append(_parse_manifest_row(raw, row_number))
    except csv.Error as exc:
        _fail(f"manifest is malformed ({exc})")

    _validate_pair_design(pairs, config)
    _validate_against_archive(root, pairs, config)
    return pairs


def verify_frozen_sources(
    repo_root: str | Path, config: Mapping[str, Any]
) -> None:
    """Reject any drift in the archived D1 sources or frozen pilot module."""

    if not isinstance(config, Mapping):
        _fail("config differs from the frozen contract: expected a mapping")
    checked = dict(config)
    _assert_exact_tree(checked, _expected_config(), "config")
    root = Path(repo_root)
    sources = [*checked["frozen_sources"], checked["pilot_py"]]
    for index, source in enumerate(sources):
        relative = source["path"]
        expected = source["sha256"]
        if not _SHA256_RE.fullmatch(expected):
            _fail(f"source hash drift: invalid frozen SHA-256 for {relative}")
        path = _contained_path(root, relative, f"source[{index}].path")
        actual = _sha256_file(path)
        if actual != expected:
            _fail(
                f"source hash drift: {relative} expected {expected}, got {actual}"
            )
