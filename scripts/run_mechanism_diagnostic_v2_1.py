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
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from evflex.mechanism_diagnostic import (
    D1AuditStop,
    execute_pair,
    load_mechanism_config,
    load_pair_manifest,
    pair_members,
    relative_stress_evidence,
    strict_json_file,
    validate_pair_artifact,
    verify_frozen_sources,
)
from evflex.runner import atomic_write_json, exclusive_lock


def _rooted(repo_root: Path, relative: str) -> Path:
    root = repo_root.resolve(strict=False)
    target = (root / relative).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"D1 path escapes repository root: {relative}")
    return target


def _pair_path(
    root: Path, config: Mapping[str, Any], pair_id: str
) -> Path:
    relative = config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id=pair_id
    )
    return _rooted(root, relative)


def _attempt_path(
    root: Path, config: Mapping[str, Any], pair_id: str
) -> Path:
    relative = config["artifact_names"]["attempt_pattern"].format(
        pair_id=pair_id
    )
    return _rooted(root, relative)


def verify_archived_gate(
    repo_root: str | Path,
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> None:
    root = Path(repo_root).resolve(strict=True)
    script = root / "scripts" / "evaluate_pilot_gate_v2_1.py"
    if not script.is_file():
        raise ValueError("archived pilot verifier is missing")
    environment = os.environ.copy()
    environment.update(THREAD_ENVIRONMENT)
    environment["PYTHONPATH"] = str(root / "src")
    result = subprocess_runner(
        [sys.executable, str(script), "--verify-existing"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no verifier output").strip()
        raise ValueError(f"archived pilot verifier failed: {detail}")


def _verify_frozen_paths_clean(
    root: Path,
    config: Mapping[str, Any],
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> None:
    paths = [source["path"] for source in config["frozen_sources"]]
    paths.append(config["pilot_py"]["path"])
    status = subprocess_runner(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise ValueError("could not inspect frozen source worktree state")
    if status.stdout.strip():
        raise ValueError("frozen source evidence has uncommitted changes")
    comparison = subprocess_runner(
        ["git", "diff", "--quiet", config["source_commit"], "--", *paths],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if comparison.returncode not in {0, 1}:
        raise ValueError("could not compare frozen source evidence to source commit")
    if comparison.returncode == 1:
        raise ValueError("frozen source evidence differs from the source commit")


def validate_runtime_inventory(
    repo_root: str | Path,
    config: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any]],
) -> None:
    root = Path(repo_root).resolve(strict=False)
    lock = _rooted(root, config["artifact_names"]["run_lock"])
    if lock.exists():
        raise ValueError(f"D1 run lock requires inspection: {lock}")

    attempt_example = _attempt_path(root, config, "01")
    attempt_directory = attempt_example.parent
    if attempt_directory.exists():
        attempts = sorted(path for path in attempt_directory.iterdir() if path.is_file())
        if attempts:
            raise ValueError(f"D1 attempt state requires inspection: {attempts[0]}")

    allowed_pair_names = {
        _pair_path(root, config, str(pair["pair_id"])).name for pair in pairs
    }
    pair_directory = _pair_path(root, config, "01").parent
    if pair_directory.exists():
        for path in sorted(pair_directory.iterdir()):
            if path.is_file() and path.suffix == ".json" and path.name not in allowed_pair_names:
                raise ValueError(f"unexpected D1 pair file requires inspection: {path}")
            if path.is_file() and ".tmp" in path.name:
                raise ValueError(f"D1 temporary file requires inspection: {path}")

    missing_seen = False
    failure_seen = False
    for pair in pairs:
        pair_id = str(pair["pair_id"])
        path = _pair_path(root, config, pair_id)
        if not path.is_file():
            missing_seen = True
            continue
        if missing_seen or failure_seen:
            raise ValueError(
                "existing D1 pair files are not a continuous terminal prefix"
            )
        try:
            payload = strict_json_file(path)
            validate_pair_artifact(payload, pair, config)
        except ValueError as exc:
            raise ValueError(
                f"invalid existing pair artifact will not be overwritten: {path}: {exc}"
            ) from exc
        if payload["status"] != "SUCCESS":
            failure_seen = True

    for name in ("audit_csv", "report_json", "report_markdown", "hashes_csv"):
        report = _rooted(root, config["artifact_names"][name])
        if report.parent.exists():
            temporaries = sorted(report.parent.glob(f"{report.name}*.tmp*"))
            if temporaries:
                raise ValueError(
                    f"D1 evaluator temporary file requires inspection: {temporaries[0]}"
                )

    formal_directory = root / "results" / "formal_v2_1"
    formal_reports = list((root / "reports").glob("formal_v2_1*")) if (root / "reports").exists() else []
    if formal_directory.exists() or formal_reports:
        offending = formal_directory if formal_directory.exists() else formal_reports[0]
        raise ValueError(f"formal V2.1 output is forbidden during D1: {offending}")


def preflight(
    repo_root: str | Path,
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = Path(repo_root).resolve(strict=True)
    if any(os.environ.get(name) != "1" for name in _THREAD_VARIABLES):
        raise ValueError("D1 numeric thread caps are not all set to one")
    config = load_mechanism_config(root)
    pairs = load_pair_manifest(root)
    verify_frozen_sources(root, config)
    _verify_frozen_paths_clean(root, config, subprocess_runner=subprocess_runner)
    verify_archived_gate(root, subprocess_runner=subprocess_runner)
    validate_runtime_inventory(root, config, pairs)
    return config, pairs


def _unhandled_artifact(
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    bad, control = pair_members(pair)
    return {
        "protocol_version": config["protocol_version"],
        "status": "UNHANDLED_FAILURE",
        "pair_id": pair["pair_id"],
        "scenario_cluster": pair["scenario_cluster"],
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "relative_stress": relative_stress_evidence(),
        "members": {"bad": bad, "control": control},
        "audits": [],
        "failure": {
            "kind": "UNHANDLED_EXCEPTION",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "sequence_index": 0,
        },
    }


def _controlled_stop_artifact(
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
    exc: ValueError,
) -> dict[str, Any]:
    bad, control = pair_members(pair)
    return {
        "protocol_version": config["protocol_version"],
        "status": "STOP_IMPLEMENTATION",
        "pair_id": pair["pair_id"],
        "scenario_cluster": pair["scenario_cluster"],
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "relative_stress": relative_stress_evidence(),
        "members": {"bad": bad, "control": control},
        "audits": [],
        "failure": {
            "kind": "FROZEN_RULE_CONTRADICTION",
            "rule_code": "PRE_AUDIT_IMPLEMENTATION_INVALID",
            "detail": str(exc),
            "sequence_index": None,
        },
    }


def _audit_stop_artifact(
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
    exc: D1AuditStop,
) -> dict[str, Any]:
    bad, control = pair_members(pair)
    return {
        "protocol_version": config["protocol_version"],
        "status": "STOP_IMPLEMENTATION",
        "pair_id": pair["pair_id"],
        "scenario_cluster": pair["scenario_cluster"],
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "relative_stress": relative_stress_evidence(),
        "members": {"bad": bad, "control": control},
        "audits": deepcopy(exc.audits),
        "failure": {
            "kind": "FROZEN_RULE_CONTRADICTION",
            "rule_code": exc.rule_code,
            "detail": exc.detail,
            "sequence_index": exc.sequence_index,
        },
    }


def _existing_terminal(
    path: Path,
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = strict_json_file(path)
        validate_pair_artifact(payload, pair, config)
    except ValueError as exc:
        raise ValueError(
            f"invalid existing pair artifact will not be overwritten: {path}: {exc}"
        ) from exc
    return payload


def run_diagnostic(
    repo_root: str | Path,
    *,
    pair_id: str | None = None,
    config: Mapping[str, Any] | None = None,
    pairs: Sequence[Mapping[str, Any]] | None = None,
    execute_fn: Callable[..., Mapping[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=False)
    if preflight:
        loaded_config, loaded_pairs = globals()["preflight"](root)
    else:
        if config is None or pairs is None:
            raise ValueError("config and pairs are required when preflight is disabled")
        loaded_config = dict(config)
        loaded_pairs = [dict(pair) for pair in pairs]
        validate_runtime_inventory(root, loaded_config, loaded_pairs)
    if pair_id is not None:
        selected = [pair for pair in loaded_pairs if pair.get("pair_id") == pair_id]
        if len(selected) != 1:
            raise ValueError(f"unknown or duplicate D1 pair ID: {pair_id}")
        selected_index = loaded_pairs.index(selected[0])
        predecessors = loaded_pairs[:selected_index]
    else:
        selected = loaded_pairs
        predecessors = []
    compute = execute_fn or execute_pair
    if not callable(compute):
        raise ValueError("D1 execute function must be callable")

    completed: list[str] = []
    skipped: list[str] = []
    lock = _rooted(root, loaded_config["artifact_names"]["run_lock"])
    with exclusive_lock(lock):
        for predecessor in predecessors:
            predecessor_id = str(predecessor["pair_id"])
            existing = _existing_terminal(
                _pair_path(root, loaded_config, predecessor_id),
                predecessor,
                loaded_config,
            )
            if existing is None or existing["status"] != "SUCCESS":
                raise ValueError(
                    f"D1 pair {pair_id} requires a preceding SUCCESS prefix; "
                    f"pair {predecessor_id} is not SUCCESS"
                )
            skipped.append(predecessor_id)
        for pair in selected:
            current_id = str(pair["pair_id"])
            result_path = _pair_path(root, loaded_config, current_id)
            existing = _existing_terminal(result_path, pair, loaded_config)
            if existing is not None:
                skipped.append(current_id)
                if existing["status"] != "SUCCESS":
                    return {
                        "status": existing["status"],
                        "completed_pair_ids": completed,
                        "skipped_pair_ids": skipped,
                        "failure": existing["failure"],
                    }
                continue

            attempt = _attempt_path(root, loaded_config, current_id)
            if attempt.exists():
                raise ValueError(f"D1 attempt state requires inspection: {attempt}")
            atomic_write_json(
                attempt,
                {
                    "protocol_version": loaded_config["protocol_version"],
                    "pair_id": current_id,
                    "scenario_cluster": pair["scenario_cluster"],
                    "status": "RUNNING",
                },
            )
            try:
                try:
                    artifact = dict(compute(root, pair, loaded_config))
                except D1AuditStop as exc:
                    artifact = _audit_stop_artifact(pair, loaded_config, exc)
                except ValueError as exc:
                    artifact = _controlled_stop_artifact(pair, loaded_config, exc)
                except Exception as exc:
                    artifact = _unhandled_artifact(pair, loaded_config, exc)
                validate_pair_artifact(artifact, pair, loaded_config)
                atomic_write_json(result_path, artifact)
                persisted = strict_json_file(result_path)
                validate_pair_artifact(persisted, pair, loaded_config)
            except Exception:
                # The attempt record is intentionally retained for inspection.
                raise
            attempt.unlink()
            completed.append(current_id)
            if artifact["status"] != "SUCCESS":
                return {
                    "status": artifact["status"],
                    "completed_pair_ids": completed,
                    "skipped_pair_ids": skipped,
                    "failure": artifact["failure"],
                }
    return {
        "status": "SUCCESS",
        "completed_pair_ids": completed,
        "skipped_pair_ids": skipped,
        "failure": None,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen V2.1 D1 diagnostic")
    parser.add_argument("--repo-root", type=Path, default=_REPO_FROM_SCRIPT)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--pair-id")
    args = parser.parse_args(argv)
    try:
        if args.preflight_only:
            config, pairs = preflight(args.repo_root)
            summary = {
                "status": "PREFLIGHT_OK",
                "pair_count": len(pairs),
                "protocol_version": config["protocol_version"],
                "formal_v2_1_run_started": False,
            }
            exit_code = 0
        else:
            summary = run_diagnostic(args.repo_root, pair_id=args.pair_id)
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
