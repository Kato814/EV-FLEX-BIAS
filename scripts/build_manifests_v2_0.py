from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from evflex.manifests import (
    build_ablation_manifest,
    normalize_core_manifest,
    write_csv_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inherited-core", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    inherited = pd.read_csv(args.inherited_core)
    evaluations, work_units = normalize_core_manifest(inherited)
    ablations = build_ablation_manifest()
    output_dir = args.output_dir.resolve()
    write_csv_atomic(evaluations, output_dir / "core_evaluations_v2_0.csv")
    write_csv_atomic(work_units, output_dir / "core_work_units_v2_0.csv")
    write_csv_atomic(ablations, output_dir / "compact_ablation_v2_0.csv")
    summary = {
        "protocol_id": "EV-FLEX-BIAS-V2.0",
        "core_evaluations": len(evaluations),
        "core_work_units": len(work_units),
        "development_evaluations": int((evaluations.data_role == "development").sum()),
        "holdout_evaluations": int((evaluations.data_role == "holdout").sum()),
        "compact_ablations": len(ablations),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
