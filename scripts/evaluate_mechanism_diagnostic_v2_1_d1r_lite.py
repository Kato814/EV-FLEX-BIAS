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
import csv
import hashlib
import io
import json
import subprocess
import tempfile
from typing import Any

from evflex.mechanism_diagnostic import canonical_json_bytes, strict_json_file
from evflex.mechanism_diagnostic_d1r_lite import (
    final_gate,
    load_lite_config,
    load_lite_manifest,
    stage_a_gate,
    validate_lite_case_artifact,
    verify_lite_sources,
)


_OUTPUT_KEYS = ("audit_csv", "report_json", "report_markdown", "hashes_csv")
_AUDIT_COLUMNS = (
    "pair_id",
    "stage",
    "execution_order",
    "scenario_cluster",
    "sequence_index",
    "audit_point",
    "source_evaluation_id",
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
    "audited_schedule_sha256",
)
_HASH_COLUMNS = ("pair_id", "stage", "status", "path", "sha256")
_LITE_CODE_PATHS = (
    "config/mechanism_diagnostic_v2_1_d1r_lite.json",
    "manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv",
    "src/evflex/mechanism_diagnostic_d1r_lite.py",
    "scripts/run_mechanism_diagnostic_v2_1_d1r_lite.py",
    "scripts/evaluate_mechanism_diagnostic_v2_1_d1r_lite.py",
)


def _rooted(repo_root: Path, relative: str, label: str) -> Path:
    root = repo_root.resolve(strict=False)
    target = (root / relative).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"D1-R-Lite evaluator {label} escapes repository root")
    return target


def _case_path(
    root: Path, config: Mapping[str, Any], pair_id: str
) -> Path:
    relative = config["artifact_names"]["case_artifact_pattern"].format(
        pair_id=pair_id
    )
    return _rooted(root, relative, "case path")


def _output_paths(
    root: Path, config: Mapping[str, Any]
) -> dict[str, Path]:
    return {
        key: _rooted(
            root, str(config["artifact_names"][key]), f"{key} path"
        )
        for key in _OUTPUT_KEYS
    }


def _resolve_lite_code_commit(
    root: Path,
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> str:
    result = subprocess_runner(
        ["git", "log", "-1", "--format=%H", "--", *_LITE_CODE_PATHS],
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
        raise ValueError("could not resolve the D1-R-Lite production code commit")
    return commit


def _verify_archived_evaluator(
    root: Path,
    relative: str,
    label: str,
    *,
    subprocess_runner: Callable[..., Any],
) -> None:
    script = root / relative
    if not script.is_file():
        raise ValueError(f"archived {label} verifier is missing")
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
        raise ValueError(f"archived {label} verifier failed: {detail}")


def verify_evaluator_integrity(
    repo_root: str | Path,
    config: Mapping[str, Any],
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Verify frozen dependencies, predecessors, and clean production code."""

    root = Path(repo_root).resolve(strict=True)
    if any(os.environ.get(name) != "1" for name in _THREAD_VARIABLES):
        raise ValueError("D1-R-Lite evaluator thread caps are not all one")
    verify_lite_sources(root, config)
    _verify_archived_evaluator(
        root,
        "scripts/evaluate_mechanism_diagnostic_v2_1.py",
        "D1",
        subprocess_runner=subprocess_runner,
    )
    _verify_archived_evaluator(
        root,
        "scripts/evaluate_pilot_gate_v2_1.py",
        "pilot",
        subprocess_runner=subprocess_runner,
    )
    status = subprocess_runner(
        ["git", "status", "--porcelain", "--", *_LITE_CODE_PATHS],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise ValueError("could not inspect D1-R-Lite production code state")
    if status.stdout.strip():
        raise ValueError("D1-R-Lite production code paths have uncommitted changes")
    commit = _resolve_lite_code_commit(
        root, subprocess_runner=subprocess_runner
    )
    hashes: dict[str, str] = {}
    for relative in _LITE_CODE_PATHS:
        path = _rooted(root, relative, "code path")
        if not path.is_file():
            raise ValueError(f"D1-R-Lite production code is missing: {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "frozen_sources_verified": True,
        "archived_d1_verified": True,
        "archived_pilot_verified": True,
        "code_provenance": {
            "d1r_lite_code_commit": commit,
            "d1r_lite_code_paths_clean": True,
            "file_sha256": hashes,
        },
    }


def validate_evaluator_inventory(
    repo_root: str | Path,
    config: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> None:
    root = Path(repo_root).resolve(strict=False)
    lock = _rooted(
        root, str(config["artifact_names"]["run_lock"]), "run lock"
    )
    if lock.exists():
        raise ValueError(f"D1-R-Lite run lock requires inspection: {lock}")
    attempt = _rooted(
        root,
        str(config["artifact_names"]["attempt_pattern"]).format(pair_id="01"),
        "attempt path",
    )
    if attempt.parent.exists():
        attempts = sorted(attempt.parent.iterdir())
        if attempts:
            raise ValueError(
                f"D1-R-Lite attempt state requires inspection: {attempts[0]}"
            )
    allowed = {
        _case_path(root, config, str(case["pair_id"])).name for case in cases
    }
    case_directory = _case_path(root, config, "01").parent
    if case_directory.exists():
        for path in sorted(case_directory.iterdir()):
            if not path.is_file() or path.name not in allowed:
                raise ValueError(
                    f"unexpected D1-R-Lite case state requires inspection: {path}"
                )
    for path in _output_paths(root, config).values():
        if path.parent.exists():
            temporaries = list(path.parent.glob(f"{path.name}*.tmp*"))
            temporaries.extend(path.parent.glob(f".{path.name}.*.tmp"))
            if temporaries:
                raise ValueError(
                    f"D1-R-Lite evaluator temporary requires inspection: "
                    f"{sorted(temporaries)[0]}"
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


def _load_terminal_sequence(
    root: Path,
    config: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    terminal: list[dict[str, Any]] = []
    missing: list[str] = []
    missing_seen = False
    failure_seen = False
    for case in cases:
        pair_id = str(case["pair_id"])
        path = _case_path(root, config, pair_id)
        if not path.is_file():
            missing.append(pair_id)
            missing_seen = True
            continue
        if missing_seen or failure_seen:
            raise ValueError(
                "D1-R-Lite terminal sequence is not a continuous prefix"
            )
        artifact = strict_json_file(path)
        validate_lite_case_artifact(artifact, case, config)
        terminal.append(artifact)
        if artifact["status"] != "SUCCESS":
            failure_seen = True
    if not terminal:
        raise ValueError("D1-R-Lite terminal sequence is empty")
    return terminal, missing


def _classify_terminal(
    terminal: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[str, bool, dict[str, Any] | None, str | None]:
    last = terminal[-1]
    stage_a_decision: str | None = None
    if len(terminal) > 4:
        stage_result = stage_a_gate(terminal[:4], cases, config)
        stage_a_decision = str(stage_result["decision"])
        if stage_a_decision != "EXPAND_STAGE_B":
            raise ValueError("D1-R-Lite Stage B exists before expansion gate")
    if last["status"] != "SUCCESS":
        return str(last["status"]), False, None, stage_a_decision
    if len(terminal) == 4:
        gate = stage_a_gate(terminal, cases, config)
        stage_a_decision = str(gate["decision"])
        if stage_a_decision != "STOP_HETEROGENEOUS_SCREEN":
            raise ValueError(
                "D1-R-Lite terminal sequence is incomplete after expansion"
            )
        return stage_a_decision, True, gate, stage_a_decision
    if len(terminal) == len(cases):
        gate = final_gate(terminal, cases, config)
        return str(gate["decision"]), True, gate, "EXPAND_STAGE_B"
    raise ValueError(
        "D1-R-Lite terminal sequence is incomplete without terminal failure"
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
            families = ";".join(str(row["constraint_family"]) for row in violations)
            objects = ";".join(str(row["object_id"]) for row in violations)
    return {
        "pair_id": artifact["pair_id"],
        "stage": artifact["stage"],
        "execution_order": artifact["execution_order"],
        "scenario_cluster": artifact["scenario_cluster"],
        "sequence_index": audit["sequence_index"],
        "audit_point": audit["audit_point"],
        "source_evaluation_id": audit["source_evaluation_id"],
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
        "audited_schedule_sha256": audit["audited_schedule_sha256"],
    }


def _hash_rows(
    root: Path,
    config: Mapping[str, Any],
    terminal: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in terminal:
        pair_id = str(artifact["pair_id"])
        path = _case_path(root, config, pair_id)
        rows.append(
            {
                "pair_id": pair_id,
                "stage": artifact["stage"],
                "status": artifact["status"],
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return rows


def _render_markdown(report: Mapping[str, Any]) -> bytes:
    qualifying = report.get("qualifying_families")
    candidate_text = (
        "、".join(str(item) for item in qualifying)
        if isinstance(qualifying, list) and qualifying
        else "无"
    )
    lines = [
        "# EV-FLEX-BIAS V2.1 D1-R-Lite 边界机制筛查报告",
        "",
        f"- 结论：`{report['decision']}`",
        f"- 已验证案例：{report['actual_cases']}；目标审计：{report['actual_target_audits']}。",
        f"- 达标约束族：{candidate_text}",
        "- 旧 pilot 结论保持为 `NO_GO_REASSESS_BROAD_TOPIC`。",
        "- 本筛查不授权正式 V2.1，且没有启动正式 V2.1。",
        "",
        "## 结论解释",
        "",
    ]
    decision = str(report["decision"])
    if decision == "STOP_HETEROGENEOUS_SCREEN":
        lines.append(
            "4 个代表场景、8 次目标审计中，没有约束族达到预冻结的 3/4 扩展门槛，因此按计划停止，没有执行 Stage B。"
        )
    elif decision == "COMMON_CANDIDATE_CONFOUNDED":
        lines.append(
            "在 12 个案例中，上述约束族达到至少 8/12 案例且覆盖至少 3/4 场景簇的共同候选门槛。"
        )
    elif decision == "HETEROGENEOUS_12_CASES":
        lines.append(
            "12 个案例已完成，但没有约束族同时达到 8/12 案例和 3/4 场景簇门槛。"
        )
    else:
        lines.append(
            "筛查在实现或运行终态失败处停止；本报告只覆盖严格验证的连续证据前缀。"
        )
    lines.extend(
        [
            "",
            "## 证据边界",
            "",
            "本次精简筛查删除了 IEEE13 对照、全报价审计和约束数量匹配，以压缩工作量。",
            "证据仅适用于归档样本中的 LV906 固定 EV 调度轨迹及其边界外 0.002 插值点。",
            "本研究未进行三相重新优化，因此不能声称重新调度仍不可行。",
            "所有结果保持 `line_thermal_in_scope=false`，因此不包含线路热约束结论。",
            "达到共同候选门槛只表示样本内重复出现，仍受场景和固定轨迹混杂影响，不是唯一机制或因果机制。",
            "结果不能外推为所有馈线、所有运行场景或所有 EV 调度策略的普遍结论。",
            "无论结果为何，均不授权正式 V2.1；正式重跑仍需另行决策。",
        ]
    )
    missing = report.get("missing_pair_ids")
    if isinstance(missing, list) and missing:
        lines.extend(["", "## 未执行案例", "", "、".join(map(str, missing))])
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_outputs(
    root: Path,
    config: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    integrity: Mapping[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any], bool]:
    terminal, missing = _load_terminal_sequence(root, config, cases)
    decision, completed, gate, stage_a_decision = _classify_terminal(
        terminal, cases, config
    )
    audit_rows = [
        _audit_row(artifact, audit)
        for artifact in terminal
        for audit in artifact["audits"]
    ]
    terminal_failure = (
        deepcopy(terminal[-1].get("failure")) if not completed else None
    )
    report = {
        "artifact": "EV-FLEX-BIAS-V2.1-D1R-LITE-REPORT",
        "protocol_version": config["protocol_version"],
        "decision": decision,
        "diagnostic_completed": completed,
        "stage_a_decision": stage_a_decision,
        "expected_stage_a_cases": config["expected_counts"]["stage_a_cases"],
        "expected_stage_a_target_audits": config["expected_counts"][
            "stage_a_audits"
        ],
        "maximum_cases": config["expected_counts"]["maximum_cases"],
        "maximum_target_audits": config["expected_counts"]["maximum_audits"],
        "actual_cases": len(terminal),
        "actual_target_audits": len(audit_rows),
        "terminal_case_ids": [artifact["pair_id"] for artifact in terminal],
        "successful_case_ids": [
            artifact["pair_id"]
            for artifact in terminal
            if artifact["status"] == "SUCCESS"
        ],
        "missing_pair_ids": missing,
        "terminal_failure": terminal_failure,
        "family_support": deepcopy(gate["family_support"]) if gate else [],
        "qualifying_families": (
            deepcopy(gate["qualifying_families"]) if gate else []
        ),
        "threshold": deepcopy(gate["threshold"]) if gate else None,
        "removed_components": [
            "IEEE13_CONTROLS",
            "FULL_OFFER_AUDITS",
            "CONSTRAINT_COUNT_MATCHING",
            "RELATIVE_STRESS_COMPARISON",
        ],
        "limitations": {
            "lv906_fixed_trajectory_boundary_only": True,
            "three_phase_reoptimization_in_scope": False,
            "line_thermal_in_scope": False,
            "cross_feeder_causality_supported": False,
            "unique_mechanism_supported": False,
            "universal_network_claim_supported": False,
        },
        "adapter_identity": deepcopy(config["adapter_identity"]),
        "archived_pilot_decision": "NO_GO_REASSESS_BROAD_TOPIC",
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "source_commit": config["source_commit"],
        "source_integrity": {
            key: deepcopy(value)
            for key, value in integrity.items()
            if key != "code_provenance"
        },
        "code_provenance": deepcopy(integrity["code_provenance"]),
    }
    outputs = {
        "audit_csv": _csv_bytes(_AUDIT_COLUMNS, audit_rows),
        "report_json": canonical_json_bytes(report) + b"\n",
        "report_markdown": _render_markdown(report),
        "hashes_csv": _csv_bytes(
            _HASH_COLUMNS, _hash_rows(root, config, terminal)
        ),
    }
    return outputs, report, completed


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


def _validated_integrity(value: Mapping[str, Any]) -> dict[str, Any]:
    integrity = dict(value)
    provenance = integrity.get("code_provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("D1-R-Lite code provenance is missing")
    commit = provenance.get("d1r_lite_code_commit")
    hashes = provenance.get("file_sha256")
    if (
        integrity.get("frozen_sources_verified") is not True
        or integrity.get("archived_d1_verified") is not True
        or integrity.get("archived_pilot_verified") is not True
        or provenance.get("d1r_lite_code_paths_clean") is not True
        or not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or not isinstance(hashes, Mapping)
        or not hashes
        or any(
            not isinstance(item, str)
            or len(item) != 64
            or any(character not in "0123456789abcdef" for character in item)
            for item in hashes.values()
        )
    ):
        raise ValueError("D1-R-Lite evaluator source integrity was not verified")
    return integrity


def evaluate_mechanism_diagnostic_d1r_lite(
    repo_root: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
    cases: Sequence[Mapping[str, Any]] | None = None,
    integrity_verifier: Callable[
        [Path, Mapping[str, Any]], Mapping[str, Any]
    ]
    | None = None,
    verify_existing: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve(strict=False)
    loaded_config = (
        load_lite_config(root) if config is None else deepcopy(dict(config))
    )
    loaded_cases = (
        load_lite_manifest(root)
        if cases is None
        else [deepcopy(dict(case)) for case in cases]
    )
    validate_evaluator_inventory(root, loaded_config, loaded_cases)
    verifier = (
        verify_evaluator_integrity
        if integrity_verifier is None
        else integrity_verifier
    )
    integrity = _validated_integrity(verifier(root, loaded_config))
    outputs, report, completed = _build_outputs(
        root, loaded_config, loaded_cases, integrity
    )
    paths = _output_paths(root, loaded_config)
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
        "exit_code": 0 if completed else 1,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the bounded V2.1 D1-R-Lite screen"
    )
    parser.add_argument("--repo-root", type=Path, default=_REPO_FROM_SCRIPT)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = evaluate_mechanism_diagnostic_d1r_lite(
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
            allow_nan=False,
        )
    )
    return int(outcome["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
