from __future__ import annotations

import argparse
import json
from pathlib import Path

from evflex.pilot import evaluate_pilot_work_unit
from evflex.transferability_replication_v2_5b import load_replication_design, _records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--unit-id",
        default="v25b_replication_ieee13_1900_31__inc",
    )
    parser.add_argument(
        "--output",
        default="reports/v25b_diagnostic_ieee13_1900_31_inc.json",
    )
    args = parser.parse_args()

    root = Path(args.repo_root).resolve(strict=True)
    config, frame = load_replication_design(root)
    matches = [u for u in _records(frame) if u["work_unit_id"] == args.unit_id]
    if len(matches) != 1:
        raise SystemExit(f"unknown or non-unique V2.5B unit: {args.unit_id}")

    unit = matches[0]
    evaluations = evaluate_pilot_work_unit(root, unit, config=config)
    payload = {
        "diagnostic_role": "raw_shared_evaluator_output_before_v25b_wrapper_validation",
        "unit_id": args.unit_id,
        "scenario_id": unit["scenario_id"],
        "direction": unit["direction"],
        "evaluations": evaluations,
        "compact": [
            {
                key: row.get(key)
                for key in (
                    "evaluation_id",
                    "duration_min",
                    "status",
                    "scientific_status",
                    "baseline_status",
                    "active_offer",
                    "eligible_for_scientific_denominator",
                    "f_bal_kw",
                    "alpha_transfer",
                    "alpha_path_status",
                    "alpha_path_scientific_valid",
                    "status_detail",
                    "raw_schedule_failure_by_duration",
                )
            }
            for row in evaluations
        ],
    }
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("V25B_DIAGNOSTIC_COMPACT=" + json.dumps(payload["compact"], sort_keys=True, allow_nan=False))
    print(f"WROTE {output.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
