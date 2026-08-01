from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from evflex.mechanism_diagnostic import (
    canonical_json_bytes,
    load_mechanism_config,
    load_pair_manifest,
    pair_members,
    strict_json_file,
    validate_pair_artifact,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_mechanism_diagnostic_v2_1.py"
AUDIT_SEQUENCE = (
    ("BOUNDARY_FEASIBLE", "bad"),
    ("BOUNDARY_FEASIBLE", "control"),
    ("BOUNDARY_INFEASIBLE", "bad"),
    ("BOUNDARY_INFEASIBLE", "control"),
    ("FULL_OFFER", "bad"),
    ("FULL_OFFER", "control"),
)
FORMAL_CONSTRAINTS = {
    "vmin_pu": 0.95,
    "vmax_pu": 1.06,
    "vuf_limit_pct": 2.0,
    "transformer_loading_limit_pu": 1.0,
    "feeder_loading_limit_pu": 1.0,
    "line_thermal_in_scope": False,
}
THREAD_NAMES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _coverage() -> dict[str, object]:
    return {
        "all_bus_count": 2,
        "monitored_bus_count": 2,
        "energized_voltage_node_count": 2,
        "monitored_voltage_node_count": 2,
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


def _row(
    family: str,
    object_id: str,
    *,
    physical: bool = False,
) -> dict[str, object]:
    if family in {"VMIN", "VMAX"}:
        metric_id = f"V:{object_id}"
    elif family == "VUF":
        metric_id = f"U:{object_id}"
    else:
        raise AssertionError(f"unsupported synthetic family {family}")
    direction = "lo" if family == "VMIN" else "hi"
    limit = 0.95 if family == "VMIN" else 1.06 if family == "VMAX" else 2.0
    headroom = -0.01 if physical else 0.01
    value = limit + headroom if direction == "lo" else limit - headroom
    return {
        "slot": 5,
        "constraint_family": family,
        "metric_id": metric_id,
        "object_id": object_id,
        "value": value,
        "limit": limit,
        "direction": direction,
        "signed_headroom": headroom,
        "exceedance": max(0.0, -headroom),
        "is_physical_violation": physical,
    }


def _selected(*, physical: bool) -> dict[str, object]:
    rows = [
        _row("VMIN", "bus.1", physical=physical),
        _row("VMAX", "bus.1"),
        _row("VUF", "bus"),
    ]
    return {
        "slot": 5,
        "constraint_rows": rows,
        "simultaneous_violations": [deepcopy(rows[0])] if physical else [],
    }


def _alpha(pair: dict[str, object], config: dict[str, object], point: str) -> float:
    base = Decimal(str(pair["bad_alpha_transfer"]))
    delta = Decimal(str(config["audit"]["delta"]))
    if point == "BOUNDARY_FEASIBLE":
        return float(base)
    if point == "BOUNDARY_INFEASIBLE":
        return float(base + delta)
    return 1.0


def _audit(
    pair: dict[str, object],
    config: dict[str, object],
    index: int,
    *,
    contradict: bool = False,
) -> dict[str, object]:
    point, role = AUDIT_SEQUENCE[index]
    bad, control = pair_members(pair)
    member = bad if role == "bad" else control
    expected_failure = role == "bad" and point in {
        "BOUNDARY_INFEASIBLE",
        "FULL_OFFER",
    }
    failure = expected_failure and not contradict
    feasible = not failure
    checked = 6 if failure else 96
    selected = None
    if point == "BOUNDARY_INFEASIBLE":
        selected = _selected(physical=failure)
    elif point == "FULL_OFFER" and failure:
        full_row = _row("VMIN", "bus.1", physical=True)
        selected = {
            "slot": 5,
            "constraint_rows": [full_row],
            "simultaneous_violations": [deepcopy(full_row)],
        }
    alpha = _alpha(pair, config, point)
    alpha_label = f"{alpha:.3f}"
    audited_hash = _sha(f"audited-{pair['pair_id']}-{index}")
    load_hash = _sha(f"load-{role}")
    input_payload = {
        "protocol_version": config["protocol_version"],
        "pair_id": pair["pair_id"],
        "role": role,
        "source_evaluation_id": member["evaluation_id"],
        "audit_point": point,
        "alpha": alpha_label,
        "baseline_schedule_sha256": member["baseline_schedule_sha256"],
        "source_schedule_sha256": member["schedule_sha256"],
        "audited_schedule_sha256": audited_hash,
        "load_scales_sha256": load_hash,
        "formal_constraints": FORMAL_CONSTRAINTS,
    }
    return {
        "sequence_index": index,
        "pair_id": pair["pair_id"],
        "scenario_cluster": pair["scenario_cluster"],
        "role": role,
        "source_evaluation_id": member["evaluation_id"],
        "source_work_unit_id": member["work_unit_id"],
        "scenario_id": member["scenario_id"],
        "scenario_seed": member["scenario_seed"],
        "feeder": member["feeder"],
        "call_time": member["call_time"],
        "direction": member["direction"],
        "duration_min": member["duration_min"],
        "source_duration_min": member["source_duration_min"],
        "alpha_label": alpha_label,
        "baseline_schedule_sha256": member["baseline_schedule_sha256"],
        "source_schedule_sha256": member["schedule_sha256"],
        "bus_phase_time_sha256": member["bus_phase_time_sha256"],
        "audited_schedule_sha256": audited_hash,
        "load_scales_sha256": load_hash,
        "audit_input_sha256": hashlib.sha256(
            canonical_json_bytes(input_payload)
        ).hexdigest(),
        "formal_constraints": deepcopy(FORMAL_CONSTRAINTS),
        "line_thermal_in_scope": False,
        "audit_point": point,
        "alpha": alpha,
        "feasible": feasible,
        "checked_intervals": checked,
        "coverage_ratio": checked / 96.0,
        "complete_coverage": checked == 96,
        "converged_checks": checked,
        "nonconverged_checks": 0,
        "numerical_failure_checks": 0,
        "physical_violation_checks": 1 if failure else 0,
        "failure_class": "PHYSICAL_CONSTRAINT" if failure else "NONE",
        "first_failure_slot": 5 if failure else None,
        "explicit_physical_witness": failure,
        "selected_slot": selected,
        "coverage_counts": _coverage(),
        "vmin": 0.94 if failure else 1.0,
        "vmax": 1.0,
        "vufmax": 0.5,
        "transformer_loading_max": 0.5,
        "feeder_loading_max": 0.5,
    }


def _success_artifact(
    pair: dict[str, object], config: dict[str, object]
) -> dict[str, object]:
    bad, control = pair_members(pair)
    return {
        "protocol_version": config["protocol_version"],
        "status": "SUCCESS",
        "pair_id": pair["pair_id"],
        "scenario_cluster": pair["scenario_cluster"],
        "source_commit": config["source_commit"],
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
        "relative_stress": deepcopy(config["relative_stress"]),
        "members": {"bad": bad, "control": control},
        "audits": [_audit(pair, config, index) for index in range(6)],
    }


def _stop_artifact(
    pair: dict[str, object], config: dict[str, object]
) -> dict[str, object]:
    artifact = _success_artifact(pair, config)
    artifact["status"] = "STOP_IMPLEMENTATION"
    artifact["audits"] = [
        _audit(pair, config, 0),
        _audit(pair, config, 1),
        _audit(pair, config, 2, contradict=True),
    ]
    artifact["failure"] = {
        "kind": "FROZEN_RULE_CONTRADICTION",
        "rule_code": "BAD_BOUNDARY_INFEASIBLE_REQUIRED",
        "detail": "bad boundary unexpectedly remained feasible",
        "sequence_index": 2,
    }
    return artifact


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("d1_runner_for_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config_and_pairs() -> tuple[dict[str, object], list[dict[str, object]]]:
    return load_mechanism_config(REPO_ROOT), load_pair_manifest(REPO_ROOT)


def test_validate_pair_artifact_requires_exact_identity_and_six_audits() -> None:
    config, pairs = _config_and_pairs()
    pair = pairs[0]
    artifact = _success_artifact(pair, config)

    validate_pair_artifact(artifact, pair, config)

    wrong_identity = deepcopy(artifact)
    wrong_identity["pair_id"] = "99"
    with pytest.raises(ValueError, match="pair identity"):
        validate_pair_artifact(wrong_identity, pair, config)

    incomplete = deepcopy(artifact)
    incomplete["audits"].pop()
    with pytest.raises(ValueError, match="exactly six audits"):
        validate_pair_artifact(incomplete, pair, config)

    wrong_capture = deepcopy(artifact)
    wrong_capture["audits"][3]["selected_slot"]["slot"] = 4
    for row in wrong_capture["audits"][3]["selected_slot"]["constraint_rows"]:
        row["slot"] = 4
    with pytest.raises(ValueError, match="control capture slot"):
        validate_pair_artifact(wrong_capture, pair, config)


def test_validate_pair_artifact_rejects_nonfinite_or_duplicate_content(
    tmp_path: Path,
) -> None:
    config, pairs = _config_and_pairs()
    artifact = _success_artifact(pairs[0], config)
    artifact["audits"][0]["vmin"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        validate_pair_artifact(artifact, pairs[0], config)

    duplicate_row = _success_artifact(pairs[0], config)
    selected = duplicate_row["audits"][3]["selected_slot"]
    selected["constraint_rows"].insert(2, deepcopy(selected["constraint_rows"][1]))
    with pytest.raises(ValueError, match="duplicate constraint object"):
        validate_pair_artifact(duplicate_row, pairs[0], config)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"pair_id":"01","pair_id":"02"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        strict_json_file(duplicate)


def test_runner_is_sequential_and_enforces_six_thread_caps(tmp_path: Path) -> None:
    runner = _load_runner()
    config, pairs = _config_and_pairs()
    calls: list[str] = []

    def fake_execute(
        _root: Path,
        pair: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        calls.append(str(pair["pair_id"]))
        return _success_artifact(pair, config)

    summary = runner.run_diagnostic(
        tmp_path,
        config=config,
        pairs=pairs[:2],
        execute_fn=fake_execute,
        preflight=False,
    )

    assert calls == ["01", "02"]
    assert summary["status"] == "SUCCESS"
    assert runner.THREAD_ENVIRONMENT == {name: "1" for name in THREAD_NAMES}
    assert all(os.environ[name] == "1" for name in THREAD_NAMES)
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "ProcessPoolExecutor" not in source


def test_runner_atomically_writes_one_terminal_json_per_pair(tmp_path: Path) -> None:
    runner = _load_runner()
    config, pairs = _config_and_pairs()
    pair = pairs[0]

    runner.run_diagnostic(
        tmp_path,
        config=config,
        pairs=[pair],
        execute_fn=lambda _root, current, _config: _success_artifact(
            current, config
        ),
        preflight=False,
    )

    result = tmp_path / config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id="01"
    )
    assert result.is_file()
    validate_pair_artifact(strict_json_file(result), pair, config)
    assert not list(result.parent.glob("*.tmp"))
    assert not (
        tmp_path / config["artifact_names"]["attempt_pattern"].format(pair_id="01")
    ).exists()
    assert not (tmp_path / config["artifact_names"]["run_lock"]).exists()


def test_runner_resumes_only_strictly_valid_completed_pair(tmp_path: Path) -> None:
    runner = _load_runner()
    config, pairs = _config_and_pairs()
    pair = pairs[0]
    result = tmp_path / config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id="01"
    )
    result.parent.mkdir(parents=True)
    result.write_text(
        json.dumps(_success_artifact(pair, config), allow_nan=False),
        encoding="utf-8",
    )

    summary = runner.run_diagnostic(
        tmp_path,
        config=config,
        pairs=[pair],
        execute_fn=lambda *_args: pytest.fail("completed pair was recomputed"),
        preflight=False,
    )
    assert summary["skipped_pair_ids"] == ["01"]

    invalid = strict_json_file(result)
    invalid["pair_id"] = "99"
    result.write_text(json.dumps(invalid), encoding="utf-8")
    before = result.read_bytes()
    with pytest.raises(ValueError, match="invalid existing pair artifact"):
        runner.run_diagnostic(
            tmp_path,
            config=config,
            pairs=[pair],
            execute_fn=lambda *_args: pytest.fail("invalid pair was overwritten"),
            preflight=False,
        )
    assert result.read_bytes() == before


def test_runner_stops_on_invalid_existing_pair_lock_attempt_or_tmp(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    config, pairs = _config_and_pairs()

    lock_root = tmp_path / "lock_case"
    lock = lock_root / config["artifact_names"]["run_lock"]
    lock.parent.mkdir(parents=True)
    lock.write_text("123", encoding="ascii")
    with pytest.raises(ValueError, match="run lock"):
        runner.validate_runtime_inventory(lock_root, config, pairs)

    attempt_root = tmp_path / "attempt_case"
    attempt = attempt_root / config["artifact_names"]["attempt_pattern"].format(
        pair_id="01"
    )
    attempt.parent.mkdir(parents=True)
    attempt.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="attempt state"):
        runner.validate_runtime_inventory(attempt_root, config, pairs)

    temp_root = tmp_path / "temp_case"
    temporary = temp_root / config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id="01"
    )
    temporary.parent.mkdir(parents=True)
    Path(str(temporary) + ".dead.tmp").write_text("partial", encoding="utf-8")
    with pytest.raises(ValueError, match="temporary file"):
        runner.validate_runtime_inventory(temp_root, config, pairs)


def test_runner_preflight_checks_old_gate_and_forbids_formal_outputs(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    commands: list[list[str]] = []

    def fake_subprocess(command: list[str], **kwargs: object) -> object:
        commands.append(command)
        assert kwargs["cwd"] == REPO_ROOT
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    runner.verify_archived_gate(REPO_ROOT, subprocess_runner=fake_subprocess)
    assert commands and "--verify-existing" in commands[0]

    config, pairs = _config_and_pairs()
    formal = tmp_path / "results" / "formal_v2_1"
    formal.mkdir(parents=True)
    with pytest.raises(ValueError, match="formal V2.1 output"):
        runner.validate_runtime_inventory(tmp_path, config, pairs)


def test_stop_artifact_contains_only_continuous_audit_prefix() -> None:
    config, pairs = _config_and_pairs()
    pair = pairs[0]
    stop = _stop_artifact(pair, config)
    validate_pair_artifact(stop, pair, config)

    skipped = deepcopy(stop)
    skipped["audits"].pop(1)
    with pytest.raises(ValueError, match="continuous audit prefix"):
        validate_pair_artifact(skipped, pair, config)

    later = deepcopy(stop)
    later["audits"].append(_audit(pair, config, 4))
    with pytest.raises(ValueError, match="continuous audit prefix"):
        validate_pair_artifact(later, pair, config)


def test_runner_stop_reason_is_first_failed_rule_and_no_later_pair_runs(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    config, pairs = _config_and_pairs()
    calls: list[str] = []

    def fake_execute(
        _root: Path,
        pair: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        calls.append(str(pair["pair_id"]))
        return _stop_artifact(pair, config)

    summary = runner.run_diagnostic(
        tmp_path,
        config=config,
        pairs=pairs[:2],
        execute_fn=fake_execute,
        preflight=False,
    )

    assert calls == ["01"]
    assert summary["status"] == "STOP_IMPLEMENTATION"
    assert summary["failure"]["rule_code"] == "BAD_BOUNDARY_INFEASIBLE_REQUIRED"
    second = tmp_path / config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id="02"
    )
    assert not second.exists()


def test_runner_classifies_controlled_evidence_error_as_stop(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    config, pairs = _config_and_pairs()
    calls: list[str] = []

    def controlled_failure(
        _root: Path,
        pair: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        calls.append(str(pair["pair_id"]))
        raise ValueError("controlled evidence invalid")

    summary = runner.run_diagnostic(
        tmp_path,
        config=config,
        pairs=pairs[:2],
        execute_fn=controlled_failure,
        preflight=False,
    )

    assert calls == ["01"]
    assert summary["status"] == "STOP_IMPLEMENTATION"
    assert summary["failure"]["rule_code"] == "PRE_AUDIT_IMPLEMENTATION_INVALID"


def test_runner_preserves_completed_prefix_from_controlled_audit_stop(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    config, pairs = _config_and_pairs()
    pair = pairs[0]

    def audit_failure(
        _root: Path,
        _pair: dict[str, object],
        _config: dict[str, object],
    ) -> dict[str, object]:
        raise runner.D1AuditStop(
            "AUDIT_EVIDENCE_INVALID",
            "third audit evidence is inconsistent",
            audits=[_audit(pair, config, 0), _audit(pair, config, 1)],
            sequence_index=2,
        )

    summary = runner.run_diagnostic(
        tmp_path,
        config=config,
        pairs=[pair],
        execute_fn=audit_failure,
        preflight=False,
    )

    assert summary["status"] == "STOP_IMPLEMENTATION"
    result = tmp_path / config["artifact_names"]["pair_artifact_pattern"].format(
        pair_id="01"
    )
    payload = strict_json_file(result)
    assert len(payload["audits"]) == 2
    assert payload["failure"]["sequence_index"] == 2
