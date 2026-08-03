from __future__ import annotations

import os
import sys
from pathlib import Path


_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)
THREAD_ENVIRONMENT = {name: "1" for name in _THREAD_VARIABLES}
for _name, _value in THREAD_ENVIRONMENT.items():
    os.environ[_name] = _value

_REPO_FROM_SCRIPT = Path(__file__).resolve().parents[1]
_SRC = _REPO_FROM_SCRIPT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


import argparse
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import json
from typing import Any

from evflex.mechanism_diagnostic import strict_json_file
from evflex.mechanism_diagnostic_d1r_lite import (
    LiteAuditStop,
    execute_lite_case,
    final_gate,
    load_lite_config,
    load_lite_manifest,
    real_runtime_preflight,
    stage_a_gate,
    validate_lite_case_artifact,
    verify_lite_sources,
)
from evflex.runner import atomic_write_json, exclusive_lock


def _rooted(repo_root: Path, relative: str, label: str) -> Path:
    root = repo_root.resolve(strict=False)
    target = (root / relative).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"D1-R-Lite {label} escapes repository root")
    return target


def _case_path(
    root: Path, config: Mapping[str, Any], pair_id: str
) -> Path:
    relative = config["artifact_names"]["case_artifact_pattern"].format(
        pair_id=pair_id
    )
    return _rooted(root, relative, "case path")


def _attempt_path(
    root: Path, config: Mapping[str, Any], pair_id: str
) -> Path:
    relative = config["artifact_names"]["attempt_pattern"].format(
        pair_id=pair_id
    )
    return _rooted(root, relative, "attempt path")


def _read_terminal(
    path: Path,
    case: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = strict_json_file(path)
        validate_lite_case_artifact(payload, case, config)
    except ValueError as exc:
        raise ValueError(
            f"invalid existing D1-R-Lite artifact will not be overwritten: "
            f"{path}: {exc}"
        ) from exc
    return payload


def validate_runtime_inventory(
    repo_root: str | Path,
    config: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate that existing terminal files form one immutable prefix."""

    root = Path(repo_root).resolve(strict=False)
    lock = _rooted(root, config["artifact_names"]["run_lock"], "run lock")
    if lock.exists():
        raise ValueError(f"D1-R-Lite run lock requires inspection: {lock}")

    attempt_directory = _attempt_path(root, config, "01").parent
    if attempt_directory.exists():
        attempts = sorted(path for path in attempt_directory.iterdir())
        if attempts:
            raise ValueError(
                f"D1-R-Lite attempt state requires inspection: {attempts[0]}"
            )

    allowed_names = {
        _case_path(root, config, str(case["pair_id"])).name for case in cases
    }
    case_directory = _case_path(root, config, "01").parent
    if case_directory.exists():
        for path in sorted(case_directory.iterdir()):
            if not path.is_file() or path.name not in allowed_names:
                raise ValueError(
                    f"unexpected D1-R-Lite case state requires inspection: {path}"
                )

    prefix: list[dict[str, Any]] = []
    missing_seen = False
    failure_seen = False
    for case in cases:
        path = _case_path(root, config, str(case["pair_id"]))
        payload = _read_terminal(path, case, config)
        if payload is None:
            missing_seen = True
            continue
        if missing_seen or failure_seen:
            raise ValueError(
                "existing D1-R-Lite case files are not a continuous terminal prefix"
            )
        prefix.append(payload)
        if payload["status"] != "SUCCESS":
            failure_seen = True

    if len(prefix) > config["expected_counts"]["stage_a_cases"]:
        stage_result = stage_a_gate(prefix[:4], cases, config)
        if stage_result["decision"] != "EXPAND_STAGE_B":
            raise ValueError(
                "D1-R-Lite Stage B artifacts exist before expansion gate"
            )

    result_root = _rooted(
        root, config["artifact_names"]["result_root"], "result root"
    )
    if result_root.exists():
        for path in result_root.rglob("*"):
            if path.is_file() and ".tmp" in path.name:
                raise ValueError(
                    f"D1-R-Lite temporary file requires inspection: {path}"
                )
    formal_directory = root / "results" / "formal_v2_1"
    formal_reports = (
        list((root / "reports").glob("formal_v2_1*"))
        if (root / "reports").exists()
        else []
    )
    if formal_directory.exists() or formal_reports:
        offending = formal_directory if formal_directory.exists() else formal_reports[0]
        raise ValueError(
            f"formal V2.1 output is forbidden during D1-R-Lite: {offending}"
        )
    return prefix


def preflight(
    repo_root: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Run all read-only source, inventory, and real-runtime checks."""

    root = Path(repo_root).resolve(strict=True)
    if any(os.environ.get(name) != "1" for name in _THREAD_VARIABLES):
        raise ValueError("D1-R-Lite numeric thread caps are not all set to one")
    config = load_lite_config(root)
    cases = load_lite_manifest(root)
    verify_lite_sources(root, config)
    validate_runtime_inventory(root, config, cases)
    integration = real_runtime_preflight(root, config)
    return config, cases, integration


def _base_artifact(
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    status: str,
    audits: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "protocol_version": config["protocol_version"],
        "status": status,
        "pair_id": case["pair_id"],
        "stage": case["stage"],
        "execution_order": case["execution_order"],
        "scenario_cluster": case["scenario_cluster"],
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "formal_v2_1_run_authorized": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "member": deepcopy(dict(case)),
        "audits": [deepcopy(dict(audit)) for audit in audits],
    }


def _audit_stop_artifact(
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    exc: LiteAuditStop,
) -> dict[str, Any]:
    artifact = _base_artifact(
        case,
        config,
        status="STOP_IMPLEMENTATION",
        audits=exc.audits,
    )
    artifact["failure"] = {
        "kind": "FROZEN_RULE_CONTRADICTION",
        "rule_code": exc.rule_code,
        "detail": exc.detail,
        "sequence_index": exc.sequence_index,
    }
    return artifact


def _controlled_stop_artifact(
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    exc: ValueError,
) -> dict[str, Any]:
    artifact = _base_artifact(case, config, status="STOP_IMPLEMENTATION")
    artifact["failure"] = {
        "kind": "FROZEN_RULE_CONTRADICTION",
        "rule_code": "PRE_AUDIT_IMPLEMENTATION_INVALID",
        "detail": str(exc) or "unspecified pre-audit validation failure",
        "sequence_index": None,
    }
    return artifact


def _unhandled_artifact(
    case: Mapping[str, Any],
    config: Mapping[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    artifact = _base_artifact(case, config, status="UNHANDLED_FAILURE")
    artifact["failure"] = {
        "kind": "UNHANDLED_EXCEPTION",
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "sequence_index": 0,
    }
    return artifact


def _failure_summary(
    artifact: Mapping[str, Any],
    *,
    completed: Sequence[str],
    skipped: Sequence[str],
) -> dict[str, Any]:
    return {
        "status": artifact["status"],
        "decision": artifact["status"],
        "stage_a_decision": None,
        "completed_pair_ids": list(completed),
        "skipped_pair_ids": list(skipped),
        "failure": deepcopy(artifact["failure"]),
        "formal_v2_1_run_started": False,
    }


def _success_summary(
    gate: Mapping[str, Any],
    *,
    completed: Sequence[str],
    skipped: Sequence[str],
    stage_a_decision: str,
) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "decision": gate["decision"],
        "stage_a_decision": stage_a_decision,
        "completed_pair_ids": list(completed),
        "skipped_pair_ids": list(skipped),
        "evaluated_case_count": gate["evaluated_case_count"],
        "evaluated_target_audit_count": gate[
            "evaluated_target_audit_count"
        ],
        "qualifying_families": deepcopy(gate["qualifying_families"]),
        "failure": None,
        "formal_v2_1_run_started": False,
    }


def run_diagnostic(
    repo_root: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
    cases: Sequence[Mapping[str, Any]] | None = None,
    execute_fn: Callable[..., Mapping[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    """Run the adaptive screen sequentially with immutable prefix resume."""

    root = Path(repo_root).resolve(strict=False)
    if preflight:
        loaded_config, loaded_cases, _ = globals()["preflight"](root)
    else:
        if config is None or cases is None:
            raise ValueError(
                "config and cases are required when preflight is disabled"
            )
        loaded_config = dict(config)
        loaded_cases = [dict(case) for case in cases]
        validate_runtime_inventory(root, loaded_config, loaded_cases)
    compute = execute_fn or execute_lite_case
    if not callable(compute):
        raise ValueError("D1-R-Lite execute function must be callable")

    completed: list[str] = []
    skipped: list[str] = []
    retained: list[dict[str, Any]] = []
    stage_a_result: dict[str, Any] | None = None
    lock = _rooted(
        root, loaded_config["artifact_names"]["run_lock"], "run lock"
    )
    with exclusive_lock(lock):
        for index, case in enumerate(loaded_cases):
            if index == loaded_config["expected_counts"]["stage_a_cases"]:
                stage_a_result = stage_a_gate(
                    retained[:4], loaded_cases, loaded_config
                )
                if stage_a_result["decision"] == "STOP_HETEROGENEOUS_SCREEN":
                    return _success_summary(
                        stage_a_result,
                        completed=completed,
                        skipped=skipped,
                        stage_a_decision=stage_a_result["decision"],
                    )

            pair_id = str(case["pair_id"])
            result_path = _case_path(root, loaded_config, pair_id)
            artifact = _read_terminal(
                result_path, case, loaded_config
            )
            if artifact is not None:
                skipped.append(pair_id)
                retained.append(artifact)
                if artifact["status"] != "SUCCESS":
                    return _failure_summary(
                        artifact, completed=completed, skipped=skipped
                    )
                continue

            attempt = _attempt_path(root, loaded_config, pair_id)
            if attempt.exists():
                raise ValueError(
                    f"D1-R-Lite attempt state requires inspection: {attempt}"
                )
            atomic_write_json(
                attempt,
                {
                    "protocol_version": loaded_config["protocol_version"],
                    "pair_id": pair_id,
                    "stage": case["stage"],
                    "status": "RUNNING",
                    "formal_v2_1_run_started": False,
                },
            )
            try:
                try:
                    artifact = dict(compute(root, case, loaded_config))
                except LiteAuditStop as exc:
                    artifact = _audit_stop_artifact(case, loaded_config, exc)
                except ValueError as exc:
                    artifact = _controlled_stop_artifact(
                        case, loaded_config, exc
                    )
                except Exception as exc:
                    artifact = _unhandled_artifact(case, loaded_config, exc)
                validate_lite_case_artifact(artifact, case, loaded_config)
                atomic_write_json(result_path, artifact)
                persisted = strict_json_file(result_path)
                validate_lite_case_artifact(persisted, case, loaded_config)
            except Exception:
                raise
            attempt.unlink()
            completed.append(pair_id)
            retained.append(artifact)
            if artifact["status"] != "SUCCESS":
                return _failure_summary(
                    artifact, completed=completed, skipped=skipped
                )

    if stage_a_result is None:
        stage_a_result = stage_a_gate(retained[:4], loaded_cases, loaded_config)
    final_result = final_gate(retained, loaded_cases, loaded_config)
    return _success_summary(
        final_result,
        completed=completed,
        skipped=skipped,
        stage_a_decision=stage_a_result["decision"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded V2.1 D1-R-Lite screen"
    )
    parser.add_argument("--repo-root", type=Path, default=_REPO_FROM_SCRIPT)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.preflight_only:
            config, cases, integration = preflight(args.repo_root)
            summary = {
                "status": "PREFLIGHT_OK",
                "protocol_version": config["protocol_version"],
                "case_count": len(cases),
                "integration": integration,
                "formal_v2_1_run_started": False,
            }
            exit_code = 0
        else:
            summary = run_diagnostic(args.repo_root)
            exit_code = 0 if summary["status"] == "SUCCESS" else 1
    except Exception as exc:
        summary = {
            "status": "RUNNER_ERROR",
            "error_type": type(exc).__name__,
            "detail": str(exc),
            "formal_v2_1_run_started": False,
        }
        exit_code = 1
    print(
        json.dumps(
            summary,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
