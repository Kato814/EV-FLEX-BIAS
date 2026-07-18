from __future__ import annotations

import json
from pathlib import Path

from evflex.network import run_network_smoke, validate_feeder_tree, write_json_atomic


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    dependencies = {
        "ieee13": validate_feeder_tree(
            repo / "data" / "feeders" / "ieee13", "IEEE13Nodeckt.dss"
        ),
        "lv906": validate_feeder_tree(
            repo / "data" / "feeders" / "lv906_core", "MasterStaticAudit.dss"
        ),
    }
    report = run_network_smoke(repo)
    report["dependencies"] = {
        feeder: [str(path.relative_to(repo)).replace("\\", "/") for path in paths]
        for feeder, paths in dependencies.items()
    }
    target = repo / "reports" / "network_smoke_v2_0.json"
    write_json_atomic(target, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["gate"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
