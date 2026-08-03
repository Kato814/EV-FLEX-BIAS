from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from evflex.numerical_certainty_replay_d1r_lite import (
    load_replay_config,
    load_replay_source,
    select_replay_cases,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_frozen_replay_inputs(destination: Path) -> None:
    config = load_replay_config(REPO_ROOT)
    paths = {
        "config/numerical_certainty_replay_v2_1_d1r_lite.json",
        "manifests/mechanism_diagnostic_pairs_v2_1.csv",
        *(item["path"] for item in config["frozen_sources"]),
    }
    for pair_id in config["source_pair_order"]:
        paths.add(
            config["source_artifact_names"]["case_artifact_pattern"].format(
                pair_id=pair_id
            )
        )
    for relative in sorted(paths):
        source = REPO_ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _selection_row(
    pair_id: str,
    cluster: str,
    exceedance: float,
    *,
    slot: int = 1,
    metric_id: str = "V:test.1",
) -> dict[str, object]:
    return {
        "pair_id": pair_id,
        "stage": "B",
        "execution_order": int(pair_id),
        "scenario_cluster": cluster,
        "source_evaluation_id": f"evaluation_{pair_id}",
        "alpha": 0.5,
        "alpha_label": "0.500",
        "selected_slot": slot,
        "constraint_family": "VMAX",
        "metric_id": metric_id,
        "object_id": metric_id.removeprefix("V:"),
        "direction": "hi",
        "value": 1.06 + exceedance,
        "limit": 1.06,
        "exceedance": exceedance,
        "audited_schedule_sha256": "a" * 64,
    }


def test_replay_config_freezes_three_settings_and_scope() -> None:
    config = load_replay_config(REPO_ROOT)

    assert config["selected_pair_ids"] == ["01", "05", "08", "12"]
    assert [item["label"] for item in config["solver_settings"]] == [
        "NATIVE_1E4",
        "TIGHT_1E6",
        "ULTRA_1E8",
    ]
    assert [
        item["convergence_tolerance"] for item in config["solver_settings"]
    ] == [1e-4, 1e-6, 1e-8]
    assert config["target_replay_evaluations"] == 12
    assert config["formal_v2_1_run_authorized"] is False


def test_source_selection_rederives_exact_four_representatives() -> None:
    source = load_replay_source(REPO_ROOT, load_replay_config(REPO_ROOT))

    assert [item["pair_id"] for item in source["selected"]] == [
        "01",
        "05",
        "08",
        "12",
    ]
    assert [item["selected_slot"] for item in source["selected"]] == [
        28,
        48,
        56,
        75,
    ]
    assert [item["metric_id"] for item in source["selected"]] == [
        "V:860.1",
        "V:563.1",
        "V:900.1",
        "V:780.3",
    ]


def test_selection_uses_closest_exceedance_then_pair_id() -> None:
    rows = [
        _selection_row("02", "cluster_a", 9e-6),
        _selection_row("01", "cluster_a", 11e-6),
        _selection_row("03", "cluster_a", 3e-5),
    ]

    selected = select_replay_cases(rows, ["cluster_a"], guard_band=1e-5)

    assert [item["pair_id"] for item in selected] == ["01"]


def test_source_loader_rejects_n0_or_case_hash_drift(tmp_path: Path) -> None:
    n0_root = tmp_path / "n0"
    _copy_frozen_replay_inputs(n0_root)
    n0_path = n0_root / "reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json"
    n0_path.write_bytes(n0_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="frozen source hash drift"):
        load_replay_source(n0_root, load_replay_config(n0_root))

    case_root = tmp_path / "case"
    _copy_frozen_replay_inputs(case_root)
    case_path = (
        case_root
        / "results/mechanism_diagnostic_v2_1_d1r_lite/cases/case_01.json"
    )
    case_path.write_bytes(case_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="case artifact hash drift"):
        load_replay_source(case_root, load_replay_config(case_root))
