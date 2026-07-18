from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd


POPULATION_COLUMNS = (
    "scenario_id",
    "ev_id",
    "battery_kwh",
    "initial_energy_kwh",
    "target_energy_kwh",
    "reserve_energy_kwh",
    "arrival_slot",
    "departure_slot",
    "p_charge_kw",
    "p_discharge_kw",
    "eta_charge",
    "eta_discharge",
    "v2g_flag",
    "v2g_budget_kwh",
    "bus",
    "phase",
    "kv_ln",
)


@dataclass(frozen=True)
class FleetBundle:
    scenario: pd.Series
    population: pd.DataFrame
    fleet: list
    baseline: np.ndarray
    load_scales: np.ndarray


def load_fleet_bundle(
    repo_root: Path,
    scenario_id: str,
    archived_engine: ModuleType,
    legacy_core: ModuleType,
) -> FleetBundle:
    """Load one frozen scenario and construct its D5-compatible baseline."""
    repo = repo_root.resolve(strict=True)
    inherited = repo / "data" / "inherited"

    scenarios = pd.read_csv(inherited / "base_scenarios_v1_2.csv")
    selected = scenarios.loc[scenarios["scenario_id"] == scenario_id]
    if len(selected) != 1:
        raise ValueError(f"Expected exactly one frozen scenario {scenario_id}, found {len(selected)}")
    scenario = selected.iloc[0].copy()

    population = pd.read_csv(
        inherited / "formal_ev_populations_v1_2.csv",
        usecols=list(POPULATION_COLUMNS),
    )
    population = population.loc[population["scenario_id"] == scenario_id].copy()
    if population.empty:
        raise ValueError(f"No frozen EV population for {scenario_id}")
    if population["ev_id"].duplicated().any():
        raise ValueError(f"Duplicate EV IDs in frozen population for {scenario_id}")

    load_profile = pd.read_csv(inherited / "controlled_native_load_profile_v1_2.csv")
    fleet = archived_engine.build_fleet(population, legacy_core.EV)
    baseline = archived_engine.uniform_baseline(fleet)
    load_scales = archived_engine.scenario_load_scales(load_profile, scenario)
    return FleetBundle(
        scenario=scenario,
        population=population,
        fleet=fleet,
        baseline=baseline,
        load_scales=load_scales,
    )
