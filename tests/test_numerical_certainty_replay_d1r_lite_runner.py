from __future__ import annotations

import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

from evflex.numerical_certainty_replay_d1r_lite import load_replay_config
from tests.test_numerical_certainty_replay_d1r_lite import (
    _case_artifact,
    _stable_observations,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = (
    REPO_ROOT / "scripts" / "run_numerical_certainty_replay_v2_1_d1r_lite.py"
)
THREAD_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("n1_replay_runner_test", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load N1 replay runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _stable_compute(calls: list[str]):
    def execute(
        _root: Path,
        selection: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        calls.append(str(selection["pair_id"]))
        return _case_artifact(deepcopy(selection))

    return execute


def test_runner_sets_all_numeric_threads_to_one_before_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in THREAD_NAMES:
        monkeypatch.setenv(name, "9")

    runner = _load_runner()

    assert runner.THREAD_ENVIRONMENT == {name: "1" for name in THREAD_NAMES}
    assert {os.environ[name] for name in THREAD_NAMES} == {"1"}


def test_runner_processes_four_cases_sequentially_and_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    config = load_replay_config(REPO_ROOT)
    selections = deepcopy(config["selected_cases"])
    writes: list[Path] = []
    original_atomic = runner.atomic_write_json

    def recording_atomic(path: Path, payload: dict[str, object]) -> None:
        writes.append(path)
        original_atomic(path, payload)

    monkeypatch.setattr(runner, "atomic_write_json", recording_atomic)
    calls: list[str] = []

    summary = runner.run_replay(
        tmp_path,
        config=config,
        selections=selections,
        execute_fn=_stable_compute(calls),
        preflight=False,
    )

    assert calls == ["01", "05", "08", "12"]
    assert summary["decision"] == "NUMERICALLY_STABLE_SELECTED_WITNESSES"
    assert [path.name for path in writes if path.parent.name == "cases"] == [
        "case_01.json",
        "case_05.json",
        "case_08.json",
        "case_12.json",
    ]
    assert not list((tmp_path / config["artifact_names"]["result_root"]).rglob("*.tmp"))
    assert "ProcessPoolExecutor" not in RUNNER_PATH.read_text(encoding="utf-8")
    assert "multiprocessing" not in RUNNER_PATH.read_text(encoding="utf-8")


def test_runner_resumes_only_a_valid_immutable_prefix(tmp_path: Path) -> None:
    runner = _load_runner()
    config = load_replay_config(REPO_ROOT)
    selections = deepcopy(config["selected_cases"])
    for selection in selections[:2]:
        _persist(
            _case_path(tmp_path, config, str(selection["pair_id"])),
            _case_artifact(selection),
        )
    calls: list[str] = []

    summary = runner.run_replay(
        tmp_path,
        config=config,
        selections=selections,
        execute_fn=_stable_compute(calls),
        preflight=False,
    )

    assert calls == ["08", "12"]
    assert summary["skipped_pair_ids"] == ["01", "05"]
    assert summary["completed_pair_ids"] == ["08", "12"]

    gap_root = tmp_path / "gap"
    _persist(_case_path(gap_root, config, "05"), _case_artifact(selections[1]))
    with pytest.raises(ValueError, match="continuous"):
        runner.validate_runtime_inventory(gap_root, config, selections)


@pytest.mark.parametrize("kind", ["attempt", "lock", "unexpected", "formal"])
def test_inventory_stops_on_unsafe_state(tmp_path: Path, kind: str) -> None:
    runner = _load_runner()
    config = load_replay_config(REPO_ROOT)
    selections = deepcopy(config["selected_cases"])
    if kind == "attempt":
        path = tmp_path / config["artifact_names"]["attempt_pattern"].format(pair_id="01")
    elif kind == "lock":
        path = tmp_path / config["artifact_names"]["run_lock"]
    elif kind == "unexpected":
        path = _case_path(tmp_path, config, "01").parent / "case_99.json"
    else:
        path = tmp_path / "results" / "formal_v2_1" / "forbidden.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="requires inspection|forbidden"):
        runner.validate_runtime_inventory(tmp_path, config, selections)


def test_runner_persists_validated_stop_then_does_not_advance(tmp_path: Path) -> None:
    runner = _load_runner()
    config = load_replay_config(REPO_ROOT)
    selections = deepcopy(config["selected_cases"])
    calls: list[str] = []

    def stop_first(
        _root: Path,
        selection: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        calls.append(str(selection["pair_id"]))
        observations = _stable_observations(selection)
        observations[0]["metric_value"] = float(selection["value"]) + 2e-9
        observations[0]["exceedance"] = observations[0]["metric_value"] - float(
            selection["limit"]
        )
        return _case_artifact(selection, observations)

    summary = runner.run_replay(
        tmp_path,
        config=config,
        selections=selections,
        execute_fn=stop_first,
        preflight=False,
    )

    assert calls == ["01"]
    assert summary["decision"] == "STOP_REPLAY_IDENTITY_MISMATCH"
    assert _case_path(tmp_path, config, "01").is_file()
    assert not _case_path(tmp_path, config, "05").exists()


def test_cli_emits_one_strict_json_object_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

