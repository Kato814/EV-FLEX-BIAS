"""Continuous V1G trajectory LP and balanced planning calculations."""
from __future__ import annotations
import math
from dataclasses import asdict
from typing import Dict, Literal, Tuple
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, lil_matrix


DT = 0.25

T = 96

CALL_SLOTS = {"19:00": 28, "00:00": 48, "02:00": 56, "06:00": 72}

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

def scenario_load_scales(load_profile: pd.DataFrame, scenario) -> np.ndarray:
    base = load_profile.sort_values("slot")["normalized_native_load"].to_numpy(dtype=float)
    if len(base) != T:
        raise RuntimeError("Controlled load profile must have 96 rows")
    return np.round(base * float(scenario.native_load_multiplier), 8)
