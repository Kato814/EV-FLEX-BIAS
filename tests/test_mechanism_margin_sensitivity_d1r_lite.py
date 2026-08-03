from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from evflex.mechanism_margin_sensitivity_d1r_lite import (
    load_margin_config,
    load_margin_source,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_source_tree(destination: Path) -> None:
    config = load_margin_config(REPO_ROOT)
    relative_paths = {
        "config/mechanism_margin_sensitivity_v2_1_d1r_lite.json",
        "manifests/mechanism_diagnostic_pairs_v2_1.csv",
        *(item["path"] for item in config["frozen_sources"]),
    }
    for pair_id in config["source_pair_order"]:
        relative_paths.add(
            config["artifact_names"]["source_case_artifact_pattern"].format(
                pair_id=pair_id
            )
        )
    for relative in sorted(relative_paths):
        source = REPO_ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def test_margin_config_freezes_candidate_bands_gate_and_zero_power_flows() -> None:
    config = load_margin_config(REPO_ROOT)

    assert config["candidate_family"] == "VMAX"
    assert config["voltage_guard_bands_pu"] == [0.0, 1e-6, 1e-5, 1e-4]
    assert config["decisive_guard_band_pu"] == 1e-5
    assert config["minimum_cases"] == 8
    assert config["minimum_clusters"] == 3
    assert config["new_power_flow_solves"] == 0
    assert config["formal_v2_1_run_authorized"] is False


def test_source_loader_accepts_exact_archived_twelve_case_evidence() -> None:
    source = load_margin_source(REPO_ROOT, load_margin_config(REPO_ROOT))

    assert len(source["cases"]) == 12
    assert len(source["artifacts"]) == 12
    assert source["report"]["qualifying_families"] == ["VMAX"]


def test_source_loader_rejects_frozen_hash_or_case_drift(tmp_path: Path) -> None:
    frozen_root = tmp_path / "frozen_hash_drift"
    _copy_source_tree(frozen_root)
    report_path = frozen_root / "reports/mechanism_diagnostic_v2_1_d1r_lite.json"
    report_path.write_bytes(report_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="frozen source hash drift"):
        load_margin_source(frozen_root, load_margin_config(frozen_root))

    case_root = tmp_path / "case_hash_drift"
    _copy_source_tree(case_root)
    case_path = (
        case_root
        / "results/mechanism_diagnostic_v2_1_d1r_lite/cases/case_01.json"
    )
    case_path.write_bytes(case_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="case artifact hash drift"):
        load_margin_source(case_root, load_margin_config(case_root))
