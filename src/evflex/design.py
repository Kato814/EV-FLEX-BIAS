"""Load the final 46-case INC/V1G experiment and its physical constraints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_design(repo_root: str | Path) -> tuple[dict[str, Any], pd.DataFrame]:
    root = Path(repo_root).resolve(strict=True)
    config = json.loads((root / "config/experiment.json").read_text(encoding="utf-8"))
    expected = {
        "formal_constraints": {
            "vmin_pu": 0.95,
            "vmax_pu": 1.06,
            "vuf_limit_pct": 2.0,
            "transformer_loading_limit_pu": 1.0,
            "feeder_loading_limit_pu": 1.0,
            "line_thermal_in_scope": False,
        },
        "alpha_search": {"coarse_step": 0.02, "refine_tolerance": 0.002},
        "feeder_kva": {"ieee13": 5000, "lv906": 800},
    }
    if config != expected:
        raise ValueError("Experiment settings differ from the final physical/search contract")

    units = pd.read_csv(root / "config/cases.csv")
    required = {"work_unit_id", "scenario_id", "feeder", "call_time", "direction", "scenario_seed"}
    if set(units.columns) != required or len(units) != 46:
        raise ValueError("Expected the six-column final 46-case work-unit manifest")
    if units["scenario_id"].duplicated().any() or units["work_unit_id"].duplicated().any():
        raise ValueError("Final case identities must be unique")
    if set(units["direction"]) != {"inc"}:
        raise ValueError("The final experiment contains increasing-direction V1G cases only")
    if units["feeder"].value_counts().to_dict() != {"lv906": 24, "ieee13": 22}:
        raise ValueError("Final feeder case counts must be IEEE13=22 and LV906=24")
    if set(units["call_time"]) != {"19:00", "00:00", "02:00", "06:00"}:
        raise ValueError("Unexpected flexibility call time")

    scenarios = pd.read_csv(root / "data/scenarios.csv")
    if len(scenarios) != 46 or scenarios["scenario_id"].duplicated().any():
        raise ValueError("Expected exactly 46 unique frozen scenarios")
    if set(scenarios["scenario_id"]) != set(units["scenario_id"]):
        raise ValueError("Final manifest and scenario identities differ")
    by_id = scenarios.set_index("scenario_id")
    for row in units.itertuples(index=False):
        if row.work_unit_id != f"v25b_replication_{row.scenario_id}__inc":
            raise ValueError(f"Frozen work-unit identity differs for {row.scenario_id}")
        source = by_id.loc[row.scenario_id]
        if (str(row.feeder) != str(source["feeder"])
                or str(row.call_time) != str(source["call_time"])
                or int(row.scenario_seed) != int(source["scenario_seed"])):
            raise ValueError(f"Frozen scenario parameters differ for {row.scenario_id}")
    return config, units
