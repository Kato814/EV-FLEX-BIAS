from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from evflex.engine import select_nested_candidate
from evflex.pilot import (
    _create_real_pilot_runtime,
    _normalize_raw_balanced_result,
    _validated_schedule,
    canonical_schedule_sha256,
)
from evflex.transferability_replication_v2_5b import load_replication_design

TOL = 1e-12


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        record = {key: (None if pd.isna(value) else value) for key, value in raw.items()}
        record["scenario_seed"] = int(record["scenario_seed"])
        record["prior_holdout_open_acknowledged"] = bool(
            record["prior_holdout_open_acknowledged"]
        )
        records.append(record)
    return records


def _constraint_class(metric: str, direction: str) -> str:
    if metric.startswith("V:"):
        return "voltage_low" if direction == "lo" else "voltage_high"
    if metric.startswith("U:"):
        return "vuf"
    if metric.startswith("S:transformer:"):
        return "transformer_loading"
    if metric == "S:feeder":
        return "feeder_loading"
    return "other"


def _physical_constraints(slot_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = slot_record.get("violations", [])
    result: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, Mapping) or item.get("kind") != "physical_constraint":
            continue
        metric = str(item.get("metric"))
        direction = str(item.get("direction"))
        value = float(item["value"])
        limit = float(item["limit"])
        magnitude = limit - value if direction == "lo" else value - limit
        result.append(
            {
                "metric": metric,
                "constraint_class": _constraint_class(metric, direction),
                "direction": direction,
                "value": value,
                "limit": limit,
                "violation_magnitude": float(magnitude),
                "relative_violation": float(magnitude / max(abs(limit), 1e-12)),
            }
        )
    return result


def _first_failure(raw_audit: Mapping[str, Any]) -> tuple[int | None, list[dict[str, Any]]]:
    violations = raw_audit.get("violations", [])
    if not isinstance(violations, list):
        return None, []
    physical_slots: list[tuple[int, list[dict[str, Any]]]] = []
    for record in violations:
        if not isinstance(record, Mapping):
            continue
        if record.get("failure_class") != "PHYSICAL_CONSTRAINT":
            continue
        try:
            slot = int(record["slot"])
        except (KeyError, TypeError, ValueError):
            continue
        constraints = _physical_constraints(record)
        if constraints:
            physical_slots.append((slot, constraints))
    if not physical_slots:
        return None, []
    slot = min(value[0] for value in physical_slots)
    constraints: list[dict[str, Any]] = []
    for observed_slot, observed in physical_slots:
        if observed_slot == slot:
            constraints.extend(observed)
    return slot, constraints


def _archived_probe(row: Mapping[str, Any]) -> tuple[float, int | None]:
    alpha = float(row["alpha_transfer"])
    audit = row.get("alpha_path_audit")
    if not isinstance(audit, Mapping):
        raise ValueError(f"{row['evaluation_id']} lacks alpha_path_audit")
    trace = audit.get("alpha_trace")
    if not isinstance(trace, list):
        raise ValueError(f"{row['evaluation_id']} lacks alpha_trace")
    failures = []
    for item in trace:
        if not isinstance(item, Mapping) or item.get("feasible") is not False:
            continue
        candidate = float(item["alpha"])
        if candidate > alpha + TOL:
            failures.append(item)
    if not failures:
        raise ValueError(f"{row['evaluation_id']} has no failing alpha above alpha_transfer")
    probe = min(failures, key=lambda item: float(item["alpha"]))
    slot = probe.get("first_failure_slot")
    return float(probe["alpha"]), (None if slot is None else int(slot))


def _load_completed_results(summary_path: Path, predictions_path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    predictions = pd.read_csv(predictions_path)
    if len(predictions) != 288 or len(summary.get("evaluations", [])) != 288:
        raise ValueError("completed R2 results must contain 288 evaluations")
    return summary, predictions


def _target_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for raw in summary["evaluations"]:
        if (
            int(raw.get("duration_min", -1)) == 15
            and raw.get("active_offer") is True
            and raw.get("eligible_for_scientific_denominator") is True
            and raw.get("scientific_status") == "VALID"
            and raw.get("alpha_path_status") == "VALID"
            and isinstance(raw.get("alpha_transfer"), (int, float))
            and float(raw["alpha_transfer"]) < 1.0 - TOL
        ):
            rows.append(dict(raw))
    return rows


def diagnose(
    repo_root: Path,
    *,
    summary_path: Path,
    predictions_path: Path,
) -> dict[str, Any]:
    completed, predictions = _load_completed_results(summary_path, predictions_path)
    config, frame = load_replication_design(repo_root)
    units = {row["work_unit_id"]: row for row in _records(frame)}
    prediction_map = {
        str(row.evaluation_id): row._asdict()
        for row in predictions.itertuples(index=False)
    }
    targets = _target_rows(completed)
    if len(targets) != 56:
        raise ValueError(f"expected 56 limited primary rows, got {len(targets)}")

    output_rows: list[dict[str, Any]] = []
    for index, archived in enumerate(targets, start=1):
        evaluation_id = str(archived["evaluation_id"])
        work_unit_id = str(archived["work_unit_id"])
        if work_unit_id not in units:
            raise KeyError(f"missing work unit {work_unit_id}")
        unit = units[work_unit_id]
        print(f"[{index:02d}/{len(targets):02d}] {evaluation_id}", flush=True)

        runtime = _create_real_pilot_runtime(repo_root, unit, config)
        baseline = _validated_schedule(runtime.baseline, len(runtime.fleet), "runtime baseline")

        raw_by_duration: dict[int, dict[str, Any]] = {}
        for duration in config["durations_min"]:
            raw = runtime.generate_balanced_raw(int(duration), "balanced")
            raw_by_duration[int(duration)] = _normalize_raw_balanced_result(
                raw,
                int(duration),
                runtime.fleet,
                baseline,
                direction=str(unit["direction"]),
            )
        selected = select_nested_candidate(raw_by_duration, 15)
        schedule = _validated_schedule(
            selected["schedule"], len(runtime.fleet), "selected balanced schedule"
        )
        observed_hash = canonical_schedule_sha256(runtime.fleet, schedule)
        expected_hash = str(archived["schedule_sha256"])
        if observed_hash != expected_hash:
            raise AssertionError(
                f"schedule hash differs for {evaluation_id}: {observed_hash} != {expected_hash}"
            )

        alpha_transfer = float(archived["alpha_transfer"])
        probe_alpha, archived_failure_slot = _archived_probe(archived)
        candidate = baseline + probe_alpha * (schedule - baseline)
        truth_cache = runtime.create_corrected_truth_cache()
        raw_audit = runtime.audit_corrected(
            candidate,
            truth_cache,
            baseline_slot_results=None,
            stop_on_violation=True,
            retain_slot_results=True,
        )
        observed_failure_slot, constraints = _first_failure(raw_audit)
        physical = bool(
            raw_audit.get("failure_class") == "PHYSICAL_CONSTRAINT"
            and raw_audit.get("numerical_failure_checks", 0) == 0
            and raw_audit.get("nonconverged_checks", 0) == 0
            and constraints
        )
        boundary_reproduced = bool(
            raw_audit.get("feasible") is False
            and physical
            and observed_failure_slot == archived_failure_slot
        )

        pred_row = prediction_map[evaluation_id]
        phicte_factor = pd.to_numeric(pd.Series([pred_row.get("phicte_factor")]), errors="coerce").iloc[0]
        phicte_false_safe = bool(
            pd.notna(phicte_factor)
            and float(phicte_factor) > 0.0
            and alpha_transfer + TOL < 0.95 * float(phicte_factor)
        )
        classes = sorted({item["constraint_class"] for item in constraints})
        metrics = sorted({item["metric"] for item in constraints})
        call_slots = selected.get("call_slots")
        if call_slots is None:
            call_slots_list: list[int] = []
        else:
            call_slots_list = sorted({int(value) for value in call_slots})

        output_rows.append(
            {
                "evaluation_id": evaluation_id,
                "scenario_id": str(archived["scenario_id"]),
                "work_unit_id": work_unit_id,
                "feeder": str(archived["feeder"]),
                "call_time": str(archived["call_time"]),
                "direction": str(archived["direction"]),
                "alpha_transfer": alpha_transfer,
                "probe_alpha": probe_alpha,
                "archived_first_failure_slot": archived_failure_slot,
                "observed_first_failure_slot": observed_failure_slot,
                "call_slots": call_slots_list,
                "first_failure_in_call_slots": bool(
                    observed_failure_slot is not None and observed_failure_slot in call_slots_list
                ),
                "boundary_reproduced": boundary_reproduced,
                "numerical_failure_checks": int(raw_audit.get("numerical_failure_checks", 0)),
                "nonconverged_checks": int(raw_audit.get("nonconverged_checks", 0)),
                "constraint_classes": classes,
                "metrics": metrics,
                "constraints": constraints,
                "phicte_factor": None if pd.isna(phicte_factor) else float(phicte_factor),
                "phicte_material_false_safe": phicte_false_safe,
                "schedule_sha256": observed_hash,
            }
        )
        print(
            f"  slot={observed_failure_slot} classes={','.join(classes) or 'NONE'} "
            f"reproduced={boundary_reproduced}",
            flush=True,
        )

    if not all(row["boundary_reproduced"] for row in output_rows):
        failed = [row["evaluation_id"] for row in output_rows if not row["boundary_reproduced"]]
        raise AssertionError(f"boundary witness reproduction failed for {failed}")

    by_feeder: dict[str, Any] = {}
    for feeder in sorted({row["feeder"] for row in output_rows}):
        subset = [row for row in output_rows if row["feeder"] == feeder]
        case_counts: Counter[str] = Counter()
        for row in subset:
            for name in set(row["constraint_classes"]):
                case_counts[name] += 1
        by_feeder[feeder] = {
            "limited_case_n": len(subset),
            "first_failure_in_call_slots_n": sum(row["first_failure_in_call_slots"] for row in subset),
            "constraint_class_case_counts": dict(sorted(case_counts.items())),
            "multi_constraint_case_n": sum(len(row["constraint_classes"]) > 1 for row in subset),
        }

    false_safe_rows = [row for row in output_rows if row["phicte_material_false_safe"]]
    false_safe_summary = [
        {
            "evaluation_id": row["evaluation_id"],
            "feeder": row["feeder"],
            "call_time": row["call_time"],
            "direction": row["direction"],
            "alpha_transfer": row["alpha_transfer"],
            "phicte_factor": row["phicte_factor"],
            "first_failure_slot": row["observed_first_failure_slot"],
            "constraint_classes": row["constraint_classes"],
            "metrics": row["metrics"],
            "constraints": row["constraints"],
        }
        for row in false_safe_rows
    ]

    overall_counts: Counter[str] = Counter()
    for row in output_rows:
        for name in set(row["constraint_classes"]):
            overall_counts[name] += 1

    return {
        "analysis": "V2.5B-R2 boundary-witness diagnostic",
        "role": "post-hoc mechanism diagnostic; no method or threshold tuning",
        "source_result_generated_at_utc": completed.get("generated_at_utc"),
        "target_definition": (
            "all scientifically eligible active 15-minute R2 evaluations with alpha_transfer < 1"
        ),
        "probe_definition": (
            "the smallest archived failing alpha strictly above each archived alpha_transfer; "
            "the exact archived balanced schedule is regenerated and verified by SHA-256"
        ),
        "target_n": len(output_rows),
        "boundary_reproduced_n": sum(row["boundary_reproduced"] for row in output_rows),
        "first_failure_in_call_slots_n": sum(row["first_failure_in_call_slots"] for row in output_rows),
        "constraint_class_case_counts": dict(sorted(overall_counts.items())),
        "multi_constraint_case_n": sum(len(row["constraint_classes"]) > 1 for row in output_rows),
        "by_feeder": by_feeder,
        "phicte_material_false_safe_boundary_witnesses": false_safe_summary,
        "rows": output_rows,
        "interpretation_boundary": [
            "A first-failure witness identifies which formal constraint(s) are violated at the archived boundary probe; it does not establish a universal causal mechanism beyond the audited case.",
            "Cases with multiple simultaneous first-slot violations are retained as co-binding witness sets; no arbitrary single dominant constraint is assigned.",
            "Line thermal constraints remain outside the formal audited constraint set.",
        ],
    }


def _write_markdown(result: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# V2.5B-R2 boundary-witness diagnostic",
        "",
        f"- Target limited primary cases: **{result['target_n']}**",
        f"- Boundary probes reproduced: **{result['boundary_reproduced_n']}/{result['target_n']}**",
        f"- First failure inside declared call slot(s): **{result['first_failure_in_call_slots_n']}/{result['target_n']}**",
        f"- Multi-constraint first-boundary cases: **{result['multi_constraint_case_n']}**",
        "",
        "## First-boundary constraint classes",
        "",
    ]
    for name, count in result["constraint_class_case_counts"].items():
        lines.append(f"- `{name}`: {count} cases")
    lines.extend(["", "## By feeder", ""])
    for feeder, block in result["by_feeder"].items():
        lines.append(f"### {feeder}")
        lines.append(f"- Limited cases: {block['limited_case_n']}")
        lines.append(
            f"- First failure in call slot(s): {block['first_failure_in_call_slots_n']}"
        )
        lines.append(f"- Multi-constraint cases: {block['multi_constraint_case_n']}")
        for name, count in block["constraint_class_case_counts"].items():
            lines.append(f"- `{name}`: {count}")
        lines.append("")
    lines.extend(["## PHiCTE material false-safe witnesses", ""])
    for item in result["phicte_material_false_safe_boundary_witnesses"]:
        lines.append(
            f"- `{item['evaluation_id']}`: alpha={item['alpha_transfer']:.3f}, "
            f"PHiCTE={item['phicte_factor']:.3f}, slot={item['first_failure_slot']}, "
            f"classes={', '.join(item['constraint_classes'])}"
        )
        for constraint in item["constraints"]:
            lines.append(
                f"  - `{constraint['metric']}`: value={constraint['value']:.8g}, "
                f"limit={constraint['limit']:.8g}, direction={constraint['direction']}"
            )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            *[f"- {text}" for text in result["interpretation_boundary"]],
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--json-output", default="reports/v2_5b_boundary_witness.json")
    parser.add_argument("--csv-output", default="reports/v2_5b_boundary_witness.csv")
    parser.add_argument("--md-output", default="reports/v2_5b_boundary_witness.md")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve(strict=True)
    result = diagnose(
        root,
        summary_path=Path(args.summary).resolve(strict=True),
        predictions_path=Path(args.predictions).resolve(strict=True),
    )
    json_path = root / args.json_output
    csv_path = root / args.csv_output
    md_path = root / args.md_output
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    flat_rows = []
    for row in result["rows"]:
        flat = dict(row)
        for name in ("call_slots", "constraint_classes", "metrics", "constraints"):
            flat[name] = json.dumps(flat[name], separators=(",", ":"), sort_keys=True)
        flat_rows.append(flat)
    pd.DataFrame(flat_rows).to_csv(csv_path, index=False)
    _write_markdown(result, md_path)
    print(json.dumps({
        "status": "PASS",
        "target_n": result["target_n"],
        "boundary_reproduced_n": result["boundary_reproduced_n"],
        "json": str(json_path.relative_to(root)),
        "csv": str(csv_path.relative_to(root)),
        "markdown": str(md_path.relative_to(root)),
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
