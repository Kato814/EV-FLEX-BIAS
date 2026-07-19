from __future__ import annotations

import argparse
import json
from pathlib import Path

from evflex.holdout import create_unlock_payload
from evflex.runner import atomic_write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    freeze_path = args.freeze if args.freeze.is_absolute() else repo / args.freeze
    output = args.output if args.output.is_absolute() else repo / args.output
    expected_freeze = repo / "reports" / "pre_holdout_freeze_v2_0.json"
    expected_output = repo / "state" / "holdout_unlock_v2_0.json"
    if freeze_path.resolve(strict=False) != expected_freeze.resolve(strict=False):
        raise SystemExit(f"freeze input must be {expected_freeze}")
    if output.resolve(strict=False) != expected_output.resolve(strict=False):
        raise SystemExit(f"unlock output must be {expected_output}")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    payload = create_unlock_payload(repo, freeze_path, freeze)
    atomic_write_json(output, payload)
    print(f"Status: {payload['status']}")
    print(f"Holdout open count: {payload['holdout_open_count']}")
    print(f"Source commit: {payload['source_commit']}")
    print(f"Audit commit: {payload['audit_commit']}")
    print(f"Freeze SHA256: {payload['freeze_report_sha256']}")


if __name__ == "__main__":
    main()
