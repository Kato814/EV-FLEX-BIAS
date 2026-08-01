from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from evflex.mechanism_diagnostic import (
    load_mechanism_config,
    load_pair_manifest,
    pair_members,
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
