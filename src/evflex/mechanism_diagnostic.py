from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path, PurePosixPath
from typing import Any


_CONFIG_RELATIVE_PATH = "config/mechanism_diagnostic_v2_1.json"
_ARCHIVED_EVALUATIONS_PATH = "results/pilot_v2_1/pilot_evaluations_v2_1.csv"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ASCII_INTEGER_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_BAD_ALPHA_RE = re.compile(r"0\.[0-9]{3}\Z")
_ARCHIVED_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]+\Z")
_SCENARIO_SEED_MAX = 2_147_483_647
_DURATION_MIN_MAX = 24 * 60

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


class _StrictDecodeError(ValueError):
    pass


class D1AuditStop(ValueError):
    """Carry a controlled audit-stage stop with its validated prefix."""

    def __init__(
        self,
        rule_code: str,
        detail: str,
        *,
        audits: Sequence[Mapping[str, Any]],
        sequence_index: int,
    ) -> None:
        if (
            not isinstance(rule_code, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", rule_code) is None
        ):
            raise ValueError("D1 audit stop rule code is invalid")
        if not isinstance(detail, str) or not detail:
            raise ValueError("D1 audit stop detail must be nonempty")
        if (
            isinstance(sequence_index, bool)
            or not isinstance(sequence_index, int)
            or not 0 <= sequence_index < 6
        ):
            raise ValueError("D1 audit stop sequence index is invalid")
        if isinstance(audits, (str, bytes)) or not isinstance(audits, Sequence):
            raise ValueError("D1 audit stop audits must be a sequence")
        if not all(isinstance(audit, Mapping) for audit in audits):
            raise ValueError("D1 audit stop audits must contain mappings")
        retained = [deepcopy(dict(audit)) for audit in audits]
        if len(retained) not in {sequence_index, sequence_index + 1}:
            raise ValueError("D1 audit stop prefix length is inconsistent")
        if any(
            audit.get("sequence_index") != index
            for index, audit in enumerate(retained)
        ):
            raise ValueError("D1 audit stop prefix is not continuous")
        super().__init__(detail)
        self.rule_code = rule_code
        self.detail = detail
        self.audits = retained
        self.sequence_index = sequence_index


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictDecodeError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json(token: str) -> None:
    raise _StrictDecodeError(f"non-finite JSON number {token}")


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
    except (OSError, UnicodeError) as exc:
        _fail(f"{label}: unreadable JSON ({type(exc).__name__})")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json,
        )
    except _StrictDecodeError as exc:
        _fail(f"{label}: {exc}")
    except json.JSONDecodeError as exc:
        _fail(
            f"{label}: malformed JSON at line {exc.lineno}, column {exc.colno}"
        )
    _validate_finite_tree(value, label)
    return value


def strict_json_file(path: str | Path) -> dict[str, Any]:
    """Read one finite duplicate-key-free JSON object."""

    target = Path(path)
    value = _strict_json_file(target, str(target))
    if not isinstance(value, dict):
        _fail(f"{target}: JSON root must be an object")
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


def _strict_int(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if not isinstance(value, str) or not _ASCII_INTEGER_RE.fullmatch(value):
        _fail(f"{label} must use canonical ASCII integer syntax")
    if len(value) > len(str(maximum)):
        _fail(f"{label} must be between {minimum} and {maximum}")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        _fail(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _strict_manifest_alpha(value: Any, label: str, *, role: str) -> Decimal:
    if role == "bad":
        if not isinstance(value, str) or not _BAD_ALPHA_RE.fullmatch(value):
            _fail(
                f"manifest {label} must use exactly three decimal places "
                "in 0.ddd form"
            )
    elif role == "control":
        if value != "1.0":
            _fail(f"manifest {label} must be exactly 1.0")
    else:
        raise AssertionError(f"unexpected manifest role {role!r}")
    return Decimal(value)


def _strict_archived_decimal(value: Any, label: str) -> Decimal:
    if (
        not isinstance(value, str)
        or len(value) > 128
        or not _ARCHIVED_DECIMAL_RE.fullmatch(value)
    ):
        _fail(f"{label} must use canonical finite decimal syntax")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        _fail(f"{label} must use canonical finite decimal syntax ({exc})")


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
            raw["bad_scenario_seed"],
            f"manifest {prefix} bad_scenario_seed",
            minimum=0,
            maximum=_SCENARIO_SEED_MAX,
        ),
        "bad_feeder": _strict_text(raw["bad_feeder"], f"{prefix} bad_feeder"),
        "bad_call_time": _strict_text(
            raw["bad_call_time"], f"{prefix} bad_call_time"
        ),
        "bad_direction": _strict_text(
            raw["bad_direction"], f"{prefix} bad_direction"
        ),
        "duration_min": _strict_int(
            raw["duration_min"],
            f"manifest {prefix} duration_min",
            minimum=1,
            maximum=_DURATION_MIN_MAX,
        ),
        "bad_alpha_transfer": _strict_manifest_alpha(
            raw["bad_alpha_transfer"],
            f"{prefix} bad_alpha_transfer",
            role="bad",
        ),
        "bad_source_duration_min": _strict_int(
            raw["bad_source_duration_min"],
            f"manifest {prefix} bad_source_duration_min",
            minimum=1,
            maximum=_DURATION_MIN_MAX,
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
            raw["control_scenario_seed"],
            f"manifest {prefix} control_scenario_seed",
            minimum=0,
            maximum=_SCENARIO_SEED_MAX,
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
        "control_alpha_transfer": _strict_manifest_alpha(
            raw["control_alpha_transfer"],
            f"{prefix} control_alpha_transfer",
            role="control",
        ),
        "control_source_duration_min": _strict_int(
            raw["control_source_duration_min"],
            f"manifest {prefix} control_source_duration_min",
            minimum=1,
            maximum=_DURATION_MIN_MAX,
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
        _fail(f"{_ARCHIVED_EVALUATIONS_PATH}: unreadable CSV ({type(exc).__name__})")
    try:
        with stream:
            reader = csv.DictReader(stream, strict=True)
            fieldnames = tuple(reader.fieldnames or ())
            if len(fieldnames) != len(set(fieldnames)):
                duplicate = next(
                    name for name in fieldnames if fieldnames.count(name) > 1
                )
                _fail(
                    f"{_ARCHIVED_EVALUATIONS_PATH}: duplicate CSV header {duplicate}"
                )
            missing = sorted(required - set(fieldnames))
            if missing:
                _fail(
                    f"{_ARCHIVED_EVALUATIONS_PATH}: missing CSV columns {missing}"
                )
            rows: dict[str, dict[str, str]] = {}
            for row_number, raw in enumerate(reader, start=2):
                if None in raw or any(value is None for value in raw.values()):
                    _fail(
                        f"{_ARCHIVED_EVALUATIONS_PATH}: row {row_number} "
                        "has unexpected or missing columns"
                    )
                evaluation_id = raw["evaluation_id"]
                if evaluation_id in rows:
                    _fail(
                        f"{_ARCHIVED_EVALUATIONS_PATH}: duplicate evaluation_id "
                        f"{evaluation_id}"
                    )
                rows[evaluation_id] = dict(raw)
    except csv.Error as exc:
        _fail(f"{_ARCHIVED_EVALUATIONS_PATH}: malformed CSV ({exc})")
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
        if not Decimal("0.000") <= bad["alpha_transfer"] < Decimal("0.950"):
            _fail(f"manifest pair {pair['pair_id']} bad alpha is not frozen-bad")
        if control["alpha_transfer"] != Decimal("1.0"):
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
                minimum = 0 if field == "scenario_seed" else 1
                maximum = (
                    _SCENARIO_SEED_MAX
                    if field == "scenario_seed"
                    else _DURATION_MIN_MAX
                )
                archived_value = _strict_int(
                    row[field],
                    f"archive {evaluation_id} {field}",
                    minimum=minimum,
                    maximum=maximum,
                )
                if archived_value != member[field]:
                    _fail(
                        f"manifest {field} mismatch with archive for {evaluation_id}"
                    )
            archived_alpha = _strict_archived_decimal(
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
        _fail(f"{relative}: unreadable CSV ({type(exc).__name__})")
    try:
        with stream:
            reader = csv.DictReader(stream, strict=True)
            fieldnames = tuple(reader.fieldnames or ())
            if len(fieldnames) != len(set(fieldnames)):
                duplicate = next(
                    name for name in fieldnames if fieldnames.count(name) > 1
                )
                _fail(f"{relative}: duplicate CSV header {duplicate}")
            if fieldnames != _MANIFEST_COLUMNS:
                _fail(f"{relative}: columns differ from the frozen schema")
            pairs: list[dict[str, Any]] = []
            for row_number, raw in enumerate(reader, start=2):
                if None in raw or any(value is None for value in raw.values()):
                    _fail(
                        f"{relative}: row {row_number} has unexpected or missing columns"
                    )
                pairs.append(_parse_manifest_row(raw, row_number))
    except csv.Error as exc:
        _fail(f"{relative}: malformed CSV ({exc})")

    _validate_pair_design(pairs, config)
    _validate_against_archive(root, pairs, config)
    for pair in pairs:
        pair["bad_alpha_transfer"] = float(pair["bad_alpha_transfer"])
        pair["control_alpha_transfer"] = float(pair["control_alpha_transfer"])
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


_CONSTRAINT_FAMILY_ORDER = (
    "VMIN",
    "VMAX",
    "VUF",
    "TRANSFORMER",
    "FEEDER",
)
_AUDIT_POINTS = (
    "BOUNDARY_FEASIBLE",
    "BOUNDARY_INFEASIBLE",
    "FULL_OFFER",
)


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        _fail(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(f"{label} must be a finite number")
    if not math.isfinite(result):
        _fail(f"{label} must be a finite number")
    return result


def _strict_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{label} must be a nonnegative integer")
    return value


def _slot_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a mapping")
    return value


def _validated_slot_payload(
    slot_result: Mapping[str, Any],
) -> tuple[
    int,
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
    Mapping[str, Any],
]:
    slot = _strict_nonnegative_int(slot_result.get("slot"), "audit slot")
    if slot > 95:
        _fail("audit slot must be between 0 and 95")
    context = _slot_mapping(slot_result.get("audit_context"), "audit context")
    coverage = _slot_mapping(slot_result.get("coverage"), "slot coverage")
    result = _slot_mapping(slot_result.get("result"), "slot result")
    metrics = _slot_mapping(result.get("metrics"), "slot metrics")
    result_coverage = _slot_mapping(result.get("coverage"), "result coverage")
    if context.get("line_thermal_in_scope") is not False:
        _fail("line thermal evidence is outside the D1 scope")
    if coverage.get("line_thermal_in_scope") is not False:
        _fail("line thermal evidence is outside the D1 scope")
    if result_coverage.get("line_thermal_in_scope") is not False:
        _fail("line thermal evidence is outside the D1 scope")
    vmin = _finite_float(context.get("vmin_pu"), "vmin")
    vmax = _finite_float(context.get("vmax_pu"), "vmax")
    vuf_limit = _finite_float(context.get("vuf_limit_pct"), "VUF limit")
    transformer_limit = _finite_float(
        context.get("transformer_loading_limit_pu"), "transformer limit"
    )
    feeder_limit = _finite_float(
        context.get("feeder_loading_limit_pu"), "feeder limit"
    )
    if (
        vmin >= vmax
        or vuf_limit <= 0.0
        or transformer_limit != 1.0
        or feeder_limit != 1.0
    ):
        _fail("formal constraint context is invalid")
    if dict(coverage) != dict(result_coverage):
        _fail("slot and result formal coverage differ")
    record_integrity = _slot_mapping(
        slot_result.get("formal_integrity"), "slot formal integrity"
    )
    result_integrity = _slot_mapping(
        result.get("formal_integrity"), "result formal integrity"
    )
    if dict(record_integrity) != dict(result_integrity):
        _fail("slot and result formal integrity differ")
    required_integrity = {
        "validated",
        "result_schema_valid",
        "metrics_finite",
        "summary_finite",
        "coverage_complete",
        "summary_consistent",
    }
    if set(record_integrity) != required_integrity or not all(
        record_integrity.get(name) is True for name in required_integrity
    ):
        _fail("formal metric coverage integrity is invalid")
    if result.get("numerical_failure") is not False:
        _fail("audit contains a numerical failure")
    if result.get("converged") is not True:
        _fail("audit contains a nonconverged slot")
    if not isinstance(result.get("feasible"), bool):
        _fail("slot feasibility must be boolean")
    if not isinstance(result.get("violations"), list):
        _fail("slot violations must be a list")
    try:
        from evflex import pilot as frozen_pilot

        coverage_valid = frozen_pilot._formal_coverage_is_complete(
            coverage, metrics
        )
        summary_valid = frozen_pilot._formal_summary_matches_metrics(
            result, metrics
        )
    except Exception as exc:
        _fail(
            "formal metric coverage validation failed "
            f"({type(exc).__name__}: {exc})"
        )
    if not coverage_valid or not summary_valid:
        _fail("formal metric coverage is incomplete or inconsistent")
    return slot, context, coverage, result, metrics


def _metric_spec(
    metric_id: str,
    context: Mapping[str, Any],
) -> list[tuple[str, str, float, str]]:
    if metric_id.startswith("V:"):
        object_id = metric_id.removeprefix("V:")
        specs = [
            ("VMIN", "lo", _finite_float(context.get("vmin_pu"), "vmin"), object_id),
            ("VMAX", "hi", _finite_float(context.get("vmax_pu"), "vmax"), object_id),
        ]
    elif metric_id.startswith("U:"):
        object_id = metric_id.removeprefix("U:")
        specs = [
            (
                "VUF",
                "hi",
                _finite_float(context.get("vuf_limit_pct"), "VUF limit"),
                object_id,
            )
        ]
    elif metric_id.startswith("S:transformer:"):
        object_id = metric_id.removeprefix("S:transformer:")
        specs = [
            (
                "TRANSFORMER",
                "hi",
                _finite_float(
                    context.get("transformer_loading_limit_pu"),
                    "transformer limit",
                ),
                object_id,
            )
        ]
    elif metric_id == "S:feeder":
        specs = [
            (
                "FEEDER",
                "hi",
                _finite_float(
                    context.get("feeder_loading_limit_pu"), "feeder limit"
                ),
                "feeder",
            )
        ]
    else:
        _fail(f"unsupported monitored metric {metric_id!r}")
    if any(not object_id for _, _, _, object_id in specs):
        _fail(f"monitored metric has an empty object ID: {metric_id!r}")
    return specs


def constraint_rows_from_slot(
    slot_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Extract ordered signed margins while preserving explicit pilot witnesses."""

    if not isinstance(slot_result, Mapping):
        _fail("slot result must be a mapping")
    slot, context, _coverage, result, metrics = _validated_slot_payload(
        slot_result
    )
    values: dict[str, float] = {}
    specs_by_key: dict[tuple[str, str], tuple[str, str, float, str]] = {}
    object_keys: set[tuple[str, str]] = set()
    for raw_metric_id, raw_value in metrics.items():
        if not isinstance(raw_metric_id, str) or not raw_metric_id:
            _fail("formal metric IDs must be non-empty strings")
        value = _finite_float(raw_value, f"metric {raw_metric_id}")
        values[raw_metric_id] = value
        for family, direction, limit, object_id in _metric_spec(
            raw_metric_id, context
        ):
            object_key = (family, object_id)
            if object_key in object_keys:
                _fail(f"duplicate object ID {object_id!r} in family {family}")
            object_keys.add(object_key)
            specs_by_key[(raw_metric_id, direction)] = (
                family,
                direction,
                limit,
                object_id,
            )

    explicit: set[tuple[str, str]] = set()
    for index, raw_witness in enumerate(result["violations"]):
        witness = _slot_mapping(raw_witness, f"slot violation {index}")
        if witness.get("kind") != "physical_constraint":
            _fail("audit contains a nonphysical violation record")
        metric_id = witness.get("metric")
        direction = witness.get("direction")
        if not isinstance(metric_id, str) or direction not in {"lo", "hi"}:
            _fail("physical witness identity is invalid")
        key = (metric_id, direction)
        spec = specs_by_key.get(key)
        if spec is None:
            _fail("physical witness is absent from the declared formal metrics")
        if key in explicit:
            _fail("duplicate physical witness identity")
        witness_value = _finite_float(
            witness.get("value"), f"physical witness {metric_id} value"
        )
        witness_limit = _finite_float(
            witness.get("limit"), f"physical witness {metric_id} limit"
        )
        if witness_value != values[metric_id] or witness_limit != spec[2]:
            _fail("physical witness value or limit differs from the formal metric")
        explicit.add(key)

    rows: list[dict[str, Any]] = []
    for (metric_id, direction), (family, _, limit, object_id) in specs_by_key.items():
        value = values[metric_id]
        signed_headroom = value - limit if direction == "lo" else limit - value
        rows.append(
            {
                "slot": slot,
                "constraint_family": family,
                "metric_id": metric_id,
                "object_id": object_id,
                "value": value,
                "limit": limit,
                "direction": direction,
                "signed_headroom": signed_headroom,
                "exceedance": max(0.0, -signed_headroom),
                "is_physical_violation": (metric_id, direction) in explicit,
            }
        )
    family_index = {
        family: index for index, family in enumerate(_CONSTRAINT_FAMILY_ORDER)
    }
    rows.sort(
        key=lambda row: (
            family_index[row["constraint_family"]],
            row["metric_id"],
            row["direction"],
        )
    )
    return rows


def compact_targeted_audit(
    raw: Mapping[str, Any],
    *,
    audit_point: str,
    alpha: float,
    capture_slot: int | None = None,
) -> dict[str, Any]:
    """Validate one targeted audit and retain only its diagnostic slot details."""

    if not isinstance(raw, Mapping):
        _fail("targeted audit must be a mapping")
    if audit_point not in _AUDIT_POINTS:
        _fail(f"unknown audit point {audit_point!r}")
    alpha_value = _finite_float(alpha, "audit alpha")
    if not 0.0 <= alpha_value <= 1.0:
        _fail("audit alpha must be between 0 and 1")
    if capture_slot is not None:
        capture_slot = _strict_nonnegative_int(capture_slot, "capture slot")
        if capture_slot > 95:
            _fail("capture slot must be between 0 and 95")

    numerical_checks = _strict_nonnegative_int(
        raw.get("numerical_failure_checks"), "numerical failure count"
    )
    nonconverged_checks = _strict_nonnegative_int(
        raw.get("nonconverged_checks"), "nonconverged count"
    )
    if numerical_checks or nonconverged_checks:
        _fail("targeted audit contains a numerical failure")
    if not isinstance(raw.get("feasible"), bool):
        _fail("targeted audit feasibility must be boolean")
    checked = _strict_nonnegative_int(
        raw.get("checked_intervals"), "checked interval count"
    )
    slot_results = raw.get("slot_results")
    trace = raw.get("slot_audit_trace")
    if not isinstance(slot_results, list) or not isinstance(trace, list):
        _fail("targeted audit must retain slot results and audit trace")
    if checked != len(slot_results) or checked != len(trace):
        _fail("targeted audit checked interval count is inconsistent")
    if checked == 0 or checked > 96:
        _fail("targeted audit checked interval count is invalid")

    rows_by_slot: dict[int, list[dict[str, Any]]] = {}
    result_violations_by_slot: dict[int, list[Any]] = {}
    validated_results: list[Mapping[str, Any]] = []
    physical_slots: list[int] = []
    constraint_signature: tuple[float, ...] | None = None
    for expected_slot, record in enumerate(slot_results):
        if not isinstance(record, Mapping) or record.get("slot") != expected_slot:
            _fail("targeted audit slot sequence is not contiguous from zero")
        rows = constraint_rows_from_slot(record)
        rows_by_slot[expected_slot] = rows
        result = _slot_mapping(record.get("result"), "slot result")
        validated_results.append(result)
        result_violations_by_slot[expected_slot] = deepcopy(result["violations"])
        context = _slot_mapping(record.get("audit_context"), "audit context")
        observed_signature = tuple(
            _finite_float(context.get(name), f"audit context {name}")
            for name in (
                "vmin_pu",
                "vmax_pu",
                "vuf_limit_pct",
                "transformer_loading_limit_pu",
                "feeder_loading_limit_pu",
            )
        )
        if constraint_signature is None:
            constraint_signature = observed_signature
        elif observed_signature != constraint_signature:
            _fail("formal constraint limits differ across retained slots")
        violated = [row for row in rows if row["is_physical_violation"]]
        if bool(violated) == bool(result.get("feasible")):
            _fail("slot feasibility and explicit physical witnesses disagree")
        if violated:
            physical_slots.append(expected_slot)
        trace_record = _slot_mapping(
            trace[expected_slot], f"slot audit trace {expected_slot}"
        )
        expected_failure_class = "PHYSICAL_CONSTRAINT" if violated else "NONE"
        expected_trace = {
            "slot": expected_slot,
            "feasible": bool(result["feasible"]),
            "converged": True,
            "numerical_failure": False,
            "failure_class": expected_failure_class,
            "physical_witness": bool(violated),
        }
        if dict(trace_record) != expected_trace:
            _fail("slot audit trace differs from retained slot evidence")

    feasible = bool(raw["feasible"])
    complete = raw.get("complete_coverage")
    if not isinstance(complete, bool):
        _fail("targeted audit complete_coverage must be boolean")
    if complete is not (checked == 96):
        _fail("targeted audit complete_coverage is inconsistent")
    coverage_ratio = _finite_float(raw.get("coverage_ratio"), "coverage ratio")
    if not math.isclose(
        coverage_ratio, checked / 96.0, rel_tol=0.0, abs_tol=1e-15
    ):
        _fail("targeted audit coverage ratio is inconsistent")
    converged_checks = _strict_nonnegative_int(
        raw.get("converged_checks"), "converged count"
    )
    if converged_checks != checked:
        _fail("targeted audit converged count is inconsistent")
    physical_checks = _strict_nonnegative_int(
        raw.get("physical_violation_checks"), "physical violation count"
    )
    if physical_checks != len(physical_slots):
        _fail("targeted audit physical violation count is inconsistent")
    expected_failure_class = (
        "PHYSICAL_CONSTRAINT" if physical_slots else "NONE"
    )
    if raw.get("failure_class") != expected_failure_class:
        _fail("targeted audit failure class is inconsistent")
    aggregate_violations = raw.get("violations")
    if not isinstance(aggregate_violations, list):
        _fail("aggregate violation evidence must be a list")
    if len(aggregate_violations) != len(physical_slots):
        _fail("aggregate violation evidence differs from retained slots")
    for index, (aggregate, physical_slot) in enumerate(
        zip(aggregate_violations, physical_slots, strict=True)
    ):
        aggregate_record = _slot_mapping(
            aggregate, f"aggregate violation evidence {index}"
        )
        expected_aggregate = {
            "slot": physical_slot,
            "converged": True,
            "numerical_failure": False,
            "failure_class": "PHYSICAL_CONSTRAINT",
            "physical_witness": True,
            "violations": result_violations_by_slot[physical_slot],
        }
        if dict(aggregate_record) != expected_aggregate:
            _fail("aggregate violation evidence differs from retained slots")
    first_failure_slot = min(physical_slots) if physical_slots else None
    if feasible:
        if physical_slots:
            _fail("feasible audit contains an explicit physical witness")
        if checked != 96 or complete is not True:
            _fail("feasible audit requires complete 96-slot coverage")
        selected_index = capture_slot
    else:
        if first_failure_slot is None:
            _fail("infeasible audit lacks an explicit physical witness")
        if checked != first_failure_slot + 1:
            _fail("physical audit early-stop consistency is invalid")
        if slot_results[-1].get("slot") != first_failure_slot:
            _fail("first physical failure must be the final retained slot")
        selected_index = first_failure_slot
        if capture_slot is not None and capture_slot != first_failure_slot:
            _fail("capture slot differs from the first physical failure")

    if selected_index is not None and selected_index >= checked:
        _fail("capture slot was not evaluated")
    selected = None
    if selected_index is not None:
        selected_rows = rows_by_slot[selected_index]
        selected = {
            "slot": selected_index,
            "constraint_rows": deepcopy(selected_rows),
            "simultaneous_violations": [
                deepcopy(row)
                for row in selected_rows
                if row["is_physical_violation"]
            ],
        }

    coverage_counts = _slot_mapping(
        raw.get("coverage_counts"), "aggregate formal coverage"
    )
    if coverage_counts.get("line_thermal_in_scope") is not False:
        _fail("line thermal evidence is outside the D1 scope")
    for index, record in enumerate(slot_results):
        slot_coverage = _slot_mapping(
            record.get("coverage"), f"slot coverage {index}"
        )
        if dict(slot_coverage) != dict(coverage_counts):
            _fail("aggregate formal coverage differs from retained slots")

    power_flow_evaluations = _strict_nonnegative_int(
        raw.get("power_flow_evaluations"), "power-flow evaluation count"
    )
    reused_baseline_intervals = _strict_nonnegative_int(
        raw.get("reused_baseline_intervals"), "reused baseline interval count"
    )
    if (
        power_flow_evaluations + reused_baseline_intervals != checked
        or raw.get("eligible_for_v01_pass") is not feasible
        or raw.get("nonconverged_slots") != []
    ):
        _fail("targeted audit evaluation accounting is inconsistent")

    extrema: dict[str, float] = {}
    for aggregate_name, result_name, reducer in (
        ("vmin", "vmin", min),
        ("vmax", "vmax", max),
        ("vufmax", "vufmax", max),
        ("transformer_loading_max", "transformer_loading_max", max),
        ("feeder_loading_max", "feeder_loading", max),
    ):
        observed = _finite_float(
            raw.get(aggregate_name), f"targeted audit {aggregate_name}"
        )
        expected = reducer(
            _finite_float(result.get(result_name), f"slot {result_name}")
            for result in validated_results
        )
        if observed != expected:
            _fail("targeted audit aggregate extrema are inconsistent")
        extrema[aggregate_name] = observed
    return {
        "audit_point": audit_point,
        "alpha": alpha_value,
        "feasible": feasible,
        "checked_intervals": checked,
        "coverage_ratio": coverage_ratio,
        "complete_coverage": complete,
        "converged_checks": converged_checks,
        "nonconverged_checks": nonconverged_checks,
        "numerical_failure_checks": numerical_checks,
        "physical_violation_checks": physical_checks,
        "failure_class": expected_failure_class,
        "first_failure_slot": first_failure_slot,
        "explicit_physical_witness": first_failure_slot is not None,
        "selected_slot": selected,
        "coverage_counts": deepcopy(dict(coverage_counts)),
        **extrema,
    }


_COUNT_MATCH_FAMILIES = ("VMIN", "VMAX", "VUF")
_RELATIVE_STRESS_REASON = (
    "RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR"
)


def relative_stress_evidence() -> dict[str, Any]:
    """Return the frozen declaration for the unresolved stress confound."""

    return {
        "reason_code": _RELATIVE_STRESS_REASON,
        "global_ratio": None,
        "phase_ratios": None,
    }


def _strict_count(value: Any, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{label} must be an integer")
    minimum = 1 if positive else 0
    if value < minimum:
        qualifier = "positive" if positive else "nonnegative"
        _fail(f"{label} must be {qualifier}")
    return value


def exact_count_match_probability(N: int, K: int, m: int) -> dict[str, Any]:
    """Compute the exact without-replacement probability of detecting a witness."""

    population = _strict_count(N, "N", positive=True)
    violations = _strict_count(K, "K")
    sample = _strict_count(m, "m", positive=True)
    if violations > population:
        _fail("K must not exceed N")
    if sample > population:
        _fail("m must not exceed N")

    denominator = math.comb(population, sample)
    no_witness = (
        math.comb(population - violations, sample)
        if population - violations >= sample
        else 0
    )
    numerator = denominator - no_witness
    divisor = math.gcd(numerator, denominator)
    reduced_numerator = numerator // divisor
    reduced_denominator = denominator // divisor
    precision = max(
        50,
        len(str(reduced_numerator)) + len(str(reduced_denominator)) + 20,
    )
    with localcontext() as context:
        context.prec = precision
        display_decimal = (
            Decimal(reduced_numerator) / Decimal(reduced_denominator)
        ).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)
    return {
        "numerator": reduced_numerator,
        "denominator": reduced_denominator,
        "display": format(display_decimal, ".12f"),
    }


def _pair_audit(
    pair_artifact: Mapping[str, Any],
    *,
    audit_point: str,
    role: str,
) -> Mapping[str, Any]:
    audits = pair_artifact.get("audits")
    if not isinstance(audits, list) or not all(
        isinstance(item, Mapping) for item in audits
    ):
        _fail("pair artifact audits must be a mapping list")
    matches = [
        item
        for item in audits
        if item.get("audit_point") == audit_point and item.get("role") == role
    ]
    if len(matches) != 1:
        _fail(
            f"pair artifact must contain exactly one {audit_point}/{role} audit"
        )
    return matches[0]


def _selected_constraint_rows(
    audit: Mapping[str, Any], label: str
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    selected = _slot_mapping(audit.get("selected_slot"), f"{label} selected slot")
    rows = selected.get("constraint_rows")
    simultaneous = selected.get("simultaneous_violations")
    if not isinstance(rows, list) or not all(
        isinstance(row, Mapping) for row in rows
    ):
        _fail(f"{label} constraint rows must be a mapping list")
    if not isinstance(simultaneous, list) or not all(
        isinstance(row, Mapping) for row in simultaneous
    ):
        _fail(f"{label} simultaneous violations must be a mapping list")
    expected_simultaneous = [
        row for row in rows if row.get("is_physical_violation") is True
    ]
    if [dict(row) for row in simultaneous] != [
        dict(row) for row in expected_simultaneous
    ]:
        _fail(f"{label} simultaneous violations differ from constraint rows")
    return list(rows), list(simultaneous)


def _constraint_object_sets(
    rows: Sequence[Mapping[str, Any]], label: str
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    objects = {family: set() for family in _CONSTRAINT_FAMILY_ORDER}
    physical = {family: set() for family in _CONSTRAINT_FAMILY_ORDER}
    for index, row in enumerate(rows):
        family = row.get("constraint_family")
        object_id = row.get("object_id")
        metric_id = row.get("metric_id")
        marker = row.get("is_physical_violation")
        if family not in objects:
            _fail(f"{label} row {index} has an invalid constraint family")
        if not isinstance(object_id, str) or not object_id:
            _fail(f"{label} row {index} has an invalid object ID")
        if not isinstance(metric_id, str) or not metric_id:
            _fail(f"{label} row {index} has an invalid metric ID")
        if not isinstance(marker, bool):
            _fail(f"{label} row {index} has an invalid physical marker")
        objects[family].add(object_id)
        if marker:
            physical[family].add(object_id)
    if objects["VMIN"] != objects["VMAX"]:
        _fail(f"{label} VMIN and VMAX object sets differ")
    return objects, physical


def _diagnostic_pair_identity(
    pair_artifact: Mapping[str, Any], index: int
) -> tuple[str, str]:
    if pair_artifact.get("status") != "SUCCESS":
        _fail(f"pair artifact {index} is not a successful terminal artifact")
    pair_id = pair_artifact.get("pair_id")
    scenario_cluster = pair_artifact.get("scenario_cluster")
    if not isinstance(pair_id, str) or not pair_id:
        _fail(f"pair artifact {index} has an invalid pair ID")
    if not isinstance(scenario_cluster, str) or not scenario_cluster:
        _fail(f"pair artifact {index} has an invalid scenario cluster")
    if pair_artifact.get("relative_stress") != relative_stress_evidence():
        _fail(f"pair artifact {pair_id} changed the relative-stress boundary")
    return pair_id, scenario_cluster


def build_count_match_rows(
    pair_artifacts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build case-by-family exact count-matching diagnostics."""

    if isinstance(pair_artifacts, (str, bytes)) or not isinstance(
        pair_artifacts, Sequence
    ):
        _fail("pair artifacts must be a sequence")
    output: list[dict[str, Any]] = []
    seen_pair_ids: set[str] = set()
    for index, pair_artifact in enumerate(pair_artifacts):
        if not isinstance(pair_artifact, Mapping):
            _fail(f"pair artifact {index} must be a mapping")
        pair_id, scenario_cluster = _diagnostic_pair_identity(
            pair_artifact, index
        )
        if pair_id in seen_pair_ids:
            _fail(f"duplicate pair artifact ID {pair_id}")
        seen_pair_ids.add(pair_id)
        bad_audit = _pair_audit(
            pair_artifact,
            audit_point="BOUNDARY_INFEASIBLE",
            role="bad",
        )
        control_audit = _pair_audit(
            pair_artifact,
            audit_point="BOUNDARY_INFEASIBLE",
            role="control",
        )
        bad_selected = _slot_mapping(
            bad_audit.get("selected_slot"), "bad boundary selected slot"
        )
        control_selected = _slot_mapping(
            control_audit.get("selected_slot"),
            "control boundary selected slot",
        )
        bad_slot = _strict_nonnegative_int(
            bad_selected.get("slot"), "bad boundary selected slot"
        )
        control_slot = _strict_nonnegative_int(
            control_selected.get("slot"), "control boundary selected slot"
        )
        if bad_slot != control_slot:
            _fail(f"pair {pair_id} count-match slots differ")
        bad_rows, _ = _selected_constraint_rows(
            bad_audit, f"pair {pair_id} bad boundary"
        )
        control_rows, _ = _selected_constraint_rows(
            control_audit, f"pair {pair_id} control boundary"
        )
        bad_objects, bad_physical = _constraint_object_sets(
            bad_rows, f"pair {pair_id} bad boundary"
        )
        control_objects, _ = _constraint_object_sets(
            control_rows, f"pair {pair_id} control boundary"
        )

        for family in _COUNT_MATCH_FAMILIES:
            if not bad_physical[family]:
                continue
            population = len(bad_objects[family])
            violations = len(bad_physical[family])
            sample = len(control_objects[family])
            row: dict[str, Any] = {
                "pair_id": pair_id,
                "scenario_cluster": scenario_cluster,
                "constraint_family": family,
                "N": population,
                "K": violations,
                "m": sample,
            }
            if sample == 0:
                row.update(
                    {
                        "probability_status": "NOT_APPLICABLE",
                        "p_detect": None,
                        "not_applicable_reason": "CONTROL_FAMILY_ABSENT",
                    }
                )
            else:
                row.update(
                    {
                        "probability_status": "ELIGIBLE",
                        "p_detect": exact_count_match_probability(
                            population, violations, sample
                        ),
                        "not_applicable_reason": None,
                    }
                )
            output.append(row)
    return output


def _validated_probability_fraction(
    row: Mapping[str, Any], label: str
) -> tuple[int, int]:
    probability = _slot_mapping(row.get("p_detect"), f"{label} probability")
    numerator = _strict_count(
        probability.get("numerator"), f"{label} probability numerator"
    )
    denominator = _strict_count(
        probability.get("denominator"),
        f"{label} probability denominator",
        positive=True,
    )
    if numerator > denominator:
        _fail(f"{label} probability must lie between zero and one")
    return numerator, denominator


def classify_count_match(
    rows: Sequence[Mapping[str, Any]], family: str
) -> dict[str, Any]:
    """Classify exact count-match detection sensitivity for one family."""

    if family not in _COUNT_MATCH_FAMILIES:
        _fail(f"count matching is not defined for family {family!r}")
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        _fail("count-match rows must be a sequence")
    family_rows: list[Mapping[str, Any]] = []
    seen_pair_ids: set[str] = set()
    eligible: list[tuple[int, int]] = []
    not_applicable = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _fail(f"count-match row {index} must be a mapping")
        if row.get("constraint_family") != family:
            continue
        pair_id = row.get("pair_id")
        if not isinstance(pair_id, str) or not pair_id:
            _fail(f"count-match row {index} has an invalid pair ID")
        if pair_id in seen_pair_ids:
            _fail(f"duplicate count-match row for pair {pair_id} and {family}")
        seen_pair_ids.add(pair_id)
        family_rows.append(row)
        status = row.get("probability_status")
        if status == "ELIGIBLE":
            population = _strict_count(
                row.get("N"), f"count-match row {pair_id} N", positive=True
            )
            violations = _strict_count(
                row.get("K"), f"count-match row {pair_id} K", positive=True
            )
            sample = _strict_count(
                row.get("m"), f"count-match row {pair_id} m", positive=True
            )
            observed = _validated_probability_fraction(
                row, f"count-match row {pair_id}"
            )
            expected = exact_count_match_probability(
                population, violations, sample
            )
            if observed != (
                expected["numerator"],
                expected["denominator"],
            ):
                _fail(
                    f"count-match row {pair_id} probability differs from exact counts"
                )
            if row.get("not_applicable_reason") is not None:
                _fail(f"count-match row {pair_id} has an invalid eligible reason")
            eligible.append(observed)
        elif status == "NOT_APPLICABLE":
            population = _strict_count(
                row.get("N"), f"count-match row {pair_id} N", positive=True
            )
            violations = _strict_count(
                row.get("K"), f"count-match row {pair_id} K", positive=True
            )
            sample = _strict_count(
                row.get("m"), f"count-match row {pair_id} m"
            )
            if (
                violations > population
                or sample != 0
                or row.get("p_detect") is not None
                or row.get("not_applicable_reason")
                != "CONTROL_FAMILY_ABSENT"
            ):
                _fail(f"count-match row {pair_id} has invalid N/A evidence")
            not_applicable += 1
        else:
            _fail(f"count-match row {pair_id} has an invalid probability status")

    n_eligible = len(eligible)
    required = (4 * n_eligible + 4) // 5
    high_count = sum(
        numerator * 5 >= denominator * 4
        for numerator, denominator in eligible
    )
    low_count = sum(
        numerator * 5 <= denominator
        for numerator, denominator in eligible
    )
    if n_eligible < 4:
        classification = "COUNT_MATCH_NOT_APPLICABLE"
    elif high_count >= required:
        classification = "COUNT_MATCH_HIGH_DETECTION"
    elif low_count >= required:
        classification = "COUNT_MATCH_LOW_DETECTION"
    else:
        classification = "COUNT_MATCH_INDETERMINATE"
    return {
        "constraint_family": family,
        "classification": classification,
        "n_rows": len(family_rows),
        "n_eligible": n_eligible,
        "n_not_applicable": not_applicable,
        "required_80pct_count": required,
        "high_detection_count": high_count,
        "low_detection_count": low_count,
    }


def candidate_families(
    pair_artifacts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return every prospectively qualifying common-family candidate."""

    if isinstance(pair_artifacts, (str, bytes)) or not isinstance(
        pair_artifacts, Sequence
    ):
        _fail("pair artifacts must be a sequence")
    if len(pair_artifacts) != 12:
        _fail("candidate classification requires exactly 12 pair artifacts")
    cases = {family: set() for family in _CONSTRAINT_FAMILY_ORDER}
    clusters = {family: set() for family in _CONSTRAINT_FAMILY_ORDER}
    seen_pair_ids: set[str] = set()
    all_clusters: set[str] = set()
    for index, pair_artifact in enumerate(pair_artifacts):
        if not isinstance(pair_artifact, Mapping):
            _fail(f"pair artifact {index} must be a mapping")
        pair_id, scenario_cluster = _diagnostic_pair_identity(
            pair_artifact, index
        )
        if pair_id in seen_pair_ids:
            _fail(f"duplicate pair artifact ID {pair_id}")
        seen_pair_ids.add(pair_id)
        all_clusters.add(scenario_cluster)
        boundary = _pair_audit(
            pair_artifact,
            audit_point="BOUNDARY_INFEASIBLE",
            role="bad",
        )
        _, simultaneous = _selected_constraint_rows(
            boundary, f"pair {pair_id} bad boundary"
        )
        if not simultaneous:
            _fail(f"pair {pair_id} bad boundary lacks a physical witness")
        present: set[str] = set()
        for row in simultaneous:
            family = row.get("constraint_family")
            if family not in cases:
                _fail(f"pair {pair_id} has an invalid candidate family")
            if row.get("is_physical_violation") is not True:
                _fail(f"pair {pair_id} candidate row is not an explicit witness")
            present.add(family)
        for family in present:
            cases[family].add(pair_id)
            clusters[family].add(scenario_cluster)
    if len(all_clusters) != 4:
        _fail("candidate classification requires exactly four scenario clusters")

    output = []
    for family in _CONSTRAINT_FAMILY_ORDER:
        case_count = len(cases[family])
        cluster_count = len(clusters[family])
        if case_count >= 8 and cluster_count >= 3:
            output.append(
                {
                    "constraint_family": family,
                    "bad_case_count": case_count,
                    "total_bad_cases": 12,
                    "scenario_cluster_count": cluster_count,
                    "total_scenario_clusters": 4,
                }
            )
    return output


_D1_MEMBER_KEYS = {
    "pair_id",
    "scenario_cluster",
    "role",
    "evaluation_id",
    "work_unit_id",
    "scenario_id",
    "scenario_seed",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "requested_duration_min",
    "source_duration_min",
    "alpha_transfer",
    "schedule_sha256",
    "bus_phase_time_sha256",
    "baseline_schedule_sha256",
}
_D1_AUDIT_SEQUENCE = (
    ("BOUNDARY_FEASIBLE", "bad"),
    ("BOUNDARY_FEASIBLE", "control"),
    ("BOUNDARY_INFEASIBLE", "bad"),
    ("BOUNDARY_INFEASIBLE", "control"),
    ("FULL_OFFER", "bad"),
    ("FULL_OFFER", "control"),
)
_FORMAL_CONSTRAINT_FIELDS = (
    "vmin_pu",
    "vmax_pu",
    "vuf_limit_pct",
    "transformer_loading_limit_pu",
    "feeder_loading_limit_pu",
)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize finite JSON with the frozen canonical D1 encoding."""

    _validate_finite_tree(value, "canonical JSON")
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        _fail(f"canonical JSON serialization failed ({type(exc).__name__}: {exc})")
    return text.encode("utf-8")


def _validated_member(member: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(member, Mapping) or set(member) != _D1_MEMBER_KEYS:
        _fail("source member has unexpected or missing keys")
    normalized = dict(member)
    role = normalized.get("role")
    if role not in {"bad", "control"}:
        _fail("source member role must be bad or control")
    for name in (
        "pair_id",
        "scenario_cluster",
        "evaluation_id",
        "work_unit_id",
        "scenario_id",
        "feeder",
        "call_time",
        "direction",
    ):
        value = normalized.get(name)
        if not isinstance(value, str) or not value:
            _fail(f"source member {name} must be a nonempty string")
    if normalized["direction"] not in {"inc", "dec"}:
        _fail("source member direction must be inc or dec")
    for name in (
        "scenario_seed",
        "duration_min",
        "requested_duration_min",
        "source_duration_min",
    ):
        value = normalized.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            _fail(f"source member {name} must be a nonnegative integer")
    if (
        normalized["duration_min"] <= 0
        or normalized["requested_duration_min"] != normalized["duration_min"]
        or normalized["source_duration_min"] != normalized["duration_min"]
    ):
        _fail("source duration differs from the frozen requested duration")
    alpha = _finite_float(normalized.get("alpha_transfer"), "source alpha")
    if not 0.0 <= alpha <= 1.0:
        _fail("source alpha must be between zero and one")
    normalized["alpha_transfer"] = alpha
    for name in (
        "schedule_sha256",
        "bus_phase_time_sha256",
        "baseline_schedule_sha256",
    ):
        value = normalized.get(name)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            _fail(f"source member {name} must be a lowercase SHA-256")
    return normalized


def reconstruct_case(
    repo_root: str | Path,
    member: Mapping[str, Any],
    *,
    pilot_config: Mapping[str, Any] | None = None,
    runtime_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct and hash-check one archived fixed balanced schedule."""

    import numpy as np
    from evflex import pilot

    root = Path(repo_root).resolve(strict=True)
    source = _validated_member(member)
    loaded_pilot_config = (
        pilot.load_pilot_config(root)
        if pilot_config is None
        else pilot_config
    )
    if not isinstance(loaded_pilot_config, Mapping):
        _fail("pilot config must be a mapping")
    factory = runtime_factory or pilot._create_real_pilot_runtime
    if not callable(factory):
        _fail("runtime factory must be callable")
    work_unit = {
        "work_unit_id": source["work_unit_id"],
        "scenario_id": source["scenario_id"],
        "scenario_seed": source["scenario_seed"],
        "feeder": source["feeder"],
        "call_time": source["call_time"],
        "direction": source["direction"],
    }
    runtime = factory(root, work_unit, loaded_pilot_config)
    for name in (
        "generate_balanced_raw",
        "create_corrected_truth_cache",
        "audit_corrected",
    ):
        if not callable(getattr(runtime, name, None)):
            _fail(f"pilot runtime lacks callable {name}")
    fleet = getattr(runtime, "fleet", None)
    if not isinstance(fleet, Sequence) or isinstance(fleet, (str, bytes)) or not fleet:
        _fail("pilot runtime fleet must be a nonempty sequence")
    baseline = np.asarray(getattr(runtime, "baseline", None), dtype=float)
    if baseline.shape != (len(fleet), 96) or not np.isfinite(baseline).all():
        _fail("pilot runtime baseline must be a finite fleet-by-96 matrix")
    load_scales = np.asarray(
        getattr(runtime, "load_scales", None), dtype=float
    )
    if load_scales.shape != (96,) or not np.isfinite(load_scales).all():
        _fail("pilot runtime load scales must be 96 finite values")

    raw = runtime.generate_balanced_raw(
        source["source_duration_min"], "balanced"
    )
    normalized = pilot._normalize_raw_balanced_result(
        raw,
        source["source_duration_min"],
        fleet,
        baseline,
        direction=source["direction"],
    )
    if (
        normalized.get("success") is not True
        or normalized.get("physical_feasible") is not True
        or normalized.get("duration_min") != source["source_duration_min"]
    ):
        _fail("frozen balanced source schedule is not physically valid")
    schedule = np.asarray(normalized.get("schedule"), dtype=float)
    if schedule.shape != baseline.shape or not np.isfinite(schedule).all():
        _fail("reconstructed source schedule is not finite fleet-by-96")
    schedule_hash = pilot.canonical_schedule_sha256(fleet, schedule)
    if schedule_hash != source["schedule_sha256"]:
        _fail("reconstructed schedule hash differs from the archive")
    bus_phase_hash = pilot._canonical_bus_phase_time_sha256(fleet, schedule)
    if bus_phase_hash != source["bus_phase_time_sha256"]:
        _fail("reconstructed bus-phase-time hash differs from the archive")
    baseline_hash = pilot.canonical_schedule_sha256(fleet, baseline)
    if baseline_hash != source["baseline_schedule_sha256"]:
        _fail("reconstructed baseline schedule hash differs from the archive")
    return {
        "member": deepcopy(source),
        "runtime": runtime,
        "fleet": list(fleet),
        "baseline": baseline.copy(),
        "schedule": schedule.copy(),
        "load_scales": load_scales.copy(),
        "source_duration_min": source["source_duration_min"],
        "flex_kw": _finite_float(normalized.get("flex_kw"), "source flex"),
        "schedule_sha256": schedule_hash,
        "bus_phase_time_sha256": bus_phase_hash,
        "baseline_schedule_sha256": baseline_hash,
    }


def _load_scales_sha256(load_scales: Any) -> str:
    import numpy as np

    values = np.asarray(load_scales, dtype=np.float64)
    if values.shape != (96,) or not np.isfinite(values).all():
        _fail("load scales must contain exactly 96 finite values")
    normalized = np.ascontiguousarray(values, dtype="<f8")
    return hashlib.sha256(
        b"evflex.d1.load-scales.v1\0" + normalized.tobytes(order="C")
    ).hexdigest()


def _validate_raw_formal_constraints(
    raw: Mapping[str, Any],
    formal_constraints: Mapping[str, Any],
    *,
    member: Mapping[str, Any],
    load_scales: Any,
) -> None:
    import numpy as np

    if not isinstance(raw, Mapping):
        _fail("raw targeted audit must be a mapping")
    if not isinstance(formal_constraints, Mapping):
        _fail("formal constraints must be a mapping")
    expected = {
        name: _finite_float(
            formal_constraints.get(name), f"formal constraint {name}"
        )
        for name in _FORMAL_CONSTRAINT_FIELDS
    }
    if formal_constraints.get("line_thermal_in_scope") is not False:
        _fail("line thermal evidence is outside the D1 scope")
    records = raw.get("slot_results")
    if not isinstance(records, list) or not records:
        _fail("raw targeted audit lacks retained slot results")
    expected_scales = np.asarray(load_scales, dtype=float)
    if expected_scales.shape != (96,) or not np.isfinite(expected_scales).all():
        _fail("raw audit load-scale identity is invalid")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            _fail(f"raw targeted audit slot {index} must be a mapping")
        if (
            record.get("slot") != index
            or record.get("verified") is not True
            or record.get("feeder") != member.get("feeder")
            or record.get("model") != "3ph"
            or record.get("source") not in {"power_flow", "baseline_reuse"}
        ):
            _fail("raw audit source identity differs from the reconstructed case")
        context = _slot_mapping(
            record.get("audit_context"), f"raw audit slot {index} context"
        )
        observed = {
            name: _finite_float(
                context.get(name), f"raw audit slot {index} {name}"
            )
            for name in _FORMAL_CONSTRAINT_FIELDS
        }
        if observed != expected or context.get("line_thermal_in_scope") is not False:
            _fail("raw audit formal constraints differ from the frozen pilot config")
        expected_scale = float(expected_scales[index])
        record_scale = _finite_float(
            record.get("load_scale"), f"raw audit slot {index} load scale"
        )
        context_scale = _finite_float(
            context.get("load_scale"),
            f"raw audit slot {index} context load scale",
        )
        if (
            record_scale != expected_scale
            or context_scale != expected_scale
            or context.get("adapter_schema")
            != "EV-FLEX-BIAS-PILOT-NETWORK-AUDIT"
            or context.get("adapter_version") != "1.0"
            or context.get("feeder") != member.get("feeder")
            or context.get("model") != "3ph"
        ):
            _fail("raw audit load-scale identity differs from the reconstructed case")


def _prepare_runtime_audit_state(
    reconstructed: Mapping[str, Any],
    formal_constraints: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = reconstructed["runtime"]
    cache = runtime.create_corrected_truth_cache()
    raw = runtime.audit_corrected(
        reconstructed["baseline"],
        cache,
        baseline_slot_results=None,
        stop_on_violation=False,
        retain_slot_results=True,
    )
    _validate_raw_formal_constraints(
        raw,
        formal_constraints,
        member=reconstructed["member"],
        load_scales=reconstructed["load_scales"],
    )
    compact = compact_targeted_audit(
        raw,
        audit_point="BOUNDARY_FEASIBLE",
        alpha=0.0,
    )
    if compact["feasible"] is not True or compact["complete_coverage"] is not True:
        _fail("source baseline audit is not feasible with complete coverage")
    baseline_slots = raw.get("slot_results")
    if not isinstance(baseline_slots, list) or len(baseline_slots) != 96:
        _fail("source baseline audit did not retain exactly 96 slots")
    return {
        "runtime": runtime,
        "cache": cache,
        "baseline_slots": baseline_slots,
    }


def _audit_alpha_points(
    bad_alpha: float, delta: float
) -> dict[str, tuple[float, str]]:
    try:
        base = Decimal(str(bad_alpha))
        increment = Decimal(str(delta))
    except InvalidOperation as exc:
        _fail(f"audit alpha cannot be represented exactly ({exc})")
    if not Decimal("0") <= base < Decimal("0.950"):
        _fail("bad source alpha is outside the frozen bad range")
    if increment != Decimal("0.002"):
        _fail("D1 audit delta must remain exactly 0.002")
    points = {
        "BOUNDARY_FEASIBLE": base,
        "BOUNDARY_INFEASIBLE": min(base + increment, Decimal("1.000")),
        "FULL_OFFER": Decimal("1.000"),
    }
    return {
        name: (float(value), format(value, ".3f"))
        for name, value in points.items()
    }


def _prune_selected_evidence(
    compact: Mapping[str, Any], *, role: str, audit_point: str
) -> dict[str, Any]:
    output = deepcopy(dict(compact))
    selected = output.get("selected_slot")
    if selected is None:
        return output
    if not isinstance(selected, Mapping):
        _fail("selected audit evidence must be a mapping")
    rows = selected.get("constraint_rows")
    if not isinstance(rows, list):
        _fail("selected audit constraint rows must be a list")
    if audit_point == "BOUNDARY_INFEASIBLE":
        retained = [
            row
            for row in rows
            if row.get("constraint_family") in _COUNT_MATCH_FAMILIES
            or row.get("is_physical_violation") is True
        ]
    elif role == "bad" and audit_point == "FULL_OFFER":
        retained = [
            row for row in rows if row.get("is_physical_violation") is True
        ]
    else:
        retained = []
    selected["constraint_rows"] = retained
    selected["simultaneous_violations"] = [
        deepcopy(row)
        for row in retained
        if row.get("is_physical_violation") is True
    ]
    return output


def _audit_input_sha256(
    *,
    protocol_version: str,
    pair_id: str,
    role: str,
    source_evaluation_id: str,
    audit_point: str,
    alpha_label: str,
    baseline_schedule_sha256: str,
    source_schedule_sha256: str,
    audited_schedule_sha256: str,
    load_scales_sha256: str,
    formal_constraints: Mapping[str, Any],
) -> str:
    payload = {
        "protocol_version": protocol_version,
        "pair_id": pair_id,
        "role": role,
        "source_evaluation_id": source_evaluation_id,
        "audit_point": audit_point,
        "alpha": alpha_label,
        "baseline_schedule_sha256": baseline_schedule_sha256,
        "source_schedule_sha256": source_schedule_sha256,
        "audited_schedule_sha256": audited_schedule_sha256,
        "load_scales_sha256": load_scales_sha256,
        "formal_constraints": deepcopy(dict(formal_constraints)),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def execute_pair(
    repo_root: str | Path,
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    runtime_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute the fixed six-audit D1 protocol for one frozen pair."""

    import numpy as np
    from evflex import pilot

    if not isinstance(config, Mapping):
        _fail("mechanism config must be a mapping")
    _assert_exact_tree(dict(config), _expected_config(), "mechanism config")
    root = Path(repo_root).resolve(strict=True)
    bad_member, control_member = pair_members(pair)
    bad_member = _validated_member(bad_member)
    control_member = _validated_member(control_member)
    if (
        bad_member["pair_id"] != control_member["pair_id"]
        or bad_member["scenario_cluster"] != control_member["scenario_cluster"]
    ):
        _fail("pair members disagree on pair identity")
    pilot_config = pilot.load_pilot_config(root)
    formal_constraints = _slot_mapping(
        pilot_config.get("formal_constraints"), "pilot formal constraints"
    )
    bad = reconstruct_case(
        root,
        bad_member,
        pilot_config=pilot_config,
        runtime_factory=runtime_factory,
    )
    control = reconstruct_case(
        root,
        control_member,
        pilot_config=pilot_config,
        runtime_factory=runtime_factory,
    )
    reconstructed = {"bad": bad, "control": control}
    states = {
        role: _prepare_runtime_audit_state(case, formal_constraints)
        for role, case in reconstructed.items()
    }
    alpha_points = _audit_alpha_points(
        bad_member["alpha_transfer"], config["audit"]["delta"]
    )
    load_scale_hashes = {
        role: _load_scales_sha256(case["load_scales"])
        for role, case in reconstructed.items()
    }
    audits: list[dict[str, Any]] = []
    bad_failure_slot: int | None = None
    for sequence_index, (audit_point, role) in enumerate(_D1_AUDIT_SEQUENCE):
        try:
            case = reconstructed[role]
            member = case["member"]
            alpha, alpha_label = alpha_points[audit_point]
            audited_schedule = case["baseline"] + alpha * (
                case["schedule"] - case["baseline"]
            )
            if not np.isfinite(audited_schedule).all():
                _fail("audited fixed schedule contains a non-finite value")
            stop_on_violation = bool(
                role == "bad" and audit_point != "BOUNDARY_FEASIBLE"
            )
            raw = states[role]["runtime"].audit_corrected(
                audited_schedule,
                states[role]["cache"],
                baseline_slot_results=states[role]["baseline_slots"],
                stop_on_violation=stop_on_violation,
                retain_slot_results=True,
            )
            _validate_raw_formal_constraints(
                raw,
                formal_constraints,
                member=case["member"],
                load_scales=case["load_scales"],
            )
            capture_slot = (
                bad_failure_slot
                if role == "control" and audit_point == "BOUNDARY_INFEASIBLE"
                else None
            )
            compact = compact_targeted_audit(
                raw,
                audit_point=audit_point,
                alpha=alpha,
                capture_slot=capture_slot,
            )
        except D1AuditStop:
            raise
        except ValueError as exc:
            raise D1AuditStop(
                "AUDIT_EVIDENCE_INVALID",
                str(exc),
                audits=audits,
                sequence_index=sequence_index,
            ) from exc
        should_be_feasible = bool(
            role == "control" or audit_point == "BOUNDARY_FEASIBLE"
        )
        if should_be_feasible:
            matches_frozen_rule = compact["feasible"] is True
            contradiction_detail = f"{audit_point}/{role} must remain feasible"
        else:
            matches_frozen_rule = bool(
                compact["feasible"] is False
                and compact["explicit_physical_witness"] is True
                and compact["failure_class"] == "PHYSICAL_CONSTRAINT"
            )
            contradiction_detail = (
                f"{audit_point}/{role} must be physically infeasible "
                "with an explicit physical witness"
            )
        if (
            matches_frozen_rule
            and role == "bad"
            and audit_point == "BOUNDARY_INFEASIBLE"
        ):
            bad_failure_slot = compact["first_failure_slot"]
            if not isinstance(bad_failure_slot, int):
                raise D1AuditStop(
                    "AUDIT_EVIDENCE_INVALID",
                    "bad boundary audit lacks an explicit first failure slot",
                    audits=audits,
                    sequence_index=sequence_index,
                )

        try:
            compact = _prune_selected_evidence(
                compact, role=role, audit_point=audit_point
            )
            audited_hash = pilot.canonical_schedule_sha256(
                case["fleet"], audited_schedule
            )
            audit_input_hash = _audit_input_sha256(
                protocol_version=config["protocol_version"],
                pair_id=member["pair_id"],
                role=role,
                source_evaluation_id=member["evaluation_id"],
                audit_point=audit_point,
                alpha_label=alpha_label,
                baseline_schedule_sha256=case["baseline_schedule_sha256"],
                source_schedule_sha256=case["schedule_sha256"],
                audited_schedule_sha256=audited_hash,
                load_scales_sha256=load_scale_hashes[role],
                formal_constraints=formal_constraints,
            )
            audit_record = {
                "sequence_index": sequence_index,
                "pair_id": member["pair_id"],
                "scenario_cluster": member["scenario_cluster"],
                "role": role,
                "source_evaluation_id": member["evaluation_id"],
                "source_work_unit_id": member["work_unit_id"],
                "scenario_id": member["scenario_id"],
                "scenario_seed": member["scenario_seed"],
                "feeder": member["feeder"],
                "call_time": member["call_time"],
                "direction": member["direction"],
                "duration_min": member["duration_min"],
                "source_duration_min": member["source_duration_min"],
                "alpha_label": alpha_label,
                "baseline_schedule_sha256": case[
                    "baseline_schedule_sha256"
                ],
                "source_schedule_sha256": case["schedule_sha256"],
                "bus_phase_time_sha256": case["bus_phase_time_sha256"],
                "audited_schedule_sha256": audited_hash,
                "load_scales_sha256": load_scale_hashes[role],
                "audit_input_sha256": audit_input_hash,
                "formal_constraints": deepcopy(dict(formal_constraints)),
                "line_thermal_in_scope": False,
                **compact,
            }
        except D1AuditStop:
            raise
        except ValueError as exc:
            raise D1AuditStop(
                "AUDIT_EVIDENCE_INVALID",
                str(exc),
                audits=audits,
                sequence_index=sequence_index,
            ) from exc
        audits.append(audit_record)
        if not matches_frozen_rule:
            raise D1AuditStop(
                _STOP_RULE_BY_SEQUENCE[sequence_index],
                contradiction_detail,
                audits=audits,
                sequence_index=sequence_index,
            )
    if bad_failure_slot is None:
        _fail("D1 pair completed without a bad boundary failure slot")
    return {
        "protocol_version": config["protocol_version"],
        "status": "SUCCESS",
        "pair_id": bad_member["pair_id"],
        "scenario_cluster": bad_member["scenario_cluster"],
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "relative_stress": relative_stress_evidence(),
        "members": {
            "bad": deepcopy(bad_member),
            "control": deepcopy(control_member),
        },
        "audits": audits,
    }


_FROZEN_FORMAL_CONSTRAINTS = {
    "vmin_pu": 0.95,
    "vmax_pu": 1.06,
    "vuf_limit_pct": 2.0,
    "transformer_loading_limit_pu": 1.0,
    "feeder_loading_limit_pu": 1.0,
    "line_thermal_in_scope": False,
}
_PAIR_COMMON_KEYS = {
    "protocol_version",
    "status",
    "pair_id",
    "scenario_cluster",
    "source_commit",
    "line_thermal_in_scope",
    "resource_policy",
    "relative_stress",
    "members",
    "audits",
}
_AUDIT_ARTIFACT_KEYS = {
    "sequence_index",
    "pair_id",
    "scenario_cluster",
    "role",
    "source_evaluation_id",
    "source_work_unit_id",
    "scenario_id",
    "scenario_seed",
    "feeder",
    "call_time",
    "direction",
    "duration_min",
    "source_duration_min",
    "alpha_label",
    "baseline_schedule_sha256",
    "source_schedule_sha256",
    "bus_phase_time_sha256",
    "audited_schedule_sha256",
    "load_scales_sha256",
    "audit_input_sha256",
    "formal_constraints",
    "line_thermal_in_scope",
    "audit_point",
    "alpha",
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
_CONSTRAINT_ROW_KEYS = {
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
_COVERAGE_KEYS = {
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
_STOP_RULE_BY_SEQUENCE = {
    0: "BAD_BOUNDARY_FEASIBLE_REQUIRED",
    1: "CONTROL_FEASIBLE_REQUIRED",
    2: "BAD_BOUNDARY_INFEASIBLE_REQUIRED",
    3: "CONTROL_FEASIBLE_REQUIRED",
    4: "BAD_FULL_OFFER_INFEASIBLE_REQUIRED",
    5: "CONTROL_FEASIBLE_REQUIRED",
}


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


def _validate_coverage_artifact(value: Any, label: str) -> None:
    coverage = _slot_mapping(value, label)
    if set(coverage) != _COVERAGE_KEYS:
        _fail(f"{label} has unexpected or missing fields")
    counts = {
        name: _artifact_int(coverage.get(name), f"{label}.{name}")
        for name in (
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
    }
    ratings = _slot_mapping(
        coverage.get("transformer_ratings_kva"),
        f"{label}.transformer_ratings_kva",
    )
    raw_ratings = _slot_mapping(
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


def _validate_constraint_rows_artifact(
    selected: Mapping[str, Any],
    *,
    audit_index: int,
) -> None:
    slot = _artifact_int(selected.get("slot"), "selected slot")
    if slot > 95:
        _fail("selected slot must be between zero and 95")
    rows = selected.get("constraint_rows")
    simultaneous = selected.get("simultaneous_violations")
    if not isinstance(rows, list) or not isinstance(simultaneous, list):
        _fail("selected evidence rows must be lists")
    family_index = {
        family: index for index, family in enumerate(_CONSTRAINT_FAMILY_ORDER)
    }
    previous: tuple[int, str, str] | None = None
    seen_objects: set[tuple[str, str]] = set()
    physical_rows: list[dict[str, Any]] = []
    voltage_objects = {"VMIN": set(), "VMAX": set()}
    for row_index, raw_row in enumerate(rows):
        row = _slot_mapping(raw_row, f"constraint row {row_index}")
        if set(row) != _CONSTRAINT_ROW_KEYS:
            _fail("constraint row has unexpected or missing fields")
        if row.get("slot") != slot:
            _fail("constraint row slot differs from selected slot")
        family = row.get("constraint_family")
        metric_id = row.get("metric_id")
        object_id = row.get("object_id")
        direction = row.get("direction")
        marker = row.get("is_physical_violation")
        if (
            family not in family_index
            or not isinstance(metric_id, str)
            or not metric_id
            or not isinstance(object_id, str)
            or not object_id
            or direction not in {"lo", "hi"}
            or not isinstance(marker, bool)
        ):
            _fail("constraint row identity is invalid")
        object_key = (family, object_id)
        if object_key in seen_objects:
            _fail("duplicate constraint object within a family")
        seen_objects.add(object_key)
        expected_direction = "lo" if family == "VMIN" else "hi"
        expected_limit = {
            "VMIN": _FROZEN_FORMAL_CONSTRAINTS["vmin_pu"],
            "VMAX": _FROZEN_FORMAL_CONSTRAINTS["vmax_pu"],
            "VUF": _FROZEN_FORMAL_CONSTRAINTS["vuf_limit_pct"],
            "TRANSFORMER": _FROZEN_FORMAL_CONSTRAINTS[
                "transformer_loading_limit_pu"
            ],
            "FEEDER": _FROZEN_FORMAL_CONSTRAINTS[
                "feeder_loading_limit_pu"
            ],
        }[family]
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
        value = _artifact_number(row.get("value"), "constraint value")
        limit = _artifact_number(row.get("limit"), "constraint limit")
        headroom = _artifact_number(
            row.get("signed_headroom"), "constraint signed headroom"
        )
        exceedance = _artifact_number(
            row.get("exceedance"), "constraint exceedance"
        )
        expected_headroom = (
            value - limit if direction == "lo" else limit - value
        )
        if (
            direction != expected_direction
            or not prefix_valid
            or limit != expected_limit
            or not math.isclose(
                headroom, expected_headroom, rel_tol=0.0, abs_tol=1e-12
            )
            or not math.isclose(
                exceedance,
                max(0.0, -headroom),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            _fail("constraint row value, limit, or margin is inconsistent")
        order_key = (family_index[family], metric_id, direction)
        if previous is not None and order_key < previous:
            _fail("constraint rows are not in frozen order")
        previous = order_key
        if family in voltage_objects:
            voltage_objects[family].add(object_id)
        if marker:
            physical_rows.append(dict(row))
        if audit_index in {2, 3} and family not in _COUNT_MATCH_FAMILIES and not marker:
            _fail("boundary evidence retains an out-of-scope nonphysical row")
        if audit_index == 4 and not marker:
            _fail("full-offer evidence retains a nonphysical row")
    if audit_index in {2, 3} and (
        not rows or voltage_objects["VMIN"] != voltage_objects["VMAX"]
    ):
        _fail("boundary count-match voltage rows are incomplete")
    if [dict(row) for row in simultaneous] != physical_rows:
        _fail("simultaneous violations differ from explicit constraint rows")


def _validate_audit_artifact(
    audit: Mapping[str, Any],
    *,
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
    index: int,
) -> bool:
    if set(audit) != _AUDIT_ARTIFACT_KEYS:
        _fail("audit artifact has unexpected or missing fields")
    point, role = _D1_AUDIT_SEQUENCE[index]
    members = pair_members(pair)
    member = members[0] if role == "bad" else members[1]
    identity_pairs = {
        "sequence_index": index,
        "pair_id": pair["pair_id"],
        "scenario_cluster": pair["scenario_cluster"],
        "role": role,
        "source_evaluation_id": member["evaluation_id"],
        "source_work_unit_id": member["work_unit_id"],
        "scenario_id": member["scenario_id"],
        "scenario_seed": member["scenario_seed"],
        "feeder": member["feeder"],
        "call_time": member["call_time"],
        "direction": member["direction"],
        "duration_min": member["duration_min"],
        "source_duration_min": member["source_duration_min"],
        "baseline_schedule_sha256": member["baseline_schedule_sha256"],
        "source_schedule_sha256": member["schedule_sha256"],
        "bus_phase_time_sha256": member["bus_phase_time_sha256"],
        "audit_point": point,
    }
    if any(audit.get(name) != value for name, value in identity_pairs.items()):
        _fail("audit identity or order differs from the frozen pair")
    alpha, alpha_label = _audit_alpha_points(
        float(pair["bad_alpha_transfer"]), float(config["audit"]["delta"])
    )[point]
    if (
        audit.get("alpha_label") != alpha_label
        or _artifact_number(audit.get("alpha"), "audit alpha") != alpha
        or audit.get("formal_constraints") != _FROZEN_FORMAL_CONSTRAINTS
        or audit.get("line_thermal_in_scope") is not False
    ):
        _fail("audit alpha or formal constraints differ from the frozen protocol")
    for name in (
        "audited_schedule_sha256",
        "load_scales_sha256",
        "audit_input_sha256",
    ):
        value = audit.get(name)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            _fail(f"audit {name} must be a lowercase SHA-256")
    expected_input_hash = _audit_input_sha256(
        protocol_version=str(config["protocol_version"]),
        pair_id=str(pair["pair_id"]),
        role=role,
        source_evaluation_id=str(member["evaluation_id"]),
        audit_point=point,
        alpha_label=alpha_label,
        baseline_schedule_sha256=str(member["baseline_schedule_sha256"]),
        source_schedule_sha256=str(member["schedule_sha256"]),
        audited_schedule_sha256=str(audit["audited_schedule_sha256"]),
        load_scales_sha256=str(audit["load_scales_sha256"]),
        formal_constraints=_FROZEN_FORMAL_CONSTRAINTS,
    )
    if audit.get("audit_input_sha256") != expected_input_hash:
        _fail("audit input hash differs from the retained identity")

    feasible = audit.get("feasible")
    complete = audit.get("complete_coverage")
    explicit = audit.get("explicit_physical_witness")
    if not all(isinstance(value, bool) for value in (feasible, complete, explicit)):
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
    if (
        checked > 96
        or converged != checked
        or nonconverged != 0
        or numerical != 0
        or complete is not (checked == 96)
        or not math.isclose(ratio, checked / 96.0, rel_tol=0.0, abs_tol=1e-15)
    ):
        _fail("audit coverage or convergence counters are inconsistent")
    selected = audit.get("selected_slot")
    if selected is not None:
        selected = _slot_mapping(selected, "selected audit evidence")
        if set(selected) != {
            "slot",
            "constraint_rows",
            "simultaneous_violations",
        }:
            _fail("selected audit evidence has unexpected fields")
        _validate_constraint_rows_artifact(selected, audit_index=index)
    _validate_coverage_artifact(
        audit.get("coverage_counts"), "audit formal coverage"
    )
    for name in (
        "vmin",
        "vmax",
        "vufmax",
        "transformer_loading_max",
        "feeder_loading_max",
    ):
        _artifact_number(audit.get(name), f"audit {name}")

    if feasible:
        structurally_valid = bool(
            checked == 96
            and complete is True
            and physical == 0
            and audit.get("failure_class") == "NONE"
            and audit.get("first_failure_slot") is None
            and explicit is False
        )
    else:
        first_failure = _artifact_int(
            audit.get("first_failure_slot"), "audit first failure slot"
        )
        structurally_valid = bool(
            checked == first_failure + 1
            and complete is False
            and physical == 1
            and audit.get("failure_class") == "PHYSICAL_CONSTRAINT"
            and explicit is True
            and isinstance(selected, Mapping)
            and selected.get("slot") == first_failure
            and bool(selected.get("simultaneous_violations"))
        )
    if not structurally_valid:
        _fail("audit feasibility and physical witness evidence are inconsistent")
    if index == 2:
        if not feasible and not isinstance(selected, Mapping):
            _fail("bad boundary audit lacks selected count-match evidence")
    elif index == 3:
        if not isinstance(selected, Mapping):
            _fail("control boundary audit lacks selected count-match evidence")
    elif selected is not None and not (index == 4 and not feasible):
        _fail("audit retains detailed slot evidence outside the frozen scope")
    expected_feasible = not (
        role == "bad" and point in {"BOUNDARY_INFEASIBLE", "FULL_OFFER"}
    )
    return feasible is expected_feasible


def validate_pair_artifact(
    artifact: Mapping[str, Any],
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    """Strictly validate one immutable D1 terminal pair artifact."""

    if not isinstance(artifact, Mapping):
        _fail("pair artifact must be a mapping")
    _validate_finite_tree(artifact, "pair artifact")
    _assert_exact_tree(dict(config), _expected_config(), "mechanism config")
    status = artifact.get("status")
    if status not in {"SUCCESS", "STOP_IMPLEMENTATION", "UNHANDLED_FAILURE"}:
        _fail("pair artifact status is not terminal")
    expected_keys = set(_PAIR_COMMON_KEYS)
    if status != "SUCCESS":
        expected_keys.add("failure")
    if set(artifact) != expected_keys:
        _fail("pair artifact has unexpected or missing fields")
    if (
        artifact.get("protocol_version") != config["protocol_version"]
        or artifact.get("pair_id") != pair.get("pair_id")
        or artifact.get("scenario_cluster") != pair.get("scenario_cluster")
    ):
        _fail("pair identity differs from the frozen manifest")
    if (
        artifact.get("source_commit") != config["source_commit"]
        or artifact.get("line_thermal_in_scope") is not False
        or artifact.get("resource_policy") != config["resource_policy"]
        or artifact.get("relative_stress") != relative_stress_evidence()
    ):
        _fail("pair provenance, resource policy, or scope differs")
    bad, control = pair_members(pair)
    if artifact.get("members") != {"bad": bad, "control": control}:
        _fail("pair member identity differs from the frozen manifest")
    audits = artifact.get("audits")
    if not isinstance(audits, list) or not all(
        isinstance(audit, Mapping) for audit in audits
    ):
        _fail("pair artifact audits must be a mapping list")
    if status == "SUCCESS" and len(audits) != 6:
        _fail("successful pair artifact must contain exactly six audits")
    if status != "SUCCESS" and len(audits) > 6:
        _fail("failure artifact exceeds the continuous audit prefix")

    matches_expected: list[bool] = []
    for index, audit in enumerate(audits):
        if audit.get("sequence_index") != index:
            _fail("failure artifact does not contain a continuous audit prefix")
        matches_expected.append(
            _validate_audit_artifact(
                audit,
                pair=pair,
                config=config,
                index=index,
            )
        )
    if len(audits) >= 4:
        bad_slot = audits[2].get("first_failure_slot")
        control_selected = audits[3].get("selected_slot")
        if (
            not isinstance(bad_slot, int)
            or isinstance(bad_slot, bool)
            or not isinstance(control_selected, Mapping)
            or control_selected.get("slot") != bad_slot
        ):
            _fail("control capture slot differs from the bad first failure slot")
    if status == "SUCCESS":
        if not all(matches_expected):
            _fail("successful artifact contradicts a frozen audit rule")
        return

    failure = _slot_mapping(artifact.get("failure"), "terminal failure")
    if status == "STOP_IMPLEMENTATION":
        if set(failure) != {"kind", "rule_code", "detail", "sequence_index"}:
            _fail("STOP_IMPLEMENTATION failure fields are invalid")
        sequence_index = failure.get("sequence_index")
        rule_code = failure.get("rule_code")
        if (
            not isinstance(rule_code, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", rule_code) is None
        ):
            _fail("STOP_IMPLEMENTATION rule code is invalid")
        if not isinstance(failure.get("detail"), str) or not failure.get("detail"):
            _fail("STOP_IMPLEMENTATION detail must be nonempty")
        if not audits and sequence_index is None:
            if rule_code != "PRE_AUDIT_IMPLEMENTATION_INVALID":
                _fail("pre-audit STOP_IMPLEMENTATION rule code is invalid")
        elif sequence_index == len(audits):
            if (
                sequence_index >= len(_D1_AUDIT_SEQUENCE)
                or any(not item for item in matches_expected)
                or rule_code != "AUDIT_EVIDENCE_INVALID"
            ):
                _fail("STOP_IMPLEMENTATION has an invalid audit-stage prefix")
        elif audits:
            if (
                sequence_index != len(audits) - 1
                or any(not item for item in matches_expected[:-1])
                or matches_expected[-1]
                or rule_code != _STOP_RULE_BY_SEQUENCE[len(audits) - 1]
            ):
                _fail("STOP_IMPLEMENTATION is not the first failed frozen rule")
        else:
            _fail("STOP_IMPLEMENTATION does not identify a valid stop point")
        if failure.get("kind") != "FROZEN_RULE_CONTRADICTION":
            _fail("STOP_IMPLEMENTATION failure kind is invalid")
    else:
        if set(failure) != {"kind", "exception_type", "message", "sequence_index"}:
            _fail("UNHANDLED_FAILURE fields are invalid")
        if (
            failure.get("kind") != "UNHANDLED_EXCEPTION"
            or failure.get("sequence_index") != len(audits)
            or any(not item for item in matches_expected)
            or not isinstance(failure.get("exception_type"), str)
            or not failure.get("exception_type")
            or not isinstance(failure.get("message"), str)
        ):
            _fail("UNHANDLED_FAILURE is not a valid continuous audit prefix")
