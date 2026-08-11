from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence


ANALYSIS_VERSION = (
    "EV-FLEX-BIAS-V2.3B-RETROSPECTIVE-DERATING-BASELINE-COMPARISON"
)
MAXIMUM_MATERIAL_FALSE_SAFE_RATE = 0.05
MATERIAL_DELIVERABILITY_RATIO = 0.95
NUMERIC_TOLERANCE = 1e-12

POLICY_SPECS: dict[str, tuple[str, ...] | None] = {
    "raw_balanced_offer": None,
    "global_derating": (),
    "feeder_only": ("feeder",),
    "direction_only": ("direction",),
    "local_feeder_direction_duration": (
        "feeder",
        "direction",
        "duration_min",
    ),
}


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def is_material_false_safe(
    alpha_transfer: float,
    prescribed_factor: float,
) -> bool:
    """Return whether at least 5% of the prescription is not transferable."""

    return (
        float(alpha_transfer) + NUMERIC_TOLERANCE
        < MATERIAL_DELIVERABILITY_RATIO * float(prescribed_factor)
    )


def fit_maximum_retention_factor(
    alpha_values: Sequence[float],
    *,
    maximum_risk: float = MAXIMUM_MATERIAL_FALSE_SAFE_RATE,
) -> float:
    """Fit the largest factor satisfying the empirical material-risk limit."""

    if not alpha_values:
        raise ValueError("at least one alpha value is required")
    if not _finite_number(maximum_risk) or not 0.0 <= maximum_risk < 1.0:
        raise ValueError("maximum_risk must be finite and in [0, 1)")
    alphas = sorted(float(value) for value in alpha_values)
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in alphas):
        raise ValueError("alpha values must be finite and in [0, 1]")

    permitted_failures = math.floor(maximum_risk * len(alphas) + NUMERIC_TOLERANCE)
    boundary_alpha = alphas[permitted_failures]
    return min(1.0, boundary_alpha / MATERIAL_DELIVERABILITY_RATIO)


def validate_evaluation_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_name: str,
) -> None:
    """Validate the grain and active/inactive semantics used by this analysis."""

    seen: set[str] = set()
    for index, row in enumerate(rows):
        evaluation_id = row.get("evaluation_id")
        if not isinstance(evaluation_id, str) or not evaluation_id:
            raise ValueError(f"{dataset_name} row {index} has invalid evaluation_id")
        if evaluation_id in seen:
            raise ValueError(f"{dataset_name} has duplicate evaluation_id")
        seen.add(evaluation_id)

        for field in ("feeder", "direction"):
            if not isinstance(row.get(field), str) or not row.get(field):
                raise ValueError(f"{dataset_name} {evaluation_id} has invalid {field}")
        duration = row.get("duration_min")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise ValueError(f"{dataset_name} {evaluation_id} has invalid duration")
        if not _finite_number(row.get("f_bal_kw")):
            raise ValueError(f"{dataset_name} {evaluation_id} has invalid f_bal_kw")

        active = row.get("active_offer")
        if not isinstance(active, bool):
            raise ValueError(f"{dataset_name} {evaluation_id} has invalid active_offer")
        alpha = row.get("alpha_transfer")
        if active:
            if not _finite_number(alpha) or not 0.0 <= float(alpha) <= 1.0:
                raise ValueError(f"{dataset_name} active offer has invalid alpha_transfer")
            if row.get("eligible_for_scientific_denominator") is not True:
                raise ValueError(f"{dataset_name} active offer is not eligible")
            if row.get("status") != "SUCCESS" or row.get("scientific_status") != "VALID":
                raise ValueError(f"{dataset_name} active offer is not scientifically valid")
            if row.get("alpha_path_status") != "VALID":
                raise ValueError(f"{dataset_name} active offer has invalid alpha path")
        else:
            if alpha is not None:
                raise ValueError(f"{dataset_name} inactive offer has alpha_transfer")
            if row.get("eligible_for_scientific_denominator") is not False:
                raise ValueError(f"{dataset_name} inactive offer is eligible")
            if row.get("status") != "INACTIVE_OFFER":
                raise ValueError(f"{dataset_name} inactive offer has invalid status")


def _group_key(row: Mapping[str, Any], fields: Sequence[str]) -> tuple[Any, ...]:
    return tuple(row[field] for field in fields)


def fit_policy(
    development_rows: Sequence[Mapping[str, Any]],
    *,
    grouping_fields: tuple[str, ...],
    maximum_risk: float = MAXIMUM_MATERIAL_FALSE_SAFE_RATE,
) -> dict[str, Any]:
    """Fit group factors from development outcomes only."""

    validate_evaluation_rows(development_rows, dataset_name="development")
    grouped: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in development_rows:
        if bool(row["active_offer"]):
            grouped[_group_key(row, grouping_fields)].append(
                float(row["alpha_transfer"])
            )
    if not grouped:
        raise ValueError("development has no active offers")

    factors = {
        key: fit_maximum_retention_factor(values, maximum_risk=maximum_risk)
        for key, values in sorted(grouped.items(), key=lambda item: repr(item[0]))
    }
    return {
        "grouping_fields": grouping_fields,
        "maximum_development_material_false_safe_rate": maximum_risk,
        "factors": factors,
        "development_group_n": {key: len(values) for key, values in grouped.items()},
    }


def apply_fitted_policy(
    row: Mapping[str, Any],
    fitted_policy: Mapping[str, Any],
) -> tuple[float, bool]:
    """Apply a development-fitted policy; unseen groups conservatively abstain."""

    fields = fitted_policy.get("grouping_fields")
    if fields is None:
        return float(fitted_policy.get("fixed_factor", 1.0)), True
    key = _group_key(row, tuple(fields))
    factors = fitted_policy.get("factors", {})
    if key not in factors:
        return 0.0, False
    return float(factors[key]), True


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    """Two-sided 95% Wilson score interval for a binomial proportion."""

    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("Wilson interval requires 0 <= successes <= total")
    z = 1.959963984540054
    proportion = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = (proportion + z2 / (2.0 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z2 / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, centre - radius), min(1.0, centre + radius)


def evaluate_policy(
    rows: Sequence[Mapping[str, Any]],
    fitted_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate retention and risk while keeping inactive offers in coverage."""

    validate_evaluation_rows(rows, dataset_name="evaluation")
    active_rows = [row for row in rows if bool(row["active_offer"])]
    decisions: list[tuple[Mapping[str, Any], float, bool]] = []
    for row in active_rows:
        factor, matched = apply_fitted_policy(row, fitted_policy)
        if not math.isfinite(factor) or not 0.0 <= factor <= 1.0:
            raise ValueError("fitted policy returned a factor outside [0, 1]")
        decisions.append((row, factor, matched))

    prescribed = [item for item in decisions if item[1] > 0.0 and item[2]]
    material_n = sum(
        is_material_false_safe(float(row["alpha_transfer"]), factor)
        for row, factor, _ in prescribed
    )
    exceeds_n = sum(
        factor > float(row["alpha_transfer"]) + NUMERIC_TOLERANCE
        for row, factor, _ in prescribed
    )
    total_offer_kw = sum(abs(float(row["f_bal_kw"])) for row in active_rows)
    retained_offer_kw = sum(
        factor * abs(float(row["f_bal_kw"])) for row, factor, _ in decisions
    )
    active_n = len(active_rows)
    prescribed_n = len(prescribed)
    if prescribed_n:
        false_safe_rate = material_n / prescribed_n
        exceeds_rate = exceeds_n / prescribed_n
        wilson_low, wilson_high = wilson_interval(material_n, prescribed_n)
    else:
        false_safe_rate = None
        exceeds_rate = None
        wilson_low = None
        wilson_high = None

    return {
        "planned_n": len(rows),
        "active_n": active_n,
        "inactive_n": len(rows) - active_n,
        "offer_coverage": active_n / len(rows) if rows else None,
        "prescribed_n": prescribed_n,
        "decision_coverage": prescribed_n / active_n if active_n else None,
        "mean_retained_fraction": (
            sum(factor for _, factor, _ in decisions) / active_n if active_n else None
        ),
        "kw_weighted_retained_fraction": (
            retained_offer_kw / total_offer_kw if total_offer_kw > 0.0 else None
        ),
        "material_false_safe_n": material_n,
        "material_false_safe_rate": false_safe_rate,
        "material_false_safe_wilson95_low": wilson_low,
        "material_false_safe_wilson95_high": wilson_high,
        "exceeds_verified_bound_n": exceeds_n,
        "exceeds_verified_bound_rate": exceeds_rate,
    }


def assess_local_policy_value(
    local_metrics: Mapping[str, Any],
    simple_metrics: Mapping[str, Mapping[str, Any]],
    *,
    maximum_risk: float = MAXIMUM_MATERIAL_FALSE_SAFE_RATE,
) -> dict[str, Any]:
    """Apply a no-margin risk/Pareto gate to the local policy."""

    local_risk = local_metrics.get("material_false_safe_rate")
    local_retention = local_metrics.get("kw_weighted_retained_fraction")
    if not _finite_number(local_risk) or not _finite_number(local_retention):
        return {"status": "NOT_EVALUABLE", "dominated_by": []}
    if float(local_risk) > maximum_risk + NUMERIC_TOLERANCE:
        return {"status": "FAILS_EMPIRICAL_RISK_TARGET", "dominated_by": []}

    dominated_by: list[str] = []
    for name, metrics in simple_metrics.items():
        risk = metrics.get("material_false_safe_rate")
        retention = metrics.get("kw_weighted_retained_fraction")
        if not _finite_number(risk) or not _finite_number(retention):
            continue
        no_more_risky = float(risk) <= float(local_risk) + NUMERIC_TOLERANCE
        no_less_retention = (
            float(retention) + NUMERIC_TOLERANCE >= float(local_retention)
        )
        strictly_better = (
            float(risk) < float(local_risk) - NUMERIC_TOLERANCE
            or float(retention) > float(local_retention) + NUMERIC_TOLERANCE
        )
        if no_more_risky and no_less_retention and strictly_better:
            dominated_by.append(name)

    return {
        "status": (
            "DOMINATED_BY_SIMPLE_BASELINE"
            if dominated_by
            else "NONDOMINATED_EXPLORATORY"
        ),
        "dominated_by": sorted(dominated_by),
    }


def _serialize_fitted_policy(
    fitted_policy: Mapping[str, Any],
) -> dict[str, Any]:
    fields = fitted_policy.get("grouping_fields")
    if fields is None:
        return {
            "grouping_fields": None,
            "development_outcomes_used": False,
            "groups": [
                {
                    "group": {},
                    "factor": float(fitted_policy.get("fixed_factor", 1.0)),
                    "development_n": None,
                }
            ],
        }
    field_names = tuple(fields)
    factors = fitted_policy["factors"]
    group_sizes = fitted_policy["development_group_n"]
    groups = []
    for key in sorted(factors, key=repr):
        groups.append(
            {
                "group": dict(zip(field_names, key, strict=True)),
                "factor": float(factors[key]),
                "development_n": int(group_sizes[key]),
            }
        )
    return {
        "grouping_fields": list(field_names),
        "development_outcomes_used": True,
        "groups": groups,
    }


def _add_risk_checks(metrics: dict[str, Any]) -> dict[str, Any]:
    rate = metrics["material_false_safe_rate"]
    upper = metrics["material_false_safe_wilson95_high"]
    metrics["empirical_material_risk_target_met"] = (
        rate is not None
        and float(rate)
        <= MAXIMUM_MATERIAL_FALSE_SAFE_RATE + NUMERIC_TOLERANCE
    )
    metrics["wilson95_upper_risk_target_met"] = (
        upper is not None
        and float(upper)
        <= MAXIMUM_MATERIAL_FALSE_SAFE_RATE + NUMERIC_TOLERANCE
    )
    return metrics


def _identity_intersection_count(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    field: str,
) -> int | None:
    if not all(field in row and row[field] is not None for row in [*left, *right]):
        return None
    return len({row[field] for row in left} & {row[field] for row in right})


def build_baseline_comparison(
    development_rows: Sequence[Mapping[str, Any]],
    external_rows: Sequence[Mapping[str, Any]],
    *,
    code_commit: str,
    generated_at_utc: str,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the locked, retrospective five-policy go/no-go comparison."""

    validate_evaluation_rows(development_rows, dataset_name="development")
    validate_evaluation_rows(external_rows, dataset_name="external")
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise ValueError("code_commit must be a 40-character Git commit")

    fitted: dict[str, dict[str, Any]] = {
        "raw_balanced_offer": {
            "grouping_fields": None,
            "fixed_factor": 1.0,
        }
    }
    for policy_name, grouping_fields in POLICY_SPECS.items():
        if policy_name == "raw_balanced_offer":
            continue
        assert grouping_fields is not None
        fitted[policy_name] = fit_policy(
            development_rows,
            grouping_fields=grouping_fields,
            maximum_risk=MAXIMUM_MATERIAL_FALSE_SAFE_RATE,
        )

    development_metrics = {
        name: _add_risk_checks(evaluate_policy(development_rows, policy))
        for name, policy in fitted.items()
    }
    scope_rows = {
        "primary_15min": [
            row for row in external_rows if int(row["duration_min"]) == 15
        ],
        "descriptive_all_durations": list(external_rows),
    }
    external_scopes: dict[str, Any] = {}
    local_statuses: list[str] = []
    for scope_name, rows in scope_rows.items():
        policies = {
            name: _add_risk_checks(evaluate_policy(rows, policy))
            for name, policy in fitted.items()
        }
        local_value = assess_local_policy_value(
            policies["local_feeder_direction_duration"],
            {
                name: policies[name]
                for name in ("global_derating", "feeder_only", "direction_only")
            },
            maximum_risk=MAXIMUM_MATERIAL_FALSE_SAFE_RATE,
        )
        local_statuses.append(str(local_value["status"]))
        active_n = sum(bool(row["active_offer"]) for row in rows)
        external_scopes[scope_name] = {
            "planned_n": len(rows),
            "active_n": active_n,
            "inactive_n": len(rows) - active_n,
            "policies": policies,
            "local_policy_value": local_value,
        }

    stop_statuses = {
        "FAILS_EMPIRICAL_RISK_TARGET",
        "DOMINATED_BY_SIMPLE_BASELINE",
        "NOT_EVALUABLE",
    }
    if any(status in stop_statuses for status in local_statuses):
        decision_status = "STOP_LOCAL_COMPLEXITY_CLAIM"
    else:
        decision_status = "LOCAL_RULE_REMAINS_EXPLORATORY"

    development_active = sum(bool(row["active_offer"]) for row in development_rows)
    external_active = sum(bool(row["active_offer"]) for row in external_rows)
    return {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_role": "retrospective_exploratory_go_no_go",
        "generated_at_utc": generated_at_utc,
        "blind_holdout_claim": False,
        "fitting_rule": {
            "source": "V2.2 development active offers only",
            "selection": (
                "largest factor with empirical material false-safe rate <= 5% "
                "within each declared development group"
            ),
            "external_outcomes_used_for_fitting": False,
            "unseen_external_group_policy": "abstain_with_factor_zero",
        },
        "risk_definitions": {
            "material_false_safe": "alpha_transfer < 0.95 * prescribed_factor",
            "exceeds_verified_bound": "prescribed_factor > alpha_transfer",
            "maximum_development_material_false_safe_rate": (
                MAXIMUM_MATERIAL_FALSE_SAFE_RATE
            ),
            "retention": (
                "prescribed factor averaged both equally and by absolute "
                "balanced-offer kW over active offers; abstention contributes zero"
            ),
        },
        "data_quality": {
            "development": {
                "planned_n": len(development_rows),
                "active_n": development_active,
                "inactive_n": len(development_rows) - development_active,
                "unique_evaluation_id_n": len(
                    {row["evaluation_id"] for row in development_rows}
                ),
            },
            "external": {
                "planned_n": len(external_rows),
                "active_n": external_active,
                "inactive_n": len(external_rows) - external_active,
                "unique_evaluation_id_n": len(
                    {row["evaluation_id"] for row in external_rows}
                ),
            },
            "cross_cohort_identity_intersections": {
                field: _identity_intersection_count(
                    development_rows, external_rows, field
                )
                for field in (
                    "evaluation_id",
                    "work_unit_id",
                    "scenario_id",
                    "vehicle_identity_sha256",
                )
            },
        },
        "fitted_policies": {
            name: _serialize_fitted_policy(policy) for name, policy in fitted.items()
        },
        "development_resubstitution": development_metrics,
        "external_scopes": external_scopes,
        "decision": {
            "status": decision_status,
            "basis": (
                "local policy must meet the empirical 5% material-risk target and "
                "must not be Pareto-dominated by global, feeder-only, or "
                "direction-only baselines in either reported external scope"
            ),
            "confirmatory_claim_supported": False,
            "paper_claim_implication": (
                "This retrospective comparison can stop an unsupported local-rule "
                "claim, but cannot establish a deployable 5% risk guarantee."
            ),
        },
        "limitations": [
            "The external cohort had already been opened and is not a blind holdout.",
            "Scenario identities are disjoint, but household-disjoint independence is not established.",
            "The 15-minute primary scope has one inactive offer and incomplete planned coverage.",
            "The 30- and 60-minute results remain descriptive under the V2.3A amendment.",
            "Line thermal constraints are outside the audited constraint set.",
        ],
        "provenance": {"code_commit": code_commit, **dict(provenance)},
    }


_CSV_FIELDS = (
    "scope",
    "policy",
    "planned_n",
    "active_n",
    "inactive_n",
    "offer_coverage",
    "prescribed_n",
    "decision_coverage",
    "mean_retained_fraction",
    "kw_weighted_retained_fraction",
    "material_false_safe_n",
    "material_false_safe_rate",
    "material_false_safe_wilson95_low",
    "material_false_safe_wilson95_high",
    "empirical_material_risk_target_met",
    "wilson95_upper_risk_target_met",
    "exceeds_verified_bound_n",
    "exceeds_verified_bound_rate",
    "local_policy_value_status",
    "local_policy_dominated_by",
)


def write_results(summary: Mapping[str, Any], output_directory: str | Path) -> list[Path]:
    """Write only the compact machine-readable JSON and CSV artifacts."""

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "summary.json"
    csv_path = output / "summary.csv"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for scope_name, scope in summary["external_scopes"].items():
            local_value = scope["local_policy_value"]
            for policy_name, metrics in scope["policies"].items():
                record = {
                    "scope": scope_name,
                    "policy": policy_name,
                    **metrics,
                    "local_policy_value_status": (
                        local_value["status"]
                        if policy_name == "local_feeder_direction_duration"
                        else ""
                    ),
                    "local_policy_dominated_by": (
                        "|".join(local_value["dominated_by"])
                        if policy_name == "local_feeder_direction_duration"
                        else ""
                    ),
                }
                writer.writerow({field: record.get(field) for field in _CSV_FIELDS})
    return [json_path, csv_path]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _development_collection_sha256(paths: Sequence[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_project_evaluations(
    repo_root: str | Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Load the completed V2.2 development and V2.3A external evaluations."""

    root = Path(repo_root).resolve(strict=True)
    development_directory = root / "results/transferability_dev_v2_2/work_units"
    development_paths = sorted(development_directory.glob("*.json"))
    if len(development_paths) != 32:
        raise ValueError("expected exactly 32 completed V2.2 development work units")
    development_rows: list[dict[str, Any]] = []
    for path in development_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        evaluations = payload.get("evaluations")
        if not isinstance(evaluations, list):
            raise ValueError(f"development work unit lacks evaluations: {path.name}")
        development_rows.extend(evaluations)

    external_path = root / "results/transferability_external_validation_v2_3/summary.json"
    external_payload = json.loads(external_path.read_text(encoding="utf-8"))
    external_rows = external_payload.get("evaluations")
    if not isinstance(external_rows, list):
        raise ValueError("V2.3A external summary lacks evaluations")

    provenance = {
        "development_work_unit_count": len(development_paths),
        "development_collection_sha256": _development_collection_sha256(
            development_paths, root
        ),
        "external_summary_relative_path": external_path.relative_to(root).as_posix(),
        "external_summary_sha256": _sha256(external_path),
    }
    return development_rows, list(external_rows), provenance


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the retrospective five-policy transferability comparison."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--output-directory",
        default="results/transferability_baseline_comparison_v2_3",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve(strict=True)
    development, external, provenance = load_project_evaluations(root)
    summary = build_baseline_comparison(
        development,
        external,
        code_commit=_git_commit(root),
        generated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance=provenance,
    )
    paths = write_results(summary, root / args.output_directory)
    print(
        json.dumps(
            {
                "status": summary["decision"]["status"],
                "outputs": [path.relative_to(root).as_posix() for path in paths],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
