from __future__ import annotations

import csv
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from evflex.mechanism_diagnostic import (
    build_count_match_rows,
    candidate_families,
    classify_count_match,
    compact_targeted_audit,
    constraint_rows_from_slot,
    exact_count_match_probability,
    load_mechanism_config,
    load_pair_manifest,
    pair_members,
    relative_stress_evidence,
    verify_frozen_sources,
)


REPO_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_COLUMNS = (
    "pair_id",
    "scenario_cluster",
    "bad_evaluation_id",
    "bad_work_unit_id",
    "bad_scenario_id",
    "bad_scenario_seed",
    "bad_feeder",
    "bad_call_time",
    "bad_direction",
    "duration_min",
    "bad_alpha_transfer",
    "bad_source_duration_min",
    "bad_schedule_sha256",
    "bad_bus_phase_time_sha256",
    "bad_baseline_schedule_sha256",
    "control_evaluation_id",
    "control_work_unit_id",
    "control_scenario_id",
    "control_scenario_seed",
    "control_feeder",
    "control_call_time",
    "control_direction",
    "control_alpha_transfer",
    "control_source_duration_min",
    "control_schedule_sha256",
    "control_bus_phase_time_sha256",
    "control_baseline_schedule_sha256",
)

PAIR_IDENTITIES = (
    (
        "01",
        "lv906_1900_18",
        "v20_core_lv906_1900_18__dec__15m",
        "v20_core_ieee13_1900_17__dec__15m",
    ),
    (
        "02",
        "lv906_1900_18",
        "v20_core_lv906_1900_18__dec__30m",
        "v20_core_ieee13_1900_17__dec__30m",
    ),
    (
        "03",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__inc__15m",
        "v20_core_ieee13_0000_09__inc__15m",
    ),
    (
        "04",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__inc__30m",
        "v20_core_ieee13_0000_09__inc__30m",
    ),
    (
        "05",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__dec__15m",
        "v20_core_ieee13_0000_09__dec__15m",
    ),
    (
        "06",
        "lv906_0000_11",
        "v20_core_lv906_0000_11__dec__30m",
        "v20_core_ieee13_0000_09__dec__30m",
    ),
    (
        "07",
        "lv906_0200_03",
        "v20_core_lv906_0200_03__dec__15m",
        "v20_core_ieee13_0200_17__dec__15m",
    ),
    (
        "08",
        "lv906_0200_03",
        "v20_core_lv906_0200_03__dec__30m",
        "v20_core_ieee13_0200_17__dec__30m",
    ),
    (
        "09",
        "lv906_0200_03",
        "v20_core_lv906_0200_03__dec__60m",
        "v20_core_ieee13_0200_17__dec__60m",
    ),
    (
        "10",
        "lv906_0600_02",
        "v20_core_lv906_0600_02__dec__15m",
        "v20_core_ieee13_0600_24__dec__15m",
    ),
    (
        "11",
        "lv906_0600_02",
        "v20_core_lv906_0600_02__dec__30m",
        "v20_core_ieee13_0600_24__dec__30m",
    ),
    (
        "12",
        "lv906_0600_02",
        "v20_core_lv906_0600_02__dec__60m",
        "v20_core_ieee13_0600_24__dec__60m",
    ),
)

EXPECTED_SOURCE_FIELDS = {
    "v20_core_lv906_1900_18__dec__15m": (
        "v20_work_lv906_1900_18__dec",
        "lv906_1900_18",
        2026072017,
        "lv906",
        "19:00",
        "dec",
        15,
        15,
        0.940,
        "1f68cba3e80904535c4a95e428a40893196da61db4327567f86c9b4b994b990f",
        "71cfbde690781c27e1046b3447b791b8f3071a60f07fd6601c8e557914293090",
        "8f21edcd9ddd0481d1fb432b2a5e84228d230969513db0f7414427c16335f4b8",
    ),
    "v20_core_ieee13_1900_17__dec__15m": (
        "v20_work_ieee13_1900_17__dec",
        "ieee13_1900_17",
        2026071616,
        "ieee13",
        "19:00",
        "dec",
        15,
        15,
        1.0,
        "e57f41b2819b802cf4a42576c56917808f994c16e8ecd45d14d05767892d75b6",
        "37e5f9b99813d6ee22a0ae09e948213e52ab686e4b15b0486d36da28c5630846",
        "6280af04e4c13212c2ad5bfaa178151743c9628d27ec0378f333ebe9450b7dd4",
    ),
    "v20_core_lv906_1900_18__dec__30m": (
        "v20_work_lv906_1900_18__dec",
        "lv906_1900_18",
        2026072017,
        "lv906",
        "19:00",
        "dec",
        30,
        30,
        0.940,
        "4e7c01cef3d42bb23e157e651acf864712a972e6779f99a4bc721cb24c783869",
        "8187efb60493e97b30272046e05bd14eaffd270dbf071eccbd81f2e3ed8b9383",
        "8f21edcd9ddd0481d1fb432b2a5e84228d230969513db0f7414427c16335f4b8",
    ),
    "v20_core_ieee13_1900_17__dec__30m": (
        "v20_work_ieee13_1900_17__dec",
        "ieee13_1900_17",
        2026071616,
        "ieee13",
        "19:00",
        "dec",
        30,
        30,
        1.0,
        "e6c3ac9010e84ec10023f6b8a3bd2aafc410209688a3ba2b628a5afccd822fe4",
        "5472d1ef568df0a5534880138534a1e64c0b94e64c325720b3834b27651984da",
        "6280af04e4c13212c2ad5bfaa178151743c9628d27ec0378f333ebe9450b7dd4",
    ),
    "v20_core_lv906_0000_11__inc__15m": (
        "v20_work_lv906_0000_11__inc",
        "lv906_0000_11",
        2026072110,
        "lv906",
        "00:00",
        "inc",
        15,
        15,
        0.642,
        "8955072b1d0202673c9e1f118a3b9fb766991cd5444898f431dcfb0467eca726",
        "aea7821330207208d720952d57d846538261a7a17d0aac6ca9cb14f1a0d56ba2",
        "1d7765467d66427bbac6c5e69e4c6bffdd204b2c3d24492239ee3a8628e3df41",
    ),
    "v20_core_ieee13_0000_09__inc__15m": (
        "v20_work_ieee13_0000_09__inc",
        "ieee13_0000_09",
        2026071708,
        "ieee13",
        "00:00",
        "inc",
        15,
        15,
        1.0,
        "c4e5006252cfec4706bd40789c6111db38850439f7f372f9df1548e9a457cd4f",
        "9e0f5c2f74ba9fc3873a663f0a898171cd374210e6c3bcf490e47d9c0a713629",
        "04ee74df9e3fbce9a17dc87d569d0f46e085cb8db94114d75154f0ae813ad0a2",
    ),
    "v20_core_lv906_0000_11__inc__30m": (
        "v20_work_lv906_0000_11__inc",
        "lv906_0000_11",
        2026072110,
        "lv906",
        "00:00",
        "inc",
        30,
        30,
        0.696,
        "fd30a554b39970350ee3412d118ef1f2cf95c4fec24e1e412c43ef521f6a05d3",
        "dec07f7be1ed452b4d2f2242c160504bab1bec8a2aab1d177504aaeaccaa0a1b",
        "1d7765467d66427bbac6c5e69e4c6bffdd204b2c3d24492239ee3a8628e3df41",
    ),
    "v20_core_ieee13_0000_09__inc__30m": (
        "v20_work_ieee13_0000_09__inc",
        "ieee13_0000_09",
        2026071708,
        "ieee13",
        "00:00",
        "inc",
        30,
        30,
        1.0,
        "e1e00637a5ad817641158236c20e35cdf677919260aeb083485a5804f130edbd",
        "ca6307113619eb9e415c9a209e28563b934767592f8109b985c3582c9d37671e",
        "04ee74df9e3fbce9a17dc87d569d0f46e085cb8db94114d75154f0ae813ad0a2",
    ),
    "v20_core_lv906_0000_11__dec__15m": (
        "v20_work_lv906_0000_11__dec",
        "lv906_0000_11",
        2026072110,
        "lv906",
        "00:00",
        "dec",
        15,
        15,
        0.706,
        "fcfdec9319eba8a919124465f5a5e61828ad318aecc34517fa8d2b03f564438b",
        "6b2923d71ba224233cd04a22faa69226c316d3a2106946c8aef8ad5df4ad741f",
        "1d7765467d66427bbac6c5e69e4c6bffdd204b2c3d24492239ee3a8628e3df41",
    ),
    "v20_core_ieee13_0000_09__dec__15m": (
        "v20_work_ieee13_0000_09__dec",
        "ieee13_0000_09",
        2026071708,
        "ieee13",
        "00:00",
        "dec",
        15,
        15,
        1.0,
        "a90140274d045a7af4173dedaf92d5ea62d2408678cefe9d7b6fabde9bffc614",
        "694f15d3aacf6ee478384388a53bdd070d3db5d655c914308bdd2a81f8026af9",
        "04ee74df9e3fbce9a17dc87d569d0f46e085cb8db94114d75154f0ae813ad0a2",
    ),
    "v20_core_lv906_0000_11__dec__30m": (
        "v20_work_lv906_0000_11__dec",
        "lv906_0000_11",
        2026072110,
        "lv906",
        "00:00",
        "dec",
        30,
        30,
        0.706,
        "463bcf060c165c8bc8064024f4c6f2ea518f5e01eeaf1dc4ccc92f6336219cd3",
        "36f9c7fa56ad43f20751a4114d78cd9bc256113c3dc190c797593b11dd6f693c",
        "1d7765467d66427bbac6c5e69e4c6bffdd204b2c3d24492239ee3a8628e3df41",
    ),
    "v20_core_ieee13_0000_09__dec__30m": (
        "v20_work_ieee13_0000_09__dec",
        "ieee13_0000_09",
        2026071708,
        "ieee13",
        "00:00",
        "dec",
        30,
        30,
        1.0,
        "310825fb84d7053496840597299b721dd4b5eba29d9b3e38c36495e3eddc96e2",
        "355061ebeea1b36fef57c1541b071101bcc092e63a53c8f5acf542026294291f",
        "04ee74df9e3fbce9a17dc87d569d0f46e085cb8db94114d75154f0ae813ad0a2",
    ),
    "v20_core_lv906_0200_03__dec__15m": (
        "v20_work_lv906_0200_03__dec",
        "lv906_0200_03",
        2026072202,
        "lv906",
        "02:00",
        "dec",
        15,
        15,
        0.686,
        "693c4626652c6e9256c36200009658799bd2375db3cffa010b7a565be7181a57",
        "1e97cc9061575169e3ab0ad290fa2603a2bf528cf342f292011afc26dc2d997b",
        "39d9c49724617d9691122eb999d1a4beb1eb45741be7a2865ce74b7b63570e44",
    ),
    "v20_core_ieee13_0200_17__dec__15m": (
        "v20_work_ieee13_0200_17__dec",
        "ieee13_0200_17",
        2026071816,
        "ieee13",
        "02:00",
        "dec",
        15,
        15,
        1.0,
        "c5d569067322dd45cf3233e24ff614783aa25b0e0a3fd070c638b1ca27a4c687",
        "fcb84491713d381d992b700293823865494ab555dada3cde65ecaa67a0a558f9",
        "e3ad35458b2922c52b17b6dca86c021f473d5e856b3166c7364d06b7b59ae2eb",
    ),
    "v20_core_lv906_0200_03__dec__30m": (
        "v20_work_lv906_0200_03__dec",
        "lv906_0200_03",
        2026072202,
        "lv906",
        "02:00",
        "dec",
        30,
        30,
        0.686,
        "aa517e059c7d7424b4460691c94120164ed6dcf788727f3d7df4e84adcb080dc",
        "cfe36dd9932bdbdc7f8ce911965d9d361689b7ee7e71c8799440d7904bcb2924",
        "39d9c49724617d9691122eb999d1a4beb1eb45741be7a2865ce74b7b63570e44",
    ),
    "v20_core_ieee13_0200_17__dec__30m": (
        "v20_work_ieee13_0200_17__dec",
        "ieee13_0200_17",
        2026071816,
        "ieee13",
        "02:00",
        "dec",
        30,
        30,
        1.0,
        "ea799b296a12ed797038c6785ea3396cf6d5099ffd638c9bcd1e729f7faad474",
        "be5ab1e8af2ac865625060db976c083ff2671a02407858cbb3cd8f1419b892c4",
        "e3ad35458b2922c52b17b6dca86c021f473d5e856b3166c7364d06b7b59ae2eb",
    ),
    "v20_core_lv906_0200_03__dec__60m": (
        "v20_work_lv906_0200_03__dec",
        "lv906_0200_03",
        2026072202,
        "lv906",
        "02:00",
        "dec",
        60,
        60,
        0.824,
        "410aaee3f06ff485e9fc7ceec862177d888d905a8a1e266179b394afb9d8c8b0",
        "76e938d0d90f28b63e3922b96f51228b20d2c321f15e46d750498b5ad28a2a1d",
        "39d9c49724617d9691122eb999d1a4beb1eb45741be7a2865ce74b7b63570e44",
    ),
    "v20_core_ieee13_0200_17__dec__60m": (
        "v20_work_ieee13_0200_17__dec",
        "ieee13_0200_17",
        2026071816,
        "ieee13",
        "02:00",
        "dec",
        60,
        60,
        1.0,
        "e1f58abf4d67977f22889b1f3453b6580dcf2da332ea44ad15321451ec4ad1a8",
        "2bcf890b78072d174bb19b56715be45b5f8da36cf04f26b3b7752c26687401e1",
        "e3ad35458b2922c52b17b6dca86c021f473d5e856b3166c7364d06b7b59ae2eb",
    ),
    "v20_core_lv906_0600_02__dec__15m": (
        "v20_work_lv906_0600_02__dec",
        "lv906_0600_02",
        2026072301,
        "lv906",
        "06:00",
        "dec",
        15,
        15,
        0.616,
        "eef1efae898d72846510f63500523cf62e8eb63f1ac1962803520e0610d309c0",
        "6a7104af350a84550578157aa0f436772981dbe9e4c97679fbc30511b19f7cb3",
        "0413df92fe9a7567109e99156d3d079e668f4a6063ad6b67c7fef5c689c934ac",
    ),
    "v20_core_ieee13_0600_24__dec__15m": (
        "v20_work_ieee13_0600_24__dec",
        "ieee13_0600_24",
        2026071923,
        "ieee13",
        "06:00",
        "dec",
        15,
        15,
        1.0,
        "777823eea79d5b403218d652d1dda02f22272c14da06bf2357f6156eb604b90f",
        "c0af66696a49e2b1f65d9db77718de6efd7cfb016e0a3104418a9f0e7924b9e1",
        "8dca25aa799502db5013e0986160d8fceebe65459fbccd98931510d8863eb598",
    ),
    "v20_core_lv906_0600_02__dec__30m": (
        "v20_work_lv906_0600_02__dec",
        "lv906_0600_02",
        2026072301,
        "lv906",
        "06:00",
        "dec",
        30,
        30,
        0.616,
        "2644fd86960359706faadbda046e9491e6f0429507123eff2c6922294fcfb90a",
        "1d44166721edad23ad4fa037fb8c7364b198ca29a3beb5117856d1abb4cc4100",
        "0413df92fe9a7567109e99156d3d079e668f4a6063ad6b67c7fef5c689c934ac",
    ),
    "v20_core_ieee13_0600_24__dec__30m": (
        "v20_work_ieee13_0600_24__dec",
        "ieee13_0600_24",
        2026071923,
        "ieee13",
        "06:00",
        "dec",
        30,
        30,
        1.0,
        "e650ca7fe6f455397f5e93b6e220e013fe59b475bc13c50df9a4ae791eb46cd6",
        "2d1fd6f4d0a0b8b3b4197e2386961c1f65d9a6980a690ae0351e69690e10c7bb",
        "8dca25aa799502db5013e0986160d8fceebe65459fbccd98931510d8863eb598",
    ),
    "v20_core_lv906_0600_02__dec__60m": (
        "v20_work_lv906_0600_02__dec",
        "lv906_0600_02",
        2026072301,
        "lv906",
        "06:00",
        "dec",
        60,
        60,
        0.610,
        "44024a727160870392a4dfac05a267af1b4cea9383d5e8a7aaffcf58c0f083c6",
        "d6184863bf490fa07d24077c3cea7129b9d84c6dab9502405156524eb7224b70",
        "0413df92fe9a7567109e99156d3d079e668f4a6063ad6b67c7fef5c689c934ac",
    ),
    "v20_core_ieee13_0600_24__dec__60m": (
        "v20_work_ieee13_0600_24__dec",
        "ieee13_0600_24",
        2026071923,
        "ieee13",
        "06:00",
        "dec",
        60,
        60,
        1.0,
        "b934880605b880b4d01a343ce0fd334c940f32b45b82497534401ad96c7976e2",
        "15c6e364013858fedbfe713d1bc92ef6228b4929d73b1b5c7bb0f8362980afc1",
        "8dca25aa799502db5013e0986160d8fceebe65459fbccd98931510d8863eb598",
    ),
}


def _copy_protocol_files(destination: Path) -> None:
    for relative in (
        Path("config/mechanism_diagnostic_v2_1.json"),
        Path("manifests/mechanism_diagnostic_pairs_v2_1.csv"),
        Path("results/pilot_v2_1/pilot_evaluations_v2_1.csv"),
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)


def _rewrite_manifest_cell(
    destination: Path, column: str, value: str, *, row_index: int = 0
) -> None:
    path = destination / "manifests/mechanism_diagnostic_pairs_v2_1.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == MANIFEST_COLUMNS
    rows[row_index][column] = value
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _rewrite_archived_rows(destination: Path, rows: list[dict[str, str]]) -> None:
    path = destination / "results/pilot_v2_1/pilot_evaluations_v2_1.csv"
    with (REPO_ROOT / "results/pilot_v2_1/pilot_evaluations_v2_1.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        fieldnames = tuple(csv.DictReader(stream).fieldnames or ())
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _archived_rows(destination: Path) -> list[dict[str, str]]:
    path = destination / "results/pilot_v2_1/pilot_evaluations_v2_1.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_load_config_requires_exact_frozen_contract(tmp_path: Path) -> None:
    config = load_mechanism_config(REPO_ROOT)

    assert config["protocol_version"] == "EV-FLEX-BIAS-V2.1-D1-MECHANISM"
    assert config["source_protocol_version"] == "EV-FLEX-BIAS-V2.1-PILOT"
    assert config["source_commit"] == "e1740f912a351b1822b5ee019f9e4f05b6b71c6f"
    assert config["artifact_names"] == {
        "config": "config/mechanism_diagnostic_v2_1.json",
        "pair_manifest": "manifests/mechanism_diagnostic_pairs_v2_1.csv",
        "result_root": "results/mechanism_diagnostic_v2_1",
        "pair_artifact_pattern": (
            "results/mechanism_diagnostic_v2_1/pairs/pair_{pair_id}.json"
        ),
        "run_lock": "results/mechanism_diagnostic_v2_1/.run.lock",
        "attempt_pattern": (
            "results/mechanism_diagnostic_v2_1/.attempts/pair_{pair_id}.json"
        ),
        "audit_csv": "reports/mechanism_diagnostic_audits_v2_1.csv",
        "report_json": "reports/mechanism_diagnostic_v2_1.json",
        "report_markdown": "reports/mechanism_diagnostic_v2_1.md",
        "hashes_csv": "reports/mechanism_diagnostic_hashes_v2_1.csv",
    }
    assert config["expected_counts"] == {
        "pairs": 12,
        "sources": 24,
        "audits": 72,
    }
    assert config["pilot_py"] == {
        "path": "src/evflex/pilot.py",
        "sha256": "37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b",
    }
    assert config["audit"] == {
        "delta": 0.002,
        "point_order": [
            "BOUNDARY_FEASIBLE",
            "BOUNDARY_INFEASIBLE",
            "FULL_OFFER",
        ],
        "family_order": ["VMIN", "VMAX", "VUF", "TRANSFORMER", "FEEDER"],
    }
    assert config["candidate_thresholds"] == {
        "minimum_bad_cases": 8,
        "total_bad_cases": 12,
        "minimum_scenario_clusters": 3,
        "total_scenario_clusters": 4,
    }
    assert config["count_match_thresholds"] == {
        "high": {"numerator": 4, "denominator": 5},
        "low": {"numerator": 1, "denominator": 5},
        "minimum_eligible_rows": 4,
        "fraction_display_precision": 12,
    }
    assert config["relative_stress"] == {
        "reason_code": "RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR",
        "global_ratio": None,
        "phase_ratios": None,
    }
    assert config["line_thermal_in_scope"] is False
    assert config["resource_policy"] == {
        "workers": 1,
        "numeric_threads": {
            "OMP_NUM_THREADS": 1,
            "OPENBLAS_NUM_THREADS": 1,
            "MKL_NUM_THREADS": 1,
            "NUMEXPR_NUM_THREADS": 1,
            "VECLIB_MAXIMUM_THREADS": 1,
            "BLIS_NUM_THREADS": 1,
        },
    }
    assert {item["path"]: item["sha256"] for item in config["frozen_sources"]} == {
        "config/pilot_gate_v2_1.json": "1ecc530362e5bd51f144c85156e4bae93eb9ec30137238cf7041bf9887cb122b",
        "manifests/audit_pilot_work_units_v2_1.csv": "d7d5d0424935185de2d49bf5b9aa8524ca3abf66cd23e3677b5b70e5e5936615",
        "manifests/core_work_units_v2_0.csv": "856431b21d240010b44f0125de92ab7447bcef924c9d6987cf3caf12c2a6ce69",
        "reports/pilot_gate_v2_1.json": "041b0d3521c3fbb22ee45578936a72c623cb8c7749a0139f6e63238649551751",
        "reports/pilot_gate_v2_1.md": "30f0b639a1a1044ed92bd3ac86af446862d561c4720eda74cad3ac6c7b56e187",
        "reports/pilot_work_unit_hashes_v2_1.csv": "4f801c8a169f1569dee46f3398e505a4556c92096682569095fe1aea33d4131e",
        "results/pilot_v2_1/pilot_evaluations_v2_1.csv": "bfb22446390191bcbc39f4de3f9363f211a090e8022f89f91c1ef515a9cf547a",
        "results/pilot_v2_1/work_units/v20_work_ieee13_0000_09__dec.json": "3946ac043bfea3091a2e260df29f8d2615519f197512852d9dfbd6e8140a7a98",
        "results/pilot_v2_1/work_units/v20_work_ieee13_0000_09__inc.json": "a0613f67395b2c641c12a9018413b5de19a4e01825a3d5f8b9f414a0c3c1a718",
        "results/pilot_v2_1/work_units/v20_work_ieee13_0200_17__dec.json": "86f2665a4b7c3a855cf3d63c4d5e65371782264be2afdb232ffc8c3437ff1887",
        "results/pilot_v2_1/work_units/v20_work_ieee13_0600_24__dec.json": "c09edf990b50fcb699466f9d6b8d1d1065601969f9d7894a2f552d8288625df4",
        "results/pilot_v2_1/work_units/v20_work_ieee13_1900_17__dec.json": "cc482778e32c2f72918ca722ceeb7245d8edcbdc1da7014d36698f7c96ad744c",
        "results/pilot_v2_1/work_units/v20_work_lv906_0000_11__dec.json": "1d702bbc729243c8b4ef7ad2c49d275518202841e6320d497e261b178d059f2c",
        "results/pilot_v2_1/work_units/v20_work_lv906_0000_11__inc.json": "1e2e852140e3b44a0726323ce2ca0f397897e9dfe4d848b933ef1ffda0cee86c",
        "results/pilot_v2_1/work_units/v20_work_lv906_0200_03__dec.json": "c6110985a82d02379c822b84aebf48165fad56f91e9781dab5e338a8a99f1472",
        "results/pilot_v2_1/work_units/v20_work_lv906_0600_02__dec.json": "62a2c79561b81ec504558ebd50d4c61c03d432a6f73b4d2b54dc72beac9ac6ca",
        "results/pilot_v2_1/work_units/v20_work_lv906_1900_18__dec.json": "4146541d33ad30924edab28eaaf6546de6e32e2055de3a7b56445194cdaf058a",
        "scripts/run_pilot_gate_v2_1.py": "6489a712bf1a674a7995ad6f240af25647864aa4e1c2ae95db5768770a3212ba",
        "scripts/evaluate_pilot_gate_v2_1.py": "51dea1efb55c093e1fc368102d391c5483afef770ec27b6ad5c81caf747cd491",
    }

    target = tmp_path / "config" / "mechanism_diagnostic_v2_1.json"
    target.parent.mkdir(parents=True)
    mutated = json.loads(
        (REPO_ROOT / "config/mechanism_diagnostic_v2_1.json").read_text(
            encoding="utf-8"
        )
    )
    mutated["resource_policy"]["workers"] = 2
    target.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen contract"):
        load_mechanism_config(tmp_path)


def test_load_pair_manifest_has_exact_12_pairs_and_24_sources() -> None:
    pairs = load_pair_manifest(REPO_ROOT)

    assert [pair["pair_id"] for pair in pairs] == [f"{index:02d}" for index in range(1, 13)]
    assert [
        (
            pair["pair_id"],
            pair["scenario_cluster"],
            pair["bad_evaluation_id"],
            pair["control_evaluation_id"],
        )
        for pair in pairs
    ] == list(PAIR_IDENTITIES)
    assert {pair["scenario_cluster"] for pair in pairs} == {
        "lv906_1900_18",
        "lv906_0000_11",
        "lv906_0200_03",
        "lv906_0600_02",
    }

    sources = [member for pair in pairs for member in pair_members(pair)]
    assert len(sources) == 24
    assert len({source["evaluation_id"] for source in sources}) == 24
    assert {source["evaluation_id"] for source in sources} == set(
        EXPECTED_SOURCE_FIELDS
    )
    assert all(source["requested_duration_min"] == source["duration_min"] for source in sources)
    assert all(source["source_duration_min"] == source["duration_min"] for source in sources)
    assert all(source["alpha_transfer"] == 1.0 for source in sources if source["role"] == "control")
    assert [
        source["alpha_transfer"] for source in sources if source["role"] == "bad"
    ] == [0.940, 0.940, 0.642, 0.696, 0.706, 0.706, 0.686, 0.686, 0.824, 0.616, 0.616, 0.610]

    for source in sources:
        expected = EXPECTED_SOURCE_FIELDS[source["evaluation_id"]]
        assert (
            source["work_unit_id"],
            source["scenario_id"],
            source["scenario_seed"],
            source["feeder"],
            source["call_time"],
            source["direction"],
            source["duration_min"],
            source["source_duration_min"],
            source["alpha_transfer"],
            source["schedule_sha256"],
            source["bus_phase_time_sha256"],
            source["baseline_schedule_sha256"],
        ) == expected


def test_manifest_matches_archived_evaluation_rows() -> None:
    pairs = load_pair_manifest(REPO_ROOT)
    with (REPO_ROOT / "results/pilot_v2_1/pilot_evaluations_v2_1.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        archived_rows = {
            row["evaluation_id"]: row for row in csv.DictReader(stream)
        }

    for pair in pairs:
        bad, control = pair_members(pair)
        for member in (bad, control):
            archived = archived_rows[member["evaluation_id"]]
            assert archived["work_unit_id"] == member["work_unit_id"]
            assert archived["scenario_id"] == member["scenario_id"]
            assert int(archived["scenario_seed"]) == member["scenario_seed"]
            assert archived["feeder"] == member["feeder"]
            assert archived["call_time"] == member["call_time"]
            assert archived["direction"] == member["direction"]
            assert int(archived["duration_min"]) == member["duration_min"]
            assert int(archived["requested_duration_min"]) == member["requested_duration_min"]
            assert int(archived["source_duration_min"]) == member["source_duration_min"]
            assert float(archived["alpha_transfer"]) == member["alpha_transfer"]
            assert archived["schedule_sha256"] == member["schedule_sha256"]
            assert archived["bus_phase_time_sha256"] == member["bus_phase_time_sha256"]
            assert archived["baseline_schedule_sha256"] == member["baseline_schedule_sha256"]


@pytest.mark.parametrize("mutation", ["duplicate", "identity"])
def test_manifest_rejects_duplicate_or_mutated_identity(
    tmp_path: Path, mutation: str
) -> None:
    _copy_protocol_files(tmp_path)
    path = tmp_path / "manifests/mechanism_diagnostic_pairs_v2_1.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert tuple(reader.fieldnames or ()) == MANIFEST_COLUMNS

    if mutation == "duplicate":
        rows[1]["pair_id"] = rows[0]["pair_id"]
    else:
        rows[0]["bad_evaluation_id"] = "v20_core_lv906_1900_18__dec__60m"

    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="manifest"):
        load_pair_manifest(tmp_path)


@pytest.mark.parametrize("value", ["15.0", "1.5e1", "+15", "1_5"])
def test_manifest_rejects_noncanonical_ascii_integer_syntax(
    tmp_path: Path, value: str
) -> None:
    _copy_protocol_files(tmp_path)
    _rewrite_manifest_cell(tmp_path, "duration_min", value)

    with pytest.raises(
        ValueError,
        match=r"manifest row 2 duration_min must use canonical ASCII integer syntax",
    ):
        load_pair_manifest(tmp_path)


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        (
            "bad_scenario_seed",
            "9" * 1000,
            r"manifest row 2 bad_scenario_seed must be between 0 and 2147483647",
        ),
        (
            "bad_scenario_seed",
            "2147483648",
            r"manifest row 2 bad_scenario_seed must be between 0 and 2147483647",
        ),
        (
            "duration_min",
            "1441",
            r"manifest row 2 duration_min must be between 1 and 1440",
        ),
    ],
)
def test_manifest_rejects_oversized_or_out_of_range_integer(
    tmp_path: Path, column: str, value: str, expected: str
) -> None:
    _copy_protocol_files(tmp_path)
    _rewrite_manifest_cell(tmp_path, column, value)

    with pytest.raises(ValueError, match=expected):
        load_pair_manifest(tmp_path)


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        (
            "bad_alpha_transfer",
            "9.40e-1",
            r"manifest row 2 bad_alpha_transfer must use exactly three decimal places in 0.ddd form",
        ),
        (
            "bad_alpha_transfer",
            "0.9400",
            r"manifest row 2 bad_alpha_transfer must use exactly three decimal places in 0.ddd form",
        ),
        (
            "bad_alpha_transfer",
            "0." + ("0" * 400) + "1",
            r"manifest row 2 bad_alpha_transfer must use exactly three decimal places in 0.ddd form",
        ),
        (
            "control_alpha_transfer",
            "1e0",
            r"manifest row 2 control_alpha_transfer must be exactly 1.0",
        ),
        (
            "control_alpha_transfer",
            "1.00",
            r"manifest row 2 control_alpha_transfer must be exactly 1.0",
        ),
    ],
)
def test_manifest_rejects_noncanonical_alpha_syntax(
    tmp_path: Path, column: str, value: str, expected: str
) -> None:
    _copy_protocol_files(tmp_path)
    _rewrite_manifest_cell(tmp_path, column, value)

    with pytest.raises(ValueError, match=expected):
        load_pair_manifest(tmp_path)


def test_archive_alpha_is_compared_as_exact_decimal(tmp_path: Path) -> None:
    _copy_protocol_files(tmp_path)
    rows = _archived_rows(tmp_path)
    target = next(
        row
        for row in rows
        if row["evaluation_id"] == "v20_core_lv906_1900_18__dec__15m"
    )
    target["alpha_transfer"] = "0.9400000000000000000000000000000000000001"
    _rewrite_archived_rows(tmp_path, rows)

    with pytest.raises(
        ValueError,
        match=(
            r"manifest alpha_transfer mismatch with archive for "
            r"v20_core_lv906_1900_18__dec__15m"
        ),
    ):
        load_pair_manifest(tmp_path)


def test_archive_integer_rejects_noncanonical_syntax(tmp_path: Path) -> None:
    _copy_protocol_files(tmp_path)
    rows = _archived_rows(tmp_path)
    target = next(
        row
        for row in rows
        if row["evaluation_id"] == "v20_core_lv906_1900_18__dec__15m"
    )
    target["duration_min"] = "15.0"
    _rewrite_archived_rows(tmp_path, rows)

    with pytest.raises(
        ValueError,
        match=(
            r"archive v20_core_lv906_1900_18__dec__15m duration_min "
            r"must use canonical ASCII integer syntax"
        ),
    ):
        load_pair_manifest(tmp_path)


def test_source_hash_drift_is_rejected(tmp_path: Path) -> None:
    config = load_mechanism_config(REPO_ROOT)
    for source in config["frozen_sources"]:
        relative = Path(source["path"])
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    pilot_relative = Path(config["pilot_py"]["path"])
    pilot_target = tmp_path / pilot_relative
    pilot_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / pilot_relative, pilot_target)

    verify_frozen_sources(tmp_path, config)
    drifted = tmp_path / config["frozen_sources"][0]["path"]
    drifted.write_bytes(drifted.read_bytes() + b"\nDRIFT")

    with pytest.raises(ValueError, match="source hash drift"):
        verify_frozen_sources(tmp_path, config)


def test_source_hash_config_freezes_archived_pilot_runner_source() -> None:
    config = load_mechanism_config(REPO_ROOT)
    sources = {source["path"]: source["sha256"] for source in config["frozen_sources"]}

    assert sources.get("scripts/run_pilot_gate_v2_1.py") == (
        "6489a712bf1a674a7995ad6f240af25647864aa4e1c2ae95db5768770a3212ba"
    )


def test_source_hash_archived_pilot_runner_drift_is_rejected(
    tmp_path: Path,
) -> None:
    config = load_mechanism_config(REPO_ROOT)
    runner_source = next(
        (
            source
            for source in config["frozen_sources"]
            if source["path"] == "scripts/run_pilot_gate_v2_1.py"
        ),
        None,
    )
    assert runner_source == {
        "path": "scripts/run_pilot_gate_v2_1.py",
        "sha256": (
            "6489a712bf1a674a7995ad6f240af25647864aa4e1c2ae95db5768770a3212ba"
        ),
    }

    for source in config["frozen_sources"]:
        relative = Path(source["path"])
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    pilot_relative = Path(config["pilot_py"]["path"])
    pilot_target = tmp_path / pilot_relative
    pilot_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / pilot_relative, pilot_target)

    runner_target = tmp_path / runner_source["path"]
    runner_target.write_bytes(runner_target.read_bytes() + b"\nDRIFT")

    with pytest.raises(ValueError, match="source hash drift"):
        verify_frozen_sources(tmp_path, config)


def test_provenance_rejects_archive_schedule_hash_drift(tmp_path: Path) -> None:
    _copy_protocol_files(tmp_path)
    rows = _archived_rows(tmp_path)
    evaluation_id = "v20_core_lv906_1900_18__dec__15m"
    target = next(row for row in rows if row["evaluation_id"] == evaluation_id)
    target["schedule_sha256"] = "0" * 64
    _rewrite_archived_rows(tmp_path, rows)

    with pytest.raises(
        ValueError,
        match=rf"manifest schedule_sha256 mismatch with archive for {evaluation_id}",
    ):
        load_pair_manifest(tmp_path)


def test_provenance_rejects_missing_archive_evaluation_id(tmp_path: Path) -> None:
    _copy_protocol_files(tmp_path)
    rows = _archived_rows(tmp_path)
    evaluation_id = "v20_core_lv906_1900_18__dec__15m"
    rows = [row for row in rows if row["evaluation_id"] != evaluation_id]
    _rewrite_archived_rows(tmp_path, rows)

    with pytest.raises(
        ValueError,
        match=rf"manifest source ID is missing from archive: {evaluation_id}",
    ):
        load_pair_manifest(tmp_path)


def test_provenance_rejects_duplicate_archive_evaluation_id(tmp_path: Path) -> None:
    _copy_protocol_files(tmp_path)
    rows = _archived_rows(tmp_path)
    evaluation_id = "v20_core_lv906_1900_18__dec__15m"
    target = next(row for row in rows if row["evaluation_id"] == evaluation_id)
    rows.append(dict(target))
    _rewrite_archived_rows(tmp_path, rows)

    with pytest.raises(
        ValueError,
        match=(
            r"results/pilot_v2_1/pilot_evaluations_v2_1.csv: "
            rf"duplicate evaluation_id {evaluation_id}"
        ),
    ):
        load_pair_manifest(tmp_path)


def test_source_hash_provenance_rejects_direct_pilot_py_drift(
    tmp_path: Path,
) -> None:
    config = load_mechanism_config(REPO_ROOT)
    for source in config["frozen_sources"]:
        relative = Path(source["path"])
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    pilot_relative = Path(config["pilot_py"]["path"])
    pilot_target = tmp_path / pilot_relative
    pilot_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / pilot_relative, pilot_target)
    pilot_target.write_bytes(pilot_target.read_bytes() + b"\nDRIFT")

    with pytest.raises(
        ValueError,
        match=(
            r"source hash drift: src/evflex/pilot.py expected "
            r"37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b"
        ),
    ):
        verify_frozen_sources(tmp_path, config)


def test_provenance_rejects_duplicate_config_json_key(tmp_path: Path) -> None:
    source = (REPO_ROOT / "config/mechanism_diagnostic_v2_1.json").read_text(
        encoding="utf-8"
    )
    mutated = source.replace(
        '{\n  "protocol_version":',
        '{\n  "protocol_version": "DUPLICATE",\n  "protocol_version":',
        1,
    )
    target = tmp_path / "config/mechanism_diagnostic_v2_1.json"
    target.parent.mkdir(parents=True)
    target.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"config/mechanism_diagnostic_v2_1.json: "
            r"duplicate JSON key 'protocol_version'"
        ),
    ):
        load_mechanism_config(tmp_path)


def test_provenance_rejects_nonfinite_config_json_number(tmp_path: Path) -> None:
    source = (REPO_ROOT / "config/mechanism_diagnostic_v2_1.json").read_text(
        encoding="utf-8"
    )
    mutated = source.replace('"delta": 0.002', '"delta": NaN', 1)
    target = tmp_path / "config/mechanism_diagnostic_v2_1.json"
    target.parent.mkdir(parents=True)
    target.write_text(mutated, encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"config/mechanism_diagnostic_v2_1.json: "
            r"non-finite JSON number NaN"
        ),
    ):
        load_mechanism_config(tmp_path)


def test_provenance_rejects_duplicate_manifest_csv_header(tmp_path: Path) -> None:
    _copy_protocol_files(tmp_path)
    path = tmp_path / "manifests/mechanism_diagnostic_pairs_v2_1.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("pair_id,scenario_cluster", "pair_id,pair_id", 1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"manifests/mechanism_diagnostic_pairs_v2_1.csv: "
            r"duplicate CSV header pair_id"
        ),
    ):
        load_pair_manifest(tmp_path)


def test_provenance_rejects_malformed_manifest_csv_cell(tmp_path: Path) -> None:
    _copy_protocol_files(tmp_path)
    path = tmp_path / "manifests/mechanism_diagnostic_pairs_v2_1.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = '"' + lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"manifests/mechanism_diagnostic_pairs_v2_1.csv: "
            r"malformed CSV"
        ),
    ):
        load_pair_manifest(tmp_path)


def _formal_coverage() -> dict[str, object]:
    return {
        "all_bus_count": 2,
        "monitored_bus_count": 2,
        "energized_voltage_node_count": 3,
        "monitored_voltage_node_count": 3,
        "three_phase_bus_count": 1,
        "monitored_vuf_bus_count": 1,
        "enabled_transformer_count": 1,
        "rated_transformer_count": 1,
        "transformer_rating_coverage": 1.0,
        "line_count": 1,
        "line_thermal_in_scope": False,
        "feeder_rating_multiplier": 1.0,
        "transformer_ratings_kva": {"t1": 100.0},
        "transformer_raw_ratings_kva": {"t1": 100.0},
        "transformer_rating_multiplier": 1.0,
        "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
        "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
    }


def _safe_metrics() -> dict[str, float]:
    return {
        "V:bus1.1": 1.0,
        "V:bus2.2": 1.0,
        "V:near.3": 0.94999995,
        "U:bus1": 0.5,
        "S:transformer:t1": 0.5,
        "S:feeder": 0.5,
    }


def _violating_metrics() -> dict[str, float]:
    return {
        "V:bus1.1": 0.949,
        "V:bus2.2": 1.051,
        "V:near.3": 1.0,
        "U:bus1": 2.2,
        "S:transformer:t1": 1.1,
        "S:feeder": 1.05,
    }


def _physical_violation(
    metric: str, value: float, limit: float, direction: str
) -> dict[str, object]:
    return {
        "kind": "physical_constraint",
        "metric": metric,
        "value": value,
        "limit": limit,
        "direction": direction,
    }


def _all_physical_violations() -> list[dict[str, object]]:
    return [
        _physical_violation("V:bus1.1", 0.949, 0.95, "lo"),
        _physical_violation("V:bus2.2", 1.051, 1.05, "hi"),
        _physical_violation("U:bus1", 2.2, 2.0, "hi"),
        _physical_violation("S:transformer:t1", 1.1, 1.0, "hi"),
        _physical_violation("S:feeder", 1.05, 1.0, "hi"),
    ]


def _slot_result(
    slot: int,
    *,
    metrics: dict[str, float] | None = None,
    violations: list[dict[str, object]] | None = None,
    numerical_failure: bool = False,
    line_thermal_in_scope: bool = False,
) -> dict[str, object]:
    values = dict(metrics or _safe_metrics())
    witnesses = list(violations or [])
    coverage = _formal_coverage()
    coverage["line_thermal_in_scope"] = line_thermal_in_scope
    formal_integrity = {
        "validated": True,
        "result_schema_valid": True,
        "metrics_finite": True,
        "summary_finite": True,
        "coverage_complete": True,
        "summary_consistent": True,
    }
    return {
        "slot": slot,
        "verified": True,
        "baseline_exact": False,
        "baseline_schedule": None,
        "load_scale": 1.0,
        "feeder": "lv906",
        "model": "3ph",
        "source": "power_flow",
        "audit_context": {
            "adapter_schema": "EV-FLEX-BIAS-PILOT-NETWORK-AUDIT",
            "adapter_version": "1.0",
            "feeder": "lv906",
            "model": "3ph",
            "load_scale": 1.0,
            "vmin_pu": 0.95,
            "vmax_pu": 1.05,
            "vuf_limit_pct": 2.0,
            "transformer_loading_limit_pu": 1.0,
            "feeder_loading_limit_pu": 1.0,
            "feeder_kva": 1000.0,
            "line_thermal_in_scope": line_thermal_in_scope,
            "transformer_power_basis": "SYSTEM_TOTAL_TERMINAL_POWER",
            "transformer_rating_basis": "NATIVE_SYSTEM_TOTAL_KVA",
            "transformer_rating_multiplier": 1.0,
            "groups": [],
        },
        "group_power": [0.0],
        "coverage": deepcopy(coverage),
        "formal_integrity": deepcopy(formal_integrity),
        "result": {
            "metrics": values,
            "feasible": not numerical_failure and not witnesses,
            "converged": not numerical_failure,
            "numerical_failure": numerical_failure,
            "violations": witnesses,
            "vmin": min(value for key, value in values.items() if key.startswith("V:")),
            "vmax": max(value for key, value in values.items() if key.startswith("V:")),
            "vufmax": max(
                (value for key, value in values.items() if key.startswith("U:")),
                default=0.0,
            ),
            "transformer_loading_max": max(
                (
                    value
                    for key, value in values.items()
                    if key.startswith("S:transformer:")
                ),
                default=0.0,
            ),
            "feeder_loading": values.get("S:feeder"),
            "line_thermal_in_scope": line_thermal_in_scope,
            "coverage": deepcopy(coverage),
            "formal_integrity": deepcopy(formal_integrity),
        },
    }


def _raw_audit(slot_results: list[dict[str, object]]) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    trace: list[dict[str, object]] = []
    numerical_checks = 0
    physical_checks = 0
    for record in slot_results:
        result = record["result"]
        assert isinstance(result, dict)
        witnesses = result["violations"]
        assert isinstance(witnesses, list)
        numerical = bool(result["numerical_failure"])
        physical = any(item.get("kind") == "physical_constraint" for item in witnesses)
        if numerical:
            numerical_checks += 1
        if physical:
            physical_checks += 1
        if numerical or witnesses:
            failure_class = "NUMERICAL_INVALID" if numerical else "PHYSICAL_CONSTRAINT"
            failures.append(
                {
                    "slot": record["slot"],
                    "converged": bool(result["converged"]),
                    "numerical_failure": numerical,
                    "failure_class": failure_class,
                    "physical_witness": physical,
                    "violations": deepcopy(witnesses),
                }
            )
        else:
            failure_class = "NONE"
        trace.append(
            {
                "slot": record["slot"],
                "feasible": bool(result["feasible"]),
                "converged": bool(result["converged"]),
                "numerical_failure": numerical,
                "failure_class": failure_class,
                "physical_witness": physical,
            }
        )
    checked = len(slot_results)
    complete = checked == 96
    feasible = complete and not failures
    failure_class = (
        "NUMERICAL_INVALID"
        if numerical_checks
        else "PHYSICAL_CONSTRAINT"
        if physical_checks
        else "NONE"
    )
    return {
        "feasible": feasible,
        "checked_intervals": checked,
        "coverage_ratio": checked / 96.0,
        "complete_coverage": complete,
        "eligible_for_v01_pass": feasible,
        "power_flow_evaluations": checked,
        "reused_baseline_intervals": 0,
        "converged_checks": checked - numerical_checks,
        "nonconverged_checks": numerical_checks,
        "numerical_failure_checks": numerical_checks,
        "physical_violation_checks": physical_checks,
        "failure_class": failure_class,
        "nonconverged_slots": [
            item["slot"] for item in failures if not item["converged"]
        ],
        "violations": failures,
        "slot_results": slot_results,
        "slot_audit_trace": trace,
        "coverage_counts": deepcopy(_formal_coverage()),
        "vmin": min(
            record["result"]["vmin"] for record in slot_results
        ),
        "vmax": max(
            record["result"]["vmax"] for record in slot_results
        ),
        "vufmax": max(
            record["result"]["vufmax"] for record in slot_results
        ),
        "transformer_loading_max": max(
            record["result"]["transformer_loading_max"] for record in slot_results
        ),
        "feeder_loading_max": max(
            record["result"]["feeder_loading"] for record in slot_results
        ),
    }


def test_constraint_rows_emit_both_voltage_bounds_and_fixed_order() -> None:
    rows = constraint_rows_from_slot(_slot_result(7))

    assert [(row["constraint_family"], row["metric_id"]) for row in rows] == [
        ("VMIN", "V:bus1.1"),
        ("VMIN", "V:bus2.2"),
        ("VMIN", "V:near.3"),
        ("VMAX", "V:bus1.1"),
        ("VMAX", "V:bus2.2"),
        ("VMAX", "V:near.3"),
        ("VUF", "U:bus1"),
        ("TRANSFORMER", "S:transformer:t1"),
        ("FEEDER", "S:feeder"),
    ]
    near = next(
        row
        for row in rows
        if row["constraint_family"] == "VMIN" and row["metric_id"] == "V:near.3"
    )
    assert near["signed_headroom"] == pytest.approx(-5e-8)
    assert near["is_physical_violation"] is False


def test_constraint_rows_cover_all_five_families_and_exclude_lines() -> None:
    slot = _slot_result(
        7,
        metrics=_violating_metrics(),
        violations=_all_physical_violations(),
    )
    rows = constraint_rows_from_slot(slot)
    violated = [row for row in rows if row["is_physical_violation"]]

    assert [row["constraint_family"] for row in violated] == [
        "VMIN",
        "VMAX",
        "VUF",
        "TRANSFORMER",
        "FEEDER",
    ]
    assert [row["object_id"] for row in violated] == [
        "bus1.1",
        "bus2.2",
        "bus1",
        "t1",
        "feeder",
    ]
    line_slot = _slot_result(7)
    line_slot["result"]["metrics"]["S:line:l1"] = 1.1
    with pytest.raises(ValueError, match="unsupported monitored metric"):
        constraint_rows_from_slot(line_slot)


def test_compactor_retains_all_simultaneous_first_slot_violations() -> None:
    slots = [
        _slot_result(0),
        _slot_result(1),
        _slot_result(
            2,
            metrics=_violating_metrics(),
            violations=_all_physical_violations(),
        ),
    ]
    compact = compact_targeted_audit(
        _raw_audit(slots), audit_point="BOUNDARY_INFEASIBLE", alpha=0.942
    )

    assert compact["first_failure_slot"] == 2
    assert compact["checked_intervals"] == 3
    assert compact["explicit_physical_witness"] is True
    selected = compact["selected_slot"]
    assert selected["slot"] == 2
    assert [item["constraint_family"] for item in selected["simultaneous_violations"]] == [
        "VMIN",
        "VMAX",
        "VUF",
        "TRANSFORMER",
        "FEEDER",
    ]


def test_compactor_uses_explicit_physical_witness_not_headroom_sign() -> None:
    rows = constraint_rows_from_slot(_slot_result(3))
    negative = [row for row in rows if row["signed_headroom"] < 0]

    assert negative
    assert all(row["is_physical_violation"] is False for row in negative)


def test_compactor_rejects_numerical_or_incomplete_metric_evidence() -> None:
    numerical = _raw_audit([_slot_result(0, numerical_failure=True)])
    with pytest.raises(ValueError, match="numerical failure"):
        compact_targeted_audit(
            numerical, audit_point="BOUNDARY_INFEASIBLE", alpha=0.942
        )

    incomplete_slot = _slot_result(
        0,
        metrics=_violating_metrics(),
        violations=_all_physical_violations(),
    )
    del incomplete_slot["result"]["metrics"]["S:feeder"]
    incomplete = _raw_audit([incomplete_slot])
    with pytest.raises(ValueError, match="formal metric coverage"):
        compact_targeted_audit(
            incomplete, audit_point="BOUNDARY_INFEASIBLE", alpha=0.942
        )


def test_compactor_validates_early_stop_and_96_slot_feasible_coverage() -> None:
    failure_slots = [
        _slot_result(0),
        _slot_result(
            1,
            metrics=_violating_metrics(),
            violations=_all_physical_violations(),
        ),
        _slot_result(2),
    ]
    invalid_stop = _raw_audit(failure_slots)
    with pytest.raises(ValueError, match="early-stop consistency"):
        compact_targeted_audit(
            invalid_stop, audit_point="BOUNDARY_INFEASIBLE", alpha=0.942
        )

    incomplete_feasible = _raw_audit([_slot_result(slot) for slot in range(95)])
    incomplete_feasible["feasible"] = True
    with pytest.raises(ValueError, match="96-slot coverage"):
        compact_targeted_audit(
            incomplete_feasible, audit_point="BOUNDARY_FEASIBLE", alpha=0.94
        )

    complete = _raw_audit([_slot_result(slot) for slot in range(96)])
    compact = compact_targeted_audit(
        complete,
        audit_point="BOUNDARY_INFEASIBLE",
        alpha=0.7,
        capture_slot=42,
    )
    assert compact["feasible"] is True
    assert compact["complete_coverage"] is True
    assert compact["selected_slot"]["slot"] == 42


def test_compactor_rejects_aggregate_witness_or_constraint_drift() -> None:
    valid = _raw_audit(
        [
            _slot_result(0),
            _slot_result(
                1,
                metrics=_violating_metrics(),
                violations=_all_physical_violations(),
            ),
        ]
    )

    missing_aggregate = deepcopy(valid)
    missing_aggregate["violations"] = []
    with pytest.raises(ValueError, match="aggregate violation evidence"):
        compact_targeted_audit(
            missing_aggregate,
            audit_point="BOUNDARY_INFEASIBLE",
            alpha=0.942,
        )

    trace_drift = deepcopy(valid)
    trace_drift["slot_audit_trace"][-1]["physical_witness"] = False
    with pytest.raises(ValueError, match="slot audit trace"):
        compact_targeted_audit(
            trace_drift,
            audit_point="BOUNDARY_INFEASIBLE",
            alpha=0.942,
        )

    count_drift = deepcopy(valid)
    count_drift["physical_violation_checks"] = 0
    with pytest.raises(ValueError, match="physical violation count"):
        compact_targeted_audit(
            count_drift,
            audit_point="BOUNDARY_INFEASIBLE",
            alpha=0.942,
        )

    constraint_drift = _slot_result(0)
    constraint_drift["audit_context"]["vmin_pu"] = 1.06
    with pytest.raises(ValueError, match="formal constraint context"):
        constraint_rows_from_slot(constraint_drift)


def test_compactor_rejects_aggregate_coverage_extrema_or_accounting_drift() -> None:
    valid = _raw_audit(
        [
            _slot_result(0),
            _slot_result(
                1,
                metrics=_violating_metrics(),
                violations=_all_physical_violations(),
            ),
        ]
    )

    coverage_drift = deepcopy(valid)
    coverage_drift["coverage_counts"]["line_count"] = 2
    with pytest.raises(ValueError, match="aggregate formal coverage"):
        compact_targeted_audit(
            coverage_drift,
            audit_point="BOUNDARY_INFEASIBLE",
            alpha=0.942,
        )

    extrema_drift = deepcopy(valid)
    extrema_drift["vmin"] = 0.5
    with pytest.raises(ValueError, match="aggregate extrema"):
        compact_targeted_audit(
            extrema_drift,
            audit_point="BOUNDARY_INFEASIBLE",
            alpha=0.942,
        )

    accounting_drift = deepcopy(valid)
    accounting_drift["power_flow_evaluations"] = 1
    with pytest.raises(ValueError, match="evaluation accounting"):
        compact_targeted_audit(
            accounting_drift,
            audit_point="BOUNDARY_INFEASIBLE",
            alpha=0.942,
        )

    limit_drift = deepcopy(valid)
    limit_drift["slot_results"][0]["audit_context"]["vmin_pu"] = 0.94
    with pytest.raises(ValueError, match="constraint limits differ"):
        compact_targeted_audit(
            limit_drift,
            audit_point="BOUNDARY_INFEASIBLE",
            alpha=0.942,
        )


def _diagnostic_constraint_row(
    family: str,
    object_id: str,
    *,
    physical: bool = False,
    signed_headroom: float | None = None,
) -> dict[str, object]:
    if family in {"VMIN", "VMAX"}:
        metric_id = f"V:{object_id}"
    elif family == "VUF":
        metric_id = f"U:{object_id}"
    elif family == "TRANSFORMER":
        metric_id = f"S:transformer:{object_id}"
    elif family == "FEEDER":
        metric_id = "S:feeder"
        object_id = "feeder"
    else:
        raise AssertionError(f"unexpected family {family}")
    direction = "lo" if family == "VMIN" else "hi"
    limit = 0.95 if family == "VMIN" else 1.05 if family == "VMAX" else 1.0
    margin = (-0.01 if physical else 0.01) if signed_headroom is None else signed_headroom
    value = limit + margin if direction == "lo" else limit - margin
    return {
        "slot": 5,
        "constraint_family": family,
        "metric_id": metric_id,
        "object_id": object_id,
        "value": value,
        "limit": limit,
        "direction": direction,
        "signed_headroom": margin,
        "exceedance": max(0.0, -margin),
        "is_physical_violation": physical,
    }


def _diagnostic_audit(
    audit_point: str,
    role: str,
    rows: list[dict[str, object]] | None,
) -> dict[str, object]:
    selected = None
    if rows is not None:
        selected = {
            "slot": 5,
            "constraint_rows": deepcopy(rows),
            "simultaneous_violations": [
                deepcopy(row)
                for row in rows
                if row["is_physical_violation"] is True
            ],
        }
    return {
        "audit_point": audit_point,
        "role": role,
        "selected_slot": selected,
    }


def _diagnostic_pair(
    pair_id: str,
    scenario_cluster: str,
    bad_boundary_rows: list[dict[str, object]],
    control_boundary_rows: list[dict[str, object]] | None = None,
    *,
    bad_full_rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "protocol_version": "EV-FLEX-BIAS-V2.1-D1-MECHANISM",
        "status": "SUCCESS",
        "pair_id": pair_id,
        "scenario_cluster": scenario_cluster,
        "relative_stress": {
            "reason_code": "RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR",
            "global_ratio": None,
            "phase_ratios": None,
        },
        "audits": [
            _diagnostic_audit("BOUNDARY_FEASIBLE", "bad", None),
            _diagnostic_audit("BOUNDARY_FEASIBLE", "control", None),
            _diagnostic_audit("BOUNDARY_INFEASIBLE", "bad", bad_boundary_rows),
            _diagnostic_audit(
                "BOUNDARY_INFEASIBLE",
                "control",
                control_boundary_rows if control_boundary_rows is not None else [],
            ),
            _diagnostic_audit("FULL_OFFER", "bad", bad_full_rows),
            _diagnostic_audit("FULL_OFFER", "control", None),
        ],
    }


def _eligible_count_row(
    pair_id: str,
    family: str,
    numerator: int,
    denominator: int,
    *,
    display: str = "0.800000000000",
) -> dict[str, object]:
    return {
        "pair_id": pair_id,
        "constraint_family": family,
        "probability_status": "ELIGIBLE",
        "N": denominator,
        "K": numerator,
        "m": 1,
        "p_detect": {
            "numerator": numerator,
            "denominator": denominator,
            "display": display,
        },
        "not_applicable_reason": None,
    }


def test_exact_count_probability_preserves_fraction_and_display() -> None:
    result = exact_count_match_probability(10, 2, 3)

    assert result == {
        "numerator": 8,
        "denominator": 15,
        "display": "0.533333333333",
    }


def test_exact_count_probability_handles_n_minus_k_below_m() -> None:
    result = exact_count_match_probability(5, 4, 2)

    assert result == {
        "numerator": 1,
        "denominator": 1,
        "display": "1.000000000000",
    }


def test_count_match_uses_unique_explicit_violation_objects_only() -> None:
    bad_rows = [
        _diagnostic_constraint_row("VMIN", "a", physical=True),
        _diagnostic_constraint_row("VMIN", "a", physical=True),
        _diagnostic_constraint_row(
            "VMIN", "b", physical=False, signed_headroom=-1e-8
        ),
        _diagnostic_constraint_row("VMIN", "c"),
        *[
            _diagnostic_constraint_row("VMAX", object_id)
            for object_id in ("a", "b", "c")
        ],
        _diagnostic_constraint_row("VUF", "u1"),
    ]
    control_rows = [
        *[
            _diagnostic_constraint_row("VMIN", object_id)
            for object_id in ("x", "y")
        ],
        *[
            _diagnostic_constraint_row("VMAX", object_id)
            for object_id in ("x", "y")
        ],
        _diagnostic_constraint_row("VUF", "u2"),
    ]

    rows = build_count_match_rows(
        [_diagnostic_pair("01", "cluster_1", bad_rows, control_rows)]
    )

    assert len(rows) == 1
    assert rows[0]["constraint_family"] == "VMIN"
    assert (rows[0]["N"], rows[0]["K"], rows[0]["m"]) == (3, 1, 2)
    assert rows[0]["p_detect"] == {
        "numerator": 2,
        "denominator": 3,
        "display": "0.666666666667",
    }


def test_count_match_excludes_not_applicable_rows_from_denominator() -> None:
    bad_rows = [_diagnostic_constraint_row("VUF", "u1", physical=True)]
    built = build_count_match_rows(
        [_diagnostic_pair("01", "cluster_1", bad_rows, [])]
    )
    assert built[0]["probability_status"] == "NOT_APPLICABLE"
    assert built[0]["p_detect"] is None

    rows = [
        built[0],
        *[
            _eligible_count_row(f"{index:02d}", "VUF", 4, 5)
            for index in range(2, 6)
        ],
    ]
    result = classify_count_match(rows, "VUF")

    assert result["classification"] == "COUNT_MATCH_HIGH_DETECTION"
    assert result["n_rows"] == 5
    assert result["n_eligible"] == 4
    assert result["n_not_applicable"] == 1
    assert result["required_80pct_count"] == 4


def test_count_match_thresholds_use_exact_fraction_not_display() -> None:
    rows = [
        _eligible_count_row("01", "VMIN", 4, 5),
        _eligible_count_row("02", "VMIN", 4, 5),
        _eligible_count_row("03", "VMIN", 4, 5),
        _eligible_count_row(
            "04",
            "VMIN",
            7_999_999_999_999,
            10_000_000_000_000,
            display="0.800000000000",
        ),
    ]

    result = classify_count_match(rows, "VMIN")

    assert result["high_detection_count"] == 3
    assert result["classification"] == "COUNT_MATCH_INDETERMINATE"


def test_count_match_rejects_probability_drift_from_exact_counts() -> None:
    row = _eligible_count_row("01", "VMIN", 4, 5)
    row["p_detect"]["numerator"] = 3

    with pytest.raises(ValueError, match="differs from exact counts"):
        classify_count_match([row], "VMIN")

    not_applicable = {
        "pair_id": "02",
        "constraint_family": "VMIN",
        "probability_status": "NOT_APPLICABLE",
        "N": 5,
        "K": 1,
        "m": False,
        "p_detect": None,
        "not_applicable_reason": "CONTROL_FAMILY_ABSENT",
    }
    with pytest.raises(ValueError, match="m must be an integer"):
        classify_count_match([not_applicable], "VMIN")


def test_candidate_families_use_boundary_infeasible_and_scenario_clusters_only() -> None:
    clusters = [
        "c1",
        "c2",
        "c1",
        "c2",
        "c1",
        "c2",
        "c1",
        "c2",
        "c3",
        "c3",
        "c4",
        "c4",
    ]
    vmin_indices = {*range(7), 8}
    pairs = []
    for index, cluster in enumerate(clusters):
        boundary_rows = []
        if index < 8:
            boundary_rows.append(
                _diagnostic_constraint_row("VMAX", f"vmax_{index}", physical=True)
            )
        if index in vmin_indices:
            boundary_rows.append(
                _diagnostic_constraint_row("VMIN", f"vmin_{index}", physical=True)
            )
        if not boundary_rows:
            boundary_rows.append(
                _diagnostic_constraint_row("FEEDER", "feeder", physical=True)
            )
        pairs.append(
            _diagnostic_pair(
                f"{index + 1:02d}",
                cluster,
                boundary_rows,
                [_diagnostic_constraint_row("VUF", "control", physical=True)],
                bad_full_rows=[
                    _diagnostic_constraint_row("VUF", "full", physical=True)
                ],
            )
        )

    candidates = candidate_families(pairs)

    assert [item["constraint_family"] for item in candidates] == ["VMIN"]
    assert candidates[0]["bad_case_count"] == 8
    assert candidates[0]["scenario_cluster_count"] == 3


def test_candidate_families_allow_multiple_in_fixed_order() -> None:
    clusters = ["c1", "c2", "c3", "c4"] * 3
    pairs = []
    for index, cluster in enumerate(clusters):
        families = (
            ["FEEDER", "VUF", "VMAX", "TRANSFORMER", "VMIN"]
            if index < 8
            else ["VMIN"]
        )
        rows = [
            _diagnostic_constraint_row(
                family,
                "feeder" if family == "FEEDER" else f"{family.lower()}_{index}",
                physical=True,
            )
            for family in families
        ]
        pairs.append(_diagnostic_pair(f"{index + 1:02d}", cluster, rows))

    candidates = candidate_families(pairs)

    assert [item["constraint_family"] for item in candidates] == [
        "VMIN",
        "VMAX",
        "VUF",
        "TRANSFORMER",
        "FEEDER",
    ]
    assert all(item["bad_case_count"] >= 8 for item in candidates)
    assert all(item["scenario_cluster_count"] >= 3 for item in candidates)


def test_relative_stress_is_null_with_frozen_reason() -> None:
    first = relative_stress_evidence()
    first["global_ratio"] = 1.0

    assert relative_stress_evidence() == {
        "reason_code": "RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR",
        "global_ratio": None,
        "phase_ratios": None,
    }
