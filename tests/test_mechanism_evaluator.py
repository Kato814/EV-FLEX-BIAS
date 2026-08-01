from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from evflex.mechanism_diagnostic import (
    load_mechanism_config,
    load_pair_manifest,
    strict_json_file,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = REPO_ROOT / "scripts" / "evaluate_mechanism_diagnostic_v2_1.py"
RUNNER_TEST_PATH = REPO_ROOT / "tests" / "test_mechanism_runner.py"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_evaluator() -> ModuleType:
    return _load_module(EVALUATOR_PATH, "d1_evaluator_for_test")


def _load_artifact_support() -> ModuleType:
    return _load_module(RUNNER_TEST_PATH, "d1_artifact_support_for_evaluator")


def _inputs() -> tuple[dict[str, object], list[dict[str, object]]]:
    return load_mechanism_config(REPO_ROOT), load_pair_manifest(REPO_ROOT)


def _pair_path(root: Path, config: dict[str, object], pair_id: str) -> Path:
    relative = config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id=pair_id
    )
    return root / relative


def _report_path(root: Path, config: dict[str, object], key: str) -> Path:
    return root / config["artifact_names"][key]


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
        newline="",
    )


def _write_success_pairs(
    root: Path,
    config: dict[str, object],
    pairs: list[dict[str, object]],
) -> None:
    support = _load_artifact_support()
    for pair in pairs:
        _write_json(
            _pair_path(root, config, str(pair["pair_id"])),
            support._success_artifact(pair, config),
        )


def _verified_integrity(
    _root: Path, _config: dict[str, object]
) -> dict[str, object]:
    return {
        "frozen_sources_verified": True,
        "archived_pilot_verified": True,
    }


def _evaluate(
    evaluator: ModuleType,
    root: Path,
    config: dict[str, object],
    pairs: list[dict[str, object]],
    *,
    verify_existing: bool = False,
) -> dict[str, object]:
    return evaluator.evaluate_mechanism_diagnostic(
        root,
        config=config,
        pairs=pairs,
        integrity_verifier=_verified_integrity,
        verify_existing=verify_existing,
    )


def test_valid_classification_requires_exact_12_success_pairs_and_no_state_files(
    tmp_path: Path,
) -> None:
    evaluator = _load_evaluator()
    config, pairs = _inputs()
    _write_success_pairs(tmp_path, config, pairs)

    outcome = _evaluate(evaluator, tmp_path, config, pairs)

    assert outcome["exit_code"] == 0
    assert outcome["report"]["diagnostic_completed"] is True
    assert outcome["report"]["decision"] == "COMMON_CANDIDATE_CONFOUNDED"

    _pair_path(tmp_path, config, "12").unlink()
    with pytest.raises(ValueError, match="terminal sequence"):
        _evaluate(evaluator, tmp_path, config, pairs)

    support = _load_artifact_support()
    _write_json(
        _pair_path(tmp_path, config, "12"),
        support._success_artifact(pairs[11], config),
    )
    attempt = tmp_path / config["artifact_names"]["attempt_pattern"].format(
        pair_id="01"
    )
    _write_json(attempt, {"status": "RUNNING"})
    with pytest.raises(ValueError, match="attempt state"):
        _evaluate(evaluator, tmp_path, config, pairs)


def test_evaluator_builds_deterministic_72_row_audit_csv(tmp_path: Path) -> None:
    evaluator = _load_evaluator()
    config, pairs = _inputs()
    _write_success_pairs(tmp_path, config, pairs)

    _evaluate(evaluator, tmp_path, config, pairs)
    audit_csv = _report_path(tmp_path, config, "audit_csv")
    with audit_csv.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 72
    assert [(row["pair_id"], row["sequence_index"]) for row in rows[:7]] == [
        ("01", str(index)) for index in range(6)
    ] + [("02", "0")]
    first = audit_csv.read_bytes()
    _evaluate(evaluator, tmp_path, config, pairs)
    assert audit_csv.read_bytes() == first


def test_evaluator_failure_prefix_report_covers_actual_rows_and_lists_missing_pairs(
    tmp_path: Path,
) -> None:
    evaluator = _load_evaluator()
    support = _load_artifact_support()
    config, pairs = _inputs()
    _write_json(
        _pair_path(tmp_path, config, "01"),
        support._success_artifact(pairs[0], config),
    )
    _write_json(
        _pair_path(tmp_path, config, "02"),
        support._stop_artifact(pairs[1], config),
    )

    outcome = _evaluate(evaluator, tmp_path, config, pairs)

    assert outcome["exit_code"] == 1
    report = strict_json_file(_report_path(tmp_path, config, "report_json"))
    assert report["decision"] == "STOP_IMPLEMENTATION"
    assert report["diagnostic_completed"] is False
    assert report["actual_audits"] == 9
    assert report["missing_pair_ids"] == [f"{index:02d}" for index in range(3, 13)]
    with _report_path(tmp_path, config, "audit_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        assert len(list(csv.DictReader(stream))) == 9
    markdown = _report_path(tmp_path, config, "report_markdown").read_text(
        encoding="utf-8"
    )
    assert "D1 未完成" in markdown
    verified = _evaluate(
        evaluator,
        tmp_path,
        config,
        pairs,
        verify_existing=True,
    )
    assert verified["exit_code"] == 0
    assert verified["verified"] is True
    assert verified["decision"] == "STOP_IMPLEMENTATION"


def test_evaluator_writes_conservative_chinese_markdown(tmp_path: Path) -> None:
    evaluator = _load_evaluator()
    config, pairs = _inputs()
    _write_success_pairs(tmp_path, config, pairs)

    _evaluate(evaluator, tmp_path, config, pairs)
    markdown = _report_path(tmp_path, config, "report_markdown").read_text(
        encoding="utf-8"
    )

    for required in (
        "固定 EV 调度轨迹",
        "未进行三相重新优化",
        "line_thermal_in_scope=false",
        "RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR",
        "COMMON_CANDIDATE_CONFOUNDED",
        "NO_GO_REASSESS_BROAD_TOPIC",
        "不授权正式 V2.1",
        "IEEE13 仅是时间、方向和时长匹配的设计单元对照，不是因果匹配",
        "四个分组是场景簇，不是独立重复",
        "约束数量匹配只衡量检测敏感性，既不证明也不排除数量效应",
    ):
        assert required in markdown


def test_evaluator_hash_csv_covers_all_pair_artifacts(tmp_path: Path) -> None:
    evaluator = _load_evaluator()
    config, pairs = _inputs()
    _write_success_pairs(tmp_path, config, pairs)

    _evaluate(evaluator, tmp_path, config, pairs)
    with _report_path(tmp_path, config, "hashes_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))

    assert [row["pair_id"] for row in rows] == [f"{index:02d}" for index in range(1, 13)]
    for row in rows:
        pair_path = _pair_path(tmp_path, config, row["pair_id"])
        assert row["sha256"] == hashlib.sha256(pair_path.read_bytes()).hexdigest()


def test_verify_existing_is_read_only_and_detects_byte_tampering(
    tmp_path: Path,
) -> None:
    evaluator = _load_evaluator()
    config, pairs = _inputs()
    _write_success_pairs(tmp_path, config, pairs)
    _evaluate(evaluator, tmp_path, config, pairs)
    paths = [
        _report_path(tmp_path, config, key)
        for key in ("audit_csv", "report_json", "report_markdown", "hashes_csv")
    ]
    before = {path: path.read_bytes() for path in paths}

    verified = _evaluate(
        evaluator,
        tmp_path,
        config,
        pairs,
        verify_existing=True,
    )

    assert verified["exit_code"] == 0
    assert verified["verified"] is True
    assert {path: path.read_bytes() for path in paths} == before

    markdown = _report_path(tmp_path, config, "report_markdown")
    tampered = markdown.read_bytes() + b"tampered\n"
    markdown.write_bytes(tampered)
    failed = _evaluate(
        evaluator,
        tmp_path,
        config,
        pairs,
        verify_existing=True,
    )
    assert failed["exit_code"] == 1
    assert failed["verified"] is False
    assert markdown.read_bytes() == tampered
