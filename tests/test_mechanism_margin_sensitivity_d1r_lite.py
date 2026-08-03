from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from evflex.mechanism_margin_sensitivity_d1r_lite import (
    compute_margin_sensitivity,
    load_margin_config,
    load_margin_source,
    validate_margin_result,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


_CLUSTERS = {
    "01": "lv906_1900_18",
    "02": "lv906_1900_18",
    "03": "lv906_0000_11",
    "04": "lv906_0000_11",
    "05": "lv906_0000_11",
    "06": "lv906_0000_11",
    "07": "lv906_0200_03",
    "08": "lv906_0200_03",
    "09": "lv906_0200_03",
    "10": "lv906_0600_02",
    "11": "lv906_0600_02",
    "12": "lv906_0600_02",
}


def _row(family: str, exceedance: float) -> dict[str, object]:
    return {
        "constraint_family": family,
        "exceedance": exceedance,
        "is_physical_violation": True,
    }


def _synthetic_source(
    support: dict[str, list[dict[str, object]]],
    *,
    clusters: dict[str, str] | None = None,
) -> dict[str, object]:
    config = load_margin_config(REPO_ROOT)
    cluster_by_pair = _CLUSTERS if clusters is None else clusters
    cases = [
        {"pair_id": pair_id, "scenario_cluster": cluster_by_pair[pair_id]}
        for pair_id in config["source_pair_order"]
    ]
    artifacts = [
        {
            "pair_id": case["pair_id"],
            "scenario_cluster": case["scenario_cluster"],
            "status": "SUCCESS",
            "audits": [
                {
                    "audit_point": "BOUNDARY_INFEASIBLE",
                    "selected_slot": {
                        "simultaneous_violations": support.get(
                            str(case["pair_id"]), []
                        )
                    },
                }
            ],
        }
        for case in cases
    ]
    return {
        "report": {
            "decision": "COMMON_CANDIDATE_CONFOUNDED",
            "actual_cases": 12,
            "actual_target_audits": 16,
            "qualifying_families": ["VMAX"],
        },
        "cases": cases,
        "artifacts": artifacts,
        "hash_rows": [
            {
                "pair_id": pair_id,
                "stage": "A" if index < 4 else "B",
                "status": "SUCCESS",
                "path": config["artifact_names"][
                    "source_case_artifact_pattern"
                ].format(pair_id=pair_id),
                "sha256": f"{index + 1:064x}",
            }
            for index, pair_id in enumerate(config["source_pair_order"])
        ],
        "frozen_source_hashes": {
            item["path"]: item["sha256"] for item in config["frozen_sources"]
        },
    }


def _support_row(
    result: dict[str, object], family: str, guard_band: float
) -> dict[str, object]:
    return next(
        row
        for row in result["support"]
        if row["constraint_family"] == family
        and row["guard_band"] == guard_band
    )


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


def test_guard_band_counts_case_presence_not_metric_rows() -> None:
    source = _synthetic_source(
        {"01": [_row("VMAX", 2e-5), _row("VMAX", 3e-5)]}
    )

    result = compute_margin_sensitivity(source, load_margin_config(REPO_ROOT))
    support = _support_row(result, "VMAX", 1e-5)

    assert support["case_count"] == 1
    assert support["metric_witness_count"] == 2
    assert support["pair_ids"] == ["01"]


def test_guard_band_comparison_is_inclusive_at_exact_threshold() -> None:
    source = _synthetic_source({"01": [_row("VMAX", 1e-5)]})

    result = compute_margin_sensitivity(source, load_margin_config(REPO_ROOT))

    assert _support_row(result, "VMAX", 1e-5)["pair_ids"] == ["01"]


def test_cluster_support_counts_unique_clusters() -> None:
    source = _synthetic_source(
        {
            pair_id: [_row("VMAX", 2e-5)]
            for pair_id in ["01", "02", "04", "03", "05", "07", "08", "10"]
        }
    )

    result = compute_margin_sensitivity(source, load_margin_config(REPO_ROOT))
    support = _support_row(result, "VMAX", 1e-5)

    assert support["case_count"] == 8
    assert support["scenario_cluster_count"] == 4
    assert support["scenario_clusters"] == [
        "lv906_1900_18",
        "lv906_0000_11",
        "lv906_0200_03",
        "lv906_0600_02",
    ]


@pytest.mark.parametrize(
    ("pair_ids", "expected"),
    [
        (
            ["01", "04", "07", "10", "02", "03", "08", "11"],
            "MARGIN_ROBUST_AT_1E5",
        ),
        (
            ["01", "04", "07", "10", "02", "03", "08"],
            "HOLD_MARGIN_FRAGILE_AT_1E5",
        ),
    ],
)
def test_decisive_band_returns_robust_only_at_eight_cases_and_three_clusters(
    pair_ids: list[str], expected: str
) -> None:
    source = _synthetic_source(
        {pair_id: [_row("VMAX", 1e-5)] for pair_id in pair_ids}
    )

    result = compute_margin_sensitivity(source, load_margin_config(REPO_ROOT))

    assert result["decision"] == expected
    validate_margin_result(result, load_margin_config(REPO_ROOT))


def test_decisive_band_also_requires_three_clusters() -> None:
    config = load_margin_config(REPO_ROOT)
    cluster_order = [
        "synthetic_a",
        "synthetic_a",
        "synthetic_a",
        "synthetic_a",
        "synthetic_b",
        "synthetic_b",
        "synthetic_b",
        "synthetic_b",
        "synthetic_c",
        "synthetic_c",
        "synthetic_d",
        "synthetic_d",
    ]
    clusters = dict(zip(config["source_pair_order"], cluster_order, strict=True))
    supported = config["source_pair_order"][:8]
    source = _synthetic_source(
        {pair_id: [_row("VMAX", 1e-5)] for pair_id in supported},
        clusters=clusters,
    )

    result = compute_margin_sensitivity(source, config)

    assert result["decisive_support"]["case_count"] == 8
    assert result["decisive_support"]["scenario_cluster_count"] == 2
    assert result["decision"] == "HOLD_MARGIN_FRAGILE_AT_1E5"


def test_margin_result_preserves_frozen_band_and_family_order() -> None:
    result = compute_margin_sensitivity(
        _synthetic_source({}), load_margin_config(REPO_ROOT)
    )

    assert [
        (row["constraint_family"], row["guard_band"])
        for row in result["support"]
    ] == [
        ("VMIN", 0.0),
        ("VMIN", 1e-6),
        ("VMIN", 1e-5),
        ("VMIN", 1e-4),
        ("VMAX", 0.0),
        ("VMAX", 1e-6),
        ("VMAX", 1e-5),
        ("VMAX", 1e-4),
        ("VUF", 0.0),
        ("TRANSFORMER", 0.0),
        ("FEEDER", 0.0),
    ]


def test_non_voltage_families_are_not_filtered_by_voltage_guard_bands() -> None:
    result = compute_margin_sensitivity(
        _synthetic_source({"01": [_row("TRANSFORMER", 1e-12)]}),
        load_margin_config(REPO_ROOT),
    )
    rows = [
        row
        for row in result["support"]
        if row["constraint_family"] == "TRANSFORMER"
    ]

    assert len(rows) == 1
    assert rows[0]["guard_band"] == 0.0
    assert rows[0]["guard_band_applied"] is False
    assert rows[0]["case_count"] == 1
