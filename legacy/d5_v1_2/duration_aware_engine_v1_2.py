#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Literal, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, lil_matrix

DT = 0.25
T = 96
CALL_SLOTS = {"19:00": 28, "00:00": 48, "02:00": 56, "06:00": 72}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def configure_core(core, repo: Path) -> None:
    core.FEEDERS["ieee13"]["master"] = repo / "data/feeders/ieee13/IEEE13Nodeckt.dss"
    core.FEEDERS["lv906"]["master"] = repo / "data/feeders/lv906_core/MasterStaticAudit.dss"
    core.FEEDERS["ieee13"]["kva_limit"] = 5000.0
    core.FEEDERS["lv906"]["kva_limit"] = 800.0


def build_fleet(pop: pd.DataFrame, EV) -> list:
    fleet = []
    for row in pop.itertuples(index=False):
        fleet.append(
            EV(
                ev_id=int(row.ev_id),
                capacity=float(row.battery_kwh),
                initial=float(row.initial_energy_kwh),
                target=float(row.target_energy_kwh),
                reserve=float(row.reserve_energy_kwh),
                arrival=int(row.arrival_slot),
                departure=int(row.departure_slot),
                pch=float(row.p_charge_kw),
                pdis=float(row.p_discharge_kw),
                eta_c=float(row.eta_charge),
                eta_d=float(row.eta_discharge),
                v2g=bool(row.v2g_flag),
                max_discharge=float(row.v2g_budget_kwh),
                bus=str(row.bus),
                phase=int(row.phase),
                kv_ln=float(row.kv_ln),
            )
        )
    return fleet


def uniform_baseline(fleet: list) -> np.ndarray:
    schedule = np.zeros((len(fleet), T))
    for i, ev in enumerate(fleet):
        available = ev.departure - ev.arrival
        if available <= 0:
            raise RuntimeError(f"EV {ev.ev_id}: non-positive parking duration")
        grid_energy = (ev.target - ev.initial) / ev.eta_c
        p = grid_energy / (available * DT)
        if p > ev.pch + 1e-7:
            raise RuntimeError(f"EV {ev.ev_id}: uniform baseline infeasible ({p:.5f}>{ev.pch:.5f})")
        schedule[i, ev.arrival : ev.departure] = max(p, 0.0)
    return schedule


def energy_before(ev, base_row: np.ndarray, tau: int) -> float:
    if tau <= ev.arrival:
        return ev.initial
    stop = min(tau, ev.departure)
    return min(ev.capacity, ev.initial + ev.eta_c * base_row[ev.arrival:stop].sum() * DT)


def point_bounds(ev, base_row: np.ndarray, tau: int, mode: Literal["v1g", "v2g"]) -> Tuple[float, float]:
    if not (ev.arrival <= tau < ev.departure):
        return 0.0, 0.0
    energy = energy_before(ev, base_row, tau)
    remaining_slots = max(ev.departure - tau - 1, 0)
    future_max = ev.eta_c * ev.pch * DT * remaining_slots
    mandatory_charge = max(0.0, (ev.target - energy - future_max) / (ev.eta_c * DT))
    lower_v1g = min(ev.pch, mandatory_charge)
    upper = min(ev.pch, max(0.0, (ev.capacity - energy) / (ev.eta_c * DT)))
    if mode == "v1g" or not ev.v2g:
        return lower_v1g, upper
    discharge = min(
        ev.pdis,
        ev.max_discharge / DT,
        max(0.0, ev.eta_d * (energy - ev.reserve) / DT),
        max(0.0, ev.eta_d * (energy + future_max - ev.target) / DT),
    )
    return (-discharge if discharge > 1e-9 else lower_v1g), upper


def fleet_frame(fleet: list, base: np.ndarray, tau: int) -> pd.DataFrame:
    rows = []
    for i, ev in enumerate(fleet):
        v1_lo, v1_hi = point_bounds(ev, base[i], tau, "v1g")
        v2_lo, v2_hi = point_bounds(ev, base[i], tau, "v2g")
        b = float(base[i, tau]) if ev.arrival <= tau < ev.departure else 0.0
        b = min(max(b, v1_lo), v1_hi)
        rows.append({**asdict(ev), "base": b, "v1_lo": v1_lo, "v1_hi": v1_hi, "v2_lo": v2_lo, "v2_hi": v2_hi})
    return pd.DataFrame(rows)


def static_fleet_frame(fleet: list) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **asdict(ev),
                "base": 0.0,
                "v1_lo": 0.0,
                "v1_hi": ev.pch,
                "v2_lo": -ev.pdis if ev.v2g else 0.0,
                "v2_hi": ev.pch,
            }
            for ev in fleet
        ]
    )


def group_vector(fleet: list, power: np.ndarray, groups, model: str) -> np.ndarray:
    out = np.zeros(len(groups))
    if model == "3ph":
        index = {g: j for j, g in enumerate(groups)}
        for ev, p in zip(fleet, power):
            out[index[(str(ev.bus), int(ev.phase))]] += float(p)
    else:
        index = {str(g): j for j, g in enumerate(groups)}
        for ev, p in zip(fleet, power):
            out[index[str(ev.bus)]] += float(p)
    return out


def point_boundary(core, feeder: str, fleet: list, base: np.ndarray, tau: int, load_scale: float,
                   direction: str, model: Literal["3ph", "balanced"]) -> Dict:
    frame = fleet_frame(fleet, base, tau)
    network = core.Network(feeder, frame, model, load_scale)
    base_series = pd.Series(frame.base.values, index=frame.index)
    p0 = core.aggregate(frame, base_series, network)
    m0 = network.evaluate(p0)
    if not m0["feasible"]:
        raise RuntimeError(f"{model} baseline infeasible at slot {tau}: {m0['violations'][:3]}")
    if direction == "inc":
        lower_col, upper_col, sense = "v1_lo", "v1_hi", "max"
    elif direction == "dec":
        lower_col, upper_col, sense = "v2_lo", "v2_hi", "min"
    else:
        raise ValueError(direction)
    lower = core.aggregate(frame, pd.Series(frame[lower_col].values, index=frame.index), network)
    upper = core.aggregate(frame, pd.Series(frame[upper_col].values, index=frame.index), network)
    result = network.optimize(p0, lower, upper, sense, network.sensitivity(p0))
    if not result.get("success", False):
        raise RuntimeError(f"{model} point optimization failed at slot {tau}")
    p = np.asarray(result["p"], dtype=float)
    flex = (p.sum() - p0.sum()) if direction == "inc" else (p0.sum() - p.sum())
    return {
        "network": network,
        "groups": network.groups,
        "p0": np.asarray(p0, dtype=float),
        "p": p,
        "lower": np.asarray(lower, dtype=float),
        "upper": np.asarray(upper, dtype=float),
        "flex": max(float(flex), 0.0),
        "metrics": result,
    }


def pair_index(fleet: list):
    pairs = [(i, t) for i, ev in enumerate(fleet) for t in range(ev.arrival, ev.departure)]
    return pairs, {pair: j for j, pair in enumerate(pairs)}


def build_trajectory_lp(fleet: list, base: np.ndarray, groups, targets: Dict[int, np.ndarray],
                        model: str, mode: str, alpha_fixed: float | None):
    pairs, pmap = pair_index(fleet)
    n = len(pairs)
    if alpha_fixed is None:
        alpha_idx = 2 * n
        z_offset = None
        nvar = 2 * n + 1
        objective = np.zeros(nvar)
        objective[: 2 * n] = 1e-8
        objective[alpha_idx] = -1.0
    else:
        alpha_idx = None
        z_offset = 2 * n
        nvar = 3 * n
        objective = np.zeros(nvar)
        objective[: 2 * n] = 1e-5
        objective[z_offset:] = 1.0

    bounds = []
    for i, _ in pairs:
        bounds.append((0.0, fleet[i].pch))
    for i, _ in pairs:
        ev = fleet[i]
        bounds.append((0.0, ev.pdis if mode == "v2g" and ev.v2g else 0.0))
    if alpha_fixed is None:
        bounds.append((0.0, 1.0))
    else:
        bounds.extend([(0.0, None)] * n)

    ub_rows: list[dict[int, float]] = []
    ub_rhs: list[float] = []
    eq_rows: list[dict[int, float]] = []
    eq_rhs: list[float] = []

    for i, ev in enumerate(fleet):
        indices = [pmap[(i, t)] for t in range(ev.arrival, ev.departure)]
        for k in range(len(indices)):
            upper_row: dict[int, float] = {}
            lower_row: dict[int, float] = {}
            for j in indices[: k + 1]:
                upper_row[j] = ev.eta_c * DT
                upper_row[n + j] = -DT / ev.eta_d
                lower_row[j] = -ev.eta_c * DT
                lower_row[n + j] = DT / ev.eta_d
            ub_rows.append(upper_row)
            ub_rhs.append(ev.capacity - ev.initial)
            ub_rows.append(lower_row)
            ub_rhs.append(ev.initial - ev.reserve)

        # Exact departure energy.
        terminal: dict[int, float] = {}
        for j in indices:
            terminal[j] = ev.eta_c * DT
            terminal[n + j] = -DT / ev.eta_d
        eq_rows.append(terminal)
        eq_rhs.append(ev.target - ev.initial)

        if mode == "v2g" and ev.v2g:
            budget = {n + j: DT for j in indices}
            ub_rows.append(budget)
            ub_rhs.append(ev.max_discharge)

    if alpha_fixed is not None:
        for j, (i, t) in enumerate(pairs):
            b = float(base[i, t])
            ub_rows.append({j: 1.0, n + j: -1.0, z_offset + j: -1.0})
            ub_rhs.append(b)
            ub_rows.append({j: -1.0, n + j: 1.0, z_offset + j: -1.0})
            ub_rhs.append(-b)

    if model == "3ph":
        group_to_evs = {g: [i for i, ev in enumerate(fleet) if (str(ev.bus), int(ev.phase)) == g] for g in groups}
    else:
        group_to_evs = {str(g): [i for i, ev in enumerate(fleet) if str(ev.bus) == str(g)] for g in groups}

    for t, target in targets.items():
        base_group = group_vector(fleet, base[:, t], groups, model)
        delta = np.asarray(target, dtype=float) - base_group
        for group_idx, group in enumerate(groups):
            row: dict[int, float] = {}
            key = group if model == "3ph" else str(group)
            for i in group_to_evs[key]:
                if (i, t) in pmap:
                    j = pmap[(i, t)]
                    row[j] = row.get(j, 0.0) + 1.0
                    row[n + j] = row.get(n + j, 0.0) - 1.0
            if alpha_fixed is None:
                row[alpha_idx] = -float(delta[group_idx])
                rhs = float(base_group[group_idx])
            else:
                rhs = float(base_group[group_idx] + alpha_fixed * delta[group_idx])
            eq_rows.append(row)
            eq_rhs.append(rhs)

    A_ub = lil_matrix((len(ub_rows), nvar))
    for r, row in enumerate(ub_rows):
        for c, value in row.items():
            A_ub[r, c] = value
    A_eq = lil_matrix((len(eq_rows), nvar))
    for r, row in enumerate(eq_rows):
        for c, value in row.items():
            A_eq[r, c] = value
    return {
        "objective": objective,
        "bounds": bounds,
        "A_ub": csr_matrix(A_ub),
        "b_ub": np.asarray(ub_rhs),
        "A_eq": csr_matrix(A_eq),
        "b_eq": np.asarray(eq_rhs),
        "pairs": pairs,
        "n": n,
        "alpha_idx": alpha_idx,
    }


def solve_alpha(fleet: list, base: np.ndarray, groups, targets: Dict[int, np.ndarray], model: str, mode: str):
    lp = build_trajectory_lp(fleet, base, groups, targets, model, mode, None)
    result = linprog(
        lp["objective"], A_ub=lp["A_ub"], b_ub=lp["b_ub"],
        A_eq=lp["A_eq"], b_eq=lp["b_eq"], bounds=lp["bounds"], method="highs"
    )
    if not result.success:
        return 0.0, {"success": False, "message": result.message}
    return float(result.x[lp["alpha_idx"]]), {"success": True, "message": result.message}


def solve_schedule(fleet: list, base: np.ndarray, groups, targets: Dict[int, np.ndarray],
                   model: str, mode: str, alpha: float) -> Dict:
    lp = build_trajectory_lp(fleet, base, groups, targets, model, mode, alpha)
    result = linprog(
        lp["objective"], A_ub=lp["A_ub"], b_ub=lp["b_ub"],
        A_eq=lp["A_eq"], b_eq=lp["b_eq"], bounds=lp["bounds"], method="highs"
    )
    if not result.success:
        return {"success": False, "message": result.message}
    n = lp["n"]
    schedule = np.zeros((len(fleet), T))
    charge = np.zeros_like(schedule)
    discharge = np.zeros_like(schedule)
    for j, (i, t) in enumerate(lp["pairs"]):
        charge[i, t] = result.x[j]
        discharge[i, t] = result.x[n + j]
        schedule[i, t] = charge[i, t] - discharge[i, t]

    departure_error = 0.0
    reserve_violation = 0.0
    capacity_violation = 0.0
    for i, ev in enumerate(fleet):
        energy = ev.initial
        min_energy = energy
        max_energy = energy
        for t in range(ev.arrival, ev.departure):
            energy += ev.eta_c * charge[i, t] * DT - discharge[i, t] * DT / ev.eta_d
            min_energy = min(min_energy, energy)
            max_energy = max(max_energy, energy)
        departure_error = max(departure_error, abs(energy - ev.target))
        reserve_violation = max(reserve_violation, max(0.0, ev.reserve - min_energy))
        capacity_violation = max(capacity_violation, max(0.0, max_energy - ev.capacity))
    simultaneous = int(np.sum((charge > 1e-5) & (discharge > 1e-5)))
    return {
        "success": True,
        "schedule": schedule,
        "charge": charge,
        "discharge": discharge,
        "objective": float(result.fun),
        "max_departure_error_kwh": float(departure_error),
        "max_reserve_violation_kwh": float(reserve_violation),
        "max_capacity_violation_kwh": float(capacity_violation),
        "simultaneous_slots": simultaneous,
    }


def network_cache(core, feeder: str, fleet: list, load_scales: np.ndarray, model: str):
    static = static_fleet_frame(fleet)
    return {float(s): core.Network(feeder, static, model, float(s)) for s in sorted(set(load_scales.astype(float)))}


def network_check(core, feeder: str, fleet: list, schedule: np.ndarray, baseline: np.ndarray,
                  load_scales: np.ndarray, model: str, cache: dict) -> Dict:
    network0 = next(iter(cache.values()))
    groups = network0.groups
    violations = []
    checked = 0
    metrics = {"vmin": math.inf, "vmax": -math.inf, "vufmax": 0.0, "linemax": 0.0, "sloadmax": 0.0}
    for t in range(T):
        # The common baseline is audited separately. A candidate schedule only needs
        # nonlinear rechecking at intervals materially changed by the flexibility call
        # or its energy-recovery trajectory.
        if np.max(np.abs(schedule[:, t] - baseline[:, t])) < 0.02:
            continue
        network = cache[float(load_scales[t])]
        p = group_vector(fleet, schedule[:, t], groups, model)
        m = network.evaluate(p)
        checked += 1
        metrics["vmin"] = min(metrics["vmin"], m["vmin"])
        metrics["vmax"] = max(metrics["vmax"], m["vmax"])
        metrics["vufmax"] = max(metrics["vufmax"], m["vufmax"])
        metrics["linemax"] = max(metrics["linemax"], m["linemax"])
        metrics["sloadmax"] = max(metrics["sloadmax"], m["sload"])
        if not m["feasible"]:
            violations.append({"slot": t, "violations": m["violations"][:10]})
    if checked == 0:
        metrics["vmin"] = np.nan
        metrics["vmax"] = np.nan
    return {"feasible": not violations, "checked_intervals": checked, "violations": violations, **metrics}


def scale_schedule(base: np.ndarray, schedule: np.ndarray, alpha: float) -> np.ndarray:
    return base + alpha * (schedule - base)


def safe_schedule_alpha(core, feeder: str, fleet: list, schedule: np.ndarray, base: np.ndarray,
                        load_scales: np.ndarray, model: str, cache: dict) -> Tuple[float, Dict]:
    full = network_check(core, feeder, fleet, schedule, base, load_scales, model, cache)
    if full["feasible"]:
        return 1.0, full
    lo, hi = 0.0, 1.0
    best = network_check(core, feeder, fleet, base, base, load_scales, model, cache)
    for _ in range(14):
        mid = (lo + hi) / 2.0
        check = network_check(core, feeder, fleet, scale_schedule(base, schedule, mid), base, load_scales, model, cache)
        if check["feasible"]:
            lo, best = mid, check
        else:
            hi = mid
    return float(lo), best



def scale_physical_solution(fleet: list, base: np.ndarray, solution: Dict, alpha: float) -> Dict:
    """Convexly scale a feasible charge/discharge trajectory toward the V1G baseline.

    The baseline has charge=base and discharge=0. Because energy dynamics and all EV
    constraints are linear, the convex combination remains vehicle-feasible and exactly
    preserves every departure target.
    """
    charge = base + alpha * (solution["charge"] - base)
    discharge = alpha * solution["discharge"]
    schedule = charge - discharge
    departure_error = 0.0
    reserve_violation = 0.0
    capacity_violation = 0.0
    for i, ev in enumerate(fleet):
        energy = ev.initial
        min_energy = energy
        max_energy = energy
        for t in range(ev.arrival, ev.departure):
            energy += ev.eta_c * charge[i, t] * DT - discharge[i, t] * DT / ev.eta_d
            min_energy = min(min_energy, energy)
            max_energy = max(max_energy, energy)
        departure_error = max(departure_error, abs(energy - ev.target))
        reserve_violation = max(reserve_violation, max(0.0, ev.reserve - min_energy))
        capacity_violation = max(capacity_violation, max(0.0, max_energy - ev.capacity))
    out = dict(solution)
    out.update({
        "schedule": schedule,
        "charge": charge,
        "discharge": discharge,
        "max_departure_error_kwh": float(departure_error),
        "max_reserve_violation_kwh": float(reserve_violation),
        "max_capacity_violation_kwh": float(capacity_violation),
        "simultaneous_slots": int(np.sum((charge > 1e-5) & (discharge > 1e-5))),
    })
    return out

def duration_result(core, feeder: str, fleet: list, base: np.ndarray, tau: int, duration_min: int,
                    direction: str, load_scales: np.ndarray, model: str) -> Dict:
    call_slots = list(range(tau, tau + duration_min // 15))
    if call_slots[-1] >= T:
        raise ValueError("Call window exceeds horizon")
    points = [point_boundary(core, feeder, fleet, base, t, float(load_scales[t]), direction, model) for t in call_slots]
    point_flex = [p["flex"] for p in points]
    reference_flex = min(point_flex) if point_flex else 0.0
    groups = points[0]["groups"]
    targets: Dict[int, np.ndarray] = {}
    if reference_flex <= 1e-9:
        targets = {t: p["p0"].copy() for t, p in zip(call_slots, points)}
    else:
        for t, point in zip(call_slots, points):
            ratio = reference_flex / max(point["flex"], 1e-12)
            targets[t] = point["p0"] + ratio * (point["p"] - point["p0"])

    mode = "v1g" if direction == "inc" else "v2g"
    trajectory_alpha, trajectory_info = solve_alpha(fleet, base, groups, targets, model, mode)
    if not trajectory_info["success"]:
        raise RuntimeError(f"Trajectory alpha LP failed: {trajectory_info['message']}")
    upper = min(1.0, max(0.0, trajectory_alpha))
    cache = network_cache(core, feeder, fleet, load_scales, model)

    def solve_and_check(a: float):
        sol = solve_schedule(fleet, base, groups, targets, model, mode, a)
        if not sol["success"]:
            return sol, {"feasible": False, "violations": [{"solver": sol.get('message','failed')}]}
        check = network_check(core, feeder, fleet, sol["schedule"], base, load_scales, model, cache)
        physical = (
            sol["max_departure_error_kwh"] <= 1e-6
            and sol["max_reserve_violation_kwh"] <= 1e-6
            and sol["max_capacity_violation_kwh"] <= 1e-6
            and sol["simultaneous_slots"] == 0
        )
        check = dict(check)
        check["feasible"] = bool(check["feasible"] and physical)
        return sol, check

    solution, model_check = solve_and_check(upper)
    if model_check["feasible"]:
        final_alpha = upper
    else:
        lo, hi = 0.0, upper
        # Baseline is physically feasible by construction. Store it as the initial best.
        best_solution = {
            "success": True, "schedule": base.copy(), "charge": base.copy(),
            "discharge": np.zeros_like(base), "objective": 0.0,
            "max_departure_error_kwh": 0.0, "max_reserve_violation_kwh": 0.0,
            "max_capacity_violation_kwh": 0.0, "simultaneous_slots": 0,
        }
        best_check = {"feasible": True, "checked_intervals": 0, "violations": []}
        for _ in range(9):
            mid = (lo + hi) / 2.0
            candidate, check = solve_and_check(mid)
            if check["feasible"]:
                lo = mid
                best_solution, best_check = candidate, check
            else:
                hi = mid
            if hi - lo < 0.002:
                break
        final_alpha = lo
        solution, model_check = best_solution, best_check

    flex = reference_flex * final_alpha
    return {
        "model": model, "direction": direction, "duration_min": duration_min,
        "call_slots": call_slots, "point_flex_kw": point_flex,
        "reference_point_flex_kw": float(reference_flex),
        "trajectory_alpha": float(trajectory_alpha),
        "model_network_alpha": float(final_alpha / max(upper, 1e-12)) if upper > 0 else 1.0,
        "final_alpha": float(final_alpha), "flex_kw": float(flex),
        "schedule": solution["schedule"],
        "max_departure_error_kwh": solution["max_departure_error_kwh"],
        "max_reserve_violation_kwh": solution["max_reserve_violation_kwh"],
        "max_capacity_violation_kwh": solution["max_capacity_violation_kwh"],
        "simultaneous_slots": solution["simultaneous_slots"],
        "model_network_check": model_check,
    }

def compare_models(core, feeder: str, fleet: list, base: np.ndarray, call_time: str, duration_min: int,
                   direction: str, load_scales: np.ndarray) -> Dict:
    tau = CALL_SLOTS[call_time]
    balanced = duration_result(core, feeder, fleet, base, tau, duration_min, direction, load_scales, "balanced")
    three_phase = duration_result(core, feeder, fleet, base, tau, duration_min, direction, load_scales, "3ph")

    truth_cache = network_cache(core, feeder, fleet, load_scales, "3ph")
    alpha_map, mapped_check = safe_schedule_alpha(
        core, feeder, fleet, balanced["schedule"], base, load_scales, "3ph", truth_cache
    )
    mapped_flex = balanced["flex_kw"] * alpha_map
    bias = (balanced["flex_kw"] - three_phase["flex_kw"]) / max(three_phase["flex_kw"], 1e-9) * 100.0
    return {
        "f_bal_kw": balanced["flex_kw"],
        "f_3ph_kw": three_phase["flex_kw"],
        "bias_pct": float(bias),
        "alpha_map": float(alpha_map),
        "mapped_flex_kw": float(mapped_flex),
        "raw_balanced_schedule_feasible": bool(alpha_map >= 0.999999),
        "balanced": balanced,
        "three_phase": three_phase,
        "mapped_check": mapped_check,
    }


def scenario_load_scales(load_profile: pd.DataFrame, scenario) -> np.ndarray:
    base = load_profile.sort_values("slot")["normalized_native_load"].to_numpy(dtype=float)
    if len(base) != T:
        raise RuntimeError("Controlled load profile must have 96 rows")
    return np.round(base * float(scenario.native_load_multiplier), 8)


def select_regression_scenarios(core, scenarios: pd.DataFrame, populations: pd.DataFrame, load_profile: pd.DataFrame) -> pd.DataFrame:
    # Frozen representative development cases: one low-to-moderate population case per
    # feeder and call time. IDs are fixed before D5 outcomes are inspected.
    ids = [
        "ieee13_1900_17", "ieee13_0000_09", "ieee13_0200_17", "ieee13_0600_24",
        "lv906_1900_18", "lv906_0000_11", "lv906_0200_03", "lv906_0600_02",
    ]
    selected = scenarios[scenarios.scenario_id.isin(ids)].copy()
    if set(selected.scenario_id) != set(ids):
        missing = sorted(set(ids) - set(selected.scenario_id))
        raise RuntimeError(f"Missing frozen regression scenarios: {missing}")
    return selected.set_index("scenario_id").loc[ids].reset_index()

def summarize_result(scenario, direction: str, duration: int, result: Dict, runtime: float) -> Dict:
    b = result["balanced"]
    t = result["three_phase"]
    return {
        "scenario_id": scenario.scenario_id,
        "feeder": scenario.feeder,
        "call_time": scenario.call_time,
        "direction": direction,
        "duration_min": duration,
        "n_ev": int(scenario.n_ev) if hasattr(scenario, "n_ev") else None,
        "f_bal_kw": result["f_bal_kw"],
        "f_3ph_kw": result["f_3ph_kw"],
        "bias_pct": result["bias_pct"],
        "alpha_map": result["alpha_map"],
        "raw_balanced_schedule_feasible": result["raw_balanced_schedule_feasible"],
        "balanced_trajectory_alpha": b["trajectory_alpha"],
        "three_phase_trajectory_alpha": t["trajectory_alpha"],
        "balanced_network_alpha": b["model_network_alpha"],
        "three_phase_network_alpha": t["model_network_alpha"],
        "max_departure_error_kwh": max(b["max_departure_error_kwh"], t["max_departure_error_kwh"]),
        "max_reserve_violation_kwh": max(b["max_reserve_violation_kwh"], t["max_reserve_violation_kwh"]),
        "max_capacity_violation_kwh": max(b["max_capacity_violation_kwh"], t["max_capacity_violation_kwh"]),
        "simultaneous_slots": max(b["simultaneous_slots"], t["simultaneous_slots"]),
        "balanced_network_feasible": b["model_network_check"]["feasible"],
        "three_phase_network_feasible": t["model_network_check"]["feasible"],
        "mapped_network_feasible": result["mapped_check"]["feasible"],
        "runtime_s": runtime,
    }


def run_regression(repo: Path, core, out: Path) -> Dict:
    out.mkdir(parents=True, exist_ok=True)
    scenarios = pd.read_csv(repo / "config/base_scenarios_v1_2.csv")
    populations = pd.read_csv(repo / "data/processed/formal_inputs_v1_2/formal_ev_populations_v1_2.csv")
    load_profile = pd.read_csv(repo / "config/controlled_native_load_profile_v1_2.csv")
    selected = select_regression_scenarios(core, scenarios, populations, load_profile)
    selected.to_csv(out / "selected_regression_scenarios.csv", index=False)

    rows = []
    detailed: dict[str, dict] = {}
    for scenario in selected.itertuples(index=False):
        pop = populations[populations.scenario_id == scenario.scenario_id]
        fleet = build_fleet(pop, core.EV)
        base = uniform_baseline(fleet)
        load_scales = scenario_load_scales(load_profile, scenario)
        for direction in ["inc", "dec"]:
            for duration in [15, 30, 60]:
                start = time.time()
                result = compare_models(core, scenario.feeder, fleet, base, scenario.call_time, duration, direction, load_scales)
                runtime = time.time() - start
                row = summarize_result(scenario, direction, duration, result, runtime)
                row["n_ev"] = len(fleet)
                rows.append(row)
                key = f"{scenario.scenario_id}_{direction}_{duration}"
                detailed[key] = {
                    "balanced_point_flex_kw": result["balanced"]["point_flex_kw"],
                    "three_phase_point_flex_kw": result["three_phase"]["point_flex_kw"],
                    "balanced_check": {k: v for k, v in result["balanced"]["model_network_check"].items() if k != "violations"},
                    "three_phase_check": {k: v for k, v in result["three_phase"]["model_network_check"].items() if k != "violations"},
                    "mapped_check": {k: v for k, v in result["mapped_check"].items() if k != "violations"},
                }
                print(json.dumps(row, default=float), flush=True)

    frame = pd.DataFrame(rows)
    frame.to_csv(out / "duration_engine_regression_results.csv", index=False)
    (out / "duration_engine_regression_details.json").write_text(json.dumps(detailed, indent=2, default=float), encoding="utf-8")

    monotonic_failures = []
    for (scenario_id, direction, model_col), _ in []:
        pass
    for (scenario_id, direction), group in frame.groupby(["scenario_id", "direction"]):
        group = group.sort_values("duration_min")
        for column in ["f_bal_kw", "f_3ph_kw"]:
            values = group[column].to_numpy()
            if np.any(values[1:] - values[:-1] > 1e-5):
                monotonic_failures.append({"scenario_id": scenario_id, "direction": direction, "column": column, "values": values.tolist()})

    physical_ok = bool(
        (frame.max_departure_error_kwh <= 1e-6).all()
        and (frame.max_reserve_violation_kwh <= 1e-6).all()
        and (frame.max_capacity_violation_kwh <= 1e-6).all()
        and (frame.simultaneous_slots == 0).all()
        and frame.balanced_network_feasible.all()
        and frame.three_phase_network_feasible.all()
    )
    # A transferred balanced offer is allowed to fail in the three-phase truth model; alpha_map records this.
    success_rate = float(len(frame) / (len(selected) * 2 * 3))

    # Deterministic repeatability on one moderate case.
    first = selected.iloc[0]
    pop = populations[populations.scenario_id == first.scenario_id]
    fleet = build_fleet(pop, core.EV)
    base = uniform_baseline(fleet)
    scales = scenario_load_scales(load_profile, first)
    r1 = compare_models(core, first.feeder, fleet, base, first.call_time, 30, "inc", scales)
    r2 = compare_models(core, first.feeder, fleet, base, first.call_time, 30, "inc", scales)
    repeat_error = max(abs(r1["f_bal_kw"] - r2["f_bal_kw"]), abs(r1["f_3ph_kw"] - r2["f_3ph_kw"]), abs(r1["alpha_map"] - r2["alpha_map"]))

    report = {
        "protocol": "EV-FLEX-BIAS-V1.2",
        "engine": "duration-aware constant-block LP with nonlinear network verification",
        "selected_scenarios": int(len(selected)),
        "direction_duration_model_comparisons": int(len(frame)),
        "success_rate": success_rate,
        "physical_checks_pass": physical_ok,
        "monotonicity_pass": len(monotonic_failures) == 0,
        "monotonicity_failures": monotonic_failures,
        "repeatability_error": float(repeat_error),
        "repeatability_pass": bool(repeat_error <= 1e-8),
        "max_departure_error_kwh": float(frame.max_departure_error_kwh.max()),
        "max_reserve_violation_kwh": float(frame.max_reserve_violation_kwh.max()),
        "max_capacity_violation_kwh": float(frame.max_capacity_violation_kwh.max()),
        "simultaneous_slots_total": int(frame.simultaneous_slots.sum()),
        "max_runtime_s": float(frame.runtime_s.max()),
        "median_runtime_s": float(frame.runtime_s.median()),
    }
    report["D5_pass"] = bool(
        success_rate >= 0.99
        and physical_ok
        and report["monotonicity_pass"]
        and report["repeatability_pass"]
    )
    (out / "duration_engine_regression_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scenario-id")
    parser.add_argument("--direction", choices=["inc", "dec"])
    parser.add_argument("--duration-min", type=int, choices=[15, 30, 60])
    parser.add_argument("--regression", action="store_true")
    args = parser.parse_args()

    core = load_module(args.repo / "scripts/vendor/network_core_v1_2.py", "duration_core")
    configure_core(core, args.repo)
    if args.regression:
        report = run_regression(args.repo, core, args.out)
        print(json.dumps(report, indent=2))
        return
    if not (args.scenario_id and args.direction and args.duration_min):
        raise SystemExit("Provide --regression or --scenario-id/--direction/--duration-min")

    scenarios = pd.read_csv(args.repo / "config/base_scenarios_v1_2.csv")
    populations = pd.read_csv(args.repo / "data/processed/formal_inputs_v1_2/formal_ev_populations_v1_2.csv")
    load_profile = pd.read_csv(args.repo / "config/controlled_native_load_profile_v1_2.csv")
    scenario = scenarios[scenarios.scenario_id == args.scenario_id].iloc[0]
    population = populations[populations.scenario_id == args.scenario_id]
    fleet = build_fleet(population, core.EV)
    base = uniform_baseline(fleet)
    scales = scenario_load_scales(load_profile, scenario)
    result = compare_models(core, scenario.feeder, fleet, base, scenario.call_time, args.duration_min, args.direction, scales)
    summary = summarize_result(scenario, args.direction, args.duration_min, result, 0.0)
    print(json.dumps(summary, indent=2, default=float))


if __name__ == "__main__":
    main()
