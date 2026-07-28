from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "evaluate_pilot_gate_v2_1.py"
OUTPUT_PATHS = (
    Path("results/pilot_v2_1/pilot_evaluations_v2_1.csv"),
    Path("reports/pilot_work_unit_hashes_v2_1.csv"),
    Path("reports/pilot_gate_v2_1.json"),
    Path("reports/pilot_gate_v2_1.md"),
)
SCIENTIFIC_AXIS_FIELDS = (
    "baseline_status",
    "active_offer_status",
    "core_topic_status",
    "scenario_dominance_status",
    "direction_claim_status",
    "duration_claim_status",
    "feeder_replication_status",
    "tie_break_route_status",
    "screening_compute_status",
    "v2_0_reuse_status",
)


def _load_evaluator():
    assert SCRIPT_PATH.is_file(), "pilot evaluator script is not implemented"
    spec = importlib.util.spec_from_file_location(
        "evaluate_pilot_gate_v2_1_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _manifest_rows(repo: Path) -> list[dict[str, str]]:
    with (repo / "manifests/audit_pilot_work_units_v2_1.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        return list(csv.DictReader(stream))


def _evaluation_row(
    manifest_row: dict[str, str],
    evaluation_id: str,
) -> dict[str, Any]:
    duration = int(evaluation_id.rsplit("__", 1)[1][:-1])
    seed = int(manifest_row["scenario_seed"])
    return {
        "evaluation_id": evaluation_id,
        "work_unit_id": manifest_row["work_unit_id"],
        "protocol_version": manifest_row["protocol_version"],
        "scenario_id": manifest_row["scenario_id"],
        "scenario_seed": seed,
        "data_role": manifest_row["data_role"],
        "feeder": manifest_row["feeder"],
        "call_time": manifest_row["call_time"],
        "direction": manifest_row["direction"],
        "duration_min": duration,
        "requested_duration_min": duration,
        "source_duration_min": duration,
        "baseline_status": "VALID",
        "active_offer": True,
        "eligible_for_scientific_denominator": True,
        "alpha_transfer": 0.90,
        "alpha_transfer_tied": 0.95,
        "tie_comparator_valid": True,
        "tie_offer_retention": 1.0,
        "alpha1_warm_p95_s": 0.5,
        "alpha1_warm_cv": 0.1,
        "status": "SUCCESS",
        "scientific_status": "VALID",
        "nested_evidence": {"z": [2, 1], "a": "中文"},
    }


def _build_repo(
    tmp_path: Path,
    *,
    creation_order_seed: int | None = None,
) -> Path:
    repo = tmp_path / "repo"
    for relative in (
        "config/pilot_gate_v2_1.json",
        "manifests/audit_pilot_work_units_v2_1.csv",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    for relative, text in (
        ("src/evflex/pilot.py", "# fixture pilot module\n"),
        ("scripts/run_pilot_gate_v2_1.py", "# fixture runner\n"),
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    evaluator_target = repo / "scripts/evaluate_pilot_gate_v2_1.py"
    evaluator_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCRIPT_PATH, evaluator_target)

    rows = _manifest_rows(repo)
    if creation_order_seed is not None:
        random.Random(creation_order_seed).shuffle(rows)
    work_units = repo / "results/pilot_v2_1/work_units"
    work_units.mkdir(parents=True, exist_ok=True)
    for manifest_row in rows:
        evaluation_ids = json.loads(manifest_row["evaluation_ids"])
        payload = {
            "protocol_version": manifest_row["protocol_version"],
            "work_unit_id": manifest_row["work_unit_id"],
            "scenario_seed": int(manifest_row["scenario_seed"]),
            "data_role": manifest_row["data_role"],
            "status": "SUCCESS",
            "attempt_count": 1,
            "evaluations": [
                _evaluation_row(manifest_row, evaluation_id)
                for evaluation_id in evaluation_ids
            ],
        }
        _write_json(
            work_units / f"{manifest_row['work_unit_id']}.json",
            payload,
        )
    return repo


def _assessor(capture: list[dict[str, Any]] | None = None):
    def assess(evidence, _config):
        if capture is not None:
            capture.append(evidence)
        invalid = evidence["loader_validation"]["status"] != "VALID"
        if invalid:
            axis_values = {
                field: "NOT_EVALUATED_VALIDITY_STOP"
                for field in SCIENTIFIC_AXIS_FIELDS
            }
        else:
            axis_values = {
                "baseline_status": "PASS_ALL_BASELINES",
                "active_offer_status": "PASS_ACTIVE_COVERAGE",
                "core_topic_status": "GO",
                "scenario_dominance_status": "DISTRIBUTED",
                "direction_claim_status": "KEEP_CLAIM",
                "duration_claim_status": "KEEP_CLAIM",
                "feeder_replication_status": "REPLICATED",
                "tie_break_route_status": "KEEP_ORIGINAL_ROUTE",
                "screening_compute_status": "DROP_SCREENING",
                "v2_0_reuse_status": "DIAGNOSTIC_ONLY_NO_FLIP",
            }
        return {
            "validator_status": "VALIDITY_STOP" if invalid else "VALID",
            **axis_values,
            "overall_action": (
                "STOP_FIX_AND_REPEAT_16_WU_AUDIT"
                if invalid
                else "GO_TO_FORMAL_V2_1_WITH_REPORTED_SCOPE"
            ),
            "decision_class": "VALIDITY_STOP" if invalid else "GO",
            "formal_v2_1_run_started": False,
            "metrics": {"nested": {"b": 2, "a": 1}},
            "reason_codes": ["FIX_INPUT"] if invalid else ["ALL_AXES_PASS"],
            "mandatory_scope_actions": [],
            "repeat_scope": "FULL_16_WU_PILOT" if invalid else "NONE",
        }

    return assess


def _artifact_bytes(repo: Path) -> dict[str, bytes]:
    return {
        path.as_posix(): (repo / path).read_bytes()
        for path in OUTPUT_PATHS
    }


def _tree_snapshot(repo: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(repo).as_posix(): (
            path.read_bytes(),
            path.stat().st_mtime_ns,
        )
        for path in sorted(repo.rglob("*"))
        if path.is_file()
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_evaluator_writes_fixed_deterministic_artifacts_and_provenance(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    capture: list[dict[str, Any]] = []

    outcome = evaluator.evaluate_pilot_gate(
        repo,
        assessor=_assessor(capture),
    )

    assert outcome["exit_code"] == 0
    assert outcome["structural_valid"] is True
    assert all((repo / path).is_file() for path in OUTPUT_PATHS)
    with (repo / OUTPUT_PATHS[0]).open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        evaluation_rows = list(csv.DictReader(stream))
    assert len(evaluation_rows) == 48
    assert len({row["evaluation_id"] for row in evaluation_rows}) == 48
    assert evaluation_rows[0]["evaluation_id"] == (
        "v20_core_ieee13_1900_17__inc__15m"
    )
    assert evaluation_rows[-1]["evaluation_id"] == (
        "v20_core_lv906_0600_02__dec__60m"
    )
    assert evaluation_rows[0]["nested_evidence"] == (
        '{"a":"中文","z":[2,1]}'
    )
    with (repo / OUTPUT_PATHS[1]).open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        hash_rows = list(csv.DictReader(stream))
    assert len(hash_rows) == 16
    assert all(row["expected"] == "true" for row in hash_rows)
    assert all(len(row["sha256"]) == 64 for row in hash_rows)

    report = json.loads((repo / OUTPUT_PATHS[2]).read_text(encoding="utf-8"))
    assert report["formal_v2_1_run_started"] is False
    assert report["validator_status"] == "VALID"
    provenance = report["provenance"]
    expected_sources = {
        "config",
        "manifest",
        "pilot_module",
        "runner",
        "evaluator",
        "evaluation_csv",
        "raw_hash_csv",
    }
    assert set(provenance) == expected_sources
    for item in provenance.values():
        assert len(item["sha256"]) == 64
        assert "\\" not in item["path"]
    assert provenance["evaluation_csv"]["sha256"] == _sha256(
        repo / OUTPUT_PATHS[0]
    )
    assert provenance["raw_hash_csv"]["sha256"] == _sha256(
        repo / OUTPUT_PATHS[1]
    )
    markdown = (repo / OUTPUT_PATHS[3]).read_text(encoding="utf-8")
    assert "V2.1 试运行停止门评估" in markdown
    assert "未启动正式 V2.1 重跑" in markdown
    assert capture[0]["loader_validation"] == {
        "status": "VALID",
        "errors": [],
    }
    assert len(capture[0]["work_units"]) == 16
    assert len(capture[0]["evaluations"]) == 48
    for path in OUTPUT_PATHS:
        raw = (repo / path).read_bytes()
        assert b"\r\n" not in raw

    first = _artifact_bytes(repo)
    repeated = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())
    assert repeated["exit_code"] == 0
    assert _artifact_bytes(repo) == first


@pytest.mark.parametrize("kind", ["duplicate_key", "nonfinite"])
def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(
    tmp_path,
    kind,
):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    raw = sorted((repo / "results/pilot_v2_1/work_units").glob("*.json"))[0]
    text = raw.read_text(encoding="utf-8")
    if kind == "duplicate_key":
        text = text.replace(
            '"attempt_count": 1,',
            '"attempt_count": 1,\n  "attempt_count": 1,',
            1,
        )
    else:
        text = text.replace('"attempt_count": 1', '"attempt_count": NaN', 1)
    raw.write_text(text, encoding="utf-8", newline="\n")

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 1
    report = json.loads((repo / OUTPUT_PATHS[2]).read_text(encoding="utf-8"))
    assert report["validator_status"] == "VALIDITY_STOP"
    assert report["overall_action"] == "STOP_FIX_AND_REPEAT_16_WU_AUDIT"
    assert any(
        ("duplicate" if kind == "duplicate_key" else "non-finite") in error
        for error in report["loader_validation"]["errors"]
    )
    with (repo / OUTPUT_PATHS[1]).open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        hash_rows = list(csv.DictReader(stream))
    failed = next(row for row in hash_rows if row["relative_path"].endswith(raw.name))
    assert failed["parse_status"] == "ERROR"
    assert len(failed["sha256"]) == 64


def test_invalid_utf8_config_becomes_validity_stop_instead_of_crashing(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    (repo / "config/pilot_gate_v2_1.json").write_bytes(b"\xff")

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 1
    report = json.loads((repo / OUTPUT_PATHS[2]).read_text(encoding="utf-8"))
    assert report["validator_status"] == "VALIDITY_STOP"
    assert any(
        "unreadable JSON file" in error
        for error in report["loader_validation"]["errors"]
    )


def test_invalid_utf8_manifest_becomes_validity_stop_instead_of_crashing(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    (repo / "manifests/audit_pilot_work_units_v2_1.csv").write_bytes(b"\xff")

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 1
    report = json.loads((repo / OUTPUT_PATHS[2]).read_text(encoding="utf-8"))
    assert report["validator_status"] == "VALIDITY_STOP"
    assert any(
        "unreadable manifest" in error
        for error in report["loader_validation"]["errors"]
    )


@pytest.mark.parametrize(
    "kind",
    ["missing", "extra", "corrupt", "wrapper_identity", "row_identity", "filename"],
)
def test_structural_input_faults_write_validity_stop_outputs(
    tmp_path,
    kind,
):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    raw_dir = repo / "results/pilot_v2_1/work_units"
    target = sorted(raw_dir.glob("*.json"))[0]
    if kind == "missing":
        target.unlink()
    elif kind == "extra":
        _write_json(raw_dir / "unexpected.json", {"unexpected": True})
    elif kind == "corrupt":
        target.write_text("{broken", encoding="utf-8", newline="\n")
    elif kind == "filename":
        target.rename(raw_dir / "renamed.json")
    else:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if kind == "wrapper_identity":
            payload["scenario_seed"] += 1
        else:
            payload["evaluations"][0]["data_role"] = "holdout"
        _write_json(target, payload)

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 1
    assert all((repo / path).is_file() for path in OUTPUT_PATHS)
    report = json.loads((repo / OUTPUT_PATHS[2]).read_text(encoding="utf-8"))
    assert report["validator_status"] == "VALIDITY_STOP"
    assert report["formal_v2_1_run_started"] is False
    assert report["loader_validation"]["status"] == "INVALID"
    assert report["loader_validation"]["errors"]
    with (repo / OUTPUT_PATHS[1]).open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        hashes = list(csv.DictReader(stream))
    if kind in {"extra", "corrupt", "filename"}:
        assert any(row["expected"] == "false" for row in hashes) or any(
            row["parse_status"] == "ERROR" for row in hashes
        )


def test_lock_attempt_and_temporary_evidence_force_validity_stop(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    capture: list[dict[str, Any]] = []
    lock = repo / "state/runtime/locks/pilot_v2_1/unit.lock"
    attempt = repo / "state/runtime/attempts/pilot_v2_1/unit.json"
    temporary = (
        repo
        / "results/pilot_v2_1/work_units"
        / "v20_work_ieee13_1900_17__inc.json.partial.tmp"
    )
    for path in (lock, attempt, temporary):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence", encoding="utf-8", newline="\n")

    outcome = evaluator.evaluate_pilot_gate(
        repo,
        assessor=_assessor(capture),
    )

    assert outcome["exit_code"] == 1
    evidence = capture[0]
    assert evidence["active_lock_files"] == [
        "state/runtime/locks/pilot_v2_1/unit.lock"
    ]
    assert evidence["attempt_state_files"] == [
        "state/runtime/attempts/pilot_v2_1/unit.json"
    ]
    assert evidence["temporary_files"] == [
        (
            "results/pilot_v2_1/work_units/"
            "v20_work_ieee13_1900_17__inc.json.partial.tmp"
        )
    ]
    assert evidence["loader_validation"]["status"] == "INVALID"


def test_gate_validator_stop_is_a_nonzero_structural_outcome(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)

    def validity_stop(evidence, config):
        decision = _assessor()(evidence, config)
        decision["validator_status"] = "VALIDITY_STOP"
        decision["overall_action"] = "STOP_FIX_AND_REPEAT_16_WU_AUDIT"
        decision["decision_class"] = "VALIDITY_STOP"
        return decision

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=validity_stop)

    assert outcome["exit_code"] == 1
    assert outcome["structural_valid"] is False
    assert all((repo / path).is_file() for path in OUTPUT_PATHS)


def test_loader_errors_force_exact_validity_stop_axis_vocabulary(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    sorted((repo / "results/pilot_v2_1/work_units").glob("*.json"))[0].unlink()

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    report = outcome["gate"]
    assert report["validator_status"] == "VALIDITY_STOP"
    assert {
        report[field] for field in SCIENTIFIC_AXIS_FIELDS
    } == {"NOT_EVALUATED_VALIDITY_STOP"}
    assert report["mandatory_scope_actions"] == []


def test_assessor_failure_uses_exact_frozen_validity_stop_payload(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)

    def failing_assessor(_evidence, _config):
        raise RuntimeError("gate failed")

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=failing_assessor)

    report = outcome["gate"]
    assert outcome["exit_code"] == 1
    assert report["validator_status"] == "VALIDITY_STOP"
    assert {
        report[field] for field in SCIENTIFIC_AXIS_FIELDS
    } == {"NOT_EVALUATED_VALIDITY_STOP"}
    assert report["mandatory_scope_actions"] == []


def test_incomplete_or_invented_assessor_output_is_rejected(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)

    def invented_assessor(_evidence, _config):
        return {
            "validator_status": "VALID",
            "overall_action": "INVENTED_ACTION",
        }

    outcome = evaluator.evaluate_pilot_gate(
        repo, assessor=invented_assessor
    )

    report = outcome["gate"]
    assert outcome["exit_code"] == 1
    assert report["validator_status"] == "VALIDITY_STOP"
    assert {
        report[field] for field in SCIENTIFIC_AXIS_FIELDS
    } == {"NOT_EVALUATED_VALIDITY_STOP"}
    assert "ASSESSOR_FAILED" in report["reason_codes"]
    assert report["loader_validation"]["status"] == "INVALID"


def test_unhandled_wrapper_is_structurally_invalid(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    raw = sorted(
        (repo / "results/pilot_v2_1/work_units").glob("*.json")
    )[0]
    payload = json.loads(raw.read_text(encoding="utf-8"))
    payload["status"] = "UNHANDLED_FAILURE"
    for row in payload["evaluations"]:
        row["status"] = "UNHANDLED_FAILURE"
    _write_json(raw, payload)

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 1
    assert outcome["gate"]["validator_status"] == "VALIDITY_STOP"
    assert any(
        "not an accepted scientific terminal" in error
        for error in outcome["gate"]["loader_validation"]["errors"]
    )


def test_nested_unexpected_raw_file_is_hashed_and_stops_gate(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    rogue = (
        repo
        / "results/pilot_v2_1/work_units/rogue/alternate.json"
    )
    _write_json(rogue, {"unexpected": True})

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 1
    assert outcome["gate"]["unexpected_raw_files"] == [
        "results/pilot_v2_1/work_units/rogue/alternate.json"
    ]
    with (repo / OUTPUT_PATHS[1]).open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        hash_rows = list(csv.DictReader(stream))
    nested = next(
        row
        for row in hash_rows
        if row["relative_path"].endswith("rogue/alternate.json")
    )
    assert nested["expected"] == "false"
    assert len(nested["sha256"]) == 64


def test_raw_hash_and_assessment_use_one_immutable_byte_snapshot(
    tmp_path, monkeypatch
):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    capture: list[dict[str, Any]] = []
    target = sorted(
        (repo / "results/pilot_v2_1/work_units").glob("*.json")
    )[0]
    original_bytes = target.read_bytes()
    replacement = json.loads(original_bytes.decode("utf-8"))
    replacement["evaluations"][0]["nested_evidence"] = {"swapped": True}
    original_sha = evaluator._sha256_file
    swapped = False

    def swap_after_separate_hash(path):
        nonlocal swapped
        digest = original_sha(path)
        if path.resolve() == target.resolve() and not swapped:
            swapped = True
            _write_json(target, replacement)
        return digest

    monkeypatch.setattr(evaluator, "_sha256_file", swap_after_separate_hash)

    outcome = evaluator.evaluate_pilot_gate(
        repo, assessor=_assessor(capture)
    )

    assert outcome["exit_code"] == 0
    assessed = next(
        row
        for row in capture[0]["evaluations"]
        if row["evaluation_id"]
        == replacement["evaluations"][0]["evaluation_id"]
    )
    assert assessed["nested_evidence"] != {"swapped": True}
    hashed = next(
        row
        for row in capture[0]["raw_hash_rows"]
        if row["relative_path"].endswith(target.name)
    )
    assert hashed["sha256"] == hashlib.sha256(original_bytes).hexdigest()


def test_unrelated_report_temporary_file_is_outside_pilot_scope(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    unrelated = repo / "reports/unrelated_pipeline.tmp"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_text("preserve", encoding="utf-8", newline="\n")
    before = unrelated.read_bytes()

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 0
    assert outcome["gate"]["temporary_files"] == []
    assert unrelated.read_bytes() == before


def test_creation_order_does_not_change_any_artifact_bytes(tmp_path):
    evaluator = _load_evaluator()
    first_repo = _build_repo(tmp_path / "first", creation_order_seed=1)
    second_repo = _build_repo(tmp_path / "second", creation_order_seed=2)

    evaluator.evaluate_pilot_gate(first_repo, assessor=_assessor())
    evaluator.evaluate_pilot_gate(second_repo, assessor=_assessor())

    assert _artifact_bytes(first_repo) == _artifact_bytes(second_repo)


def test_verify_existing_is_read_only_and_detects_tampering(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    evaluator.evaluate_pilot_gate(repo, assessor=_assessor())
    before = _tree_snapshot(repo)

    verified = evaluator.evaluate_pilot_gate(
        repo,
        assessor=_assessor(),
        verify_existing=True,
    )

    assert verified == {
        "mode": "verify-existing",
        "verified": True,
        "errors": [],
        "exit_code": 0,
    }
    assert _tree_snapshot(repo) == before

    evaluation_csv = repo / OUTPUT_PATHS[0]
    evaluation_csv.write_bytes(evaluation_csv.read_bytes() + b"tampered\n")
    tampered_before = _tree_snapshot(repo)
    failed = evaluator.evaluate_pilot_gate(
        repo,
        assessor=_assessor(),
        verify_existing=True,
    )
    assert failed["verified"] is False
    assert failed["exit_code"] == 1
    assert any("pilot_evaluations_v2_1.csv" in error for error in failed["errors"])
    assert _tree_snapshot(repo) == tampered_before


def test_evaluator_never_touches_formal_run_paths_and_caps_all_threads(tmp_path):
    evaluator = _load_evaluator()
    repo = _build_repo(tmp_path)
    sentinel = repo / "results/formal_v2_1/sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("do not touch", encoding="utf-8", newline="\n")
    before = _tree_snapshot(sentinel.parent)

    outcome = evaluator.evaluate_pilot_gate(repo, assessor=_assessor())

    assert outcome["exit_code"] == 0
    assert _tree_snapshot(sentinel.parent) == before
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        assert os.environ[name] == "1"
    assert sys.dont_write_bytecode is True
