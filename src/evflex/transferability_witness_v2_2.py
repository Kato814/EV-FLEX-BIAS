from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
from decimal import Decimal
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping


_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)
for _thread_variable in _THREAD_VARIABLES:
    os.environ[_thread_variable] = "1"


from evflex.transferability_dev_v2_2 import (
    load_development_design,
    owned_paths,
)


BAD_ALPHA_THRESHOLD = 0.95
BOUNDARY_INCREMENT = 0.002
_EXPECTED_STRATA = {
    ("ieee13", "dec"),
    ("ieee13", "inc"),
    ("lv906", "dec"),
    ("lv906", "inc"),
}


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def load_archived_evaluations(repo_root: str | Path) -> list[dict[str, Any]]:
    """Load and identity-check the 96 completed V2.2 development evaluations."""

    root = Path(repo_root).resolve(strict=True)
    config, design = load_development_design(root)
    rows: list[dict[str, Any]] = []
    for record in design.to_dict(orient="records"):
        work_unit_id = str(record["work_unit_id"])
        path = owned_paths(root, work_unit_id).result
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"archived work unit is not a mapping: {work_unit_id}")
        provenance = payload.get("run_provenance")
        evaluations = payload.get("evaluations")
        expected_ids = json.loads(str(record["evaluation_ids"]))
        if (
            payload.get("status") != "SUCCESS"
            or payload.get("work_unit_id") != work_unit_id
            or not isinstance(provenance, dict)
            or provenance.get("config_sha256") != config["_config_sha256"]
            or provenance.get("source_manifest_sha256")
            != config["source_manifest_sha256"]
            or provenance.get("holdout_access") != "prohibited"
            or not isinstance(evaluations, list)
            or len(evaluations) != 3
        ):
            raise ValueError(f"archived work-unit identity is invalid: {work_unit_id}")
        observed_ids: list[str] = []
        for evaluation in evaluations:
            if not isinstance(evaluation, dict):
                raise ValueError(f"archived evaluation is not a mapping: {work_unit_id}")
            evaluation_id = evaluation.get("evaluation_id")
            if (
                not isinstance(evaluation_id, str)
                or evaluation.get("work_unit_id") != work_unit_id
                or evaluation.get("status") != "SUCCESS"
                or evaluation.get("scientific_status") != "VALID"
                or evaluation.get("data_role") != "development_transferability"
                or evaluation.get("protocol_version") != config["protocol_version"]
            ):
                raise ValueError(f"archived evaluation identity is invalid: {evaluation_id}")
            observed_ids.append(evaluation_id)
            rows.append(deepcopy(evaluation))
        if observed_ids != expected_ids:
            raise ValueError(f"archived evaluation order differs: {work_unit_id}")

    ids = [str(row["evaluation_id"]) for row in rows]
    if len(rows) != 96 or len(set(ids)) != 96:
        raise ValueError("V2.2 witness source must contain 96 unique evaluations")
    return sorted(rows, key=lambda row: str(row["evaluation_id"]))


def _boundary_witness(row: Mapping[str, Any]) -> tuple[float, int]:
    base = _number(row.get("alpha_transfer"), "alpha_transfer")
    path_audit = row.get("alpha_path_audit")
    trace = path_audit.get("alpha_trace") if isinstance(path_audit, Mapping) else None
    if not isinstance(trace, list):
        raise ValueError("bad evaluation must retain an alpha trace")
    base_is_feasible = any(
        isinstance(item, Mapping)
        and math.isclose(
            _number(item.get("alpha"), "trace alpha"),
            base,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and item.get("feasible") is True
        for item in trace
    )
    candidates = [
        item
        for item in trace
        if isinstance(item, Mapping)
        and _number(item.get("alpha"), "trace alpha") > base
        and item.get("feasible") is False
    ]
    if not base_is_feasible or not candidates:
        raise ValueError("bad evaluation lacks an archived feasible/infeasible boundary")
    witness = min(candidates, key=lambda item: _number(item["alpha"], "trace alpha"))
    alpha = _number(witness.get("alpha"), "boundary-infeasible alpha")
    slot = witness.get("first_failure_slot")
    if (
        not math.isclose(alpha - base, BOUNDARY_INCREMENT, rel_tol=0.0, abs_tol=1e-12)
        or witness.get("failure_class") != "PHYSICAL_CONSTRAINT"
        or witness.get("numerical_failure_checks") != 0
        or isinstance(slot, bool)
        or not isinstance(slot, int)
        or not 0 <= slot <= 95
    ):
        raise ValueError(
            "archived boundary failure must be physical and numerically clean"
        )
    return alpha, slot


def select_witness_pairs(
    evaluations: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Select one extreme failure and one non-causal safe comparator per stratum."""

    rows = [dict(row) for row in evaluations]
    strata = {
        (str(row.get("feeder")), str(row.get("direction"))) for row in rows
    }
    if strata != _EXPECTED_STRATA:
        raise ValueError("witness source must cover the exact feeder-direction strata")

    selected: list[dict[str, Any]] = []
    for index, (feeder, direction) in enumerate(sorted(_EXPECTED_STRATA), start=1):
        stratum = [
            row
            for row in rows
            if row.get("feeder") == feeder and row.get("direction") == direction
        ]
        bad_candidates = [
            row
            for row in stratum
            if _number(row.get("alpha_transfer"), "alpha_transfer")
            < BAD_ALPHA_THRESHOLD
        ]
        controls = [
            row
            for row in stratum
            if math.isclose(
                _number(row.get("alpha_transfer"), "alpha_transfer"),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ]
        if not bad_candidates or not controls:
            raise ValueError(f"stratum {feeder}/{direction} lacks bad or safe rows")
        bad = min(
            bad_candidates,
            key=lambda row: (
                _number(row.get("alpha_transfer"), "alpha_transfer"),
                str(row.get("evaluation_id")),
            ),
        )
        control = min(
            controls,
            key=lambda row: (
                0 if row.get("call_time") == bad.get("call_time") else 1,
                0 if row.get("duration_min") == bad.get("duration_min") else 1,
                str(row.get("evaluation_id")),
            ),
        )
        boundary_alpha, failure_slot = _boundary_witness(bad)
        selected.append(
            {
                "pair_id": f"{index:02d}",
                "stratum_id": f"{feeder}__{direction}",
                "bad": deepcopy(bad),
                "control": deepcopy(control),
                "boundary_infeasible_alpha": boundary_alpha,
                "archived_first_failure_slot": failure_slot,
                "control_is_causal_match": False,
                "selection_rule": (
                    "minimum alpha_transfer; safe comparator prioritizes same "
                    "call_time, then same duration, then evaluation_id"
                ),
            }
        )
    return selected


def select_representative_witnesses(
    evaluations: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Freeze one observed median-nearest failure in each failing design cell."""

    bad_cells: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for raw in evaluations:
        row = dict(raw)
        alpha = _number(row.get("alpha_transfer"), "alpha_transfer")
        if alpha >= BAD_ALPHA_THRESHOLD:
            continue
        cell = (
            str(row.get("feeder")),
            str(row.get("direction")),
            str(row.get("call_time")),
        )
        bad_cells.setdefault(cell, []).append(row)
    if len(bad_cells) != 12:
        raise ValueError("representative source must contain exactly 12 failing cells")

    selected: list[dict[str, Any]] = []
    for index, ((feeder, direction, call_time), rows) in enumerate(
        sorted(bad_cells.items()), start=1
    ):
        alpha_values = sorted(Decimal(str(row["alpha_transfer"])) for row in rows)
        midpoint = len(alpha_values) // 2
        if len(alpha_values) % 2:
            median_alpha = alpha_values[midpoint]
        else:
            median_alpha = (
                alpha_values[midpoint - 1] + alpha_values[midpoint]
            ) / Decimal(2)
        representative = min(
            rows,
            key=lambda row: (
                abs(Decimal(str(row["alpha_transfer"])) - median_alpha),
                abs(int(row["duration_min"]) - 30),
                str(row["evaluation_id"]),
            ),
        )
        boundary_alpha, failure_slot = _boundary_witness(representative)
        selected.append(
            {
                "case_id": f"{index:02d}",
                "cell_id": (
                    f"{feeder}__{direction}__{call_time.replace(':', '')}"
                ),
                "bad": deepcopy(representative),
                "cell_bad_count": len(rows),
                "cell_median_alpha": float(median_alpha),
                "distance_to_median": float(
                    abs(
                        Decimal(str(representative["alpha_transfer"]))
                        - median_alpha
                    )
                ),
                "boundary_infeasible_alpha": boundary_alpha,
                "archived_first_failure_slot": failure_slot,
                "selection_rule": (
                    "closest observed alpha_transfer to the exact decimal cell "
                    "median; ties by distance to 30 minutes, then evaluation_id"
                ),
            }
        )
    return selected


def select_tightest_constraint(
    constraint_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the smallest dimensionless formal-constraint headroom."""

    selected: dict[str, Any] | None = None
    selected_key: tuple[float, int, str, str, str] | None = None
    for raw in constraint_rows:
        row = deepcopy(dict(raw))
        limit = _number(row.get("limit"), "constraint limit")
        headroom = _number(row.get("signed_headroom"), "constraint headroom")
        if limit <= 0:
            raise ValueError("constraint limit must be positive")
        row["relative_headroom"] = headroom / limit
        key = (
            row["relative_headroom"],
            int(row["slot"]),
            str(row["constraint_family"]),
            str(row["metric_id"]),
            str(row["direction"]),
        )
        if selected_key is None or key < selected_key:
            selected = row
            selected_key = key
    if selected is None:
        raise ValueError("constraint rows must not be empty")
    return selected


def _member_from_evaluation(
    row: Mapping[str, Any], *, pair_id: str, stratum_id: str, role: str
) -> dict[str, Any]:
    if role not in {"bad", "control"}:
        raise ValueError("witness role must be bad or control")
    return {
        "pair_id": pair_id,
        "scenario_cluster": stratum_id,
        "role": role,
        "evaluation_id": str(row["evaluation_id"]),
        "work_unit_id": str(row["work_unit_id"]),
        "scenario_id": str(row["scenario_id"]),
        "scenario_seed": int(row["scenario_seed"]),
        "feeder": str(row["feeder"]),
        "call_time": str(row["call_time"]),
        "direction": str(row["direction"]),
        "duration_min": int(row["duration_min"]),
        "requested_duration_min": int(row["requested_duration_min"]),
        "source_duration_min": int(row["source_duration_min"]),
        "alpha_transfer": _number(row["alpha_transfer"], "alpha_transfer"),
        "schedule_sha256": str(row["schedule_sha256"]),
        "bus_phase_time_sha256": str(row["bus_phase_time_sha256"]),
        "baseline_schedule_sha256": str(row["baseline_schedule_sha256"]),
    }


def _all_constraint_rows(raw: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    from evflex.mechanism_diagnostic import constraint_rows_from_slot

    slot_results = raw.get("slot_results")
    if not isinstance(slot_results, list):
        raise ValueError("witness audit must retain slot results")
    for slot in slot_results:
        yield from constraint_rows_from_slot(slot)


def execute_witness_pair(
    repo_root: str | Path,
    pair: Mapping[str, Any],
    *,
    pilot_config: Mapping[str, Any] | None = None,
    runtime_factory: Any = None,
    _include_control: bool = True,
) -> dict[str, Any]:
    """Replay one selected bad boundary and its non-causal safe comparator."""

    import numpy as np

    from evflex import pilot
    from evflex.mechanism_diagnostic import (
        compact_targeted_audit,
        reconstruct_case,
    )
    from evflex.mechanism_diagnostic_d1r_lite import (
        validate_raw_audit_identity,
    )

    root = Path(repo_root).resolve(strict=True)
    if not isinstance(pair, Mapping):
        raise ValueError("witness pair must be a mapping")
    pair_id = str(pair.get("pair_id"))
    stratum_id = str(pair.get("stratum_id"))
    bad_row = pair.get("bad")
    control_row = pair.get("control")
    if not isinstance(bad_row, Mapping):
        raise ValueError("witness pair must contain a bad mapping")
    if _include_control and not isinstance(control_row, Mapping):
        raise ValueError("witness pair must contain a control mapping")
    config = (
        load_development_design(root)[0]
        if pilot_config is None
        else dict(pilot_config)
    )
    formal_constraints = config.get("formal_constraints")
    if not isinstance(formal_constraints, Mapping):
        raise ValueError("witness pilot config lacks formal constraints")

    members = {
        "bad": _member_from_evaluation(
            bad_row, pair_id=pair_id, stratum_id=stratum_id, role="bad"
        )
    }
    if _include_control:
        members["control"] = _member_from_evaluation(
            control_row,
            pair_id=pair_id,
            stratum_id=stratum_id,
            role="control",
        )
    adapter_identity = {
        "adapter_schema": pilot._PILOT_ADAPTER_SCHEMA,
        "adapter_version": pilot._PILOT_ADAPTER_VERSION,
    }
    bad_alpha = _number(bad_row.get("alpha_transfer"), "bad alpha_transfer")
    infeasible_alpha = _number(
        pair.get("boundary_infeasible_alpha"), "boundary-infeasible alpha"
    )
    expected_failure_slot = pair.get("archived_first_failure_slot")
    points_by_role = {
        "bad": (
            ("BOUNDARY_FEASIBLE", bad_alpha, False),
            ("BOUNDARY_INFEASIBLE", infeasible_alpha, True),
        ),
    }
    if _include_control:
        points_by_role["control"] = (("FULL_OFFER", 1.0, False),)
    audits: list[dict[str, Any]] = []
    for role in members:
        case = reconstruct_case(
            root,
            members[role],
            pilot_config=config,
            runtime_factory=runtime_factory,
        )
        runtime = case["runtime"]
        cache = runtime.create_corrected_truth_cache()
        baseline_raw = runtime.audit_corrected(
            case["baseline"],
            cache,
            baseline_slot_results=None,
            stop_on_violation=False,
            retain_slot_results=True,
        )
        validate_raw_audit_identity(
            baseline_raw,
            case=case,
            formal_constraints=formal_constraints,
            adapter_identity=adapter_identity,
        )
        baseline_compact = compact_targeted_audit(
            baseline_raw,
            audit_point="BOUNDARY_FEASIBLE",
            alpha=0.0,
        )
        baseline_slots = baseline_raw.get("slot_results")
        if (
            baseline_compact["feasible"] is not True
            or baseline_compact["complete_coverage"] is not True
            or not isinstance(baseline_slots, list)
            or len(baseline_slots) != 96
        ):
            raise ValueError("witness baseline must be feasible over all 96 slots")

        for audit_point, alpha, stop_on_violation in points_by_role[role]:
            schedule = case["baseline"] + alpha * (
                case["schedule"] - case["baseline"]
            )
            if not np.isfinite(schedule).all():
                raise ValueError("witness replay schedule contains non-finite values")
            raw = runtime.audit_corrected(
                schedule,
                cache,
                baseline_slot_results=baseline_slots,
                stop_on_violation=stop_on_violation,
                retain_slot_results=True,
            )
            validate_raw_audit_identity(
                raw,
                case=case,
                formal_constraints=formal_constraints,
                adapter_identity=adapter_identity,
            )
            compact = compact_targeted_audit(
                raw,
                audit_point=audit_point,
                alpha=alpha,
            )
            should_be_feasible = audit_point != "BOUNDARY_INFEASIBLE"
            if compact["feasible"] is not should_be_feasible:
                raise ValueError(
                    f"{audit_point}/{role} contradicts the archived label"
                )
            if should_be_feasible and compact["complete_coverage"] is not True:
                raise ValueError(
                    f"{audit_point}/{role} lacks complete 96-slot coverage"
                )
            if not should_be_feasible and (
                compact["failure_class"] != "PHYSICAL_CONSTRAINT"
                or compact["numerical_failure_checks"] != 0
                or compact["first_failure_slot"] != expected_failure_slot
            ):
                raise ValueError(
                    "boundary replay differs from the archived physical witness"
                )

            selected_slot = compact.get("selected_slot")
            violations: list[dict[str, Any]] = []
            tightest: dict[str, Any] | None = None
            if should_be_feasible:
                tightest = select_tightest_constraint(_all_constraint_rows(raw))
            elif isinstance(selected_slot, Mapping):
                simultaneous = selected_slot.get("simultaneous_violations")
                if not isinstance(simultaneous, list) or not simultaneous:
                    raise ValueError(
                        "boundary replay lacks simultaneous physical violations"
                    )
                for raw_violation in simultaneous:
                    violation = deepcopy(dict(raw_violation))
                    limit = _number(violation.get("limit"), "violation limit")
                    exceedance = _number(
                        violation.get("exceedance"), "violation exceedance"
                    )
                    violation["relative_exceedance"] = exceedance / limit
                    violations.append(violation)

            audits.append(
                {
                    "role": role,
                    "source_evaluation_id": members[role]["evaluation_id"],
                    "audit_point": audit_point,
                    "alpha": alpha,
                    "audited_schedule_sha256": pilot.canonical_schedule_sha256(
                        case["fleet"], schedule
                    ),
                    "feasible": compact["feasible"],
                    "checked_intervals": compact["checked_intervals"],
                    "complete_coverage": compact["complete_coverage"],
                    "failure_class": compact["failure_class"],
                    "first_failure_slot": compact["first_failure_slot"],
                    "numerical_failure_checks": compact[
                        "numerical_failure_checks"
                    ],
                    "nonconverged_checks": compact["nonconverged_checks"],
                    "physical_violation_checks": compact[
                        "physical_violation_checks"
                    ],
                    "vmin": compact["vmin"],
                    "vmax": compact["vmax"],
                    "vufmax": compact["vufmax"],
                    "transformer_loading_max": compact[
                        "transformer_loading_max"
                    ],
                    "feeder_loading_max": compact["feeder_loading_max"],
                    "tightest_constraint": tightest,
                    "simultaneous_violations": violations,
                }
            )
        del raw, baseline_raw, baseline_slots, cache, runtime, case
        gc.collect()

    return {
        "protocol_version": "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-WITNESS-DEV",
        "status": "SUCCESS",
        "pair_id": pair_id,
        "stratum_id": stratum_id,
        "control_is_causal_match": False,
        "line_thermal_in_scope": False,
        "members": deepcopy(members),
        "audits": audits,
    }


def execute_representative_witness_case(
    repo_root: str | Path,
    case: Mapping[str, Any],
    *,
    pilot_config: Mapping[str, Any] | None = None,
    runtime_factory: Any = None,
) -> dict[str, Any]:
    """Replay only the feasible/infeasible boundary of one frozen representative."""

    if not isinstance(case, Mapping) or not isinstance(case.get("bad"), Mapping):
        raise ValueError("representative witness case is invalid")
    case_id = str(case.get("case_id"))
    cell_id = str(case.get("cell_id"))
    original_bad = deepcopy(dict(case["bad"]))
    replay_bad = deepcopy(original_bad)
    duration = int(original_bad.get("duration_min"))
    requested_duration = int(original_bad.get("requested_duration_min"))
    source_duration = int(original_bad.get("source_duration_min"))
    if requested_duration != duration:
        raise ValueError("representative requested duration is inconsistent")
    duration_adapter_applied = source_duration != duration
    if duration_adapter_applied:
        if (
            original_bad.get("canonical_schedule_reused") is not True
            or original_bad.get("monotonic_closure_promoted") is not True
        ):
            raise ValueError(
                "representative source-duration reuse lacks archived evidence"
            )
        replay_bad["duration_min"] = source_duration
        replay_bad["requested_duration_min"] = source_duration
    boundary_result = execute_witness_pair(
        repo_root,
        {
            "pair_id": case_id,
            "stratum_id": cell_id,
            "bad": replay_bad,
            "boundary_infeasible_alpha": case.get(
                "boundary_infeasible_alpha"
            ),
            "archived_first_failure_slot": case.get(
                "archived_first_failure_slot"
            ),
        },
        pilot_config=pilot_config,
        runtime_factory=runtime_factory,
        _include_control=False,
    )
    if len(boundary_result["audits"]) != 2:
        raise ValueError("representative witness must contain exactly two audits")
    return {
        "protocol_version": (
            "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-REPRESENTATIVE-WITNESS-DEV"
        ),
        "status": "SUCCESS",
        "case_id": case_id,
        "cell_id": cell_id,
        "safe_control_evaluated": False,
        "line_thermal_in_scope": False,
        "source_schedule_reused": bool(
            original_bad.get("canonical_schedule_reused")
        ),
        "reconstruction_duration_adapter_applied": duration_adapter_applied,
        "selection": {
            "rule": str(case.get("selection_rule")),
            "cell_bad_count": int(case.get("cell_bad_count")),
            "cell_median_alpha": _number(
                case.get("cell_median_alpha"), "cell median alpha"
            ),
            "distance_to_median": _number(
                case.get("distance_to_median"), "distance to median"
            ),
        },
        "member": _member_from_evaluation(
            original_bad,
            pair_id=case_id,
            stratum_id=cell_id,
            role="bad",
        ),
        "audits": deepcopy(boundary_result["audits"]),
    }


def build_witness_summary(
    pair_results: Iterable[Mapping[str, Any]],
    *,
    code_commit: str,
    config_sha256: str,
    source_run_code_commit: str,
    source_result_hash_aggregate: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Build the compact, development-only witness result artifact."""

    pairs = [deepcopy(dict(pair)) for pair in pair_results]
    if len(pairs) != 4 or any(pair.get("status") != "SUCCESS" for pair in pairs):
        raise ValueError("witness summary requires four successful pair results")
    audits = [
        audit
        for pair in pairs
        for audit in pair.get("audits", [])
        if isinstance(audit, Mapping)
    ]
    if len(audits) != 12 or any(len(pair.get("audits", [])) != 3 for pair in pairs):
        raise ValueError("witness summary requires exactly three audits per pair")

    numerical_failures = sum(
        int(audit.get("numerical_failure_checks", 0)) for audit in audits
    )
    nonconverged = sum(int(audit.get("nonconverged_checks", 0)) for audit in audits)
    boundaries = [
        audit
        for audit in audits
        if audit.get("role") == "bad"
        and audit.get("audit_point") == "BOUNDARY_INFEASIBLE"
        and audit.get("feasible") is False
        and audit.get("failure_class") == "PHYSICAL_CONSTRAINT"
        and audit.get("numerical_failure_checks") == 0
        and audit.get("nonconverged_checks") == 0
        and isinstance(audit.get("simultaneous_violations"), list)
        and bool(audit["simultaneous_violations"])
    ]
    if len(boundaries) != 4 or numerical_failures or nonconverged:
        raise ValueError("witness summary lacks four numerically clean physical boundaries")

    family_counts: dict[str, int] = {}
    for audit in boundaries:
        for violation in audit["simultaneous_violations"]:
            family = str(violation.get("constraint_family"))
            family_counts[family] = family_counts.get(family, 0) + 1

    return {
        "protocol_version": "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-WITNESS-DEV",
        "status": "SUCCESS",
        "generated_at_utc": generated_at_utc,
        "formal_holdout_opened": False,
        "scientific_scope": {
            "development_only": True,
            "fixed_schedule_transfer_only": True,
            "three_phase_reoptimization_in_scope": False,
            "line_thermal_in_scope": False,
            "safe_comparators_are_causal_matches": False,
        },
        "resource_policy": {
            "workers": 1,
            "numeric_threads": {name: 1 for name in _THREAD_VARIABLES},
            "gpu_used": False,
            "gpu_reason": "OpenDSS three-phase power flow uses the CPU path",
        },
        "provenance": {
            "code_commit": code_commit,
            "config_sha256": config_sha256,
            "source_run_code_commit": source_run_code_commit,
            "source_result_hash_aggregate_sha256": (
                source_result_hash_aggregate
            ),
        },
        "counts": {
            "pairs": len(pairs),
            "selected_members": 2 * len(pairs),
            "audits": len(audits),
            "exact_boundary_witnesses": len(boundaries),
            "numerical_failure_checks": numerical_failures,
        },
        "boundary_constraint_family_counts": dict(sorted(family_counts.items())),
        "pairs": pairs,
    }


def _primary_violation(audit: Mapping[str, Any]) -> Mapping[str, Any]:
    violations = audit.get("simultaneous_violations")
    if not isinstance(violations, list) or not violations:
        raise ValueError("physical boundary must contain at least one violation")
    return max(
        violations,
        key=lambda item: (
            _number(item.get("relative_exceedance"), "relative exceedance"),
            str(item.get("constraint_family")),
            str(item.get("metric_id")),
        ),
    )


def build_representative_witness_summary(
    case_results: Iterable[Mapping[str, Any]],
    *,
    code_commit: str,
    config_sha256: str,
    source_run_code_commit: str,
    source_result_hash_aggregate: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    """Build the compact 12-cell representative boundary evidence artifact."""

    cases = [deepcopy(dict(case)) for case in case_results]
    expected_ids = [f"{index:02d}" for index in range(1, 13)]
    if (
        len(cases) != 12
        or [case.get("case_id") for case in cases] != expected_ids
        or len({case.get("cell_id") for case in cases}) != 12
        or any(case.get("status") != "SUCCESS" for case in cases)
    ):
        raise ValueError("representative summary requires 12 ordered successful cells")

    audits: list[Mapping[str, Any]] = []
    boundaries: list[Mapping[str, Any]] = []
    rules: set[str] = set()
    source_bad_rows = 0
    source_duration_reuse_cases = 0
    for case in cases:
        if (
            case.get("safe_control_evaluated") is not False
            or case.get("line_thermal_in_scope") is not False
        ):
            raise ValueError("representative scope must exclude controls and line thermal")
        selection = case.get("selection")
        member = case.get("member")
        case_audits = case.get("audits")
        if (
            not isinstance(selection, Mapping)
            or not isinstance(member, Mapping)
            or not isinstance(case_audits, list)
        ):
            raise ValueError("representative case is structurally invalid")
        duration_reused = bool(
            case.get("reconstruction_duration_adapter_applied")
        )
        if duration_reused != (
            int(member.get("duration_min"))
            != int(member.get("source_duration_min"))
        ) or (duration_reused and case.get("source_schedule_reused") is not True):
            raise ValueError("representative source-duration reuse is inconsistent")
        source_duration_reuse_cases += int(duration_reused)
        rules.add(str(selection.get("rule")))
        source_bad_rows += int(selection.get("cell_bad_count"))
        if len(case_audits) != 2:
            raise ValueError("representative case must contain exactly two audits")
        feasible, infeasible = case_audits
        if (
            not isinstance(feasible, Mapping)
            or feasible.get("audit_point") != "BOUNDARY_FEASIBLE"
            or feasible.get("feasible") is not True
            or feasible.get("complete_coverage") is not True
            or feasible.get("checked_intervals") != 96
            or not isinstance(infeasible, Mapping)
            or infeasible.get("audit_point") != "BOUNDARY_INFEASIBLE"
            or infeasible.get("feasible") is not False
            or infeasible.get("failure_class") != "PHYSICAL_CONSTRAINT"
        ):
            raise ValueError("representative case contradicts its exact boundary")
        _primary_violation(infeasible)
        audits.extend((feasible, infeasible))
        boundaries.append(infeasible)

    numerical_failures = sum(
        int(audit.get("numerical_failure_checks", 0)) for audit in audits
    )
    nonconverged = sum(int(audit.get("nonconverged_checks", 0)) for audit in audits)
    if (
        len(rules) != 1
        or source_bad_rows != 51
        or numerical_failures
        or nonconverged
    ):
        raise ValueError("representative summary is incomplete or numerically unclean")

    primary_family_counts: dict[str, int] = {}
    any_family_case_counts: dict[str, int] = {}
    for boundary in boundaries:
        primary_family = str(_primary_violation(boundary)["constraint_family"])
        primary_family_counts[primary_family] = (
            primary_family_counts.get(primary_family, 0) + 1
        )
        families = {
            str(violation.get("constraint_family"))
            for violation in boundary["simultaneous_violations"]
        }
        for family in families:
            any_family_case_counts[family] = any_family_case_counts.get(family, 0) + 1

    return {
        "protocol_version": (
            "EV-FLEX-BIAS-V2.2-TRANSFERABILITY-REPRESENTATIVE-WITNESS-DEV"
        ),
        "status": "SUCCESS",
        "generated_at_utc": generated_at_utc,
        "formal_holdout_opened": False,
        "scientific_scope": {
            "development_only": True,
            "fixed_schedule_transfer_only": True,
            "three_phase_reoptimization_in_scope": False,
            "line_thermal_in_scope": False,
            "safe_controls_evaluated": False,
            "mechanism_labels_used_for_selection": False,
            "source_duration_reuse_explicitly_recorded": True,
        },
        "selection_design": {
            "unit": "feeder-direction-call_time cell with alpha_transfer < 0.95",
            "bad_alpha_threshold": BAD_ALPHA_THRESHOLD,
            "rule": next(iter(rules)),
            "target_duration_min_for_ties": 30,
        },
        "resource_policy": {
            "workers": 1,
            "independent_child_process_per_case": True,
            "numeric_threads": {name: 1 for name in _THREAD_VARIABLES},
            "gpu_used": False,
            "gpu_reason": "OpenDSS three-phase power flow uses the CPU path",
        },
        "provenance": {
            "code_commit": code_commit,
            "config_sha256": config_sha256,
            "source_run_code_commit": source_run_code_commit,
            "source_result_hash_aggregate_sha256": source_result_hash_aggregate,
        },
        "counts": {
            "cases": len(cases),
            "selected_members": len(cases),
            "source_failing_rows_covered_by_cells": source_bad_rows,
            "audits": len(audits),
            "exact_boundary_witnesses": len(boundaries),
            "numerical_failure_checks": numerical_failures,
            "nonconverged_checks": nonconverged,
            "source_duration_reuse_cases": source_duration_reuse_cases,
        },
        "primary_boundary_constraint_family_counts": dict(
            sorted(primary_family_counts.items())
        ),
        "any_boundary_constraint_family_case_counts": dict(
            sorted(any_family_case_counts.items())
        ),
        "cases": cases,
    }


def flatten_summary_csv_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten the compact JSON summary to one human-readable row per audit."""

    pairs = summary.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("witness summary pairs must be a list")
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, Mapping) or not isinstance(pair.get("audits"), list):
            raise ValueError("witness summary pair is invalid")
        for audit in pair["audits"]:
            if not isinstance(audit, Mapping):
                raise ValueError("witness summary audit is invalid")
            violations = audit.get("simultaneous_violations")
            if not isinstance(violations, list):
                raise ValueError("witness audit violations must be a list")
            primary: Mapping[str, Any] | None
            relative_margin: float | None
            if violations:
                primary = max(
                    violations,
                    key=lambda item: (
                        _number(
                            item.get("relative_exceedance"),
                            "relative exceedance",
                        ),
                        str(item.get("constraint_family")),
                        str(item.get("metric_id")),
                    ),
                )
                relative_margin = -_number(
                    primary.get("relative_exceedance"), "relative exceedance"
                )
            else:
                tightest = audit.get("tightest_constraint")
                primary = tightest if isinstance(tightest, Mapping) else None
                relative_margin = (
                    _number(
                        primary.get("relative_headroom"), "relative headroom"
                    )
                    if primary is not None
                    else None
                )
            rows.append(
                {
                    "pair_id": pair.get("pair_id"),
                    "stratum_id": pair.get("stratum_id"),
                    "role": audit.get("role"),
                    "source_evaluation_id": audit.get("source_evaluation_id"),
                    "audit_point": audit.get("audit_point"),
                    "alpha": audit.get("alpha"),
                    "feasible": audit.get("feasible"),
                    "checked_intervals": audit.get("checked_intervals"),
                    "failure_class": audit.get("failure_class"),
                    "first_failure_slot": audit.get("first_failure_slot"),
                    "numerical_failure_checks": audit.get(
                        "numerical_failure_checks"
                    ),
                    "simultaneous_violation_count": len(violations),
                    "constraint_family": (
                        primary.get("constraint_family") if primary else None
                    ),
                    "metric_id": primary.get("metric_id") if primary else None,
                    "object_id": primary.get("object_id") if primary else None,
                    "constraint_slot": primary.get("slot") if primary else None,
                    "value": primary.get("value") if primary else None,
                    "limit": primary.get("limit") if primary else None,
                    "relative_margin": relative_margin,
                    "control_is_causal_match": False,
                }
            )
    return rows


def flatten_representative_summary_csv_rows(
    summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Flatten representative evidence to one row per boundary audit point."""

    cases = summary.get("cases")
    if not isinstance(cases, list):
        raise ValueError("representative summary cases must be a list")
    rows: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("representative summary case is invalid")
        member = case.get("member")
        selection = case.get("selection")
        audits = case.get("audits")
        if (
            not isinstance(member, Mapping)
            or not isinstance(selection, Mapping)
            or not isinstance(audits, list)
        ):
            raise ValueError("representative summary case is incomplete")
        for audit in audits:
            if not isinstance(audit, Mapping):
                raise ValueError("representative summary audit is invalid")
            violations = audit.get("simultaneous_violations")
            if not isinstance(violations, list):
                raise ValueError("representative audit violations must be a list")
            primary: Mapping[str, Any] | None
            relative_margin: float | None
            if violations:
                primary = _primary_violation(audit)
                relative_margin = -_number(
                    primary.get("relative_exceedance"), "relative exceedance"
                )
            else:
                tightest = audit.get("tightest_constraint")
                primary = tightest if isinstance(tightest, Mapping) else None
                relative_margin = (
                    _number(primary.get("relative_headroom"), "relative headroom")
                    if primary is not None
                    else None
                )
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "cell_id": case.get("cell_id"),
                    "source_evaluation_id": member.get("evaluation_id"),
                    "feeder": member.get("feeder"),
                    "direction": member.get("direction"),
                    "call_time": member.get("call_time"),
                    "duration_min": member.get("duration_min"),
                    "source_duration_min": member.get("source_duration_min"),
                    "source_duration_reuse": case.get(
                        "reconstruction_duration_adapter_applied"
                    ),
                    "cell_bad_count": selection.get("cell_bad_count"),
                    "cell_median_alpha": selection.get("cell_median_alpha"),
                    "distance_to_median": selection.get("distance_to_median"),
                    "audit_point": audit.get("audit_point"),
                    "alpha": audit.get("alpha"),
                    "feasible": audit.get("feasible"),
                    "checked_intervals": audit.get("checked_intervals"),
                    "failure_class": audit.get("failure_class"),
                    "first_failure_slot": audit.get("first_failure_slot"),
                    "numerical_failure_checks": audit.get(
                        "numerical_failure_checks"
                    ),
                    "simultaneous_violation_count": len(violations),
                    "constraint_family": (
                        primary.get("constraint_family") if primary else None
                    ),
                    "metric_id": primary.get("metric_id") if primary else None,
                    "object_id": primary.get("object_id") if primary else None,
                    "constraint_slot": primary.get("slot") if primary else None,
                    "value": primary.get("value") if primary else None,
                    "limit": primary.get("limit") if primary else None,
                    "relative_margin": relative_margin,
                    "safe_control_evaluated": False,
                }
            )
    return rows


def _write_compact_summary_artifacts(
    repo_root: str | Path,
    summary: Mapping[str, Any],
    *,
    output_name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Path]:
    from evflex.runner import atomic_write_json

    if not rows:
        raise ValueError("summary CSV rows must not be empty")
    root = Path(repo_root).resolve(strict=False)
    output = root / "results" / output_name
    json_path = output / "summary.json"
    csv_path = output / "summary.csv"
    atomic_write_json(json_path, summary)
    output.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=csv_path.name,
        suffix=".tmp",
        dir=output,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, csv_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"json": json_path, "csv": csv_path}


def write_summary_artifacts(
    repo_root: str | Path, summary: Mapping[str, Any]
) -> dict[str, Path]:
    """Atomically write the only two retained witness artifacts."""

    return _write_compact_summary_artifacts(
        repo_root,
        summary,
        output_name="transferability_witness_v2_2",
        rows=flatten_summary_csv_rows(summary),
    )


def write_representative_summary_artifacts(
    repo_root: str | Path, summary: Mapping[str, Any]
) -> dict[str, Path]:
    """Atomically retain only one JSON and one CSV for representative evidence."""

    return _write_compact_summary_artifacts(
        repo_root,
        summary,
        output_name="transferability_representative_witness_v2_2",
        rows=flatten_representative_summary_csv_rows(summary),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    commit = completed.stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError("witness code commit is not a full lowercase SHA-1")
    return commit


def _require_clean_worktree(repo_root: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.stdout.strip():
        raise ValueError("witness production run requires a clean committed worktree")


def _source_provenance(repo_root: Path) -> tuple[str, str]:
    _, design = load_development_design(repo_root)
    digest = hashlib.sha256()
    source_commits: set[str] = set()
    for work_unit_id in sorted(str(value) for value in design["work_unit_id"]):
        path = owned_paths(repo_root, work_unit_id).result
        payload = json.loads(path.read_text(encoding="utf-8"))
        provenance = payload.get("run_provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("source result lacks run provenance")
        source_commits.add(str(provenance.get("code_commit")))
        relative = path.relative_to(repo_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    if len(source_commits) != 1:
        raise ValueError("source results do not share one code commit")
    source_commit = next(iter(source_commits))
    if len(source_commit) != 40:
        raise ValueError("source result code commit is invalid")
    return source_commit, digest.hexdigest()


def run_all_witnesses(repo_root: str | Path) -> dict[str, Any]:
    """Run four isolated witness pairs and retain one JSON plus one CSV."""

    root = Path(repo_root).resolve(strict=True)
    _require_clean_worktree(root)
    output = root / "results" / "transferability_witness_v2_2"
    if (output / "summary.json").exists() or (output / "summary.csv").exists():
        raise FileExistsError("witness summary artifacts already exist")

    config, _ = load_development_design(root)
    pairs = select_witness_pairs(load_archived_evaluations(root))
    pair_results: list[dict[str, Any]] = []
    environment = {**os.environ, **{name: "1" for name in _THREAD_VARIABLES}}
    for index, pair in enumerate(pairs, start=1):
        pair_id = str(pair["pair_id"])
        print(
            f"[{index}/4] {pair['stratum_id']} ({pair_id})",
            flush=True,
        )
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "evflex.transferability_witness_v2_2",
                "--pair-id",
                pair_id,
                "--workers",
                "1",
            ],
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if child.returncode != 0:
            detail = "\n".join((child.stderr or child.stdout).splitlines()[-30:])
            raise RuntimeError(f"witness child {pair_id} failed:\n{detail}")
        lines = [
            line.removeprefix("WITNESS_JSON=")
            for line in child.stdout.splitlines()
            if line.startswith("WITNESS_JSON=")
        ]
        if len(lines) != 1:
            raise ValueError(f"witness child {pair_id} did not emit one result")
        result = json.loads(lines[0])
        if result.get("pair_id") != pair_id or result.get("status") != "SUCCESS":
            raise ValueError(f"witness child {pair_id} returned an invalid result")
        pair_results.append(result)
        boundary = result["audits"][1]
        families = sorted(
            {
                item["constraint_family"]
                for item in boundary["simultaneous_violations"]
            }
        )
        print(
            f"  boundary slot={boundary['first_failure_slot']} "
            f"family={'+'.join(families)}",
            flush=True,
        )

    source_commit, source_hash = _source_provenance(root)
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = build_witness_summary(
        pair_results,
        code_commit=_git_commit(root),
        config_sha256=str(config["_config_sha256"]),
        source_run_code_commit=source_commit,
        source_result_hash_aggregate=source_hash,
        generated_at_utc=generated,
    )
    paths = write_summary_artifacts(root, summary)
    print(f"WROTE {paths['json'].relative_to(root)}", flush=True)
    print(f"WROTE {paths['csv'].relative_to(root)}", flush=True)
    return summary


def run_all_representative_witnesses(repo_root: str | Path) -> dict[str, Any]:
    """Run 12 isolated representative boundaries and retain one JSON plus one CSV."""

    root = Path(repo_root).resolve(strict=True)
    _require_clean_worktree(root)
    output = root / "results" / "transferability_representative_witness_v2_2"
    if (output / "summary.json").exists() or (output / "summary.csv").exists():
        raise FileExistsError("representative witness artifacts already exist")

    config, _ = load_development_design(root)
    cases = select_representative_witnesses(load_archived_evaluations(root))
    case_results: list[dict[str, Any]] = []
    environment = {**os.environ, **{name: "1" for name in _THREAD_VARIABLES}}
    for index, case in enumerate(cases, start=1):
        case_id = str(case["case_id"])
        print(f"[{index}/12] {case['cell_id']} ({case_id})", flush=True)
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "evflex.transferability_witness_v2_2",
                "--representative-case-id",
                case_id,
                "--workers",
                "1",
            ],
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if child.returncode != 0:
            detail = "\n".join((child.stderr or child.stdout).splitlines()[-30:])
            raise RuntimeError(
                f"representative witness child {case_id} failed:\n{detail}"
            )
        lines = [
            line.removeprefix("REPRESENTATIVE_WITNESS_JSON=")
            for line in child.stdout.splitlines()
            if line.startswith("REPRESENTATIVE_WITNESS_JSON=")
        ]
        if len(lines) != 1:
            raise ValueError(
                f"representative witness child {case_id} did not emit one result"
            )
        result = json.loads(lines[0])
        if result.get("case_id") != case_id or result.get("status") != "SUCCESS":
            raise ValueError(
                f"representative witness child {case_id} returned an invalid result"
            )
        case_results.append(result)
        boundary = result["audits"][1]
        families = sorted(
            {
                item["constraint_family"]
                for item in boundary["simultaneous_violations"]
            }
        )
        print(
            f"  boundary slot={boundary['first_failure_slot']} "
            f"family={'+'.join(families)}",
            flush=True,
        )

    source_commit, source_hash = _source_provenance(root)
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = build_representative_witness_summary(
        case_results,
        code_commit=_git_commit(root),
        config_sha256=str(config["_config_sha256"]),
        source_run_code_commit=source_commit,
        source_result_hash_aggregate=source_hash,
        generated_at_utc=generated,
    )
    paths = write_representative_summary_artifacts(root, summary)
    print(f"WROTE {paths['json'].relative_to(root)}", flush=True)
    print(f"WROTE {paths['csv'].relative_to(root)}", flush=True)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the compact V2.2 fixed-schedule boundary witness audit."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--pair-id")
    target.add_argument("--representative-case-id")
    target.add_argument("--representative-all", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.workers != 1:
        raise SystemExit("--workers must be exactly 1")
    root = Path(__file__).resolve().parents[2]
    if args.pair_id:
        pairs = select_witness_pairs(load_archived_evaluations(root))
        matches = [pair for pair in pairs if pair["pair_id"] == args.pair_id]
        if len(matches) != 1:
            raise SystemExit(f"unknown witness pair: {args.pair_id}")
        result = execute_witness_pair(root, matches[0])
        print(
            "WITNESS_JSON="
            + json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            flush=True,
        )
        return 0
    if args.representative_case_id:
        cases = select_representative_witnesses(load_archived_evaluations(root))
        matches = [
            case
            for case in cases
            if case["case_id"] == args.representative_case_id
        ]
        if len(matches) != 1:
            raise SystemExit(
                "unknown representative witness case: "
                f"{args.representative_case_id}"
            )
        result = execute_representative_witness_case(root, matches[0])
        print(
            "REPRESENTATIVE_WITNESS_JSON="
            + json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            flush=True,
        )
        return 0
    if args.representative_all:
        summary = run_all_representative_witnesses(root)
        print(
            json.dumps(
                {
                    "status": summary["status"],
                    "cases": summary["counts"]["cases"],
                    "exact_boundary_witnesses": summary["counts"][
                        "exact_boundary_witnesses"
                    ],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0
    summary = run_all_witnesses(root)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "pairs": summary["counts"]["pairs"],
                "exact_boundary_witnesses": summary["counts"][
                    "exact_boundary_witnesses"
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
