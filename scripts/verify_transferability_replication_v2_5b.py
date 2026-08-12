from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

PROTOCOL_VERSION = "EV-FLEX-BIAS-V2.5B-R1-PHICTE-EXPANDED-RETROSPECTIVE-REPLICATION"
MATERIAL_RATIO = 0.95
TOL = 1e-12
FACTOR_COLUMNS = {
    "phicte": "phicte_factor",
    "raw_balanced_offer": "raw_balanced_offer_factor",
    "global_derating": "global_derating_factor",
    "feeder_only": "feeder_only_factor",
    "direction_only": "direction_only_factor",
    "local_feeder_direction_duration": "local_feeder_direction_duration_factor",
}


def _close(left: Any, right: Any, *, tol: float = 1e-10) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=tol, abs_tol=tol)


def _metrics(frame: pd.DataFrame, factor_column: str) -> dict[str, Any]:
    active = frame[frame["active_offer"]].copy()
    factors = pd.to_numeric(active[factor_column], errors="coerce")
    if factors.isna().any():
        raise ValueError(f"active rows contain missing {factor_column}")
    if ((factors < -TOL) | (factors > 1.0 + TOL)).any():
        raise ValueError(f"{factor_column} lies outside [0,1]")
    alpha = pd.to_numeric(active["alpha_transfer"], errors="coerce")
    if alpha.isna().any():
        raise ValueError("active rows contain missing alpha_transfer")
    prescribed = factors > 0.0
    material = (alpha + TOL < MATERIAL_RATIO * factors) & prescribed
    strict = (factors > alpha + TOL) & prescribed
    total_offer = active["f_bal_kw"].abs().sum()
    pooled = (active["f_bal_kw"].abs() * factors).sum() / total_offer
    equal = factors.mean()
    feeder_retention = []
    for _, group in active.assign(_factor=factors).groupby("feeder"):
        denom = group["f_bal_kw"].abs().sum()
        feeder_retention.append((group["f_bal_kw"].abs() * group["_factor"]).sum() / denom)
    return {
        "planned_n": int(len(frame)),
        "active_n": int(len(active)),
        "inactive_n": int(len(frame) - len(active)),
        "risk_denominator_n": int(prescribed.sum()),
        "prescribed_n": int(prescribed.sum()),
        "abstention_n": int(len(active) - prescribed.sum()),
        "material_false_safe_n": int(material.sum()),
        "material_false_safe_rate": float(material.sum() / prescribed.sum()) if prescribed.sum() else None,
        "exceeds_verified_bound_n": int(strict.sum()),
        "exceeds_verified_bound_rate": float(strict.sum() / prescribed.sum()) if prescribed.sum() else None,
        "equal_case_retention": float(equal) if len(active) else None,
        "feeder_macro_kw_retention": float(sum(feeder_retention) / len(feeder_retention)) if feeder_retention else None,
        "pooled_kw_retention_sensitivity": float(pooled) if total_offer > 0 else None,
    }


def _assert_metric_block(observed: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    exact = (
        "planned_n", "active_n", "inactive_n", "risk_denominator_n", "prescribed_n",
        "abstention_n", "material_false_safe_n", "exceeds_verified_bound_n",
    )
    numeric = (
        "material_false_safe_rate", "exceeds_verified_bound_rate", "equal_case_retention",
        "feeder_macro_kw_retention", "pooled_kw_retention_sensitivity",
    )
    for name in exact:
        if int(expected[name]) != int(observed[name]):
            raise AssertionError(f"{label}.{name}: {observed[name]} != {expected[name]}")
    for name in numeric:
        if not _close(expected.get(name), observed.get(name)):
            raise AssertionError(f"{label}.{name}: {observed.get(name)} != {expected.get(name)}")


def verify(repo_root: Path) -> dict[str, Any]:
    summary_path = repo_root / "results/transferability_replication_v2_5b/summary.json"
    predictions_path = repo_root / "results/transferability_replication_v2_5b/predictions.csv"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    frame = pd.read_csv(predictions_path)
    if summary.get("analysis_version") != PROTOCOL_VERSION:
        raise AssertionError("protocol version differs")
    if summary.get("blind_holdout_claim") is not False or summary.get("confirmatory_claim") is not False:
        raise AssertionError("retrospective claim boundary changed")
    if len(frame) != 288 or frame["evaluation_id"].nunique() != 288:
        raise AssertionError("predictions must contain 288 unique evaluations")
    if frame["scenario_id"].nunique() != 48:
        raise AssertionError("predictions must contain 48 scenarios")
    frame["active_offer"] = frame["active_offer"].astype(str).str.lower().map({"true": True, "false": False})
    if frame["active_offer"].isna().any():
        raise AssertionError("active_offer encoding is invalid")
    primary = frame[frame["duration_min"] == 15].copy()
    if len(primary) != 96:
        raise AssertionError("primary 15-minute scope must contain 96 rows")

    recomputed: dict[str, dict[str, Any]] = {}
    for policy, column in FACTOR_COLUMNS.items():
        recomputed[policy] = _metrics(primary, column)
        _assert_metric_block(
            recomputed[policy],
            summary["primary_15min"]["policies"][policy],
            f"primary.{policy}",
        )

    by_feeder: dict[str, Any] = {}
    for feeder in ("ieee13", "lv906"):
        subset = primary[primary["feeder"] == feeder].copy()
        if len(subset) != 48:
            raise AssertionError(f"{feeder} primary scope must contain 48 planned rows")
        by_feeder[feeder] = {}
        for policy, column in FACTOR_COLUMNS.items():
            metrics = _metrics(subset, column)
            by_feeder[feeder][policy] = metrics
            _assert_metric_block(
                metrics,
                summary["primary_15min"]["by_feeder"][feeder]["policies"][policy],
                f"{feeder}.{policy}",
            )

    raw_evaluations = summary.get("evaluations")
    if not isinstance(raw_evaluations, list) or len(raw_evaluations) != 288:
        raise AssertionError("summary must retain 288 raw evaluations")
    numerical_failures = 0
    for row in raw_evaluations:
        if int(row.get("duration_min", -1)) != 15 or row.get("active_offer") is not True:
            continue
        audit = row.get("alpha_path_audit")
        if not isinstance(audit, dict):
            raise AssertionError("active primary raw evaluation lacks alpha_path_audit")
        numerical_failures += int(audit.get("numerical_failure_audits", 0))
    if numerical_failures != int(summary["primary_15min"]["numerical_failure_audits"]):
        raise AssertionError("numerical-failure audit count differs")

    ph = recomputed["phicte"]
    rules = {
        "minimum_active_primary_n": ph["active_n"] >= 73,
        "minimum_primary_risk_denominator_n": ph["risk_denominator_n"] >= 73,
        "minimum_primary_risk_denominator_n_each_feeder": all(
            by_feeder[f]["phicte"]["risk_denominator_n"] >= 24 for f in by_feeder
        ),
        "phicte_empirical_material_risk": (
            ph["material_false_safe_rate"] is not None and ph["material_false_safe_rate"] <= 0.05 + TOL
        ),
        "phicte_empirical_material_risk_each_feeder": all(
            by_feeder[f]["phicte"]["material_false_safe_rate"] is not None
            and by_feeder[f]["phicte"]["material_false_safe_rate"] <= 0.05 + TOL
            for f in by_feeder
        ),
        "zero_phicte_strict_bound_exceedance": ph["exceeds_verified_bound_n"] == 0,
        "zero_phicte_strict_bound_exceedance_each_feeder": all(
            by_feeder[f]["phicte"]["exceeds_verified_bound_n"] == 0 for f in by_feeder
        ),
        "no_numerical_failure_audits": numerical_failures == 0,
    }
    reported = summary["decision"]["criteria"]
    for name, value in rules.items():
        if bool(reported.get(name)) is not bool(value):
            raise AssertionError(f"decision criterion {name} differs")

    # Independently verify the declared retention deltas and Pareto status.
    pareto_status: dict[str, str] = {}
    retention_deltas: dict[str, dict[str, float]] = {}
    for feeder in by_feeder:
        p = by_feeder[feeder]["phicte"]
        expected_deltas = {
            policy: p["pooled_kw_retention_sensitivity"] - metrics["pooled_kw_retention_sensitivity"]
            for policy, metrics in by_feeder[feeder].items() if policy != "phicte"
        }
        reported_deltas = summary["primary_15min"]["by_feeder"][feeder]["phicte_kw_retention_delta_vs"]
        for policy, value in expected_deltas.items():
            if not _close(value, reported_deltas[policy]):
                raise AssertionError(f"{feeder} retention delta vs {policy} differs")
        dominated_by = []
        for policy, candidate in by_feeder[feeder].items():
            if policy == "phicte":
                continue
            no_more_risky = candidate["material_false_safe_rate"] <= p["material_false_safe_rate"] + TOL
            no_less_retention = candidate["pooled_kw_retention_sensitivity"] >= p["pooled_kw_retention_sensitivity"] - TOL
            strictly_better = (
                candidate["material_false_safe_rate"] < p["material_false_safe_rate"] - TOL
                or candidate["pooled_kw_retention_sensitivity"] > p["pooled_kw_retention_sensitivity"] + TOL
            )
            if no_more_risky and no_less_retention and strictly_better:
                dominated_by.append(policy)
        status = "NONDOMINATED" if not dominated_by else "DOMINATED"
        reported_pareto = summary["primary_15min"]["by_feeder"][feeder]["phicte_pareto"]
        if reported_pareto["status"] != status or sorted(reported_pareto["dominated_by"]) != sorted(dominated_by):
            raise AssertionError(f"{feeder} Pareto status differs")
        pareto_status[feeder] = status
        retention_deltas[feeder] = expected_deltas

    decision_rules = {
        "phicte_pareto_nondominated_each_feeder": all(
            pareto_status[feeder] == "NONDOMINATED" for feeder in by_feeder
        ),
        "positive_kw_delta_vs_global_each_feeder": all(
            retention_deltas[feeder]["global_derating"] > TOL for feeder in by_feeder
        ),
        "positive_kw_delta_vs_direction_only_each_feeder": all(
            retention_deltas[feeder]["direction_only"] > TOL for feeder in by_feeder
        ),
        "positive_lv906_kw_delta_vs_feeder_only": (
            retention_deltas["lv906"]["feeder_only"] > TOL
        ),
    }
    rules.update(decision_rules)
    for name, value in decision_rules.items():
        if bool(reported.get(name)) is not bool(value):
            raise AssertionError(f"decision criterion {name} differs")

    evidence_sufficient = all(rules.values())
    if bool(summary["decision"].get("evidence_sufficient_for_conference_draft_with_limitations")) is not evidence_sufficient:
        raise AssertionError("overall manuscript-readiness decision differs")
    expected_status = (
        "EVIDENCE_SUFFICIENT_FOR_CONFERENCE_DRAFT_WITH_LIMITATIONS"
        if evidence_sufficient
        else "EXPERIMENT_REVIEW_REQUIRED_BEFORE_PAPER_DRAFT"
    )
    if summary["decision"].get("status") != expected_status:
        raise AssertionError("overall decision status differs")

    return {
        "status": "PASS",
        "analysis_version": PROTOCOL_VERSION,
        "predictions_rows": len(frame),
        "primary_rows": len(primary),
        "primary_active_n": ph["active_n"],
        "primary_risk_denominator_n": ph["risk_denominator_n"],
        "primary_material_false_safe_n": ph["material_false_safe_n"],
        "primary_strict_bound_exceedance_n": ph["exceeds_verified_bound_n"],
        "primary_numerical_failure_audits": numerical_failures,
        "verified_core_decision_criteria": rules,
        "note": "Core counts, risk, retention, feeder deltas, Pareto status, and numerical-failure counts were independently recomputed from archived predictions/raw evaluations.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--output",
        default="reports/v2_5b_independent_verification.json",
    )
    args = parser.parse_args()
    root = Path(args.repo_root).resolve(strict=True)
    result = verify(root)
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
