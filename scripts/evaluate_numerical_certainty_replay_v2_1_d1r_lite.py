from __future__ import annotations

import os


THREAD_ENVIRONMENT = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
}
for _name, _value in THREAD_ENVIRONMENT.items():
    os.environ[_name] = _value


import argparse
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


_REPO_FROM_SCRIPT = Path(__file__).resolve().parents[1]
_SRC = _REPO_FROM_SCRIPT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


from evflex.mechanism_diagnostic import canonical_json_bytes, strict_json_file
from evflex.numerical_certainty_replay_d1r_lite import (
    assess_replay_gate,
    load_replay_config,
    load_replay_source,
    validate_replay_case_artifact,
)


_OUTPUT_KEYS = ("report_json", "report_markdown", "report_csv", "hashes_csv")
_CODE_PATHS = (
    "config/numerical_certainty_replay_v2_1_d1r_lite.json",
    "src/evflex/numerical_certainty_replay_d1r_lite.py",
    "scripts/run_numerical_certainty_replay_v2_1_d1r_lite.py",
    "scripts/evaluate_numerical_certainty_replay_v2_1_d1r_lite.py",
)
_REPORT_COLUMNS = (
    "pair_id",
    "scenario_cluster",
    "selected_slot",
    "metric_id",
    "setting_label",
    "requested_convergence_tolerance",
    "requested_max_iterations",
    "requested_max_control_iterations",
    "observed_convergence_tolerance",
    "observed_max_iterations",
    "observed_max_control_iterations",
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
    "load_scale",
    "audited_schedule_sha256",
    "power_vector_sha256",
    "native_replay_abs_diff_pu",
    "native_to_tight_drift_pu",
    "tight_plateau_drift_pu",
    "case_decision",
)
_HASH_COLUMNS = ("kind", "pair_id", "path", "sha256")


def _rooted(root: Path, relative: str, label: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ValueError(f"N1 evaluator {label} must be relative")
    target = (root / path).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"N1 evaluator {label} escapes repository root")
    return target


def _output_paths(root: Path, config: Mapping[str, Any]) -> dict[str, Path]:
    return {
        key: _rooted(root, str(config["artifact_names"][key]), f"{key} path")
        for key in _OUTPUT_KEYS
    }


def _case_path(
    root: Path, config: Mapping[str, Any], pair_id: str
) -> Path:
    relative = config["artifact_names"]["case_artifact_pattern"].format(
        pair_id=pair_id
    )
    return _rooted(root, relative, "case artifact")


def _load_case_artifacts(
    root: Path, config: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[Path], dict[str, Any]]:
    selections = config["selected_cases"]
    allowed = {
        _case_path(root, config, str(selection["pair_id"])).name
        for selection in selections
    }
    directory = _case_path(root, config, "01").parent
    if directory.exists():
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.name not in allowed:
                raise ValueError(f"unexpected N1 replay case artifact: {path}")

    artifacts: list[dict[str, Any]] = []
    paths: list[Path] = []
    missing_seen = False
    stop_seen = False
    for selection in selections:
        path = _case_path(root, config, str(selection["pair_id"]))
        if not path.is_file():
            missing_seen = True
            continue
        if missing_seen or stop_seen:
            raise ValueError("N1 replay artifacts are not a continuous terminal prefix")
        artifact = strict_json_file(path)
        validate_replay_case_artifact(artifact, selection, config)
        artifacts.append(artifact)
        paths.append(path)
        if artifact["status"] != "SUCCESS":
            stop_seen = True
    if not artifacts:
        raise ValueError("N1 evaluator found no terminal replay artifacts")
    gate = assess_replay_gate(artifacts, config)
    return artifacts, paths, gate


def _resolve_code_commit(
    root: Path,
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> str:
    result = subprocess_runner(
        ["git", "log", "-1", "--format=%H", "--", *_CODE_PATHS],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip().lower()
    if (
        result.returncode != 0
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise ValueError("could not resolve the N1 replay production code commit")
    return commit


def verify_evaluator_integrity(
    repo_root: str | Path,
    config: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Require committed clean replay code plus the already validated sources."""

    root = Path(repo_root).resolve(strict=True)
    if any(os.environ.get(name) != "1" for name in THREAD_ENVIRONMENT):
        raise ValueError("N1 evaluator numeric thread caps are not all one")
    status = subprocess_runner(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *_CODE_PATHS,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise ValueError("could not inspect N1 replay production code state")
    if status.stdout.strip():
        raise ValueError("N1 replay production code paths have uncommitted changes")
    commit = _resolve_code_commit(root, subprocess_runner=subprocess_runner)
    hashes: dict[str, str] = {}
    for relative in _CODE_PATHS:
        path = _rooted(root, relative, "production code path")
        if not path.is_file():
            raise ValueError(f"N1 replay production code is missing: {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "frozen_source_hashes_verified": True,
        "source_case_hashes_verified": True,
        "source_artifacts_validated": len(config["source_pair_order"]),
        "replay_artifacts_validated": len(artifacts),
        "code_provenance": {
            "replay_code_commit": commit,
            "replay_code_paths_clean": True,
            "file_sha256": hashes,
        },
    }


def _validated_integrity(
    value: Mapping[str, Any], *, replay_count: int
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("N1 evaluator integrity result must be a mapping")
    integrity = deepcopy(dict(value))
    provenance = integrity.get("code_provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("N1 evaluator code provenance is missing")
    commit = provenance.get("replay_code_commit")
    hashes = provenance.get("file_sha256")
    if (
        integrity.get("frozen_source_hashes_verified") is not True
        or integrity.get("source_case_hashes_verified") is not True
        or integrity.get("source_artifacts_validated") != 12
        or integrity.get("replay_artifacts_validated") != replay_count
        or provenance.get("replay_code_paths_clean") is not True
        or not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or not isinstance(hashes, Mapping)
        or set(hashes) != set(_CODE_PATHS)
        or any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in hashes.values()
        )
    ):
        raise ValueError("N1 evaluator source, replay, or code integrity was not verified")
    return integrity


def _boolean(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    raise ValueError("expected a Boolean report value")


def _csv_bytes(
    columns: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(columns),
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _report_rows(
    artifacts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        assessment = artifact["assessment"]
        for observation in artifact["observations"]:
            requested = observation["requested_solver_settings"]
            observed = observation["observed_solver_settings"]
            label = observation["setting_label"]
            rows.append(
                {
                    "pair_id": artifact["pair_id"],
                    "scenario_cluster": artifact["scenario_cluster"],
                    "selected_slot": observation["selected_slot"],
                    "metric_id": observation["metric_id"],
                    "setting_label": label,
                    "requested_convergence_tolerance": requested[
                        "convergence_tolerance"
                    ],
                    "requested_max_iterations": requested["max_iterations"],
                    "requested_max_control_iterations": requested[
                        "max_control_iterations"
                    ],
                    "observed_convergence_tolerance": observed[
                        "convergence_tolerance"
                    ],
                    "observed_max_iterations": observed["max_iterations"],
                    "observed_max_control_iterations": observed[
                        "max_control_iterations"
                    ],
                    "metric_value": observation["metric_value"],
                    "limit": observation["limit"],
                    "direction": observation["direction"],
                    "exceedance": observation["exceedance"],
                    "physical_violation": _boolean(
                        observation["physical_violation"]
                    ),
                    "physical_violation_metrics": ";".join(
                        observation["physical_violation_metrics"]
                    ),
                    "converged": _boolean(observation["converged"]),
                    "numerical_failure": _boolean(
                        observation["numerical_failure"]
                    ),
                    "iterations": observation["iterations"],
                    "vmin": observation["vmin"],
                    "vmax": observation["vmax"],
                    "load_scale": observation["load_scale"],
                    "audited_schedule_sha256": observation[
                        "audited_schedule_sha256"
                    ],
                    "power_vector_sha256": observation["power_vector_sha256"],
                    "native_replay_abs_diff_pu": assessment[
                        "native_replay_abs_diff_pu"
                    ],
                    "native_to_tight_drift_pu": assessment[
                        "native_to_tight_drift_pu"
                    ].get(label, ""),
                    "tight_plateau_drift_pu": assessment[
                        "tight_plateau_drift_pu"
                    ],
                    "case_decision": assessment["case_decision"],
                }
            )
    return rows


def _case_hash_rows(
    config: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    paths: Sequence[Path],
    root: Path,
) -> list[dict[str, Any]]:
    rows = [
        {
            "kind": "frozen_source",
            "pair_id": "",
            "path": item["path"],
            "sha256": item["sha256"],
        }
        for item in config["frozen_sources"]
    ]
    for artifact, path in zip(artifacts, paths, strict=True):
        rows.append(
            {
                "kind": "replay_case_artifact",
                "pair_id": artifact["pair_id"],
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return rows


def _render_markdown(report: Mapping[str, Any]) -> bytes:
    decision = report["decision"]
    if decision == "NUMERICALLY_STABLE_SELECTED_WITNESSES":
        conclusion = (
            "4个已选见证点在三组最终求解设置下均保持同一电压超限，"
            "且漂移未超过冻结阈值。"
        )
    elif decision == "NUMERICAL_SENSITIVITY_DETECTED":
        conclusion = "至少一个已选见证点对最终求解设置敏感，不能扩大实验。"
    elif decision == "STOP_REPLAY_IDENTITY_MISMATCH":
        conclusion = "原生设置未复现归档身份，重放已受控停止。"
    else:
        conclusion = "至少一个求解设置失败或未被准确应用，重放已受控停止。"
    lines = [
        "# V2.1 D1-R-Lite N1 数值确定性复核",
        "",
        "## 结论",
        "",
        f"- 决策：`{decision}`。",
        f"- {conclusion}",
        (
            f"- 协议预选4个代表见证点，本次完成 {report['completed_case_count']}/4 个；"
            f"记录 {report['target_replay_evaluations']} 次目标重放。"
        ),
        "",
        "## 数据结果",
        "",
        "| 案例 | 场景簇 | 时刻 | 节点 | 原生差值 (pu) | 紧容差最大漂移 (pu) | 紧容差平台差 (pu) | 案例判定 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for case in report["cases"]:
        assessment = case["assessment"]
        maximum_drift = max(assessment["native_to_tight_drift_pu"].values())
        lines.append(
            "| "
            f"{case['pair_id']} | {case['scenario_cluster']} | "
            f"{case['selection']['selected_slot']} | {case['selection']['metric_id']} | "
            f"{assessment['native_replay_abs_diff_pu']:.12g} | "
            f"{maximum_drift:.12g} | "
            f"{assessment['tight_plateau_drift_pu']:.12g} | "
            f"{assessment['case_decision']} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 本检查只复核归档失效时刻，不是完整96时段重跑，也不重新优化 EV 调度轨迹。",
            "- 三种设置使用彼此独立的 OpenDSS 上下文，并复现相同的归档求解前状态；内部预热求解次数未作为目标重放次数报告。",
            "- 求解容差不是电压误差界；这里比较的是同一节点最终电压值的实际漂移。",
            "- 本结果不改变N0的6/12计数；N0 的 `1e-5 pu` 护栏算术仍然有效。",
            "- 本结果不代表所有场景、完整轨迹或其他馈线均通过。",
            "- 本检查不授权正式V2.1，且 `line_thermal_in_scope=false`。",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_report(
    config: Mapping[str, Any],
    source: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    paths: Sequence[Path],
    gate: Mapping[str, Any],
    integrity: Mapping[str, Any],
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hash_rows = _case_hash_rows(config, artifacts, paths, root)
    report = {
        "protocol_version": config["protocol_version"],
        "decision": gate["decision"],
        "source_evidence_commit": config["source_evidence_commit"],
        "source_n0_commit": config["source_n0_commit"],
        "runtime_version": source["runtime_version"],
        "selected_pair_ids": deepcopy(config["selected_pair_ids"]),
        "completed_pair_ids": [artifact["pair_id"] for artifact in artifacts],
        "selected_case_count": config["expected_counts"]["selected_cases"],
        "completed_case_count": gate["completed_case_count"],
        "stable_case_count": gate["stable_case_count"],
        "sensitive_case_count": gate["sensitive_case_count"],
        "target_replay_evaluations": gate["target_replay_evaluations"],
        "internal_setup_solve_count": "NOT_REPORTED",
        "solver_settings": deepcopy(config["solver_settings"]),
        "thresholds": deepcopy(config["thresholds"]),
        "cases": [
            {
                "pair_id": artifact["pair_id"],
                "scenario_cluster": artifact["scenario_cluster"],
                "selection": deepcopy(artifact["selection"]),
                "observations": deepcopy(artifact["observations"]),
                "assessment": deepcopy(artifact["assessment"]),
            }
            for artifact in artifacts
        ],
        "case_artifact_hashes": {
            row["pair_id"]: row["sha256"]
            for row in hash_rows
            if row["kind"] == "replay_case_artifact"
        },
        "source_integrity": {
            key: deepcopy(value)
            for key, value in integrity.items()
            if key != "code_provenance"
        },
        "code_provenance": deepcopy(integrity["code_provenance"]),
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
        "scope": {
            "fixed_ev_schedule": True,
            "archived_witness_slot_only": True,
            "full_96_slot_replay": False,
            "three_phase_reoptimization": False,
            "independent_scenario_validation": False,
        },
    }
    return report, hash_rows


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
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


def _verify_existing(
    paths: Mapping[str, Path], outputs: Mapping[str, bytes]
) -> dict[str, Any]:
    errors: list[str] = []
    for key in _OUTPUT_KEYS:
        path = paths[key]
        if not path.is_file():
            errors.append(f"{path}: existing artifact is missing")
        elif path.read_bytes() != outputs[key]:
            errors.append(f"{path}: byte comparison failed")
    return {
        "mode": "verify-existing",
        "verified": not errors,
        "errors": errors,
        "exit_code": 0 if not errors else 1,
    }


def evaluate_numerical_certainty_replay(
    repo_root: str | Path,
    *,
    integrity_verifier: Callable[..., Mapping[str, Any]] | None = None,
    verify_existing: bool = False,
) -> dict[str, Any]:
    """Build or byte-verify the deterministic N1 replay evidence package."""

    root = Path(repo_root).resolve(strict=True)
    config = load_replay_config(root)
    source = load_replay_source(root, config)
    artifacts, case_paths, gate = _load_case_artifacts(root, config)
    verifier = (
        verify_evaluator_integrity
        if integrity_verifier is None
        else integrity_verifier
    )
    integrity = _validated_integrity(
        verifier(root, config, artifacts), replay_count=len(artifacts)
    )
    report, hash_rows = _build_report(
        config,
        source,
        artifacts,
        case_paths,
        gate,
        integrity,
        root,
    )
    outputs = {
        "report_json": canonical_json_bytes(report) + b"\n",
        "report_markdown": _render_markdown(report),
        "report_csv": _csv_bytes(_REPORT_COLUMNS, _report_rows(artifacts)),
        "hashes_csv": _csv_bytes(_HASH_COLUMNS, hash_rows),
    }
    paths = _output_paths(root, config)
    if verify_existing:
        outcome = _verify_existing(paths, outputs)
        outcome["decision"] = report["decision"]
        return outcome
    for key in _OUTPUT_KEYS:
        _atomic_write_bytes(paths[key], outputs[key])
    return {
        "mode": "write",
        "report": report,
        "artifacts": [str(paths[key]) for key in _OUTPUT_KEYS],
        "exit_code": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the D1-R-Lite N1 numerical-certainty replay"
    )
    parser.add_argument("--repo-root", type=Path, default=_REPO_FROM_SCRIPT)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = evaluate_numerical_certainty_replay(
            args.repo_root, verify_existing=args.verify_existing
        )
    except Exception as exc:
        outcome = {
            "mode": "verify-existing" if args.verify_existing else "write",
            "verified": False if args.verify_existing else None,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "exit_code": 1,
        }
    print(
        json.dumps(
            outcome,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return int(outcome["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
