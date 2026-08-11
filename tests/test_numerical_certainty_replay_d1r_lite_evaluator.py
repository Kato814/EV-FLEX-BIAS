from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

from evflex.numerical_certainty_replay_d1r_lite import load_replay_config
from tests.test_numerical_certainty_replay_d1r_lite import (
    _case_artifact,
    _observation,
    _stable_observations,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = (
    REPO_ROOT
    / "scripts"
    / "evaluate_numerical_certainty_replay_v2_1_d1r_lite.py"
)
CODE_PATHS = (
    "config/numerical_certainty_replay_v2_1_d1r_lite.json",
    "src/evflex/numerical_certainty_replay_d1r_lite.py",
    "scripts/run_numerical_certainty_replay_v2_1_d1r_lite.py",
    "scripts/evaluate_numerical_certainty_replay_v2_1_d1r_lite.py",
)


def _evaluator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("n1_replay_evaluator_test", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {EVALUATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _integrity(
    _root: Path,
    _config: dict[str, object],
    artifacts: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "frozen_source_hashes_verified": True,
        "source_case_hashes_verified": True,
        "source_artifacts_validated": 12,
        "replay_artifacts_validated": len(artifacts),
        "code_provenance": {
            "replay_code_commit": "a" * 40,
            "replay_code_paths_clean": True,
            "file_sha256": {
                path: chr(ord("b") + index) * 64
                for index, path in enumerate(CODE_PATHS)
            },
        },
    }


def _case_path(root: Path, config: dict[str, object], pair_id: str) -> Path:
    return root / config["artifact_names"]["case_artifact_pattern"].format(
        pair_id=pair_id
    )


def _persist_cases(
    root: Path,
    config: dict[str, object],
    artifacts: list[dict[str, object]],
) -> None:
    for artifact in artifacts:
        path = _case_path(root, config, str(artifact["pair_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                artifact,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ),
            encoding="utf-8",
        )


def _artifacts(decision: str) -> list[dict[str, object]]:
    config = load_replay_config(REPO_ROOT)
    selections = deepcopy(config["selected_cases"])
    if decision == "NUMERICALLY_STABLE_SELECTED_WITNESSES":
        return [_case_artifact(selection) for selection in selections]
    if decision == "NUMERICAL_SENSITIVITY_DETECTED":
        retained = [_case_artifact(selection) for selection in selections]
        selection = selections[1]
        observations = _stable_observations(selection)
        observations[1] = _observation(
            selection,
            config["solver_settings"][1],
            float(selection["value"]) + 1.1e-6,
        )
        retained[1] = _case_artifact(selection, observations)
        return retained
    selection = selections[0]
    observations = _stable_observations(selection)
    if decision == "STOP_REPLAY_IDENTITY_MISMATCH":
        observations[0]["metric_value"] = float(selection["value"]) + 2e-9
        observations[0]["exceedance"] = observations[0]["metric_value"] - float(
            selection["limit"]
        )
    elif decision == "STOP_SOLVER_FAILURE":
        observations[0]["converged"] = False
        observations[0]["numerical_failure"] = True
    else:
        raise AssertionError(decision)
    return [_case_artifact(selection, observations)]


def _prepare(
    evaluator: ModuleType,
    root: Path,
    artifacts: list[dict[str, object]],
) -> dict[str, object]:
    config = load_replay_config(REPO_ROOT)
    _persist_cases(root, config, artifacts)
    evaluator.load_replay_config = lambda _root: deepcopy(config)
    evaluator.load_replay_source = lambda _root, _config: {
        "runtime_version": config["runtime_requirement"]["version"],
        "frozen_source_hashes": {
            item["path"]: item["sha256"] for item in config["frozen_sources"]
        },
    }
    return config


def _output(root: Path, config: dict[str, object], key: str) -> Path:
    return root / config["artifact_names"][key]


@pytest.mark.parametrize(
    "decision",
    [
        "NUMERICALLY_STABLE_SELECTED_WITNESSES",
        "NUMERICAL_SENSITIVITY_DETECTED",
        "STOP_REPLAY_IDENTITY_MISMATCH",
        "STOP_SOLVER_FAILURE",
    ],
)
def test_evaluator_supports_all_four_aggregate_decisions(
    tmp_path: Path, decision: str
) -> None:
    evaluator = _evaluator()
    _prepare(evaluator, tmp_path, _artifacts(decision))

    outcome = evaluator.evaluate_numerical_certainty_replay(
        tmp_path, integrity_verifier=_integrity
    )

    assert outcome["exit_code"] == 0
    assert outcome["report"]["decision"] == decision


def test_evaluator_csv_has_exact_case_and_setting_order(tmp_path: Path) -> None:
    evaluator = _evaluator()
    config = _prepare(
        evaluator,
        tmp_path,
        _artifacts("NUMERICALLY_STABLE_SELECTED_WITNESSES"),
    )

    evaluator.evaluate_numerical_certainty_replay(
        tmp_path, integrity_verifier=_integrity
    )

    with _output(tmp_path, config, "report_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["pair_id"], row["setting_label"]) for row in rows] == [
        (pair_id, label)
        for pair_id in ["01", "05", "08", "12"]
        for label in ["NATIVE_1E4", "TIGHT_1E6", "ULTRA_1E8"]
    ]
    assert len(rows) == 12


def test_evaluator_hashes_all_frozen_sources_and_replay_cases(tmp_path: Path) -> None:
    evaluator = _evaluator()
    artifacts = _artifacts("NUMERICALLY_STABLE_SELECTED_WITNESSES")
    config = _prepare(evaluator, tmp_path, artifacts)

    evaluator.evaluate_numerical_certainty_replay(
        tmp_path, integrity_verifier=_integrity
    )

    with _output(tmp_path, config, "hashes_csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert [row["path"] for row in rows[:8]] == [
        item["path"] for item in config["frozen_sources"]
    ]
    assert [row["pair_id"] for row in rows[8:]] == ["01", "05", "08", "12"]
    for row in rows[8:]:
        path = tmp_path / row["path"]
        assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_evaluator_writes_required_chinese_scope_and_provenance(tmp_path: Path) -> None:
    evaluator = _evaluator()
    config = _prepare(
        evaluator,
        tmp_path,
        _artifacts("NUMERICALLY_STABLE_SELECTED_WITNESSES"),
    )

    outcome = evaluator.evaluate_numerical_certainty_replay(
        tmp_path, integrity_verifier=_integrity
    )

    markdown = _output(tmp_path, config, "report_markdown").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "4个代表见证点",
        "只复核归档失效时刻",
        "不是完整96时段重跑",
        "求解容差不是电压误差界",
        "不改变N0的6/12计数",
        "不授权正式V2.1",
    ):
        assert phrase in markdown
    report = json.loads(
        _output(tmp_path, config, "report_json").read_text(encoding="utf-8")
    )
    assert report == outcome["report"]
    assert report["target_replay_evaluations"] == 12
    assert report["internal_setup_solve_count"] == "NOT_REPORTED"
    assert report["formal_v2_1_run_authorized"] is False
    assert report["code_provenance"]["replay_code_paths_clean"] is True


def test_evaluator_uses_atomic_replacement_and_byte_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluator = _evaluator()
    artifacts = _artifacts("NUMERICALLY_STABLE_SELECTED_WITNESSES")
    config = _prepare(evaluator, tmp_path, artifacts)
    replacements: list[tuple[Path, Path]] = []
    original_replace = evaluator.os.replace

    def recording_replace(source: Path, target: Path) -> None:
        replacements.append((Path(source), Path(target)))
        original_replace(source, target)

    monkeypatch.setattr(evaluator.os, "replace", recording_replace)
    write = evaluator.evaluate_numerical_certainty_replay(
        tmp_path, integrity_verifier=_integrity
    )

    assert write["exit_code"] == 0
    assert len(replacements) == 4
    assert not list(tmp_path.rglob("*.tmp"))
    verified = evaluator.evaluate_numerical_certainty_replay(
        tmp_path,
        integrity_verifier=_integrity,
        verify_existing=True,
    )
    assert verified["verified"] is True
    assert verified["exit_code"] == 0

    csv_path = _output(tmp_path, config, "report_csv")
    csv_path.write_bytes(csv_path.read_bytes() + b"drift")
    drift = evaluator.evaluate_numerical_certainty_replay(
        tmp_path,
        integrity_verifier=_integrity,
        verify_existing=True,
    )
    assert drift["verified"] is False
    assert drift["exit_code"] == 1
    assert any("byte comparison failed" in error for error in drift["errors"])
