# V2.1 D1 Mechanism Diagnostics Design

## Status and decision boundary

This design implements the smallest follow-up authorized after the frozen V2.1 pilot gate. The archived pilot decision remains `NO_GO_REASSESS_BROAD_TOPIC`, and this diagnostic must not start, emulate, or contaminate a formal V2.1 rerun.

The diagnostic studies only the transfer of fixed EV schedules generated under the existing balanced approximation. It does not perform three-phase re-optimization and therefore cannot conclude that an aggregate flexibility offer is impossible after re-dispatch.

## Goal

Determine whether the 12 archived LV906 `alpha_transfer < 0.95` results have reproducible, explicit physical constraint witnesses, and compare each result with a call-time/direction/duration-matched IEEE13 design-unit control under the same audit fractions.

## Non-goals

- Do not change or overwrite any artifact under `results/pilot_v2_1` or the archived gate reports.
- Do not start a formal V2.1 rerun.
- Do not add feeders, generate new scenarios, or fit a generalization model.
- Do not perform three-phase schedule re-optimization.
- Do not rerun tie-break or timing experiments in D1.
- Do not add line thermal constraints. Every D1 artifact must retain `line_thermal_in_scope=false`.
- Do not claim that a common causal mechanism has been proved across feeders.

## Alternatives considered

### A. Targeted mechanism diagnostic - selected

Replay the 12 archived bad evaluations and 12 matched IEEE13 controls at frozen audit points, persist constraint identities and margins, and apply a new immutable D1 gate. This directly closes the missing evidence with the least new computation.

### B. Verbose rerun of all 16 pilot work units - rejected for D1

This is simpler operationally but repeats six work units that are not needed for the paired question and recomputes complete alpha paths. It is reserved as a fallback only when a stored boundary bracket cannot be reconstructed or verified.

### C. Add feeders or three-phase re-optimization - deferred

This would answer a broader and materially different research question, substantially increase engineering and compute cost, and violate the current hard stop.

## Frozen source evidence

- Source code and archived evidence commit: `e1740f912a351b1822b5ee019f9e4f05b6b71c6f`.
- Frozen `src/evflex/pilot.py` SHA-256: `37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b`.
- Source evaluation table: `results/pilot_v2_1/pilot_evaluations_v2_1.csv`.
- Source evaluation table SHA-256: `bfb22446390191bcbc39f4de3f9363f211a090e8022f89f91c1ef515a9cf547a`.
- Source gate JSON SHA-256: `041b0d3521c3fbb22ee45578936a72c623cb8c7749a0139f6e63238649551751`.
- Source status: 16/16 work units, 48/48 evaluations, 12 bad active evaluations, `formal_v2_1_run_started=false`.

The D1 preflight must verify every source hash and refuse to run if any source identity has changed. Preflight and final verification must also confirm that the archived pilot evaluator still accepts its existing evidence with `--verify-existing`.

## Frozen paired sample

Each pair preserves call time, direction, and duration. The LV906 member is the archived bad case; the IEEE13 member is the archived safe design-unit control. These controls are matched design units, not causal matches.

| Pair | Bad evaluation | Safe control evaluation |
|---|---|---|
| 01 | `v20_core_lv906_1900_18__dec__15m` | `v20_core_ieee13_1900_17__dec__15m` |
| 02 | `v20_core_lv906_1900_18__dec__30m` | `v20_core_ieee13_1900_17__dec__30m` |
| 03 | `v20_core_lv906_0000_11__inc__15m` | `v20_core_ieee13_0000_09__inc__15m` |
| 04 | `v20_core_lv906_0000_11__inc__30m` | `v20_core_ieee13_0000_09__inc__30m` |
| 05 | `v20_core_lv906_0000_11__dec__15m` | `v20_core_ieee13_0000_09__dec__15m` |
| 06 | `v20_core_lv906_0000_11__dec__30m` | `v20_core_ieee13_0000_09__dec__30m` |
| 07 | `v20_core_lv906_0200_03__dec__15m` | `v20_core_ieee13_0200_17__dec__15m` |
| 08 | `v20_core_lv906_0200_03__dec__30m` | `v20_core_ieee13_0200_17__dec__30m` |
| 09 | `v20_core_lv906_0200_03__dec__60m` | `v20_core_ieee13_0200_17__dec__60m` |
| 10 | `v20_core_lv906_0600_02__dec__15m` | `v20_core_ieee13_0600_24__dec__15m` |
| 11 | `v20_core_lv906_0600_02__dec__30m` | `v20_core_ieee13_0600_24__dec__30m` |
| 12 | `v20_core_lv906_0600_02__dec__60m` | `v20_core_ieee13_0600_24__dec__60m` |

The pair manifest is immutable once committed. D1 may not substitute a case, seed, direction, duration, threshold, or control after execution begins.

## Schedule reconstruction and audit points

Each source schedule is reconstructed once from the frozen balanced scheduler and verified against the archived schedule identity. D1 never re-optimizes the schedule. For a source baseline `B`, fixed source schedule `S`, and audit fraction `alpha`, the audited schedule is exactly `B + alpha * (S - B)`.

For each pair, let `a` be the archived LV906 `alpha_transfer`:

- `BOUNDARY_FEASIBLE`: audit both schedules at `alpha=a`.
- `BOUNDARY_INFEASIBLE`: audit both schedules at `alpha=min(a+0.002, 1.0)`.
- `FULL_OFFER`: audit both schedules at `alpha=1.0`.

The bad member must reproduce a feasible/infeasible boundary bracket at the first two points. The safe control is evaluated at the same fractions as its paired bad member so the comparison does not use different transfer fractions. All 12 frozen controls have archived `alpha_transfer=1.0`, so all 12 must remain feasible at all three audit points; any disagreement with that archived fact is a structural failure.

If a bad bracket does not reproduce, D1 stops with `STOP_IMPLEMENTATION`; it does not silently launch a new alpha search. A complete alpha-path rerun requires a separately frozen repair protocol.

## Evidence retained per audit point

The existing network evaluator already produces physical violation records containing `metric`, `value`, `limit`, and `direction`. D1 preserves that existing evidence without changing physical limits, coverage, or power-flow behavior.

Each pair artifact contains both cases and records:

- protocol version, pair ID, role, source evaluation ID, source hashes, feeder, scenario, direction, duration, alpha, and resource policy;
- feasibility, coverage state, convergence, numerical failure count, physical violation count, and explicit physical witness;
- first failure slot and every simultaneous physical violation at that slot;
- for every retained constraint row: `constraint_family`, stable `metric_id`, `value`, `limit`, `direction`, `signed_headroom`, and nonnegative `exceedance`;
- extrema for Vmin, Vmax, VUF, transformer loading, and feeder loading;
- formal coverage counts and the literal `line_thermal_in_scope=false` declaration;
- fixed-schedule and audit-input hashes.

Constraint families are exactly `VMIN`, `VMAX`, `VUF`, `TRANSFORMER`, and `FEEDER`. No `LINE` family is permitted. Margins use one frozen sign convention:

- lower-bound constraint: `signed_headroom = value - limit`;
- upper-bound constraint: `signed_headroom = limit - value`;
- `signed_headroom >= 0` means feasible headroom and `signed_headroom < 0` means violation;
- `exceedance = max(0, -signed_headroom)`.

Every voltage object yields both a `VMIN` lower-bound row and a `VMAX` upper-bound row. VUF, transformer loading, and feeder loading are upper-bound rows. Rows are sorted by `(constraint_family_order, metric_id, direction)`, with the frozen family order `VMIN`, `VMAX`, `VUF`, `TRANSFORMER`, `FEEDER`.

An infeasible audit may stop after the first physical failure slot, but it must finish all declared metrics for that slot and retain every simultaneous violation. Its `checked_intervals` must equal `first_failure_slot + 1`, the first failure slot must be the final retained slot, and its formal metric set and coverage must be complete for that slot. A feasible audit must cover all 96 slots. D1 does not invent a unique primary cause; a largest-normalized-exceedance summary, if shown, is explicitly diagnostic.

## Constraint-count confound diagnostic

For each bad case at `BOUNDARY_INFEASIBLE`, D1 retains signed margins for all monitored voltage and VUF objects at the first failure slot. For its paired IEEE13 control, it retains the same families at the same slot and fraction.

Count matching applies only to `VMIN`, `VMAX`, and `VUF`. The diagnostic unit is `case x constraint family`, so a case with simultaneous VMIN and VUF violations contributes two rows. `N`, `K`, and `m` count unique object IDs. VMIN and VMAX use the same full set of monitored voltage object IDs.

For each row, let `N` be the number of monitored LV906 objects in that family, `K` the number of unique LV906 objects explicitly emitted as physical violations by the original evaluator, and `m` the number of monitored IEEE13 objects in the same family. `K` is not recomputed from `signed_headroom < 0`, because the original evaluator applies a frozen `1e-7` feasibility tolerance. If `0 < m <= N`, the exact without-replacement probability that a count-matched sample contains at least one violation is:

`p_detect = 1 - C(N-K, m) / C(N, m)`.

The implementation uses exact integer combinations, not Monte Carlo sampling. `C(N-K, m)` is defined as zero when `N-K < m`. It stores the exact numerator and denominator, serializes a 12-decimal `ROUND_HALF_EVEN` display value, and compares thresholds using the exact fraction rather than the rounded display. Invalid counts are structural errors; a family absent from the control is reported as `NOT_APPLICABLE`, not assigned a probability.

For each candidate family, let `n_eligible` be the number of rows with a valid exact probability. `NOT_APPLICABLE` rows do not enter the denominator or the 80% count. This is only a count-matched detection-sensitivity classification:

- `COUNT_MATCH_NOT_APPLICABLE` when `n_eligible < 4`;
- `COUNT_MATCH_HIGH_DETECTION` when at least `ceil(0.8*n_eligible)` eligible rows have exact `p_detect >= 4/5`;
- `COUNT_MATCH_LOW_DETECTION` when at least `ceil(0.8*n_eligible)` eligible rows have exact `p_detect <= 1/5`;
- `COUNT_MATCH_INDETERMINATE` otherwise.

No classification proves or excludes a count effect, and it never changes an audit's physical feasibility label.

## Relative-stress confound boundary

The existing frozen input does not expose a versioned definition of native-load power or a phase allocation rule from which an unambiguous EV-power/native-load ratio can be reconstructed. D1 therefore records `RELATIVE_STRESS_NOT_IN_SCOPE_NO_FROZEN_DENOMINATOR` for every pair, serializes global and phase ratio fields as `null`, and does not invent a post-hoc ratio or substitute `f_bal/feeder_kVA` as a proxy.

This unresolved feeder-size/stress confound is mandatory in the report and prevents a common-family candidate from being described as a causal mechanism. A later confirmation protocol may add the ratio only after freezing its numerator, denominator, phase rule, units, and zero-denominator behavior prospectively.

## Frozen gate

### Structural and implementation gate

All conditions are mandatory:

1. Exactly 12 pairs and 24 unique source evaluations are present.
2. All source IDs, hashes, schedules, seeds, and protocol fields match the frozen manifest.
3. All 12 bad `BOUNDARY_FEASIBLE` audits are feasible with complete 96-slot coverage.
4. All 12 bad `BOUNDARY_INFEASIBLE` audits are physically infeasible, have explicit finite witnesses, and are no more than 0.002 above the archived feasible alpha.
5. All 12 bad `FULL_OFFER` audits remain physically infeasible with explicit finite witnesses; a feasible full offer contradicts the archived monotone boundary and stops implementation.
6. All 12 bad cases have zero numerical failures.
7. All 12 matched controls remain feasible with complete 96-slot coverage at both paired boundary points and at `FULL_OFFER`.
8. Every violation value, limit, direction, signed headroom, exceedance, object ID, and slot passes strict validation.
9. Formal metric coverage counts are valid and `line_thermal_in_scope=false` in every case. An infeasible bad audit may stop only at its explicit first physical witness after completing that slot's metrics, with `checked_intervals = first_failure_slot + 1`.
10. No unit, rating, normalization, label-set, source-provenance, or coverage-integrity error is detected.
11. `src/evflex/pilot.py` remains byte-identical and the archived pilot report passes `--verify-existing`.

Failure of any condition yields `STOP_IMPLEMENTATION`. The existing pilot NO_GO remains unchanged.

### Diagnostic classification

After the structural gate passes:

- `COMMON_CANDIDATE_CONFOUNDED`: one or more constraint families appear among first-slot violations in at least 8/12 bad cases and cover at least 3/4 LV906 scenario clusters, while at least one count or relative-stress confound remains unresolved;
- `VALID_HETEROGENEOUS`: all 12 cases have explicit physical witnesses, but no family meets the common-candidate threshold;
- `STOP_IMPLEMENTATION`: the structural gate failed.

Only `BOUNDARY_INFEASIBLE` first-failure-slot violations enter the candidate count. A family covers a scenario cluster when it appears in at least one case from that frozen scenario ID. The four call-time/scenario groupings are scenario clusters, not independent repetitions. The 8/12 and 3/4 thresholds are prospective screening rules, not findings from the archived pilot. Multiple families may pass and all are emitted in the fixed family order; no primary mechanism is selected. A common-family candidate permits only the design of a small independent confirmation gate; it is not a unique or causal mechanism and does not authorize a formal V2.1 rerun.

## Output isolation and provenance

New artifacts use only these roots:

- `config/mechanism_diagnostic_v2_1.json`
- `manifests/mechanism_diagnostic_pairs_v2_1.csv`
- `results/mechanism_diagnostic_v2_1/`
- `reports/mechanism_diagnostic_v2_1.json`
- `reports/mechanism_diagnostic_v2_1.md`
- `reports/mechanism_diagnostic_hashes_v2_1.csv`

Writes are atomic. One terminal JSON is written per pair and contains six audits: two roles by three fractions. Resume accepts only strictly validated terminal artifacts whose identities and hashes match the manifest. Unexpected files, partial attempts, active locks, duplicate IDs, non-finite values, or source hash drift stop the run.

The evaluator is read-only with respect to pair artifacts and supports `--verify-existing` to verify an archived report without regeneration.

## Resource policy

- One process worker.
- One numeric thread.
- `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`, and `BLIS_NUM_THREADS` all equal `1`.
- Cases execute sequentially unless a future protocol explicitly changes the policy.
- Formal V2.1 output roots are forbidden by preflight.

## Components

### Frozen pilot implementation

`src/evflex/pilot.py` remains byte-identical to its frozen SHA-256. D1 calls its existing targeted runtime and audit behavior but owns all new evidence compaction in `src/evflex/mechanism_diagnostic.py`.

### D1 protocol module

`src/evflex/mechanism_diagnostic.py` owns pair loading, schedule reconstruction checks, audit-point construction, first-slot evidence compaction, strict artifact validation, exact count matching, D1-specific resume validation, and gate aggregation. It must not contain power-flow physics or modify the archived pilot schema.

### Runner and evaluator

`scripts/run_mechanism_diagnostic_v2_1.py` performs preflight, reconstructs and verifies frozen schedules, runs sequential targeted audits, and writes one terminal JSON per pair using D1-specific atomic and resume validation. It must not reuse the archived runner's three-evaluation/single-ablation expected-ID rule.

`scripts/evaluate_mechanism_diagnostic_v2_1.py` strictly loads D1 pair artifacts, produces deterministic CSV/JSON/Chinese Markdown reports, and implements `--verify-existing`.

### Tests

- `tests/test_mechanism_diagnostic.py`: frozen pairing, schedule identity, audit-point construction, all constraint families, both voltage bounds, same-slot multiple violations, earliest-slot selection, numerical failure isolation, line-thermal exclusion, exact count probability, strict schema, gate branches, source drift, D1-specific resume, atomic output, and report verification.
- Existing pilot/gate tests must remain unchanged in scientific meaning and continue to pass.

## Execution sequence

1. Commit this design and the implementation plan before production code changes.
2. Write failing unit tests for evidence preservation in the new D1 module and verify RED.
3. Implement the smallest D1 evidence compactor and verify GREEN without changing `pilot.py`.
4. Write failing protocol and gate tests and verify RED.
5. Implement the D1 module, config, manifest, runner, and evaluator in small reviewed commits.
6. Run focused tests, the complete suite, and the archived pilot `--verify-existing` regression under the one-thread environment.
7. Freeze code and source hashes before any D1 case execution.
8. Run the 24 source schedules and 72 targeted network audits sequentially.
9. Evaluate and independently review structural integrity and scientific interpretation.
10. Decide whether a separately frozen confirmation design is justified. Do not start it automatically.

## Expected workload

With no implementation defect, code, tests, targeted execution, and reporting are expected to fit within one working day. The compute portion is budgeted at 0.5-1.5 hours. One to three days is a contingency only for discovered implementation or evidence defects.
