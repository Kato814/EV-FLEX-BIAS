from __future__ import annotations

import csv
import json
from pathlib import Path
import warnings

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_locked_external_design_acknowledges_prior_open_and_uses_id_extremes() -> None:
    from evflex.transferability_external_validation_v2_3 import (
        load_external_validation_design,
    )

    config, frame = load_external_validation_design(REPO_ROOT)

    assert config["protocol_version"] == (
        "EV-FLEX-BIAS-V2.3-TRANSFERABILITY-LOCKED-EXTERNAL-VALIDATION"
    )
    assert config["blind_holdout_claim"] is False
    assert config["prior_v2_0_holdout_open_count"] == 1
    assert config["selection_rule"] == (
        "within each feeder-call_time cell, select the smallest and largest "
        "scenario suffix from the prior V2.0 holdout cohort; no outcome field used"
    )
    assert len(frame) == 32
    assert frame["scenario_id"].nunique() == 16
    assert set(frame["direction"]) == {"inc", "dec"}
    assert set(frame["data_role"]) == {"locked_external_validation"}
    assert set(frame["source_data_role"]) == {"holdout"}
    assert set(frame["source_holdout_access"]) == {"sealed"}
    assert set(frame["prior_holdout_open_acknowledged"]) == {True}
    assert {
        int(scenario_id.rsplit("_", 1)[1])
        for scenario_id in frame["scenario_id"]
    } == {25, 32}

    expected_scenarios = {
        f"{feeder}_{call_time}_{suffix:02d}"
        for feeder in ("ieee13", "lv906")
        for call_time in ("1900", "0000", "0200", "0600")
        for suffix in (25, 32)
    }
    assert set(frame["scenario_id"]) == expected_scenarios
    assert frame["work_unit_id"].is_unique
    assert all(
        value.startswith("v23_external_") for value in frame["work_unit_id"]
    )
    assert all(
        len(json.loads(value)) == 3 for value in frame["evaluation_ids"]
    )

    from evflex.transferability_dev_v2_2 import load_development_design

    _, development = load_development_design(REPO_ROOT)
    assert expected_scenarios.isdisjoint(set(development["scenario_id"]))


def test_external_validation_thresholds_are_frozen_before_outcomes() -> None:
    from evflex.transferability_external_validation_v2_3 import (
        load_external_validation_design,
    )

    config, _ = load_external_validation_design(REPO_ROOT)

    assert config["scientific_validation_thresholds"] == {
        "cell_failure_status_agreement_min": 0.75,
        "cell_median_spearman_rho_min": 0.6,
        "cell_median_alpha_mae_max": 0.15,
        "require_safe_and_bad_each_feeder": True,
    }
    assert config["workers"] == 1
    assert config["numeric_threads"] == 1


def _evaluation_rows(role: str, *, external_all_safe: bool = False):
    rows = []
    index = 0
    for feeder in ("ieee13", "lv906"):
        for direction in ("dec", "inc"):
            for call_time in ("00:00", "02:00", "06:00", "19:00"):
                failing_cell = index < 12 and not external_all_safe
                if role == "development_transferability":
                    values = [0.80, 0.84, 0.88, 1.0, 1.0, 1.0]
                else:
                    values = [0.82, 0.86, 0.90, 1.0, 1.0, 1.0]
                if not failing_cell:
                    values = [1.0] * 6
                for sample, alpha in enumerate(values):
                    rows.append(
                        {
                            "evaluation_id": f"{role}_{index:02d}_{sample}",
                            "work_unit_id": f"unit_{role}_{index:02d}_{sample // 3}",
                            "scenario_id": f"scenario_{role}_{index:02d}_{sample // 3}",
                            "scenario_seed": index * 10 + sample // 3,
                            "data_role": role,
                            "feeder": feeder,
                            "direction": direction,
                            "call_time": call_time,
                            "duration_min": (15, 30, 60)[sample % 3],
                            "requested_duration_min": (15, 30, 60)[sample % 3],
                            "source_duration_min": (15, 30, 60)[sample % 3],
                            "alpha_transfer": alpha,
                            "status": "SUCCESS",
                            "scientific_status": "VALID",
                            "alpha_path_scientific_valid": True,
                            "alpha_path_status": "VALID",
                            "alpha_path_audit": {"numerical_failure_audits": 0},
                            "schedule_sha256": f"{index * 6 + sample + 1:064x}",
                            "bus_phase_time_sha256": f"{index * 6 + sample + 101:064x}",
                            "baseline_schedule_sha256": "f" * 64,
                        }
                    )
                index += 1
    return rows


def test_external_summary_applies_predeclared_cell_pattern_thresholds() -> None:
    from evflex.transferability_external_validation_v2_3 import (
        build_external_validation_summary,
        load_external_validation_design,
    )

    config, _ = load_external_validation_design(REPO_ROOT)
    summary = build_external_validation_summary(
        _evaluation_rows("development_transferability"),
        _evaluation_rows("locked_external_validation"),
        config=config,
        code_commit="1" * 40,
        generated_at_utc="2026-08-11T00:00:00Z",
    )

    assert summary["machine_execution_gate"] == "PASS"
    assert summary["scientific_support_status"] == (
        "SUPPORTED_ON_LOCKED_RETROSPECTIVE_EXTERNAL_COHORT"
    )
    assert summary["blind_holdout_claim"] is False
    assert summary["counts"] == {
        "development_evaluations": 96,
        "external_evaluations": 96,
        "comparison_cells": 16,
        "development_failing_cells": 12,
        "external_failing_cells": 12,
        "external_numerical_failure_audits": 0,
    }
    comparison = summary["cell_pattern_comparison"]
    assert comparison["failure_status_agreement"] == pytest.approx(1.0)
    assert comparison["median_alpha_spearman_rho"] == pytest.approx(1.0)
    assert comparison["median_alpha_mae"] <= 0.15
    assert comparison["safe_and_bad_present_each_feeder"] is True
    assert all(comparison["threshold_checks"].values())
    assert len(summary["cells"]) == 16
    assert len(summary["evaluations"]) == 96


def test_external_summary_does_not_pass_when_validation_is_all_safe() -> None:
    from evflex.transferability_external_validation_v2_3 import (
        build_external_validation_summary,
        load_external_validation_design,
    )

    config, _ = load_external_validation_design(REPO_ROOT)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        summary = build_external_validation_summary(
            _evaluation_rows("development_transferability"),
            _evaluation_rows(
                "locked_external_validation", external_all_safe=True
            ),
            config=config,
            code_commit="1" * 40,
            generated_at_utc="2026-08-11T00:00:00Z",
        )

    assert summary["machine_execution_gate"] == "PASS"
    assert summary["scientific_support_status"] == "NOT_FULLY_SUPPORTED"
    assert summary["cell_pattern_comparison"]["failure_status_agreement"] < 0.75
    assert summary["cell_pattern_comparison"][
        "safe_and_bad_present_each_feeder"
    ] is False


def test_execute_external_unit_records_nonblind_provenance() -> None:
    from evflex.transferability_external_validation_v2_3 import (
        execute_external_validation_unit,
        load_external_validation_design,
    )

    config, frame = load_external_validation_design(REPO_ROOT)
    unit = frame.iloc[0].to_dict()
    expected_ids = json.loads(unit["evaluation_ids"])
    captured = {}

    def fake_evaluator(root, current, *, config):
        captured.update(root=root, unit=current, config=config)
        rows = _evaluation_rows("locked_external_validation")[:3]
        for row, evaluation_id, duration in zip(
            rows, expected_ids, (15, 30, 60), strict=True
        ):
            row.update(
                {
                    "evaluation_id": evaluation_id,
                    "work_unit_id": unit["work_unit_id"],
                    "scenario_id": unit["scenario_id"],
                    "scenario_seed": int(unit["scenario_seed"]),
                    "protocol_version": config["protocol_version"],
                    "feeder": unit["feeder"],
                    "call_time": unit["call_time"],
                    "direction": unit["direction"],
                    "duration_min": duration,
                    "requested_duration_min": duration,
                    "source_duration_min": duration,
                }
            )
        return rows

    result = execute_external_validation_unit(
        REPO_ROOT,
        unit,
        config,
        evaluator=fake_evaluator,
        code_commit="1" * 40,
    )

    assert captured == {"root": REPO_ROOT, "unit": unit, "config": config}
    assert result["status"] == "SUCCESS"
    assert result["work_unit_id"] == unit["work_unit_id"]
    assert [row["evaluation_id"] for row in result["evaluations"]] == expected_ids
    assert result["run_provenance"] == {
        "code_commit": "1" * 40,
        "config_sha256": config["_config_sha256"],
        "source_manifest_sha256": config["source_manifest_sha256"],
        "prior_v2_0_holdout_open_count": 1,
        "blind_holdout_claim": False,
        "source_outcomes_used_for_selection": False,
        "output_namespace": "results/transferability_external_validation_v2_3",
    }
    assert result["resource_policy"]["workers"] == 1
    assert result["resource_policy"]["numeric_threads"] == 1


def test_write_external_artifacts_retains_only_json_and_csv(tmp_path: Path) -> None:
    from evflex.transferability_external_validation_v2_3 import (
        build_external_validation_summary,
        load_external_validation_design,
        write_external_validation_artifacts,
    )

    config, _ = load_external_validation_design(REPO_ROOT)
    summary = build_external_validation_summary(
        _evaluation_rows("development_transferability"),
        _evaluation_rows("locked_external_validation"),
        config=config,
        code_commit="1" * 40,
        generated_at_utc="2026-08-11T00:00:00Z",
    )

    paths = write_external_validation_artifacts(tmp_path, summary)

    assert paths["json"].parent.name == (
        "transferability_external_validation_v2_3"
    )
    assert {path.name for path in paths["json"].parent.iterdir()} == {
        "summary.json",
        "summary.csv",
    }
    loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
    with paths["csv"].open("r", encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    assert loaded["counts"]["external_evaluations"] == 96
    assert len(csv_rows) == 96


def test_workers_other_than_one_are_rejected_before_design_access(tmp_path: Path) -> None:
    from evflex.transferability_external_validation_v2_3 import main

    with pytest.raises(SystemExit, match="exactly 1"):
        main(["--workers", "2", "--all"], repo_root=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_external_writer_refuses_to_overwrite_frozen_results(tmp_path: Path) -> None:
    from evflex.transferability_external_validation_v2_3 import (
        build_external_validation_summary,
        load_external_validation_design,
        write_external_validation_artifacts,
    )

    config, _ = load_external_validation_design(REPO_ROOT)
    summary = build_external_validation_summary(
        _evaluation_rows("development_transferability"),
        _evaluation_rows("locked_external_validation"),
        config=config,
        code_commit="1" * 40,
        generated_at_utc="2026-08-11T00:00:00Z",
    )
    write_external_validation_artifacts(tmp_path, summary)

    with pytest.raises(FileExistsError, match="already exist"):
        write_external_validation_artifacts(tmp_path, summary)


def test_checkpoint_rejects_mixed_unit_code_provenance(tmp_path: Path) -> None:
    from evflex.transferability_external_validation_v2_3 import (
        _checkpoint_payload,
        _load_checkpoint,
        load_external_validation_design,
    )

    config, _ = load_external_validation_design(REPO_ROOT)
    unit_result = {
        "status": "SUCCESS",
        "work_unit_id": "v23_external_ieee13_1900_25__inc",
        "run_provenance": {
            "code_commit": "2" * 40,
            "config_sha256": config["_config_sha256"],
            "blind_holdout_claim": False,
        },
        "evaluations": [],
    }
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            _checkpoint_payload(
                config=config,
                code_commit="1" * 40,
                unit_results=[unit_result],
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unit provenance"):
        _load_checkpoint(checkpoint, config=config, code_commit="1" * 40)


def test_resume_is_rejected_for_single_unit_before_design_access(
    tmp_path: Path,
) -> None:
    from evflex.transferability_external_validation_v2_3 import main

    with pytest.raises(SystemExit, match="only valid with --all"):
        main(
            [
                "--workers",
                "1",
                "--unit-id",
                "v23_external_ieee13_1900_25__inc",
                "--resume",
            ],
            repo_root=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []
