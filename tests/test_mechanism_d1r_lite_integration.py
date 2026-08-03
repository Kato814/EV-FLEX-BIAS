from __future__ import annotations

from pathlib import Path

from evflex.mechanism_diagnostic_d1r_lite import (
    load_lite_config,
    real_runtime_preflight,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pair_01_real_runtime_baseline_matches_all_96_context_records() -> None:
    config = load_lite_config(REPO_ROOT)

    summary = real_runtime_preflight(REPO_ROOT, config)

    assert summary == {
        "status": "PREFLIGHT_OK",
        "pair_id": "01",
        "record_count": 96,
        "adapter_schema": "evflex.pilot.network-audit",
        "adapter_version": 2,
        "identity_mismatch_count": 0,
        "writes_performed": False,
        "formal_v2_1_run_started": False,
    }
