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
import json
from pathlib import Path
from typing import Any

import pandas as pd

from evflex.ablation import (
    analyze_ablation_contrasts,
    assess_ablation_gate,
    merge_manifest_fields,
    render_ablation_markdown,
    validate_ablation_manifest,
)
from evflex.aggregate import write_csv_atomic
from evflex.provenance import sha256_file
from evflex.regression import write_text_atomic
from evflex.runner import WORK_TERMINAL_STATUSES, atomic_write_json


def resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def load_results(
    repo: Path, work_units: Path, manifest: pd.DataFrame
) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    by_id = manifest.set_index("ablation_id", drop=False)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    hashes: list[dict[str, Any]] = []
    for path in sorted(work_units.glob("*.json"), key=lambda item: item.name):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            unit_id = str(payload["work_unit_id"])
            if unit_id not in by_id.index:
                raise ValueError(f"result ID is absent from manifest: {unit_id}")
            if path.stem != unit_id:
                raise ValueError(f"filename/ID mismatch: {path.name} vs {unit_id}")
            if str(payload["status"]) not in WORK_TERMINAL_STATUSES:
                raise ValueError(f"nonterminal wrapper status: {payload['status']}")
            evaluations = payload.get("evaluations")
            if not isinstance(evaluations, list) or len(evaluations) != 1:
                raise ValueError("ablation wrapper must contain exactly one evaluation")
            evaluation = dict(evaluations[0])
            if str(evaluation.get("evaluation_id")) != unit_id:
                raise ValueError("evaluation ID differs from wrapper ID")
            source = by_id.loc[unit_id]
            if int(payload["scenario_seed"]) != int(source["seed"]):
                raise ValueError("wrapper seed differs from manifest")
            row = merge_manifest_fields(evaluation, source)
            row["ablation_id"] = unit_id
            row["evaluation_id"] = unit_id
            row["scenario_seed"] = int(payload["scenario_seed"])
            row["work_unit_status"] = str(payload["status"])
            row["attempt_count"] = int(payload["attempt_count"])
            row["source_result_file"] = path.name
            row["scientific_status"] = payload.get("scientific_status")
            row["terminal_message"] = payload.get("message")
            rows.append(row)
            hashes.append(
                {
                    "relative_path": str(path.relative_to(repo)).replace("\\", "/"),
                    "bytes": path.stat().st_size,
                    "last_write_utc": pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat(),
                    "sha256": sha256_file(path),
                    "ablation_id": unit_id,
                    "work_unit_status": str(payload["status"]),
                    "attempt_count": int(payload["attempt_count"]),
                }
            )
        except Exception as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
    frame = pd.DataFrame(rows)
    if not frame.empty:
        order = {
            ablation_id: index
            for index, ablation_id in enumerate(manifest["ablation_id"].astype(str))
        }
        frame["_manifest_order"] = frame["ablation_id"].map(order)
        frame = frame.sort_values("_manifest_order").drop(columns="_manifest_order")
    return frame, errors, pd.DataFrame(hashes)


def normalize_for_csv(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            key: (
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if isinstance(value, (dict, list))
                else value
            )
            for key, value in row.items()
        }
        for row in frame.to_dict(orient="records")
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--work-units", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-md", type=Path, required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    manifest_path = resolve(repo, args.manifest)
    work_units_path = resolve(repo, args.work_units)
    output_dir = resolve(repo, args.output_dir)
    report_path = resolve(repo, args.report)
    report_md_path = resolve(repo, args.report_md)
    manifest = pd.read_csv(manifest_path)
    validate_ablation_manifest(manifest)
    results, input_errors, raw_hashes = load_results(repo, work_units_path, manifest)

    if results.empty:
        contrasts = pd.DataFrame()
        report = {
            "gate": "G4_ABLATION_FREEZE",
            "gate_status": "FAIL",
            "expected_evaluations": 336,
            "actual_evaluations": 0,
            "unique_evaluation_ids": 0,
            "terminal_non_success_ids": [],
            "contrast_rows": 0,
            "bootstrap_seed": 2026072001,
            "bootstrap_resamples": 10000,
            "violations": {"input_errors": input_errors or ["no terminal results"]},
        }
    else:
        contrasts = analyze_ablation_contrasts(results)
        report = assess_ablation_gate(manifest, results, contrasts, input_errors)

    results_path = output_dir / "compact_ablation_results_v2_0.csv"
    contrasts_path = output_dir / "ablation_contrasts_v2_0.csv"
    raw_hash_path = report_path.with_name("ablation_work_unit_hashes_v2_0.csv")
    results_hash = write_csv_atomic(results_path, normalize_for_csv(results))
    contrasts_hash = write_csv_atomic(contrasts_path, normalize_for_csv(contrasts))
    raw_hash_manifest_hash = write_csv_atomic(
        raw_hash_path, normalize_for_csv(raw_hashes)
    )
    report.update(
        {
            "manifest_path": str(manifest_path.relative_to(repo)).replace("\\", "/"),
            "manifest_sha256": sha256_file(manifest_path),
            "results_path": str(results_path.relative_to(repo)).replace("\\", "/"),
            "results_sha256": results_hash,
            "contrasts_path": str(contrasts_path.relative_to(repo)).replace("\\", "/"),
            "contrasts_sha256": contrasts_hash,
            "raw_work_unit_hash_manifest": str(raw_hash_path.relative_to(repo)).replace("\\", "/"),
            "raw_work_unit_hash_manifest_sha256": raw_hash_manifest_hash,
            "raw_work_unit_files": int(len(raw_hashes)),
            "numeric_threads": 1,
            "formal_workers": 1,
        }
    )
    atomic_write_json(report_path, report)
    write_text_atomic(report_md_path, render_ablation_markdown(report, contrasts))
    print(f"Gate status: {report['gate_status']}")
    print(
        f"Terminal evaluations: {report['actual_evaluations']}/{report['expected_evaluations']}"
    )
    print(f"Unique IDs: {report['unique_evaluation_ids']}")
    print(f"Contrast rows: {report['contrast_rows']}/112")
    print(f"Terminal non-success: {len(report['terminal_non_success_ids'])}")
    print(f"Results SHA256: {results_hash}")
    print(f"Contrasts SHA256: {contrasts_hash}")
    if report["gate_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
