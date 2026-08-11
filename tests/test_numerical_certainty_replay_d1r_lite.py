from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from evflex.numerical_certainty_replay_d1r_lite import (
    assess_case_replay,
    assess_replay_gate,
    load_replay_config,
    load_replay_source,
    select_replay_cases,
    validate_replay_case_artifact,
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


def _observation(
    selection: dict[str, object],
    setting: dict[str, object],
    value: float,
    *,
    converged: bool = True,
    numerical_failure: bool = False,
    metric_id: str | None = None,
    direction: str = "hi",
    observed_tolerance: float | None = None,
) -> dict[str, object]:
    config = load_replay_config(REPO_ROOT)
    observed_metric = str(selection["metric_id"] if metric_id is None else metric_id)
    limit = float(selection["limit"])
    physical = bool(
        direction == "hi"
        and value > limit + config["thresholds"]["physical_violation_margin_pu"]
    )
    requested = deepcopy(setting)
    observed = {
        "convergence_tolerance": (
            float(setting["convergence_tolerance"])
            if observed_tolerance is None
            else observed_tolerance
        ),
        "max_iterations": int(setting["max_iterations"]),
        "max_control_iterations": int(setting["max_control_iterations"]),
    }
    return {
        "setting_label": setting["label"],
        "requested_solver_settings": requested,
        "observed_solver_settings": observed,
        "selected_slot": selection["selected_slot"],
        "load_scale": 1.0,
        "audited_schedule_sha256": selection["audited_schedule_sha256"],
        "power_vector_sha256": "b" * 64,
        "metric_id": observed_metric,
        "metric_value": value,
        "limit": limit,
        "direction": direction,
        "exceedance": max(0.0, value - limit),
        "physical_violation": physical,
        "physical_violation_metrics": [observed_metric] if physical else [],
        "converged": converged,
        "numerical_failure": numerical_failure,
        "iterations": 3,
        "vmin": 1.0,
        "vmax": value,
        "line_thermal_in_scope": False,
        "independent_context": True,
    }


def _stable_observations(selection: dict[str, object]) -> list[dict[str, object]]:
    config = load_replay_config(REPO_ROOT)
    archived = float(selection["value"])
    return [
        _observation(selection, config["solver_settings"][0], archived),
        _observation(selection, config["solver_settings"][1], archived + 2e-8),
        _observation(selection, config["solver_settings"][2], archived + 2.5e-8),
    ]


def _case_artifact(
    selection: dict[str, object],
    observations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    config = load_replay_config(REPO_ROOT)
    retained = _stable_observations(selection) if observations is None else observations
    assessment = assess_case_replay(selection, retained, config)
    return {
        "protocol_version": config["protocol_version"],
        "status": (
            "SUCCESS"
            if assessment["case_decision"]
            in {"NUMERICALLY_STABLE_WITNESS", "NUMERICAL_SENSITIVITY_DETECTED"}
            else "STOP_REPLAY"
        ),
        "pair_id": selection["pair_id"],
        "scenario_cluster": selection["scenario_cluster"],
        "selection": deepcopy(selection),
        "source_evidence_commit": config["source_evidence_commit"],
        "source_n0_commit": config["source_n0_commit"],
        "runtime_version": config["runtime_requirement"]["version"],
        "target_replay_evaluations": 3,
        "observations": deepcopy(retained),
        "assessment": assessment,
        "formal_v2_1_run_started": False,
        "formal_v2_1_run_authorized": False,
        "line_thermal_in_scope": False,
        "resource_policy": deepcopy(config["resource_policy"]),
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


def test_native_identity_accepts_exact_archive_and_rejects_over_1e_minus_9_drift() -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][0])
    stable = assess_case_replay(selection, _stable_observations(selection), config)
    drifted = _stable_observations(selection)
    drifted[0]["metric_value"] = float(selection["value"]) + 2e-9
    drifted[0]["exceedance"] = drifted[0]["metric_value"] - float(selection["limit"])

    stopped = assess_case_replay(selection, drifted, config)

    assert stable["native_replay_identity_ok"] is True
    assert stopped["native_replay_identity_ok"] is False
    assert stopped["case_decision"] == "STOP_REPLAY_IDENTITY_MISMATCH"


def test_tight_witness_requires_same_metric_hi_direction_and_physical_margin() -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][1])
    observations = _stable_observations(selection)
    observations[1] = _observation(
        selection,
        config["solver_settings"][1],
        float(selection["value"]),
        metric_id="V:other.1",
    )

    result = assess_case_replay(selection, observations, config)

    assert result["witness_persists"] == {
        "TIGHT_1E6": False,
        "ULTRA_1E8": True,
    }
    assert result["case_decision"] == "NUMERICAL_SENSITIVITY_DETECTED"


def test_case_is_stable_at_both_tight_settings_with_frozen_drifts() -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][2])

    result = assess_case_replay(selection, _stable_observations(selection), config)

    assert result["case_decision"] == "NUMERICALLY_STABLE_WITNESS"
    assert result["native_to_tight_drift_pu"]["TIGHT_1E6"] == pytest.approx(2e-8)
    assert result["tight_plateau_drift_pu"] == pytest.approx(5e-9)


def test_case_detects_native_to_tight_drift_over_1e_minus_6() -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][0])
    observations = _stable_observations(selection)
    observations[1] = _observation(
        selection,
        config["solver_settings"][1],
        float(selection["value"]) + 1.1e-6,
    )

    result = assess_case_replay(selection, observations, config)

    assert result["native_to_tight_drift_ok"]["TIGHT_1E6"] is False
    assert result["case_decision"] == "NUMERICAL_SENSITIVITY_DETECTED"


def test_case_detects_tight_plateau_drift_over_1e_minus_7() -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][3])
    observations = _stable_observations(selection)
    observations[2] = _observation(
        selection,
        config["solver_settings"][2],
        float(observations[1]["metric_value"]) + 2e-7,
    )

    result = assess_case_replay(selection, observations, config)

    assert result["tight_plateau_ok"] is False
    assert result["case_decision"] == "NUMERICAL_SENSITIVITY_DETECTED"


def test_gate_requires_all_four_cases_stable() -> None:
    config = load_replay_config(REPO_ROOT)
    artifacts = [_case_artifact(deepcopy(item)) for item in config["selected_cases"]]

    stable = assess_replay_gate(artifacts, config)
    sensitive_artifacts = deepcopy(artifacts)
    sensitive_observations = _stable_observations(
        deepcopy(config["selected_cases"][1])
    )
    sensitive_observations[1] = _observation(
        deepcopy(config["selected_cases"][1]),
        config["solver_settings"][1],
        float(config["selected_cases"][1]["value"]) + 1.1e-6,
    )
    sensitive_artifacts[1] = _case_artifact(
        deepcopy(config["selected_cases"][1]), sensitive_observations
    )
    sensitive = assess_replay_gate(sensitive_artifacts, config)

    assert stable["decision"] == "NUMERICALLY_STABLE_SELECTED_WITNESSES"
    assert stable["stable_case_count"] == 4
    assert sensitive["decision"] == "NUMERICAL_SENSITIVITY_DETECTED"


@pytest.mark.parametrize(
    ("case_decision", "expected"),
    [
        ("STOP_REPLAY_IDENTITY_MISMATCH", "STOP_REPLAY_IDENTITY_MISMATCH"),
        ("STOP_SOLVER_FAILURE", "STOP_SOLVER_FAILURE"),
    ],
)
def test_gate_distinguishes_identity_mismatch_and_solver_failure(
    case_decision: str, expected: str
) -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][0])
    observations = _stable_observations(selection)
    if case_decision == "STOP_REPLAY_IDENTITY_MISMATCH":
        observations[0]["metric_value"] = float(selection["value"]) + 2e-9
        observations[0]["exceedance"] = observations[0]["metric_value"] - float(
            selection["limit"]
        )
    else:
        observations[0]["converged"] = False
        observations[0]["numerical_failure"] = True
    artifact = _case_artifact(selection, observations)

    result = assess_replay_gate([artifact], config)

    assert result["decision"] == expected
    assert result["completed_case_count"] == 1


def test_case_artifact_rejects_nonfinite_unexpected_or_scope_expanding_fields() -> None:
    config = load_replay_config(REPO_ROOT)
    selection = deepcopy(config["selected_cases"][0])
    artifact = _case_artifact(selection)
    validate_replay_case_artifact(artifact, selection, config)

    nonfinite = deepcopy(artifact)
    nonfinite["observations"][0]["metric_value"] = float("inf")
    with pytest.raises(ValueError, match="non-finite"):
        validate_replay_case_artifact(nonfinite, selection, config)

    unexpected = deepcopy(artifact)
    unexpected["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected or missing"):
        validate_replay_case_artifact(unexpected, selection, config)

    expanded = deepcopy(artifact)
    expanded["formal_v2_1_run_authorized"] = True
    with pytest.raises(ValueError, match="scope"):
        validate_replay_case_artifact(expanded, selection, config)
