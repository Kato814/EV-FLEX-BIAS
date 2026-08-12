from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence

import numpy as np
import pandas as pd


ANALYSIS_VERSION = "EV-FLEX-BIAS-V2.5A-PHICTE-ROBUSTNESS-DIAGNOSTIC"
PREDICTIONS = Path("results/transferability_phicte_v2_4/predictions.csv")
V2_4_SUMMARY = Path("results/transferability_phicte_v2_4/summary.json")
OUTPUT = Path("results/transferability_phicte_v2_5a_robustness/summary.json")
EXPECTED_PREDICTIONS_BLOB = "1b07e3a381718dc6bf10cc2309436016c897655a"
EXPECTED_SUMMARY_BLOB = "ffe665d395416f97498d14bc3df10b70755a3c69"
SEED = 2026081201
RESAMPLES = 200000


def _git_blob(root: Path, relative: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "hash-object", relative.as_posix()],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _metrics(frame: pd.DataFrame, factor_col: str) -> dict[str, float | int]:
    active = frame[frame["active_offer"]].copy()
    factor = active[factor_col].astype(float).to_numpy()
    alpha = active["alpha_transfer"].astype(float).to_numpy()
    offer = active["f_bal_kw"].abs().astype(float).to_numpy()
    prescribed = factor > 0.0
    material = int(np.sum(alpha[prescribed] + 1e-12 < 0.95 * factor[prescribed]))
    strict = int(np.sum(factor[prescribed] > alpha[prescribed] + 1e-12))
    equal = float(np.mean(factor))
    feeder_ret = []
    feeder_labels = active["feeder"].astype(str).to_numpy()
    for feeder in sorted(set(feeder_labels)):
        mask = feeder_labels == feeder
        feeder_offer = float(np.sum(offer[mask]))
        if feeder_offer <= 0.0:
            raise ValueError(f"feeder {feeder!r} has no positive offer weight")
        feeder_ret.append(float(np.sum(factor[mask] * offer[mask]) / feeder_offer))
    pooled_offer = float(np.sum(offer))
    if pooled_offer <= 0.0:
        raise ValueError("active primary scope has no positive offer weight")
    pooled = float(np.sum(factor * offer) / pooled_offer)
    return {
        "material_false_safe_n": material,
        "strict_exceedance_n": strict,
        "equal_case_retention": equal,
        "feeder_macro_kw_retention": float(np.mean(feeder_ret)),
        "pooled_kw_retention": pooled,
    }


def _deltas(frame: pd.DataFrame) -> dict[str, float]:
    ph = _metrics(frame, "phicte_factor")
    fd = _metrics(frame, "feeder_only_factor")
    return {
        "equal_delta": float(ph["equal_case_retention"] - fd["equal_case_retention"]),
        "macro_delta": float(
            ph["feeder_macro_kw_retention"] - fd["feeder_macro_kw_retention"]
        ),
        "pooled_delta": float(ph["pooled_kw_retention"] - fd["pooled_kw_retention"]),
    }


def _describe(values: np.ndarray) -> dict[str, float]:
    q = np.quantile(values, [0.025, 0.5, 0.975])
    return {
        "p2_5": float(q[0]),
        "median": float(q[1]),
        "p97_5": float(q[2]),
        "probability_positive": float(np.mean(values > 0.0)),
    }


def _scenario_table(frame: pd.DataFrame, feeder: str) -> pd.DataFrame:
    subset = frame[(frame["feeder"] == feeder) & frame["active_offer"]].copy()
    subset["offer"] = subset["f_bal_kw"].abs().astype(float)
    subset["ph_kw"] = subset["offer"] * subset["phicte_factor"].astype(float)
    subset["fd_kw"] = subset["offer"] * subset["feeder_only_factor"].astype(float)
    subset["ph_factor"] = subset["phicte_factor"].astype(float)
    subset["fd_factor"] = subset["feeder_only_factor"].astype(float)
    return (
        subset.groupby("scenario_id", sort=True)
        .agg(
            n=("evaluation_id", "size"),
            offer=("offer", "sum"),
            ph_kw=("ph_kw", "sum"),
            fd_kw=("fd_kw", "sum"),
            ph_factor=("ph_factor", "sum"),
            fd_factor=("fd_factor", "sum"),
        )
        .reset_index()
    )


def _bootstrap(frame: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    draws: dict[str, dict[str, np.ndarray]] = {}
    for feeder in ("ieee13", "lv906"):
        table = _scenario_table(frame, feeder)
        matrix = table[["n", "offer", "ph_kw", "fd_kw", "ph_factor", "fd_factor"]].to_numpy(float)
        n = len(matrix)
        index = rng.integers(0, n, size=(RESAMPLES, n))
        summed = matrix[index].sum(axis=1)
        draws[feeder] = {
            "n": summed[:, 0],
            "offer": summed[:, 1],
            "ph_kw": summed[:, 2],
            "fd_kw": summed[:, 3],
            "ph_factor": summed[:, 4],
            "fd_factor": summed[:, 5],
        }

    feeder_delta = {
        feeder: draws[feeder]["ph_kw"] / draws[feeder]["offer"]
        - draws[feeder]["fd_kw"] / draws[feeder]["offer"]
        for feeder in draws
    }
    total_n = draws["ieee13"]["n"] + draws["lv906"]["n"]
    equal_delta = (
        (draws["ieee13"]["ph_factor"] + draws["lv906"]["ph_factor"]) / total_n
        - (draws["ieee13"]["fd_factor"] + draws["lv906"]["fd_factor"]) / total_n
    )
    macro_delta = 0.5 * (feeder_delta["ieee13"] + feeder_delta["lv906"])
    total_offer = draws["ieee13"]["offer"] + draws["lv906"]["offer"]
    pooled_delta = (
        (draws["ieee13"]["ph_kw"] + draws["lv906"]["ph_kw"]) / total_offer
        - (draws["ieee13"]["fd_kw"] + draws["lv906"]["fd_kw"]) / total_offer
    )

    feeder_specific: dict[str, Any] = {}
    for feeder in ("ieee13", "lv906"):
        subset = frame[(frame["feeder"] == feeder) & frame["active_offer"]]
        ph = _metrics(subset, "phicte_factor")
        fd = _metrics(subset, "feeder_only_factor")
        desc = _describe(feeder_delta[feeder])
        feeder_specific[feeder] = {
            "active_n": int(len(subset)),
            "phicte_kw_retention": ph["pooled_kw_retention"],
            "feeder_only_kw_retention": fd["pooled_kw_retention"],
            "kw_retention_delta": float(
                ph["pooled_kw_retention"] - fd["pooled_kw_retention"]
            ),
            "bootstrap_delta_p2_5": desc["p2_5"],
            "bootstrap_delta_median": desc["median"],
            "bootstrap_delta_p97_5": desc["p97_5"],
            "bootstrap_probability_positive": desc["probability_positive"],
            "phicte_material_false_safe_n": ph["material_false_safe_n"],
            "feeder_only_material_false_safe_n": fd["material_false_safe_n"],
        }
    return {
        "seed": SEED,
        "resamples": RESAMPLES,
        "strata": ["ieee13", "lv906"],
        "resampling_unit": "scenario_id",
        "percentile_interval": "2.5%-97.5%",
        "delta_distributions": {
            "equal_delta": _describe(equal_delta),
            "macro_delta": _describe(macro_delta),
            "pooled_delta": _describe(pooled_delta),
        },
        "feeder_specific_kw_delta": feeder_specific,
    }


def build_summary(root: Path) -> dict[str, Any]:
    if _git_blob(root, PREDICTIONS) != EXPECTED_PREDICTIONS_BLOB:
        raise ValueError("V2.4 predictions Git blob differs from the frozen source")
    if _git_blob(root, V2_4_SUMMARY) != EXPECTED_SUMMARY_BLOB:
        raise ValueError("V2.4 summary Git blob differs from the frozen source")
    frame = pd.read_csv(root / PREDICTIONS)
    frame["active_offer"] = frame["active_offer"].astype(str).str.lower().eq("true")
    primary = frame[
        (frame["cohort"] == "external") & (frame["duration_min"] == 15)
    ].copy()
    if len(primary) != 32 or int(primary["active_offer"].sum()) != 31:
        raise ValueError("unexpected V2.4 primary external scope")

    observed_ph = _metrics(primary, "phicte_factor")
    observed_fd = _metrics(primary, "feeder_only_factor")
    observed_delta = {
        "equal_case": float(
            observed_ph["equal_case_retention"] - observed_fd["equal_case_retention"]
        ),
        "feeder_macro_kw": float(
            observed_ph["feeder_macro_kw_retention"]
            - observed_fd["feeder_macro_kw_retention"]
        ),
        "pooled_kw": float(
            observed_ph["pooled_kw_retention"] - observed_fd["pooled_kw_retention"]
        ),
    }

    loso = []
    scenario_ids = sorted(primary["scenario_id"].unique())
    for scenario_id in scenario_ids:
        values = _deltas(primary[primary["scenario_id"] != scenario_id])
        loso.append({"left_out": scenario_id, **values})

    def loso_summary(name: str) -> dict[str, Any]:
        values = [(row["left_out"], float(row[name])) for row in loso]
        min_item = min(values, key=lambda item: item[1])
        max_item = max(values, key=lambda item: item[1])
        return {
            "min": min_item[1],
            "max": max_item[1],
            "positive_count": sum(value > 0.0 for _, value in values),
            "negative_count": sum(value < 0.0 for _, value in values),
            "n": len(values),
            "min_left_out": min_item[0],
            "max_left_out": max_item[0],
        }

    bootstrap = _bootstrap(primary)
    return {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_role": "retrospective_robustness_diagnostic",
        "source": {
            "predictions_path": PREDICTIONS.as_posix(),
            "predictions_blob_sha": EXPECTED_PREDICTIONS_BLOB,
            "v2_4_summary_blob_sha": EXPECTED_SUMMARY_BLOB,
            "repo_head_at_review": _git_head(root),
        },
        "scope": {
            "cohort": "V2.3A previously opened external cohort",
            "duration_min": 15,
            "planned_n": 32,
            "active_n": 31,
            "scenario_n": 16,
            "blind_holdout_claim": False,
            "confirmatory_claim": False,
        },
        "observed": {
            "phicte": observed_ph,
            "feeder_only": observed_fd,
            "delta_vs_feeder_only": observed_delta,
        },
        "leave_one_scenario_out": {
            "equal_delta": loso_summary("equal_delta"),
            "macro_delta": loso_summary("macro_delta"),
            "pooled_delta": loso_summary("pooled_delta"),
        },
        "stratified_scenario_bootstrap": bootstrap,
        "decision": {
            "status": "CONTINUE_WITH_FEEDER_STRATIFIED_REPLICATION",
            "global_dual_retention_gain_resolved_by_cluster_bootstrap": (
                bootstrap["delta_distributions"]["equal_delta"]["p2_5"] > 0.0
                and bootstrap["delta_distributions"]["macro_delta"]["p2_5"] > 0.0
            ),
            "pooled_kw_loss_resolved_by_cluster_bootstrap": (
                bootstrap["delta_distributions"]["pooled_delta"]["p97_5"] < 0.0
            ),
            "feeder_heterogeneity_resolved": (
                bootstrap["feeder_specific_kw_delta"]["ieee13"]["bootstrap_delta_p97_5"] < 0.0
                and bootstrap["feeder_specific_kw_delta"]["lv906"]["bootstrap_delta_p2_5"] > 0.0
            ),
            "next_primary_estimands": [
                "15-minute material false-safe risk by feeder",
                "15-minute kW retention delta by feeder",
                "feeder-macro retention as a secondary aggregate",
                "pooled-kW retention as sensitivity only",
            ],
        },
        "limitations": [
            "This diagnostic reuses the previously opened V2.3A cohort and is not confirmation.",
            "Bootstrap resampling quantifies finite-sample scenario variability; it does not establish exchangeability or a 5% deployment-risk guarantee.",
            "The diagnostic does not add new three-phase power-flow scenarios.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute the V2.5A PHiCTE robustness diagnostic.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve(strict=True)
    path = root / OUTPUT
    if path.exists() and not args.overwrite:
        raise FileExistsError(f"{OUTPUT} already exists; pass --overwrite to replace it")
    summary = build_summary(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": summary["decision"]["status"], "output": OUTPUT.as_posix()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
