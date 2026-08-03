from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from evflex.mechanism_diagnostic import strict_json_file
from evflex.mechanism_diagnostic_d1r_lite import (
    LiteAuditStop,
    load_lite_config,
    load_lite_manifest,
)
from tests.test_mechanism_d1r_lite import _gate_artifact


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = (
    REPO_ROOT / "scripts" / "evaluate_mechanism_diagnostic_v2_1_d1r_lite.py"
)
RUNNER_PATH = REPO_ROOT / "scripts" / "run_mechanism_diagnostic_v2_1_d1r_lite.py"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evaluator() -> ModuleType:
    return _load_module(EVALUATOR_PATH, "d1r_lite_evaluator_test")


def _runner() -> ModuleType:
    return _load_module(RUNNER_PATH, "d1r_lite_runner_for_evaluator")


def _inputs() -> tuple[dict[str, object], list[dict[str, object]]]:
    return load_lite_config(REPO_ROOT), load_lite_manifest(REPO_ROOT)


def _case_path(root: Path, config: dict[str, object], pair_id: str) -> Path:
    return root / config["artifact_names"]["case_artifact_pattern"].format(
        pair_id=pair_id
    )


def _output_path(root: Path, config: dict[str, object], key: str) -> Path:
    return root / config["artifact_names"][key]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
        newline="",
    )


def _write_successes(
    root: Path,
    config: dict[str, object],
    cases: list[dict[str, object]],
    support: dict[str, set[str]],
    *,
    count: int,
) -> None:
    for case in cases[:count]:
        pair_id = str(case["pair_id"])
        _write_json(
            _case_path(root, config, pair_id),
            _gate_artifact(case, support.get(pair_id, {"FEEDER"})),
        )


def _integrity(_root: Path, _config: dict[str, object]) -> dict[str, object]:
    return {
        "frozen_sources_verified": True,
        "archived_d1_verified": True,
        "archived_pilot_verified": True,
        "code_provenance": {
            "d1r_lite_code_commit": "a" * 40,
            "d1r_lite_code_paths_clean": True,
            "file_sha256": {
                "src/evflex/mechanism_diagnostic_d1r_lite.py": "b" * 64,
                "scripts/run_mechanism_diagnostic_v2_1_d1r_lite.py": "c" * 64,
            },
        },
    }


def _evaluate(
    evaluator: ModuleType,
    root: Path,
    config: dict[str, object],
    cases: list[dict[str, object]],
    *,
    verify_existing: bool = False,
) -> dict[str, object]:
    return evaluator.evaluate_mechanism_diagnostic_d1r_lite(
        root,
        config=config,
        cases=cases,
        integrity_verifier=_integrity,
        verify_existing=verify_existing,
    )


def _stage_a_stop_support() -> dict[str, set[str]]:
    return {
        "01": {"VMIN"},
        "04": {"VMIN"},
        "07": {"VUF"},
        "10": {"VUF"},
    }


def _common_support() -> dict[str, set[str]]:
    return {f"{index:02d}": {"VMIN"} for index in range(1, 13)}


def _heterogeneous_support() -> dict[str, set[str]]:
    return {
        "01": {"VMIN"},
        "04": {"VMIN"},
        "07": {"VMIN"},
        "10": {"VUF"},
        "02": {"VMAX"},
        "03": {"VUF"},
        "05": {"TRANSFORMER"},
        "06": {"FEEDER"},
        "08": {"VMAX"},
        "09": {"VUF"},
        "11": {"TRANSFORMER"},
        "12": {"FEEDER"},
    }


def test_evaluator_accepts_stage_a_stop_and_writes_exactly_eight_rows(
    tmp_path: Path,
) -> None:
    evaluator = _evaluator()
    config, cases = _inputs()
    _write_successes(
        tmp_path, config, cases, _stage_a_stop_support(), count=4
    )

    outcome = _evaluate(evaluator, tmp_path, config, cases)

    assert outcome["exit_code"] == 0
    assert outcome["report"]["decision"] == "STOP_HETEROGENEOUS_SCREEN"
    assert outcome["report"]["diagnostic_completed"] is True
    assert outcome["report"]["actual_cases"] == 4
    assert outcome["report"]["actual_target_audits"] == 8
    magnitude = {
        item["constraint_family"]: item
        for item in outcome["report"]["boundary_exceedance_by_family"]
    }
    assert magnitude["VMIN"] == {
        "constraint_family": "VMIN",
        "unit": "pu",
        "case_count": 2,
        "metric_witness_count": 2,
        "minimum_exceedance": pytest.approx(0.01),
        "median_exceedance": pytest.approx(0.01),
        "maximum_exceedance": pytest.approx(0.01),
    }
    with _output_path(tmp_path, config, "audit_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 8
    assert float(rows[1]["simultaneous_violation_exceedances"]) == pytest.approx(0.01)


@pytest.mark.parametrize(
    ("support_factory", "expected_decision", "expected_families"),
    [
        (_common_support, "COMMON_CANDIDATE_CONFOUNDED", ["VMIN"]),
        (_heterogeneous_support, "HETEROGENEOUS_12_CASES", []),
    ],
)
def test_evaluator_expanded_final_outcomes_write_exactly_sixteen_rows(
    tmp_path: Path,
    support_factory: object,
    expected_decision: str,
    expected_families: list[str],
) -> None:
    evaluator = _evaluator()
    config, cases = _inputs()
    support = support_factory()
    _write_successes(tmp_path, config, cases, support, count=12)

    outcome = _evaluate(evaluator, tmp_path, config, cases)

    report = outcome["report"]
    assert outcome["exit_code"] == 0
    assert report["decision"] == expected_decision
    assert report["qualifying_families"] == expected_families
    assert report["actual_cases"] == 12
    assert report["actual_target_audits"] == 16
    with _output_path(tmp_path, config, "audit_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        assert len(list(csv.DictReader(stream))) == 16


@pytest.mark.parametrize("failure_status", ["STOP_IMPLEMENTATION", "UNHANDLED_FAILURE"])
def test_evaluator_reports_terminal_failure_prefix(
    tmp_path: Path, failure_status: str
) -> None:
    evaluator = _evaluator()
    runner = _runner()
    config, cases = _inputs()
    _write_json(
        _case_path(tmp_path, config, "01"),
        _gate_artifact(cases[0], {"VMIN"}),
    )
    if failure_status == "STOP_IMPLEMENTATION":
        failure = runner._audit_stop_artifact(
            cases[1],
            config,
            LiteAuditStop(
                "PRE_AUDIT_IMPLEMENTATION_INVALID",
                "test stop",
                sequence_index=None,
            ),
        )
    else:
        failure = runner._unhandled_artifact(
            cases[1], config, RuntimeError("test failure")
        )
    _write_json(_case_path(tmp_path, config, "04"), failure)

    outcome = _evaluate(evaluator, tmp_path, config, cases)

    assert outcome["exit_code"] == 1
    report = strict_json_file(_output_path(tmp_path, config, "report_json"))
    assert report["decision"] == failure_status
    assert report["diagnostic_completed"] is False
    assert report["terminal_case_ids"] == ["01", "04"]
    assert report["actual_target_audits"] == 2
    assert report["missing_pair_ids"] == [
        "07",
        "10",
        "02",
        "03",
        "05",
        "06",
        "08",
        "09",
        "11",
        "12",
    ]


def test_evaluator_hashes_cases_and_records_clean_code_provenance(
    tmp_path: Path,
) -> None:
    evaluator = _evaluator()
    config, cases = _inputs()
    _write_successes(
        tmp_path, config, cases, _stage_a_stop_support(), count=4
    )

    _evaluate(evaluator, tmp_path, config, cases)

    with _output_path(tmp_path, config, "hashes_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert [row["pair_id"] for row in rows] == ["01", "04", "07", "10"]
    for row in rows:
        case_path = _case_path(tmp_path, config, row["pair_id"])
        assert row["sha256"] == hashlib.sha256(case_path.read_bytes()).hexdigest()
    report = strict_json_file(_output_path(tmp_path, config, "report_json"))
    assert report["code_provenance"] == _integrity(tmp_path, config)[
        "code_provenance"
    ]


def test_evaluator_writes_conservative_chinese_scope_and_byte_verifies(
    tmp_path: Path,
) -> None:
    evaluator = _evaluator()
    config, cases = _inputs()
    _write_successes(tmp_path, config, cases, _common_support(), count=12)
    _evaluate(evaluator, tmp_path, config, cases)
    markdown_path = _output_path(tmp_path, config, "report_markdown")
    markdown = markdown_path.read_text(encoding="utf-8")

    for required in (
        "IEEE13 对照",
        "全报价审计",
        "约束数量匹配",
        "LV906 固定 EV 调度轨迹",
        "未进行三相重新优化",
        "line_thermal_in_scope=false",
        "越限幅度",
        "仅作描述",
        "不是唯一机制或因果机制",
        "不授权正式 V2.1",
        "NO_GO_REASSESS_BROAD_TOPIC",
    ):
        assert required in markdown

    verified = _evaluate(
        evaluator, tmp_path, config, cases, verify_existing=True
    )
    assert verified["verified"] is True
    assert verified["exit_code"] == 0

    markdown_path.write_bytes(markdown_path.read_bytes() + b"drift")
    drift = _evaluate(evaluator, tmp_path, config, cases, verify_existing=True)
    assert drift["verified"] is False
    assert drift["exit_code"] == 1
