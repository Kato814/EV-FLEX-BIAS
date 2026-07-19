from __future__ import annotations

import os

for _name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_name] = "1"

import argparse
from pathlib import Path

import pandas as pd

from evflex.aggregate import write_csv_atomic
from evflex.modeling import assess_modeling_gate, build_feature_frame, fit_all_models
from evflex.provenance import sha256_file
from evflex.runner import atomic_write_json


def resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--oof", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    development_path = resolve(repo, args.development)
    models_path = resolve(repo, args.models)
    oof_path = resolve(repo, args.oof)
    report_path = resolve(repo, args.report)
    scenarios_path = repo / "data" / "inherited" / "base_scenarios_v1_2.csv"
    populations_path = (
        repo / "data" / "inherited" / "formal_ev_population_summary_v1_2.csv"
    )

    development = pd.read_csv(development_path)
    scenarios = pd.read_csv(scenarios_path)
    populations = pd.read_csv(populations_path)
    feature_frame = build_feature_frame(development, scenarios, populations)
    records, oof = fit_all_models(feature_frame)
    report = assess_modeling_gate(records, oof)

    source_hashes = {
        "development_evaluations": sha256_file(development_path),
        "base_scenarios": sha256_file(scenarios_path),
        "population_summary": sha256_file(populations_path),
    }
    payload = {
        "protocol_id": "EV-FLEX-BIAS-V2.0",
        "artifact": "frozen_applicability_models",
        "training_role": "development",
        "source_hashes": source_hashes,
        "feature_contract": {
            "actual_nameplate_to_transformer_ratio": "formal EV population summary",
            "native_load_multiplier": "frozen base scenario",
            "phase_imbalance_index": "(max phase ratio - min phase ratio) / sum phase ratios",
            "far_zone_probability": "frozen base scenario",
            "median_natural_urgency": "formal EV population summary",
            "call_time_encoding": "sin and cos of 2*pi*hours/24",
            "dec_only_feature": "realized V2G participation",
            "dominant_phase_categories": ["a", "b", "c"],
            "dominant_phase_reference": "a",
        },
        "model_count": len(records),
        "models": records,
    }
    atomic_write_json(models_path, payload)
    oof_hash = write_csv_atomic(oof_path, oof.to_dict(orient="records"))
    report.update(
        {
            "development_evaluations": int(len(development)),
            "modeling_eligible_evaluations": int(len(feature_frame)),
            "excluded_scientific_terminal_evaluations": int(
                len(development) - len(feature_frame)
            ),
            "source_hashes": source_hashes,
            "models_path": str(models_path.relative_to(repo)).replace("\\", "/"),
            "models_sha256": sha256_file(models_path),
            "oof_path": str(oof_path.relative_to(repo)).replace("\\", "/"),
            "oof_sha256": oof_hash,
            "oof_float_read_policy": "pandas float_precision='round_trip' for exact threshold audits",
            "numeric_threads": 1,
        }
    )
    atomic_write_json(report_path, report)

    print(f"Gate status: {report['gate_status']}")
    print(f"Model records: {report['model_records']}/{report['expected_model_records']}")
    print(f"OOF predictions: {report['oof_predictions']}")
    print(
        "Cells with applicability region: "
        f"{report['cells_with_applicability_region']}/{report['model_records']}"
    )
    if report["cells_without_applicability_region"]:
        print(
            "No qualifying region: "
            + ", ".join(report["cells_without_applicability_region"])
        )
    print(f"Models SHA256: {report['models_sha256']}")
    print(f"OOF SHA256: {report['oof_sha256']}")
    if report["gate_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
