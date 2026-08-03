# V2.1 D1-R-Lite Boundary-Mechanism Screen Design

## Objective

Repair the audit-adapter identity defect without altering the archived D1 STOP, then answer the smallest useful scientific question:

> In the sampled LV906 fixed EV trajectories, which physical constraint families first fail immediately beyond the archived transfer boundary, and are those families consistent enough to justify checking all 12 bad cases?

The protocol is an adaptive 8-to-16 target-audit screen. It is not a formal V2.1 rerun, a cross-feeder comparison, or a three-phase scheduling optimization.

## Immutable predecessors

- Preserve branch history containing result commit `77f49b7` and root-cause review commit `9027ea9`.
- Do not edit or overwrite any file under `results/mechanism_diagnostic_v2_1/` or the four existing `reports/mechanism_diagnostic_*_v2_1.*` artifacts.
- Keep `src/evflex/pilot.py` byte-identical with SHA-256 `37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b`.
- Keep the archived pilot decision `NO_GO_REASSESS_BROAD_TOPIC`; `formal_v2_1_run_started=false` throughout.
- Do not modify the original D1 config, manifest, module, runner, or evaluator. D1-R-Lite uses new filenames and a new output namespace so the old verifier remains reproducible.

## Protocol identity and files

- Protocol: `EV-FLEX-BIAS-V2.1-D1R-LITE`
- Config: `config/mechanism_diagnostic_v2_1_d1r_lite.json`
- Case manifest: `manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv`
- Logic: `src/evflex/mechanism_diagnostic_d1r_lite.py`
- Runner: `scripts/run_mechanism_diagnostic_v2_1_d1r_lite.py`
- Evaluator: `scripts/evaluate_mechanism_diagnostic_v2_1_d1r_lite.py`
- Results: `results/mechanism_diagnostic_v2_1_d1r_lite/`
- Reports: `reports/mechanism_diagnostic_v2_1_d1r_lite.{csv,json,md}` plus a case-hash CSV.

The new module may reuse schedule reconstruction and evidence compaction helpers from the unchanged original D1 module, whose file hash is pinned as a frozen dependency. It must not call the original D1 raw-identity validator or six-audit `execute_pair` path.

## Deterministic case selection

The manifest contains only the 12 archived LV906 bad members. For each of the four scenario clusters, the Stage A representative is the case whose `alpha_transfer` is closest to that cluster's median; ties use the smaller two-digit `pair_id`.

This rule freezes the representatives as:

| Scenario cluster | Stage A pair | Archived alpha | Stage B pairs |
|---|---:|---:|---|
| `lv906_1900_18` | 01 | 0.940 | 02 |
| `lv906_0000_11` | 04 | 0.696 | 03, 05, 06 |
| `lv906_0200_03` | 07 | 0.686 | 08, 09 |
| `lv906_0600_02` | 10 | 0.616 | 11, 12 |

The selection is computed and verified from the frozen 12-case manifest; runtime order or observed physical severity cannot change it.

## Audit method

All audits replay the archived balanced-model EV schedule in the existing three-phase network model. No alpha search, redispatch, phase reassignment, tie-break, timing study, control feeder, process pool, or formal-run path is allowed.

For each reconstructed case:

1. Verify scenario identity plus source, schedule, bus-phase-time, baseline, and load-scale hashes.
2. Build the corrected three-phase truth cache once.
3. Run one full baseline audit for runtime/integration validation and baseline-slot reuse. This is a precondition check, not a retained target audit.
4. Construct each audited schedule only as `baseline + alpha * (source_schedule - baseline)`.
5. Retain the first physical failure slot and every simultaneous explicit violation at that slot across `VMIN`, `VMAX`, `VUF`, `TRANSFORMER`, and `FEEDER`.

`line_thermal_in_scope=false` remains mandatory. Physical violations use the frozen pilot evaluator's explicit witness records, not a newly chosen tolerance or the sign of a recomputed margin.

## Adapter repair and integration guard

The new config freezes the actual pilot audit identity:

```text
adapter_schema  = evflex.pilot.network-audit
adapter_version = 2
```

Validation emits separate failure codes for record scale, context scale, schema, version, feeder, model, and formal constraints. It must never collapse these fields into the previous misleading load-scale message.

Before production, a read-only real-runtime integration preflight reconstructs Stage A pair 01, runs its baseline audit in memory, and proves that all 96 audit-context records match the frozen adapter identity, load scales, feeder, model, and formal constraints. It writes no result artifact.

## Stage A: eight target audits

For pairs `01`, `04`, `07`, and `10`, run exactly:

1. `BOUNDARY_FEASIBLE` at archived `alpha_transfer`; it must be feasible with complete 96-slot coverage.
2. `BOUNDARY_INFEASIBLE` at `alpha_transfer + 0.002`; it must stop on an explicit finite physical witness with no numerical failure.

Any source drift, integration mismatch, numerical failure, un-reproduced feasible boundary, or missing physical witness yields immutable `STOP_IMPLEMENTATION` and no later case.

After four successful Stage A cases, collect every constraint family present in each boundary-infeasible first-failure slot. A family qualifies for expansion when it appears in at least three of the four scenario representatives. Multiple families may qualify.

- No qualifying family: decision `STOP_HETEROGENEOUS_SCREEN`; do not run Stage B.
- One or more qualifying families: decision `EXPAND_STAGE_B`; immediately continue with Stage B under the same frozen run.

## Stage B: eight conditional target audits

Only after `EXPAND_STAGE_B`, run pairs `02`, `03`, `05`, `06`, `08`, `09`, `11`, and `12`. Each case receives exactly one `BOUNDARY_INFEASIBLE` audit at `alpha_transfer + 0.002`, with the same source and explicit-witness checks.

Across all 12 cases, report every family appearing in at least 8/12 bad cases and at least 3/4 scenario clusters.

- At least one qualifying family: `COMMON_CANDIDATE_CONFOUNDED`.
- No qualifying family: `HETEROGENEOUS_12_CASES`.

Neither decision identifies a unique or causal mechanism.

## Artifacts, resume, and stopping

- Write one immutable terminal JSON per case using atomic replacement.
- A terminal case is `SUCCESS`, `STOP_IMPLEMENTATION`, or `UNHANDLED_FAILURE`.
- Resume accepts only a continuous, strictly validated prefix in frozen execution order.
- Stage B artifacts are forbidden unless all four Stage A artifacts are successful and the recomputed Stage A gate is `EXPAND_STAGE_B`.
- Any lock, attempt, temporary, malformed, duplicate, out-of-order, or unexpected artifact blocks execution.
- Reports are generated deterministically and support read-only byte-for-byte verification.

## Resource policy

- One Python process.
- One worker.
- `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`, and `BLIS_NUM_THREADS` all equal `1`.
- Cases run sequentially in the frozen order `01,04,07,10,02,03,05,06,08,09,11,12`.

## Evidence and claim boundary

D1-R-Lite removes IEEE13 controls, full-offer audits, count matching, and relative-stress comparison. Therefore it cannot support cross-feeder, causal, unique-mechanism, redispatch-infeasibility, line-thermal, or universal-network claims.

Its strongest permitted statement is:

> Within the 12 archived LV906 fixed-trajectory boundary failures, one or more explicit first-failure constraint families met (or did not meet) the pre-frozen 8/12 and 3/4-cluster common-candidate threshold.

The screen does not authorize formal V2.1 under any outcome.

## Verification standard

Implementation is acceptable only if:

- a regression test fails against the old schema/version assumption and passes with the new contract;
- the real-runtime pair-01 integration preflight passes with 96/96 identity matches;
- unit tests prove the exact representatives, 8-to-16 audit ceiling, expansion gate, immutable resume, and field-specific failure codes;
- the full test suite passes with numeric threads capped at one;
- both archived D1 and archived pilot `--verify-existing` checks still pass;
- old result/report paths and `pilot.py` have zero diff from their frozen commits.
