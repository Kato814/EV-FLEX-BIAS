from __future__ import annotations

import argparse
from pathlib import Path

from evflex.holdout import build_pre_holdout_freeze
from evflex.runner import atomic_write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else repo / args.output
    expected = repo / "reports" / "pre_holdout_freeze_v2_0.json"
    if output.resolve(strict=False) != expected.resolve(strict=False):
        raise SystemExit(f"freeze output must be {expected}")
    if output.exists():
        raise SystemExit("pre-holdout freeze report already exists")
    report = build_pre_holdout_freeze(repo, args.source_commit)
    atomic_write_json(output, report)
    print(f"Gate status: {report['gate_status']}")
    print(f"Source commit: {report['source_commit']}")
    print(f"Tracked files hashed: {report['tracked_files_hashed']}")
    print(
        "Raw work units verified: "
        + str(
            sum(
                item["verified_raw_files"]
                for item in report["raw_work_unit_hash_manifests"]
            )
        )
    )
    print(f"Holdout opened: {report['holdout_opened']}")


if __name__ == "__main__":
    main()
