from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_transferability_dev_v2_2.py"
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
    spec = importlib.util.spec_from_file_location("v22_dev_runner_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unit():
    return {
        "work_unit_id": "v22_dev_ieee13_1900_05__inc",
        "protocol_version": "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-DEV",
        "scenario_id": "ieee13_1900_05",
        "scenario_seed": 2026071604,
        "data_role": "development_transferability",
        "evaluation_ids": json.dumps(
            [
                "v22_dev_ieee13_1900_05__inc__15m",
                "v22_dev_ieee13_1900_05__inc__30m",
                "v22_dev_ieee13_1900_05__inc__60m",
            ]
        ),
    }


def test_import_forces_single_numeric_thread_before_scientific_imports(monkeypatch):
    module = _load_runner(monkeypatch)

    assert module.THREAD_ENVIRONMENT == {name: "1" for name in THREAD_VARIABLES}
    assert all(os.environ[name] == "1" for name in THREAD_VARIABLES)


def test_workers_other_than_one_are_rejected_before_design_access(
    monkeypatch, tmp_path
):
    module = _load_runner(monkeypatch)
    called = []
    monkeypatch.setattr(
        module, "load_development_design", lambda *_: called.append(True)
    )

    with pytest.raises(SystemExit, match="exactly 1"):
        module.main(["--workers", "2"], repo_root=tmp_path)

    assert called == []
    assert list(tmp_path.iterdir()) == []


def test_compute_passes_frozen_config_and_records_provenance(monkeypatch, tmp_path):
    module = _load_runner(monkeypatch)
    captured = {}
    config = {
        "protocol_version": "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-DEV",
        "source_manifest_sha256": "a" * 64,
        "_config_sha256": "b" * 64,
    }

    def fake_evaluate(root, unit, *, config):
        captured["root"] = root
        captured["unit"] = unit
        captured["config"] = config
        return [
            {"evaluation_id": value, "status": "SUCCESS"}
            for value in json.loads(unit["evaluation_ids"])
        ]

    monkeypatch.setattr(module, "evaluate_pilot_work_unit", fake_evaluate)
    monkeypatch.setattr(module, "_git_commit", lambda *_: "c" * 40)

    payload = module._compute_payload(tmp_path, _unit(), config)

    assert captured == {"root": tmp_path, "unit": _unit(), "config": config}
    assert payload["resource_policy"] == {
        "workers": 1,
        "numeric_threads": 1,
        "environment": {name: "1" for name in THREAD_VARIABLES},
    }
    assert payload["run_provenance"] == {
        "code_commit": "c" * 40,
        "config_sha256": "b" * 64,
        "source_manifest_sha256": "a" * 64,
        "holdout_access": "prohibited",
        "output_namespace": "results/transferability_dev_v2_2",
    }
    assert len(payload["evaluations"]) == 3
