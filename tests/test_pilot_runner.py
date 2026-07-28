from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_pilot_gate_v2_1.py"
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def _load_runner(monkeypatch):
    for name in THREAD_VARIABLES:
        monkeypatch.setenv(name, "9")
    spec = importlib.util.spec_from_file_location("pilot_runner_test_module", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unit():
    return {
        "work_unit_id": "wu",
        "protocol_version": "EV-FLEX-BIAS-V2.1-PILOT",
        "scenario_id": "scenario",
        "scenario_seed": 123,
        "data_role": "development_pilot",
        "evaluation_ids": json.dumps(
            ["scenario__inc__15m", "scenario__inc__30m", "scenario__inc__60m"]
        ),
    }


def _completed_payload():
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.1-PILOT",
        "work_unit_id": "wu",
        "scenario_seed": 123,
        "data_role": "development_pilot",
        "status": "SUCCESS",
        "attempt_count": 1,
        "evaluations": [
            {"evaluation_id": f"scenario__inc__{duration}m", "status": "SUCCESS"}
            for duration in (15, 30, 60)
        ],
    }


def test_import_forces_all_numeric_thread_limits_before_scientific_work(monkeypatch):
    module = _load_runner(monkeypatch)

    assert module.THREAD_ENVIRONMENT == {
        name: "1" for name in THREAD_VARIABLES
    }
    assert all(os.environ[name] == "1" for name in THREAD_VARIABLES)


def test_workers_other_than_one_are_rejected_before_paths_are_prepared(
    monkeypatch, tmp_path
):
    module = _load_runner(monkeypatch)
    called = []
    monkeypatch.setattr(module, "_prepare_repository", lambda *_: called.append(True))

    with pytest.raises(SystemExit, match="exactly 1"):
        module.main(["--workers", "2"], repo_root=tmp_path)

    assert called == []
    assert list(tmp_path.iterdir()) == []


def test_pool_is_explicit_spawn_with_one_task_per_child(monkeypatch):
    module = _load_runner(monkeypatch)
    captured = {}

    class FakeExecutor:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(module, "ProcessPoolExecutor", FakeExecutor)
    executor = module._new_executor()

    assert isinstance(executor, FakeExecutor)
    assert captured["max_workers"] == 1
    assert captured["max_tasks_per_child"] == 1
    assert captured["mp_context"].get_start_method() == "spawn"


def test_resume_reclaims_only_dead_lock_and_preserves_attempt(tmp_path, monkeypatch):
    module = _load_runner(monkeypatch)
    paths = module._unit_paths(tmp_path, "wu")
    paths.lock.parent.mkdir(parents=True)
    paths.attempt.parent.mkdir(parents=True)
    paths.lock.write_text("4242", encoding="ascii")
    attempt = {
        "work_unit_id": "wu",
        "scenario_seed": 123,
        "attempt_count": 1,
        "errors": [],
    }
    paths.attempt.write_text(json.dumps(attempt), encoding="utf-8")
    monkeypatch.setattr(module, "_pid_is_alive", lambda pid: False)

    module._prepare_unit_artifacts(_unit(), paths, resume=True)

    assert not paths.lock.exists()
    assert json.loads(paths.attempt.read_text(encoding="utf-8")) == attempt


def test_resume_never_removes_live_or_malformed_lock(tmp_path, monkeypatch):
    module = _load_runner(monkeypatch)
    paths = module._unit_paths(tmp_path, "wu")
    paths.lock.parent.mkdir(parents=True)
    paths.lock.write_text("4242", encoding="ascii")
    monkeypatch.setattr(module, "_pid_is_alive", lambda pid: True)

    with pytest.raises(RuntimeError, match="active lock"):
        module._prepare_unit_artifacts(_unit(), paths, resume=True)
    assert paths.lock.exists()

    paths.lock.write_text("not-a-pid", encoding="ascii")
    with pytest.raises(RuntimeError, match="malformed"):
        module._prepare_unit_artifacts(_unit(), paths, resume=True)
    assert paths.lock.exists()


def test_resume_skips_valid_result_without_changing_bytes(tmp_path, monkeypatch):
    module = _load_runner(monkeypatch)
    paths = module._unit_paths(tmp_path, "wu")
    paths.result.parent.mkdir(parents=True)
    before = json.dumps(_completed_payload(), sort_keys=True).encode("utf-8")
    paths.result.write_bytes(before)

    outcome = module._prepare_unit_artifacts(_unit(), paths, resume=True)

    assert outcome["status"] == "SUCCESS"
    assert outcome["runner_status"] == "SKIPPED_COMPLETED"
    assert paths.result.read_bytes() == before


def test_resume_rejects_corrupt_result_without_overwrite(tmp_path, monkeypatch):
    module = _load_runner(monkeypatch)
    paths = module._unit_paths(tmp_path, "wu")
    paths.result.parent.mkdir(parents=True)
    paths.result.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        module._prepare_unit_artifacts(_unit(), paths, resume=True)

    assert paths.result.read_text(encoding="utf-8") == "{broken"


def test_no_resume_rejects_any_owned_runtime_artifact(tmp_path, monkeypatch):
    module = _load_runner(monkeypatch)
    paths = module._unit_paths(tmp_path, "wu")
    paths.attempt.parent.mkdir(parents=True)
    paths.attempt.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--resume"):
        module._prepare_unit_artifacts(_unit(), paths, resume=False)


def test_manifest_is_fixed_and_validated(monkeypatch, tmp_path):
    module = _load_runner(monkeypatch)
    manifest = pd.DataFrame([_unit()])
    captured = {}
    monkeypatch.setattr(module, "load_pilot_config", lambda repo: {"pilot_manifest": "x"})
    monkeypatch.setattr(pd, "read_csv", lambda path: manifest)

    def validate(frame, config):
        captured["frame"] = frame
        captured["config"] = config
        return {"work_units": 1}

    monkeypatch.setattr(module, "validate_pilot_manifest", validate)
    _, frame = module._prepare_repository(tmp_path)

    assert frame is manifest
    assert captured["config"]["pilot_manifest"] == "x"


def test_worker_records_actual_thread_policy(monkeypatch, tmp_path):
    module = _load_runner(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        module,
        "evaluate_pilot_work_unit",
        lambda repo, unit: [{"evaluation_id": "x", "status": "SUCCESS"}],
    )

    def fake_run(unit, result, lock, compute, **kwargs):
        captured["computed"] = compute(unit, 1)
        captured["kwargs"] = kwargs
        return {"work_unit_id": "wu", "status": "SUCCESS"}

    monkeypatch.setattr(module, "run_work_unit", fake_run)
    paths = module._unit_paths(tmp_path, "wu")
    outcome = module._run_pilot_unit(str(tmp_path), _unit(), True)

    assert outcome["status"] == "SUCCESS"
    assert captured["computed"]["resource_policy"] == {
        "workers": 1,
        "numeric_threads": 1,
        "environment": {name: "1" for name in THREAD_VARIABLES},
    }
    assert captured["kwargs"]["max_attempts"] == 3
    assert captured["kwargs"]["attempt_state_path"] == paths.attempt


def test_runner_has_no_formal_or_holdout_output_path(monkeypatch):
    module = _load_runner(monkeypatch)
    source = RUNNER_PATH.read_text(encoding="utf-8").lower()

    assert "formal_v2_1" not in source
    assert "holdout" not in source
    assert "results/pilot_v2_1" in source.replace("\\", "/")
