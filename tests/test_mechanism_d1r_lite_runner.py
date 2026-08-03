from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

import pytest

from evflex.mechanism_diagnostic_d1r_lite import (
    LiteAuditStop,
    load_lite_config,
    load_lite_manifest,
)
from tests.test_mechanism_d1r_lite import _gate_artifact


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_mechanism_diagnostic_v2_1_d1r_lite.py"
THREAD_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("d1r_lite_runner_test", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load D1-R-Lite runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs() -> tuple[dict[str, object], list[dict[str, object]]]:
    return load_lite_config(REPO_ROOT), load_lite_manifest(REPO_ROOT)


def _case_path(root: Path, config: dict[str, object], pair_id: str) -> Path:
    relative = config["artifact_names"]["case_artifact_pattern"].format(
        pair_id=pair_id
    )
    return root / relative


def _persist(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )


def _compute(
    support: dict[str, set[str]], calls: list[str]
):
    def execute(
        _root: Path,
        case: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        pair_id = str(case["pair_id"])
        calls.append(pair_id)
        return _gate_artifact(case, support.get(pair_id, {"FEEDER"}))

    return execute


def _expanding_support() -> dict[str, set[str]]:
    return {f"{index:02d}": {"VMIN"} for index in range(1, 13)}


def _stopping_support() -> dict[str, set[str]]:
    return {
        "01": {"VMIN"},
        "04": {"VMIN"},
        "07": {"VUF"},
        "10": {"VUF"},
    }


def test_runner_sets_all_numeric_threads_to_one_before_import(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in THREAD_NAMES:
        monkeypatch.setenv(name, "9")

    runner = _load_runner()

    assert runner.THREAD_ENVIRONMENT == {name: "1" for name in THREAD_NAMES}
    assert {os.environ[name] for name in THREAD_NAMES} == {"1"}


def test_real_preflight_completes_before_any_atomic_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    config, cases = _inputs()
    events: list[str] = []

    def fake_preflight(_root: Path):
        events.append("real_preflight")
        return config, cases, {"status": "PREFLIGHT_OK"}

    original_atomic = runner.atomic_write_json

    def recording_atomic(path: Path, payload: dict[str, object]) -> None:
        events.append(f"write:{path.name}")
        original_atomic(path, payload)

    monkeypatch.setattr(runner, "preflight", fake_preflight)
    monkeypatch.setattr(runner, "atomic_write_json", recording_atomic)
    calls: list[str] = []

    result = runner.run_diagnostic(
        tmp_path,
        execute_fn=_compute(_stopping_support(), calls),
    )

    assert result["decision"] == "STOP_HETEROGENEOUS_SCREEN"
    assert events[0] == "real_preflight"
    assert events[1].startswith("write:")


def test_runner_uses_atomic_terminal_writes_and_no_process_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    config, cases = _inputs()
    writes: list[Path] = []
    original_atomic = runner.atomic_write_json

    def recording_atomic(path: Path, payload: dict[str, object]) -> None:
        writes.append(path)
        original_atomic(path, payload)

    monkeypatch.setattr(runner, "atomic_write_json", recording_atomic)
    calls: list[str] = []
    runner.run_diagnostic(
        tmp_path,
        config=config,
        cases=cases,
        execute_fn=_compute(_stopping_support(), calls),
        preflight=False,
    )

    terminal_names = [path.name for path in writes if path.parent.name == "cases"]
    assert terminal_names == ["case_01.json", "case_04.json", "case_07.json", "case_10.json"]
    assert "ProcessPoolExecutor" not in RUNNER_PATH.read_text(encoding="utf-8")
    assert "multiprocessing" not in RUNNER_PATH.read_text(encoding="utf-8")


def test_resume_accepts_only_a_continuous_valid_prefix(tmp_path: Path) -> None:
    runner = _load_runner()
    config, cases = _inputs()
    support = _stopping_support()
    for case in cases[:2]:
        _persist(
            _case_path(tmp_path, config, str(case["pair_id"])),
            _gate_artifact(case, support[str(case["pair_id"])]),
        )
    calls: list[str] = []

    result = runner.run_diagnostic(
        tmp_path,
        config=config,
        cases=cases,
        execute_fn=_compute(support, calls),
        preflight=False,
    )

    assert calls == ["07", "10"]
    assert result["skipped_pair_ids"] == ["01", "04"]
    assert result["completed_pair_ids"] == ["07", "10"]

    gap_root = tmp_path / "gap"
    _persist(_case_path(gap_root, config, "04"), _gate_artifact(cases[1], {"VMIN"}))
    with pytest.raises(ValueError, match="continuous"):
        runner.validate_runtime_inventory(gap_root, config, cases)


def test_inventory_rejects_stage_b_artifacts_before_expansion(tmp_path: Path) -> None:
    runner = _load_runner()
    config, cases = _inputs()
    support = _stopping_support()
    for case in cases:
        _persist(
            _case_path(tmp_path, config, str(case["pair_id"])),
            _gate_artifact(case, support.get(str(case["pair_id"]), {"FEEDER"})),
        )

    with pytest.raises(ValueError, match="before expansion"):
        runner.validate_runtime_inventory(tmp_path, config, cases)


def test_runner_automatically_runs_stage_b_only_after_expansion(tmp_path: Path) -> None:
    runner = _load_runner()
    config, cases = _inputs()
    calls: list[str] = []

    result = runner.run_diagnostic(
        tmp_path,
        config=config,
        cases=cases,
        execute_fn=_compute(_expanding_support(), calls),
        preflight=False,
    )

    assert calls == config["selection"]["execution_order"]
    assert result["status"] == "SUCCESS"
    assert result["stage_a_decision"] == "EXPAND_STAGE_B"
    assert result["decision"] == "COMMON_CANDIDATE_CONFOUNDED"
    assert len(list((tmp_path / config["artifact_names"]["result_root"] / "cases").glob("*.json"))) == 12


def test_runner_stops_after_first_terminal_failure(tmp_path: Path) -> None:
    runner = _load_runner()
    config, cases = _inputs()
    calls: list[str] = []

    def stop_first(
        _root: Path,
        case: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        calls.append(str(case["pair_id"]))
        raise LiteAuditStop(
            "PRE_AUDIT_IMPLEMENTATION_INVALID",
            "controlled test stop",
            sequence_index=None,
        )

    result = runner.run_diagnostic(
        tmp_path,
        config=config,
        cases=cases,
        execute_fn=stop_first,
        preflight=False,
    )

    assert calls == ["01"]
    assert result["status"] == "STOP_IMPLEMENTATION"
    assert result["completed_pair_ids"] == ["01"]
    assert not _case_path(tmp_path, config, "04").exists()


def test_cli_emits_one_strict_json_object_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _load_runner()

    def fail(_root: Path):
        raise ValueError("预检失败")

    monkeypatch.setattr(runner, "preflight", fail)

    exit_code = runner.main(["--repo-root", str(tmp_path), "--preflight-only"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "detail": "预检失败",
        "error_type": "ValueError",
        "formal_v2_1_run_started": False,
        "status": "RUNNER_ERROR",
    }
