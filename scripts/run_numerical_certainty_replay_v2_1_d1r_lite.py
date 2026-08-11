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
import subprocess
from typing import Any

from evflex.mechanism_diagnostic import strict_json_file
from evflex.numerical_certainty_replay_d1r_lite import (
    assess_replay_gate,
    execute_replay_case,
    load_replay_config,
    load_replay_source,
    validate_replay_case_artifact,
)
from evflex.runner import atomic_write_json, exclusive_lock


def _rooted(repo_root: Path, relative: str, label: str) -> Path:
    root = repo_root.resolve(strict=False)
    path = Path(relative)
    if path.is_absolute():
        raise ValueError(f"N1 replay {label} must be relative")
    target = (root / path).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"N1 replay {label} escapes repository root")
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
    relative = config["artifact_names"]["attempt_pattern"].format(pair_id=pair_id)
    return _rooted(root, relative, "attempt path")


def _read_terminal(
    path: Path,
    selection: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = strict_json_file(path)
        validate_replay_case_artifact(payload, selection, config)
    except ValueError as exc:
        raise ValueError(
            f"invalid existing N1 replay artifact will not be overwritten: {path}: {exc}"
        ) from exc
    return payload


def _ordered_selections(
    selections: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if isinstance(selections, (str, bytes)) or not isinstance(selections, Sequence):
        raise ValueError("N1 replay selections must be a sequence")
    retained = [dict(item) if isinstance(item, Mapping) else {} for item in selections]
    if retained != config["selected_cases"]:
        raise ValueError("N1 replay selections differ from the frozen four cases")
    return retained


def validate_runtime_inventory(
    repo_root: str | Path,
    config: Mapping[str, Any],
    selections: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Require one valid immutable terminal prefix and no ambiguous run state."""

    root = Path(repo_root).resolve(strict=False)
    ordered = _ordered_selections(selections, config)
    lock = _rooted(root, config["artifact_names"]["run_lock"], "run lock")
    if lock.exists():
        raise ValueError(f"N1 replay run lock requires inspection: {lock}")
    attempt_directory = _attempt_path(root, config, "01").parent
    if attempt_directory.exists():
        attempts = sorted(attempt_directory.iterdir())
        if attempts:
            raise ValueError(
                f"N1 replay attempt state requires inspection: {attempts[0]}"
            )

    allowed_names = {
        _case_path(root, config, str(selection["pair_id"])).name
        for selection in ordered
    }
    case_directory = _case_path(root, config, "01").parent
    if case_directory.exists():
        for path in sorted(case_directory.iterdir()):
            if not path.is_file() or path.name not in allowed_names:
                raise ValueError(
                    f"unexpected N1 replay case state requires inspection: {path}"
                )

    prefix: list[dict[str, Any]] = []
    missing_seen = False
    stop_seen = False
    for selection in ordered:
        path = _case_path(root, config, str(selection["pair_id"]))
        payload = _read_terminal(path, selection, config)
        if payload is None:
            missing_seen = True
            continue
        if missing_seen or stop_seen:
            raise ValueError(
                "existing N1 replay case files are not a continuous terminal prefix"
            )
        prefix.append(payload)
        if payload["status"] != "SUCCESS":
            stop_seen = True

    result_root = _rooted(
        root, config["artifact_names"]["result_root"], "result root"
    )
    if result_root.exists():
        for path in result_root.rglob("*"):
            if path.is_file() and ".tmp" in path.name:
                raise ValueError(
                    f"N1 replay temporary file requires inspection: {path}"
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
            f"formal V2.1 output is forbidden during N1 replay: {offending}"
        )
    return prefix


def _require_clean_replay_code(repo_root: Path) -> None:
    paths = (
        "config/numerical_certainty_replay_v2_1_d1r_lite.json",
        "src/evflex/numerical_certainty_replay_d1r_lite.py",
        "scripts/run_numerical_certainty_replay_v2_1_d1r_lite.py",
    )
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *paths,
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.stdout.strip():
        raise ValueError("N1 replay code/config paths must be clean before execution")


def preflight(
    repo_root: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Validate sources, runtime inventory, resource caps, and code provenance."""

    root = Path(repo_root).resolve(strict=True)
    if any(os.environ.get(name) != "1" for name in _THREAD_VARIABLES):
        raise ValueError("N1 replay numeric thread caps are not all set to one")
    config = load_replay_config(root)
    source = load_replay_source(root, config)
    selections = _ordered_selections(source["selected"], config)
    validate_runtime_inventory(root, config, selections)
    _require_clean_replay_code(root)
    return config, selections, source


def _summary(
    gate: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    *,
    completed: Sequence[str],
    skipped: Sequence[str],
) -> dict[str, Any]:
    decision = str(gate["decision"])
    return {
        "status": "STOP_REPLAY" if decision.startswith("STOP_") else "SUCCESS",
        "decision": decision,
        "completed_pair_ids": list(completed),
        "skipped_pair_ids": list(skipped),
        "case_decisions": [
            str(artifact["assessment"]["case_decision"])
            for artifact in artifacts
        ],
        "completed_case_count": gate["completed_case_count"],
        "target_replay_evaluations": gate["target_replay_evaluations"],
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
    }


def run_replay(
    repo_root: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
    selections: Sequence[Mapping[str, Any]] | None = None,
    execute_fn: Callable[..., Mapping[str, Any]] | None = None,
    preflight: bool = True,
) -> dict[str, Any]:
    """Run the four replay cases sequentially with immutable-prefix resume."""

    root = Path(repo_root).resolve(strict=False)
    if preflight:
        loaded_config, loaded_selections, _ = globals()["preflight"](root)
    else:
        if config is None or selections is None:
            raise ValueError(
                "config and selections are required when preflight is disabled"
            )
        loaded_config = dict(config)
        loaded_selections = _ordered_selections(selections, loaded_config)
        validate_runtime_inventory(root, loaded_config, loaded_selections)
    compute = execute_fn or execute_replay_case
    if not callable(compute):
        raise ValueError("N1 replay execute function must be callable")

    completed: list[str] = []
    skipped: list[str] = []
    retained: list[dict[str, Any]] = []
    lock = _rooted(
        root, loaded_config["artifact_names"]["run_lock"], "run lock"
    )
    with exclusive_lock(lock):
        for selection in loaded_selections:
            pair_id = str(selection["pair_id"])
            result_path = _case_path(root, loaded_config, pair_id)
            artifact = _read_terminal(result_path, selection, loaded_config)
            if artifact is not None:
                skipped.append(pair_id)
                retained.append(artifact)
                if artifact["status"] != "SUCCESS":
                    gate = assess_replay_gate(retained, loaded_config)
                    return _summary(
                        gate, retained, completed=completed, skipped=skipped
                    )
                continue

            attempt = _attempt_path(root, loaded_config, pair_id)
            if attempt.exists():
                raise ValueError(f"N1 replay attempt state requires inspection: {attempt}")
            atomic_write_json(
                attempt,
                {
                    "protocol_version": loaded_config["protocol_version"],
                    "pair_id": pair_id,
                    "status": "RUNNING",
                    "formal_v2_1_run_started": False,
                },
            )
            artifact = dict(compute(root, selection, loaded_config))
            validate_replay_case_artifact(artifact, selection, loaded_config)
            atomic_write_json(result_path, artifact)
            persisted = strict_json_file(result_path)
            validate_replay_case_artifact(persisted, selection, loaded_config)
            if persisted != artifact:
                raise ValueError("persisted N1 replay artifact differs from memory")
            attempt.unlink()
            completed.append(pair_id)
            retained.append(artifact)
            if artifact["status"] != "SUCCESS":
                gate = assess_replay_gate(retained, loaded_config)
                return _summary(gate, retained, completed=completed, skipped=skipped)

    gate = assess_replay_gate(retained, loaded_config)
    return _summary(gate, retained, completed=completed, skipped=skipped)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded D1-R-Lite N1 numerical-certainty replay"
    )
    parser.add_argument("--repo-root", type=Path, default=_REPO_FROM_SCRIPT)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.preflight_only:
            config, selections, source = preflight(args.repo_root)
            summary = {
                "status": "PREFLIGHT_OK",
                "protocol_version": config["protocol_version"],
                "selected_pair_ids": [item["pair_id"] for item in selections],
                "runtime_version": source["runtime_version"],
                "formal_v2_1_run_started": False,
            }
            exit_code = 0
        else:
            summary = run_replay(args.repo_root)
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
