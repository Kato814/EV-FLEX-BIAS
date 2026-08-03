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


from evflex.mechanism_diagnostic import canonical_json_bytes
from evflex.mechanism_margin_sensitivity_d1r_lite import (
    compute_margin_sensitivity,
    load_margin_config,
    load_margin_source,
    validate_margin_result,
)


_OUTPUT_KEYS = ("report_json", "report_markdown", "report_csv", "hashes_csv")
_REPORT_COLUMNS = (
    "constraint_family",
    "guard_band",
    "guard_band_unit",
    "guard_band_applied",
    "case_count",
    "scenario_cluster_count",
    "metric_witness_count",
    "pair_ids",
    "scenario_clusters",
    "qualifies",
    "decisive",
)
_HASH_COLUMNS = ("kind", "pair_id", "stage", "path", "sha256")
_MARGIN_CODE_PATHS = (
    "config/mechanism_margin_sensitivity_v2_1_d1r_lite.json",
    "src/evflex/mechanism_margin_sensitivity_d1r_lite.py",
    "scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py",
)


def _rooted(root: Path, relative: str, label: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ValueError(f"N0 evaluator {label} must be relative")
    target = (root / path).resolve(strict=False)
    if target != root and root not in target.parents:
        raise ValueError(f"N0 evaluator {label} escapes repository root")
    return target


def _output_paths(
    root: Path, config: Mapping[str, Any]
) -> dict[str, Path]:
    return {
        key: _rooted(root, str(config["artifact_names"][key]), f"{key} path")
        for key in _OUTPUT_KEYS
    }


def _resolve_margin_code_commit(
    root: Path,
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> str:
    result = subprocess_runner(
        ["git", "log", "-1", "--format=%H", "--", *_MARGIN_CODE_PATHS],
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
        raise ValueError("could not resolve the N0 production code commit")
    return commit


def verify_evaluator_integrity(
    repo_root: str | Path,
    config: Mapping[str, Any],
    *,
    subprocess_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Require thread caps and committed, clean N0 production code."""

    root = Path(repo_root).resolve(strict=True)
    if any(os.environ.get(name) != "1" for name in THREAD_ENVIRONMENT):
        raise ValueError("N0 evaluator numeric thread caps are not all one")
    status = subprocess_runner(
        ["git", "status", "--porcelain", "--", *_MARGIN_CODE_PATHS],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise ValueError("could not inspect N0 production code state")
    if status.stdout.strip():
        raise ValueError("N0 production code paths have uncommitted changes")
    commit = _resolve_margin_code_commit(
        root, subprocess_runner=subprocess_runner
    )
    hashes: dict[str, str] = {}
    for relative in _MARGIN_CODE_PATHS:
        path = _rooted(root, relative, "production code path")
        if not path.is_file():
            raise ValueError(f"N0 production code is missing: {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "frozen_source_hashes_verified": True,
        "source_case_hashes_verified": True,
        "source_artifacts_validated": config["total_cases"],
        "code_provenance": {
            "margin_code_commit": commit,
            "margin_code_paths_clean": True,
            "file_sha256": hashes,
        },
    }


def _validated_integrity(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("N0 evaluator integrity result must be a mapping")
    integrity = deepcopy(dict(value))
    provenance = integrity.get("code_provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("N0 evaluator code provenance is missing")
    commit = provenance.get("margin_code_commit")
    hashes = provenance.get("file_sha256")
    if (
        integrity.get("frozen_source_hashes_verified") is not True
        or integrity.get("source_case_hashes_verified") is not True
        or integrity.get("source_artifacts_validated") != 12
        or provenance.get("margin_code_paths_clean") is not True
        or not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or not isinstance(hashes, Mapping)
        or set(hashes) != set(_MARGIN_CODE_PATHS)
        or any(
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in hashes.values()
        )
    ):
        raise ValueError("N0 evaluator source or code integrity was not verified")
    return integrity


def _csv_bytes(
    columns: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=list(columns), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _boolean(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    raise ValueError("expected a Boolean report value")


def _guard_band(value: Any) -> str:
    return format(float(value), ".12g")


def _report_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    decisive = result["decisive_support"]
    return [
        {
            "constraint_family": row["constraint_family"],
            "guard_band": _guard_band(row["guard_band"]),
            "guard_band_unit": row["guard_band_unit"] or "",
            "guard_band_applied": _boolean(row["guard_band_applied"]),
            "case_count": row["case_count"],
            "scenario_cluster_count": row["scenario_cluster_count"],
            "metric_witness_count": row["metric_witness_count"],
            "pair_ids": ";".join(row["pair_ids"]),
            "scenario_clusters": ";".join(row["scenario_clusters"]),
            "qualifies": _boolean(row["qualifies"]),
            "decisive": _boolean(row == decisive),
        }
        for row in result["support"]
    ]


def _hash_rows(
    config: Mapping[str, Any], source: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows = [
        {
            "kind": "frozen_source",
            "pair_id": "",
            "stage": "",
            "path": item["path"],
            "sha256": item["sha256"],
        }
        for item in config["frozen_sources"]
    ]
    source_rows = source.get("hash_rows")
    if not isinstance(source_rows, list) or len(source_rows) != config["total_cases"]:
        raise ValueError("N0 evaluator source case hashes are missing")
    for item in source_rows:
        if not isinstance(item, Mapping):
            raise ValueError("N0 evaluator source case hash row is invalid")
        rows.append(
            {
                "kind": "case_artifact",
                "pair_id": item["pair_id"],
                "stage": item["stage"],
                "path": item["path"],
                "sha256": item["sha256"],
            }
        )
    return rows


def _render_markdown(report: Mapping[str, Any]) -> bytes:
    decisive = report["decisive_support"]
    robust = report["decision"] == "MARGIN_ROBUST_AT_1E5"
    conclusion = (
        "达到冻结门槛，可另行冻结紧容差复算方案；这本身仍不是正式重跑许可。"
        if robust
        else "未达到冻结门槛，应停止在此，不进入紧容差复算或正式 V2.1。"
    )
    lines = [
        "# V2.1 D1-R-Lite N0 裕度敏感性检查",
        "",
        "## 结论",
        "",
        f"- 决策：`{report['decision']}`。",
        (
            "- 在 `1e-5 pu` 下，VMAX 保留 "
            f"**{decisive['case_count']}/12** 个案例、"
            f"**{decisive['scenario_cluster_count']}/4** 个场景簇；"
            "冻结门槛为至少 8 个案例且至少 3 个场景簇。"
        ),
        f"- {conclusion}",
        "",
        "## 各裕度下的支持度",
        "",
        "| 约束族 | 裕度 | 案例数 | 场景簇数 | 指标见证数 | 达到 8 案例/3 簇 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["support"]:
        band = (
            f"{_guard_band(row['guard_band'])} pu"
            if row["guard_band_applied"]
            else "0（仅原始超限）"
        )
        lines.append(
            "| "
            f"{row['constraint_family']} | {band} | {row['case_count']} | "
            f"{row['scenario_cluster_count']} | {row['metric_witness_count']} | "
            f"{'是' if row['qualifies'] else '否'} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 这是对既有 12 个结果的事后敏感性检查，不是独立重复实验。",
            "- 本检查不改变原始 COMMON_CANDIDATE_CONFOUNDED 结论，只判断该候选对小超限量是否敏感。",
            "- `1e-5 pu` 是本次筛查用的数值护栏，不是工程安全裕度，也不等同于 OpenDSS 收敛容差。",
            "- 本次为零次新增潮流计算；没有改变固定 EV 调度轨迹，也没有进行三相重新优化。",
            "- 本结果不授权正式 V2.1，且 `line_thermal_in_scope=false`。",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_outputs(
    result: Mapping[str, Any],
    source: Mapping[str, Any],
    integrity: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    validate_margin_result(result, config)
    report = deepcopy(dict(result))
    report["source_integrity"] = {
        key: deepcopy(value)
        for key, value in integrity.items()
        if key != "code_provenance"
    }
    report["code_provenance"] = deepcopy(integrity["code_provenance"])
    outputs = {
        "report_json": canonical_json_bytes(report) + b"\n",
        "report_markdown": _render_markdown(report),
        "report_csv": _csv_bytes(_REPORT_COLUMNS, _report_rows(report)),
        "hashes_csv": _csv_bytes(_HASH_COLUMNS, _hash_rows(config, source)),
    }
    return outputs, report


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


def evaluate_margin_sensitivity(
    repo_root: str | Path,
    *,
    integrity_verifier: Callable[
        [Path, Mapping[str, Any]], Mapping[str, Any]
    ]
    | None = None,
    verify_existing: bool = False,
) -> dict[str, Any]:
    """Evaluate and deterministically archive the zero-solve N0 check."""

    root = Path(repo_root).resolve(strict=True)
    config = load_margin_config(root)
    source = load_margin_source(root, config)
    result = compute_margin_sensitivity(source, config)
    verifier = verify_evaluator_integrity if integrity_verifier is None else integrity_verifier
    integrity = _validated_integrity(verifier(root, config))
    outputs, report = _build_outputs(result, source, integrity, config)
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
        description="Evaluate archived D1-R-Lite voltage-margin sensitivity"
    )
    parser.add_argument("--repo-root", type=Path, default=_REPO_FROM_SCRIPT)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = evaluate_margin_sensitivity(
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
