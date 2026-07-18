from __future__ import annotations

import argparse
import json
from pathlib import Path

from evflex.network import write_json_atomic
from evflex.regression import (
    render_regression_markdown,
    run_regression_gate,
    write_text_atomic,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    golden = args.golden if args.golden.is_absolute() else repo / args.golden
    output_json = args.output_json if args.output_json.is_absolute() else repo / args.output_json
    output_md = args.output_md if args.output_md.is_absolute() else repo / args.output_md
    report = run_regression_gate(repo, golden, args.repeats, args.workers)
    write_json_atomic(output_json, report)
    write_text_atomic(output_md, render_regression_markdown(report))
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "comparisons"},
            ensure_ascii=False,
            indent=2,
        )
    )
    if report["gate_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
