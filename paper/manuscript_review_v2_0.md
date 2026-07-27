# EV-FLEX-BIAS-V2.0 adversarial manuscript review

## Claim audit

| Claim | Evidence in submission | Status |
|---|---|---|
| Balanced estimates can be false-safe | Same-input definition, development map, holdout medians | PASS |
| Directional behavior depends on feeder and duration | Paired holdout contrasts with frozen bootstrap | PASS |
| Phase allocation and V2G participation expose mechanisms | Compact paired ablation; three-replicate limitation stated | PASS |
| Formal applicability is local | Twelve-cell one-pass holdout table; only two validated | PASS |
| Carbon relevance | Framed only as potential operational use; no carbon reduction claimed | PASS |

## Reviewer-risk audit

1. **Contribution — PASS.** The contribution is an auditable validity task and sealed applicability protocol, not a new generic classifier. The introduction states this distinction and the conclusion reports failures as evidence rather than suppressing them.
2. **Writing clarity — PASS.** The paper defines the balanced offer, three-phase reference, `alpha_map`, false-safe event, multi-period closure, model inputs, fold-local standardization, threshold rule, and freeze boundary.
3. **Empirical strength — PASS WITH SCOPE BOUNDARY.** The evidence covers two benchmark feeders, two directions, three durations, four call times, a 336-evaluation mechanistic ablation, and a 384-evaluation sealed holdout. The paper does not claim feeder-wide generality.
4. **Baseline fairness — PASS FOR THE STATED TASK.** This is a validity audit rather than a predictive-performance benchmark. The balanced model is the audited approximation and the same-input nonlinear three-phase model is the physical reference; changing either input set would confound the target comparison.
5. **Evaluation completeness — PASS.** All predeclared development, ablation, freeze, and holdout gates are represented. Non-successful development outcomes are counted and explained; no holdout ID, model, or threshold is replaced.
6. **Statistical interpretation — PASS.** The 5% rule uses the predeclared observed rate, while Wilson intervals are disclosed as uncertainty rather than reused for tuning. Three-replicate ablations are labeled mechanistic and exploratory.
7. **Reproducibility — PASS.** Numerical claims are injected from the frozen value ledger with hidden machine-checkable markers; source result, model, figure, and final-package hashes are recorded separately.
8. **Submission metadata — MANUAL FINALIZATION.** Author names, affiliations, and corresponding-author email are intentionally explicit placeholders because no verified identity metadata exists in the project. They must be replaced before EasyChair upload.

## Concrete revisions made after review

- Added fold-local numeric standardization and categorical encoding details.
- Added exact 30- and 60-min directional holdout contrasts.
- Removed the non-authoritative OpenDSS mirror citation.
- Kept the validated claim restricted to IEEE13 decreasing calls at 15 and 60 min.
- Retained explicit field-deployment, uncertainty, telemetry, battery, and carbon-accounting limitations.
