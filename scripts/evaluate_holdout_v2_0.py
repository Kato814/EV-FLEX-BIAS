from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

for variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[variable] = "1"

import pandas as pd

from evflex.aggregate import (
    assess_evaluations,
    load_work_unit_evaluations,
    sort_and_normalize_rows,
    write_csv_atomic,
)
from evflex.holdout_analysis import (
    HOLDOUT_BOOTSTRAP_RESAMPLES,
    HOLDOUT_BOOTSTRAP_SEED,
    build_holdout_feature_frame,
    directional_summary,
    evaluate_frozen_applicability,
)
from evflex.provenance import sha256_file
from evflex.runner import atomic_write_json


PROTOCOL_ID = "EV-FLEX-BIAS-V2.0"
EXPECTED_HOLDOUT_EVALUATIONS = 384
EXPECTED_HOLDOUT_WORK_UNITS = 128
EXPECTED_APPLICABILITY_CELLS = 12
EXPECTED_DIRECTIONAL_CELLS = 6


def _resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def _git_head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _relative(repo: Path, path: Path) -> str:
    return str(path.resolve(strict=False).relative_to(repo)).replace("\\", "/")


def _raw_hash_rows(repo: Path, work_unit_directory: Path) -> list[dict]:
    rows = []
    for path in sorted(
        work_unit_directory.glob("*.json"), key=lambda item: item.name.casefold()
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "work_unit_id": str(payload.get("work_unit_id")),
                "relative_path": _relative(repo, path),
                "bytes": int(path.stat().st_size),
                "sha256": sha256_file(path),
                "status": str(payload.get("status")),
                "attempt_count": int(payload.get("attempt_count", 0)),
                "evaluation_rows": int(len(payload.get("evaluations", []))),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-units", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--holdout-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    work_unit_directory = _resolve(repo, args.work_units).resolve(strict=True)
    model_path = _resolve(repo, args.models).resolve(strict=True)
    holdout_csv = _resolve(repo, args.holdout_csv)
    output_directory = _resolve(repo, args.output_dir)
    gate_path = _resolve(repo, args.gate)
    summary_path = _resolve(repo, args.summary)
    unlock_path = repo / "state" / "holdout_unlock_v2_0.json"

    unlock = json.loads(unlock_path.read_text(encoding="utf-8"))
    unlock_valid = (
        unlock.get("status") == "UNLOCKED"
        and unlock.get("protocol_version") == PROTOCOL_ID
        and int(unlock.get("holdout_open_count", 0)) == 1
        and unlock.get("refit_allowed") is False
        and unlock.get("rethreshold_allowed") is False
        and unlock.get("replacement_ids_allowed") is False
    )

    model_sha256_before = sha256_file(model_path)
    models_payload = json.loads(model_path.read_text(encoding="utf-8"))
    model_payload_valid = (
        models_payload.get("protocol_id") == PROTOCOL_ID
        and models_payload.get("training_role") == "development"
        and int(models_payload.get("model_count", 0)) == EXPECTED_APPLICABILITY_CELLS
    )

    evaluation_manifest = pd.read_csv(
        repo / "manifests" / "core_evaluations_v2_0.csv"
    )
    expected_manifest = evaluation_manifest.loc[
        evaluation_manifest["data_role"].eq("holdout")
    ].copy()
    expected_ids = set(expected_manifest["evaluation_id"].astype(str))
    evaluation_order = {
        evaluation_id: index
        for index, evaluation_id in enumerate(
            evaluation_manifest["evaluation_id"].astype(str)
        )
    }
    work_manifest = pd.read_csv(repo / "manifests" / "core_work_units_v2_0.csv")
    expected_work_units = set(
        work_manifest.loc[
            work_manifest["data_role"].eq("holdout"), "work_unit_id"
        ].astype(str)
    )

    raw_hash_rows = _raw_hash_rows(repo, work_unit_directory)
    raw_work_unit_ids = {row["work_unit_id"] for row in raw_hash_rows}
    rows, input_errors = load_work_unit_evaluations(work_unit_directory)
    rows = sort_and_normalize_rows(rows, evaluation_order)
    assessment = assess_evaluations(
        rows,
        EXPECTED_HOLDOUT_EVALUATIONS,
        input_errors=input_errors,
    )
    actual_ids = {str(row.get("evaluation_id")) for row in rows}
    actual_roles = sorted({str(row.get("data_role")) for row in rows})

    holdout_csv_sha256 = write_csv_atomic(holdout_csv, rows)
    holdout_frame = pd.DataFrame(rows)
    scenarios = pd.read_csv(repo / "data" / "inherited" / "base_scenarios_v1_2.csv")
    populations = pd.read_csv(
        repo / "data" / "inherited" / "formal_ev_population_summary_v1_2.csv"
    )
    features = build_holdout_feature_frame(holdout_frame, scenarios, populations)
    applicability = evaluate_frozen_applicability(
        models_payload,
        features,
        model_sha256=model_sha256_before,
    )
    directional, directional_audit = directional_summary(
        holdout_frame,
        bootstrap_resamples=HOLDOUT_BOOTSTRAP_RESAMPLES,
        bootstrap_seed=HOLDOUT_BOOTSTRAP_SEED,
    )

    applicability_path = output_directory / "applicability_validation_v2_0.csv"
    directional_path = output_directory / "directional_summary_v2_0.csv"
    applicability_sha256 = write_csv_atomic(
        applicability_path, applicability.to_dict("records")
    )
    directional_sha256 = write_csv_atomic(
        directional_path, directional.to_dict("records")
    )
    raw_hash_manifest_path = repo / "reports" / "holdout_work_unit_hashes_v2_0.csv"
    raw_hash_manifest_sha256 = write_csv_atomic(
        raw_hash_manifest_path, raw_hash_rows
    )

    model_sha256_after = sha256_file(model_path)
    model_unchanged = model_sha256_before == model_sha256_after
    unlock_model_matches = (
        str(unlock.get("frozen_model_sha256")) == model_sha256_before
    )
    claim_counts = {
        str(status): int(count)
        for status, count in applicability["claim_status"].value_counts().items()
    }

    violations = dict(assessment["violations"])
    violations.update(
        {
            "unlock_invalid": not unlock_valid,
            "unlock_frozen_model_hash_mismatch": not unlock_model_matches,
            "frozen_model_payload_invalid": not model_payload_valid,
            "frozen_model_changed_during_scoring": not model_unchanged,
            "holdout_evaluation_id_missing": sorted(expected_ids - actual_ids),
            "holdout_evaluation_id_unexpected": sorted(actual_ids - expected_ids),
            "data_role_mismatch": actual_roles != ["holdout"],
            "raw_work_unit_count_mismatch": len(raw_hash_rows)
            != EXPECTED_HOLDOUT_WORK_UNITS,
            "holdout_work_unit_id_missing": sorted(
                expected_work_units - raw_work_unit_ids
            ),
            "holdout_work_unit_id_unexpected": sorted(
                raw_work_unit_ids - expected_work_units
            ),
            "applicability_cell_count_mismatch": len(applicability)
            != EXPECTED_APPLICABILITY_CELLS,
            "directional_cell_count_mismatch": len(directional)
            != EXPECTED_DIRECTIONAL_CELLS,
        }
    )
    failed = any(
        bool(value)
        for value in violations.values()
        if not isinstance(value, dict)
    ) or any(bool(value) for value in violations.values() if isinstance(value, dict))

    gate = {
        "gate": "G6_HOLDOUT_EVIDENCE_COMPONENT",
        "gate_status": "FAIL" if failed else "PASS",
        "protocol_id": PROTOCOL_ID,
        "expected_evaluations": EXPECTED_HOLDOUT_EVALUATIONS,
        "actual_evaluations": int(assessment["actual_evaluations"]),
        "unique_evaluation_ids": int(assessment["unique_evaluation_ids"]),
        "expected_work_units": EXPECTED_HOLDOUT_WORK_UNITS,
        "actual_work_units": int(assessment["work_units"]),
        "raw_result_files": int(len(raw_hash_rows)),
        "status_counts": assessment["status_counts"],
        "scientific_terminal_count": int(
            assessment["scientific_terminal_count"]
        ),
        "scientific_terminal_ids": assessment["scientific_terminal_ids"],
        "unhandled_failure_count": int(assessment["unhandled_failure_count"]),
        "holdout_open_count": int(unlock.get("holdout_open_count", 0)),
        "frozen_model_sha256_before": model_sha256_before,
        "frozen_model_sha256_after": model_sha256_after,
        "frozen_model_unchanged": model_unchanged,
        "applicability_cells": int(len(applicability)),
        "directional_cells": int(len(directional)),
        "claim_status_counts": claim_counts,
        "violations": violations,
    }
    atomic_write_json(gate_path, gate)

    output_hashes = {
        _relative(repo, holdout_csv): holdout_csv_sha256,
        _relative(repo, applicability_path): applicability_sha256,
        _relative(repo, directional_path): directional_sha256,
        _relative(repo, raw_hash_manifest_path): raw_hash_manifest_sha256,
        _relative(repo, gate_path): sha256_file(gate_path),
    }
    summary = {
        "artifact": "final_holdout_analysis",
        "protocol_id": PROTOCOL_ID,
        "gate_status": gate["gate_status"],
        "analysis_code_commit": _git_head(repo),
        "holdout_opened_at_utc": unlock.get("opened_at_utc"),
        "holdout_open_count": int(unlock.get("holdout_open_count", 0)),
        "expected_evaluations": EXPECTED_HOLDOUT_EVALUATIONS,
        "actual_evaluations": int(assessment["actual_evaluations"]),
        "successful_evaluations": int(
            assessment["status_counts"].get("SUCCESS", 0)
        ),
        "scientific_terminal_count": int(
            assessment["scientific_terminal_count"]
        ),
        "scientific_terminal_ids": assessment["scientific_terminal_ids"],
        "failed_or_unpaired_directional_ids": sorted(
            set(directional_audit["failed_evaluation_ids"])
            | set(directional_audit["unpaired_evaluation_ids"])
        ),
        "frozen_model": _relative(repo, model_path),
        "frozen_model_sha256_before": model_sha256_before,
        "frozen_model_sha256_after": model_sha256_after,
        "frozen_model_unchanged": model_unchanged,
        "refit_performed": False,
        "rethreshold_performed": False,
        "replacement_ids_used": False,
        "applicability_cells": int(len(applicability)),
        "claim_status_counts": claim_counts,
        "directional_cells": int(len(directional)),
        "directional_bootstrap": directional_audit,
        "output_hashes": output_hashes,
    }
    atomic_write_json(summary_path, summary)
    print(
        json.dumps(
            {
                "gate_status": gate["gate_status"],
                "evaluations": gate["actual_evaluations"],
                "work_units": gate["actual_work_units"],
                "status_counts": gate["status_counts"],
                "claim_status_counts": claim_counts,
                "model_unchanged": model_unchanged,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if gate["gate_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
