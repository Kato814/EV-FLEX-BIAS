from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from evflex.aggregate import (
    assess_evaluations,
    load_work_unit_evaluations,
    render_gate_markdown,
    sort_and_normalize_rows,
    write_csv_atomic,
)
from evflex.regression import write_text_atomic
from evflex.runner import atomic_write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-evaluations", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    input_directory = args.input if args.input.is_absolute() else repo / args.input
    rows, input_errors = load_work_unit_evaluations(input_directory)
    manifest = pd.read_csv(repo / "manifests" / "core_evaluations_v2_0.csv")
    order = {evaluation_id: index for index, evaluation_id in enumerate(manifest["evaluation_id"])}
    rows = sort_and_normalize_rows(rows, order)
    report = assess_evaluations(
        rows, args.expected_evaluations, input_errors=input_errors
    )
    if args.output is not None:
        output = args.output if args.output.is_absolute() else repo / args.output
        report["output_path"] = str(output.relative_to(repo)).replace("\\", "/")
        report["output_sha256"] = write_csv_atomic(output, rows)
    else:
        report["output_path"] = None
        report["output_sha256"] = None

    report_path = args.report if args.report.is_absolute() else repo / args.report
    atomic_write_json(report_path, report)
    if args.report_md is not None:
        markdown_path = args.report_md if args.report_md.is_absolute() else repo / args.report_md
        write_text_atomic(markdown_path, render_gate_markdown(report))
    print(render_gate_markdown(report))
    if report["gate_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
