# V2.5B-R2 execution amendment — baseline ineligibility and phase-aware repair

Date: 2026-08-12

## Trigger

The first V2.5B-R1 GitHub Actions batch completed environment setup, 526 regression tests, and the first ten work units. It then stopped on `v25b_replication_ieee13_1900_31__inc` because the shared evaluator returned three explicitly noneligible rows.

A dedicated raw-evaluator diagnostic confirmed that this was a **physical baseline infeasibility**, not an OpenDSS numerical failure. For all 15/30/60-minute requests, the balanced scheduling stage reported an infeasible baseline at slot 28 because transformer `xfm1` loading was approximately 1.159755 p.u. against the frozen 1.0-p.u. limit. The independent three-phase baseline audit also classified the operating point as `BASELINE_PHYSICAL_INVALID` with complete 96-interval coverage and no convergence/numerical failures.

## R2 handling

The predetermined scenario set is unchanged. R2 changes execution semantics only:

1. Explicitly classified scientific noneligibility (`INVALID_SCHEDULE`, `INVALID_BASELINE`, or `NUMERICAL_INVALID_ALPHA_PATH` with an approved status family) is retained as a planned coverage outcome instead of terminating the complete batch.
2. Such rows are excluded from transferability risk/retention denominators because the baseline-to-call ray requires a scientifically valid alpha=0 operating point.
3. Physical baseline ineligibility is reported separately by feeder and status. Numerical baseline invalidity remains a manuscript-readiness failure condition.
4. No V2.5B outcome is used to change scenario selection, network limits, the V2.4 PHiCTE model, its features, its penalty, or its calibration correction.
5. The already-generated phase-aware tie-break comparator is promoted to a reported **schedule-repair diagnostic**. It preserves the bus-time aggregate schedule and declared offer while redispatching EV trajectories within the existing fleet constraints. The paper will distinguish this constrained repair from full three-phase reoptimization.

## Scientific rationale

Transferability `alpha_transfer` is defined on the ray from a baseline schedule to a balanced-model call schedule. If the baseline itself violates the frozen physical network constraints, alpha=0 is infeasible and the transferability factor is not scientifically defined for that planned row. Treating the row as coverage/ineligibility rather than silently dropping the scenario or aborting the entire predetermined cohort preserves the design and makes the denominator explicit.

## Claim boundary

R2 remains retrospective. It does not create a blind or confirmatory holdout and does not establish a deployable 5% risk guarantee.
