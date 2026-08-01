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
import csv
import hashlib
import io
import json
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from evflex.mechanism_diagnostic import (
    assess_mechanism_gate,
    canonical_json_bytes,
    load_mechanism_config,
    load_pair_manifest,
    relative_stress_evidence,
    strict_json_file,
    validate_pair_artifact,
    verify_frozen_sources,
)


_OUTPUT_KEYS = ("audit_csv", "report_json", "report_markdown", "hashes_csv")
_AUDIT_COLUMNS = (
    "pair_id",
    "scenario_cluster",
    "sequence_index",
    "role",
    "audit_point",
    "source_evaluation_id",
    "source_work_unit_id",
    "feeder",
    "direction",
    "duration_min",
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
    "audit_input_sha256",
)
_HASH_COLUMNS = ("pair_id", "status", "path", "sha256")


def _rooted(repo_root: Path, relative: str) -> Path:
    root = repo_root.resolve(strict=False)
    target = (root / relative).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"D1 evaluator path escapes repository root: {relative}")
    return target


def _pair_path(
    root: Path, config: Mapping[str, Any], pair_id: str
) -> Path:
    relative = config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id=pair_id
    )
    return _rooted(root, relative)


def _output_paths(
    root: Path, config: Mapping[str, Any]
) -> dict[str, Path]:
    return {
        key: _rooted(root, str(config["artifact_names"][key]))
        for key in _OUTPUT_KEYS
    }


def verify_evaluator_integrity(
    repo_root: str | Path,
    config: Mapping[str, Any],
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Read-only verification of frozen source bytes and the archived gate."""

    root = Path(repo_root).resolve(strict=True)
    if any(os.environ.get(name) != "1" for name in _THREAD_VARIABLES):
        raise ValueError("D1 evaluator numeric thread caps are not all set to one")
    verify_frozen_sources(root, config)
    archived = root / "scripts" / "evaluate_pilot_gate_v2_1.py"
    if not archived.is_file():
        raise ValueError("archived pilot verifier is missing")
    environment = os.environ.copy()
    environment.update(THREAD_ENVIRONMENT)
    environment["PYTHONPATH"] = str(root / "src")
    result = subprocess_runner(
        [sys.executable, str(archived), "--verify-existing"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no verifier output").strip()
        raise ValueError(f"archived pilot verifier failed: {detail}")
    pilot_path = _rooted(root, str(config["pilot_py"]["path"]))
    return {
        "frozen_sources_verified": True,
        "archived_pilot_verified": True,
        "source_commit": config["source_commit"],
        "pilot_py_sha256": hashlib.sha256(pilot_path.read_bytes()).hexdigest(),
    }


def validate_evaluator_inventory(
    repo_root: str | Path,
    config: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any]],
) -> None:
    root = Path(repo_root).resolve(strict=False)
    lock = _rooted(root, str(config["artifact_names"]["run_lock"]))
    if lock.exists():
        raise ValueError(f"D1 run lock requires inspection: {lock}")

    attempt_example = _rooted(
        root,
        str(config["artifact_names"]["attempt_pattern"]).format(pair_id="01"),
    )
    if attempt_example.parent.exists():
        attempts = sorted(
            path for path in attempt_example.parent.iterdir() if path.is_file()
        )
        if attempts:
            raise ValueError(f"D1 attempt state requires inspection: {attempts[0]}")

    allowed = {
        _pair_path(root, config, str(pair["pair_id"])).name for pair in pairs
    }
    pair_directory = _pair_path(root, config, "01").parent
    if pair_directory.exists():
        for path in sorted(pair_directory.iterdir()):
            if not path.is_file():
                raise ValueError(f"unexpected D1 pair entry requires inspection: {path}")
            if path.name not in allowed:
                raise ValueError(f"unexpected D1 pair file requires inspection: {path}")
            if ".tmp" in path.name:
                raise ValueError(f"D1 pair temporary requires inspection: {path}")

    for path in _output_paths(root, config).values():
        if path.parent.exists():
            temporaries = sorted(path.parent.glob(f"{path.name}*.tmp*"))
            temporaries.extend(
                sorted(path.parent.glob(f".{path.name}.*.tmp"))
            )
            if temporaries:
                raise ValueError(
                    f"D1 evaluator temporary requires inspection: {temporaries[0]}"
                )

    formal_directory = root / "results" / "formal_v2_1"
    formal_reports = (
        list((root / "reports").glob("formal_v2_1*"))
        if (root / "reports").exists()
        else []
    )
    if formal_directory.exists() or formal_reports:
        offending = formal_directory if formal_directory.exists() else formal_reports[0]
        raise ValueError(f"formal V2.1 output is forbidden during D1: {offending}")


def _load_terminal_sequence(
    root: Path,
    config: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    terminal: list[dict[str, Any]] = []
    missing: list[str] = []
    failure_seen = False
    missing_seen = False
    for pair in pairs:
        pair_id = str(pair["pair_id"])
        path = _pair_path(root, config, pair_id)
        if not path.is_file():
            missing.append(pair_id)
            missing_seen = True
            continue
        if missing_seen:
            raise ValueError("D1 terminal sequence has a pair after a missing predecessor")
        if failure_seen:
            raise ValueError("D1 terminal sequence has a pair after terminal failure")
        artifact = strict_json_file(path)
        validate_pair_artifact(artifact, pair, config)
        terminal.append(artifact)
        if artifact["status"] != "SUCCESS":
            failure_seen = True
    if len(terminal) == len(pairs):
        if all(artifact["status"] == "SUCCESS" for artifact in terminal):
            return terminal, missing
        if terminal[-1]["status"] != "SUCCESS":
            return terminal, missing
        raise ValueError("D1 terminal sequence contains a non-final failure")
    if terminal and terminal[-1]["status"] != "SUCCESS":
        return terminal, missing
    raise ValueError(
        "D1 terminal sequence is incomplete without a terminal failure artifact"
    )


def _csv_bytes(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(columns),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    return stream.getvalue().encode("utf-8")


def _audit_row(
    artifact: Mapping[str, Any], audit: Mapping[str, Any]
) -> dict[str, Any]:
    selected = audit.get("selected_slot")
    selected_slot: Any = ""
    families = ""
    objects = ""
    if isinstance(selected, Mapping):
        selected_slot = selected.get("slot")
        violations = selected.get("simultaneous_violations")
        if isinstance(violations, list):
            families = ";".join(
                str(row["constraint_family"])
                for row in violations
                if isinstance(row, Mapping)
            )
            objects = ";".join(
                str(row["object_id"])
                for row in violations
                if isinstance(row, Mapping)
            )
    return {
        "pair_id": artifact["pair_id"],
        "scenario_cluster": artifact["scenario_cluster"],
        "sequence_index": audit["sequence_index"],
        "role": audit["role"],
        "audit_point": audit["audit_point"],
        "source_evaluation_id": audit["source_evaluation_id"],
        "source_work_unit_id": audit["source_work_unit_id"],
        "feeder": audit["feeder"],
        "direction": audit["direction"],
        "duration_min": audit["duration_min"],
        "alpha_label": audit["alpha_label"],
        "feasible": str(audit["feasible"]).lower(),
        "checked_intervals": audit["checked_intervals"],
        "complete_coverage": str(audit["complete_coverage"]).lower(),
        "failure_class": audit["failure_class"],
        "first_failure_slot": (
            "" if audit["first_failure_slot"] is None else audit["first_failure_slot"]
        ),
        "explicit_physical_witness": str(
            audit["explicit_physical_witness"]
        ).lower(),
        "physical_violation_checks": audit["physical_violation_checks"],
        "numerical_failure_checks": audit["numerical_failure_checks"],
        "vmin": audit["vmin"],
        "vmax": audit["vmax"],
        "vufmax": audit["vufmax"],
        "transformer_loading_max": audit["transformer_loading_max"],
        "feeder_loading_max": audit["feeder_loading_max"],
        "selected_slot": selected_slot,
        "simultaneous_violation_families": families,
        "simultaneous_violation_objects": objects,
        "audit_input_sha256": audit["audit_input_sha256"],
    }


def _hash_rows(
    root: Path,
    config: Mapping[str, Any],
    terminal: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in terminal:
        pair_id = str(artifact["pair_id"])
        path = _pair_path(root, config, pair_id)
        relative = path.relative_to(root).as_posix()
        rows.append(
            {
                "pair_id": pair_id,
                "status": artifact["status"],
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return rows


def _render_markdown(report: Mapping[str, Any]) -> bytes:
    decision = str(report["decision"])
    completed = bool(report["diagnostic_completed"])
    candidates = [
        str(item["constraint_family"])
        for item in report.get("candidate_families", [])
        if isinstance(item, Mapping)
    ]
    candidate_text = "、".join(candidates) if candidates else "无"
    lines = [
        "# EV-FLEX-BIAS V2.1-D1 机制诊断报告",
        "",
        f"- 诊断结论：`{decision}`",
        f"- 结构门是否通过：`{str(report['structural_gate_passed']).lower()}`",
        f"- 共同候选约束族：{candidate_text}",
        "- 旧 pilot 结论保持为 `NO_GO_REASSESS_BROAD_TOPIC`。",
        "- 本诊断不授权正式 V2.1，也未启动正式 V2.1。",
        "",
        "## 完成状态",
        "",
        (
            "D1 已完成 12 对、72 次目标审计。"
            if completed
            else "D1 未完成；本报告只覆盖终端文件中连续且已验证的审计前缀。"
        ),
        f"现有终端对：{report['actual_terminal_pairs']}/12；审计行：{report['actual_audits']}/72。",
        "",
        "## 证据边界",
        "",
        "本诊断只研究固定 EV 调度轨迹在既有三相网络模型中的传递结果，未进行三相重新优化；因此不能推出重新调度后聚合灵活性仍不可行。",
        "所有结果均保留 `line_thermal_in_scope=false`，不能据此声称线路热安全已经验证。",
        "IEEE13 仅是时间、方向和时长匹配的设计单元对照，不是因果匹配。",
        "四个分组是场景簇，不是独立重复。",
        "约束数量匹配只衡量检测敏感性，既不证明也不排除数量效应。",
        "相对压力混杂保持为 `RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR`，全局和分相比值均为 null。",
        "共同候选只表示达到预冻结筛选门槛且仍受混杂影响，不是唯一机制或因果机制。",
        "",
        "## 决策边界",
        "",
        "无论本次结果为共同候选、异质机制或停止实现，都不授权正式 V2.1。后续确认实验必须另行冻结方案后再决定是否执行。",
    ]
    missing = report.get("missing_pair_ids")
    if isinstance(missing, list) and missing:
        lines.extend(
            [
                "",
                "## 缺失配对",
                "",
                "、".join(str(item) for item in missing),
            ]
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_artifacts(
    root: Path,
    config: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any], bool]:
    terminal, missing = _load_terminal_sequence(root, config, pairs)
    audit_rows = [
        _audit_row(artifact, audit)
        for artifact in terminal
        for audit in artifact["audits"]
    ]
    all_success = bool(
        len(terminal) == len(pairs)
        and all(artifact["status"] == "SUCCESS" for artifact in terminal)
    )
    if all_success:
        assessment = assess_mechanism_gate(terminal, config)
        decision = str(assessment["decision"])
        structural_passed = bool(assessment["structural_gate_passed"])
        terminal_failure = None
    else:
        last = terminal[-1]
        decision = str(last["status"])
        structural_passed = False
        terminal_failure = deepcopy(last["failure"])
        assessment = {
            "structural_checks": [],
            "candidate_families": [],
            "count_match_rows": [],
            "count_match_classifications": [],
            "relative_stress": relative_stress_evidence(),
            "limitations": {
                "fixed_schedule_transfer_only": True,
                "three_phase_reoptimization_in_scope": False,
                "line_thermal_in_scope": False,
                "matched_controls_are_causal_matches": False,
                "scenario_clusters_are_independent_repetitions": False,
                "count_matching_proves_or_excludes_count_effect": False,
            },
        }
    valid_decision = decision in {
        "VALID_HETEROGENEOUS",
        "COMMON_CANDIDATE_CONFOUNDED",
    }
    diagnostic_completed = bool(all_success and structural_passed and valid_decision)
    report = {
        "artifact": "EV-FLEX-BIAS-V2.1-D1-MECHANISM-REPORT",
        "protocol_version": config["protocol_version"],
        "decision": decision,
        "diagnostic_completed": diagnostic_completed,
        "structural_gate_passed": structural_passed,
        "structural_checks": deepcopy(assessment["structural_checks"]),
        "expected_pairs": config["expected_counts"]["pairs"],
        "actual_terminal_pairs": len(terminal),
        "terminal_pair_ids": [artifact["pair_id"] for artifact in terminal],
        "successful_pair_ids": [
            artifact["pair_id"]
            for artifact in terminal
            if artifact["status"] == "SUCCESS"
        ],
        "missing_pair_ids": missing,
        "expected_audits": config["expected_counts"]["audits"],
        "actual_audits": len(audit_rows),
        "terminal_failure": terminal_failure,
        "candidate_families": deepcopy(assessment["candidate_families"]),
        "count_match_rows": deepcopy(assessment["count_match_rows"]),
        "count_match_classifications": deepcopy(
            assessment["count_match_classifications"]
        ),
        "relative_stress": deepcopy(assessment["relative_stress"]),
        "limitations": deepcopy(assessment["limitations"]),
        "archived_pilot_decision": "NO_GO_REASSESS_BROAD_TOPIC",
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "source_commit": config["source_commit"],
        "pilot_py_sha256": config["pilot_py"]["sha256"],
        "source_integrity": deepcopy(dict(integrity)),
    }
    hash_rows = _hash_rows(root, config, terminal)
    artifacts = {
        "audit_csv": _csv_bytes(_AUDIT_COLUMNS, audit_rows),
        "report_json": canonical_json_bytes(report) + b"\n",
        "report_markdown": _render_markdown(report),
        "hashes_csv": _csv_bytes(_HASH_COLUMNS, hash_rows),
    }
    return artifacts, report, valid_decision and structural_passed


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


def _verify_existing(
    paths: Mapping[str, Path], artifacts: Mapping[str, bytes]
) -> dict[str, Any]:
    errors: list[str] = []
    for key in _OUTPUT_KEYS:
        path = paths[key]
        if not path.is_file():
            errors.append(f"{path}: existing artifact is missing")
        elif path.read_bytes() != artifacts[key]:
            errors.append(f"{path}: byte comparison failed")
    return {
        "mode": "verify-existing",
        "verified": not errors,
        "errors": errors,
        "exit_code": 0 if not errors else 1,
    }


def evaluate_mechanism_diagnostic(
    repo_root: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
    pairs: Sequence[Mapping[str, Any]] | None = None,
    integrity_verifier: Callable[
        [Path, Mapping[str, Any]], Mapping[str, Any]
    ]
    | None = None,
    verify_existing: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=False)
    loaded_config = (
        load_mechanism_config(root) if config is None else deepcopy(dict(config))
    )
    loaded_pairs = (
        load_pair_manifest(root)
        if pairs is None
        else [deepcopy(dict(pair)) for pair in pairs]
    )
    validate_evaluator_inventory(root, loaded_config, loaded_pairs)
    verifier = verify_evaluator_integrity if integrity_verifier is None else integrity_verifier
    integrity = dict(verifier(root, loaded_config))
    if (
        integrity.get("frozen_sources_verified") is not True
        or integrity.get("archived_pilot_verified") is not True
    ):
        raise ValueError("D1 evaluator source integrity was not verified")
    artifacts, report, valid_decision = _build_artifacts(
        root, loaded_config, loaded_pairs, integrity
    )
    paths = _output_paths(root, loaded_config)
    if verify_existing:
        outcome = _verify_existing(paths, artifacts)
        outcome["decision"] = report["decision"]
        return outcome
    for key in _OUTPUT_KEYS:
        _atomic_write_bytes(paths[key], artifacts[key])
    return {
        "mode": "write",
        "report": report,
        "artifacts": [str(paths[key]) for key in _OUTPUT_KEYS],
        "exit_code": 0 if valid_decision else 1,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen V2.1 D1 mechanism diagnostic"
    )
    parser.add_argument("--repo-root", type=Path, default=_REPO_FROM_SCRIPT)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = evaluate_mechanism_diagnostic(
            args.repo_root,
            verify_existing=args.verify_existing,
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
            allow_nan=False,
        )
    )
    return int(outcome["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
