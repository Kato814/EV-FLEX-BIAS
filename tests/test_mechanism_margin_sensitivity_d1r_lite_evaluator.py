from __future__ import annotations

import csv
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from evflex.mechanism_margin_sensitivity_d1r_lite import load_margin_config
from tests.test_mechanism_margin_sensitivity_d1r_lite import (
    _copy_source_tree,
    _row,
    _synthetic_source,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = (
    REPO_ROOT
    / "scripts"
    / "evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py"
)


def _evaluator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "margin_sensitivity_evaluator_test", EVALUATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _integrity(_root: Path, _config: dict[str, object]) -> dict[str, object]:
    return {
        "frozen_source_hashes_verified": True,
        "source_case_hashes_verified": True,
        "source_artifacts_validated": 12,
        "code_provenance": {
            "margin_code_commit": "a" * 40,
            "margin_code_paths_clean": True,
            "file_sha256": {
                "config/mechanism_margin_sensitivity_v2_1_d1r_lite.json": "b"
                * 64,
                "src/evflex/mechanism_margin_sensitivity_d1r_lite.py": "c" * 64,
                "scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py": "d"
                * 64,
            },
        },
    }


def _output(root: Path, key: str) -> Path:
    config = load_margin_config(root)
    return root / config["artifact_names"][key]


def _run_with_source(
    evaluator: ModuleType,
    root: Path,
    source: dict[str, object],
    *,
    verify_existing: bool = False,
) -> dict[str, object]:
    evaluator.load_margin_source = lambda _root, _config: deepcopy(source)
    return evaluator.evaluate_margin_sensitivity(
        root,
        integrity_verifier=_integrity,
        verify_existing=verify_existing,
    )


@pytest.mark.parametrize(
    ("pair_ids", "expected"),
    [
        (
            ["01", "04", "07", "10", "02", "03", "08", "11"],
            "MARGIN_ROBUST_AT_1E5",
        ),
        (
            ["01", "10", "02", "09", "11", "12"],
            "HOLD_MARGIN_FRAGILE_AT_1E5",
        ),
    ],
)
def test_evaluator_supports_both_decision_branches(
    tmp_path: Path, pair_ids: list[str], expected: str
) -> None:
    _copy_source_tree(tmp_path)
    evaluator = _evaluator()
    source = _synthetic_source(
        {pair_id: [_row("VMAX", 2e-5)] for pair_id in pair_ids}
    )

    outcome = _run_with_source(evaluator, tmp_path, source)

    assert outcome["exit_code"] == 0
    assert outcome["report"]["decision"] == expected


def test_evaluator_csv_uses_exact_frozen_family_and_band_order(
    tmp_path: Path,
) -> None:
    _copy_source_tree(tmp_path)
    evaluator = _evaluator()
    outcome = _run_with_source(evaluator, tmp_path, _synthetic_source({}))

    assert outcome["exit_code"] == 0
    with _output(tmp_path, "report_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["constraint_family"], row["guard_band"]) for row in rows] == [
        ("VMIN", "0"),
        ("VMIN", "1e-06"),
        ("VMIN", "1e-05"),
        ("VMIN", "0.0001"),
        ("VMAX", "0"),
        ("VMAX", "1e-06"),
        ("VMAX", "1e-05"),
        ("VMAX", "0.0001"),
        ("VUF", "0"),
        ("TRANSFORMER", "0"),
        ("FEEDER", "0"),
    ]


def test_evaluator_retains_all_frozen_source_and_case_hashes(
    tmp_path: Path,
) -> None:
    _copy_source_tree(tmp_path)
    evaluator = _evaluator()

    outcome = evaluator.evaluate_margin_sensitivity(
        tmp_path, integrity_verifier=_integrity
    )

    assert outcome["exit_code"] == 0
    config = load_margin_config(tmp_path)
    with _output(tmp_path, "hashes_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 18
    assert [row["path"] for row in rows[:6]] == [
        item["path"] for item in config["frozen_sources"]
    ]
    assert [row["pair_id"] for row in rows[6:]] == config["source_pair_order"]


def test_evaluator_writes_required_chinese_scope_and_clean_provenance(
    tmp_path: Path,
) -> None:
    _copy_source_tree(tmp_path)
    evaluator = _evaluator()

    outcome = evaluator.evaluate_margin_sensitivity(
        tmp_path, integrity_verifier=_integrity
    )

    markdown = _output(tmp_path, "report_markdown").read_text(encoding="utf-8")
    for phrase in (
        "事后敏感性检查",
        "不改变原始 COMMON_CANDIDATE_CONFOUNDED 结论",
        "1e-5 pu",
        "不是工程安全裕度",
        "零次新增潮流计算",
        "不授权正式 V2.1",
    ):
        assert phrase in markdown
    report = json.loads(_output(tmp_path, "report_json").read_text(encoding="utf-8"))
    assert report == outcome["report"]
    assert report["code_provenance"]["margin_code_paths_clean"] is True


def test_evaluator_uses_atomic_replacement_and_byte_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_source_tree(tmp_path)
    evaluator = _evaluator()
    source = _synthetic_source({"01": [_row("VMAX", 2e-5)]})
    replacements: list[tuple[Path, Path]] = []
    original_replace = evaluator.os.replace

    def recording_replace(source_path: Path, target_path: Path) -> None:
        replacements.append((Path(source_path), Path(target_path)))
        original_replace(source_path, target_path)

    monkeypatch.setattr(evaluator.os, "replace", recording_replace)
    write = _run_with_source(evaluator, tmp_path, source)

    assert write["exit_code"] == 0
    assert len(replacements) == 4
    assert not list(tmp_path.rglob("*.tmp"))
    verified = _run_with_source(
        evaluator, tmp_path, source, verify_existing=True
    )
    assert verified["verified"] is True
    assert verified["exit_code"] == 0

    csv_path = _output(tmp_path, "report_csv")
    csv_path.write_bytes(csv_path.read_bytes() + b"drift")
    drift = _run_with_source(evaluator, tmp_path, source, verify_existing=True)
    assert drift["verified"] is False
    assert drift["exit_code"] == 1
    assert any("byte comparison failed" in error for error in drift["errors"])
