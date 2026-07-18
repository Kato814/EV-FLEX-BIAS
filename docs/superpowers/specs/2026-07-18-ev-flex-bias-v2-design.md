# EV-FLEX-BIAS-V2.0 Rebuild Design

**Date:** 2026-07-18  
**Status:** Approved by the user through blanket approval of the recommended design  
**Submission deadline:** 2026-08-20  
**Target venue:** 2026 IEEE PES ISGT Asia

## 1. Objective

Build a new, auditable experimental lineage for the paper on directional bias and applicability of balanced-network approximations for EV-aggregator V1G/V2G deliverable flexibility. The new lineage must regenerate every formal statistic used in the paper while preserving the scientifically valid archived inputs and the sealed development/holdout split.

The protocol identifier is `EV-FLEX-BIAS-V2.0`. It is a new major version because the repository that produced v1.8 no longer exists. V2.0 must not claim bitwise or code-level reproduction of v1.8.

## 2. Fixed scientific scope

- Feeders: IEEE 13-node and European LV906.
- Directions: `inc` for additional V1G charging and `dec` for charging reduction or V2G export.
- Durations: 15, 30, and 60 minutes.
- Call times: 19:00, 00:00, 02:00, and 06:00.
- Time grid: noon-to-noon, 96 intervals of 15 minutes.
- Core scenarios: 256 archived formal scenarios.
- Core evaluations: 1,536, split into 1,152 development evaluations and 384 sealed holdout evaluations.
- Primary metric: `alpha_map`, the fraction of the balanced-model call that remains feasible after nonlinear three-phase verification.
- Frozen risk label: `false_safe = alpha_map < 0.95`.
- Formal applicability claim: selected holdout count at least 20 and selected holdout false-safe rate at most 5%.
- Universal cross-feeder thresholds and universal derating factors remain out of scope.

## 3. Asset lineage

### 3.1 Authoritative inherited assets

The following assets are copied from the archived packages into the new repository and verified before use:

- Official `2022_NHTS_V2.1_CSV.zip`.
- Processed `nhts2022_vehicle_days.csv`.
- `base_scenarios_v1_2.csv`.
- `formal_ev_populations_v1_2.csv` and its summary.
- The existing 1,536-row core manifest and its development/holdout role assignments.
- Controlled native-load profile.
- IEEE13 and LV906 DSS files with their complete redirect dependencies.
- Self-contained D5 v1.2 duration engine and network core.
- The 24-row D5 regression result set.

The import process records source archive, archive-entry path, byte count, SHA-256, and destination path in `manifests/inherited_asset_manifest_v2_0.csv`. A mismatch against the known hashes blocks all numerical work.

### 3.2 Reference-only assets

The v1.7 development results and scripts, v1.8 applicability models, v1.8 ablation manifest, and old manuscript figures are diagnostic references only. They may be used to explain numerical differences, but they cannot populate V2.0 tables, figures, thresholds, or claims.

### 3.3 Regenerated assets

V2.0 regenerates the environment lock, run IDs, core results, applicability models, risk thresholds, compact ablation results, holdout results, tables, figures, and manuscript statistics.

## 4. Repository architecture

The new repository root is `EV_FLEX_BIAS_V2_0/` and contains:

```text
EV_FLEX_BIAS_V2_0/
  README.md
  .gitignore
  requirements.lock.txt
  protocol/protocol_v2_0.json
  config/
  data/inherited/
  data/feeders/
  legacy/d5_v1_2/
  manifests/
  src/evflex/
    provenance.py
    schema.py
    network.py
    fleet.py
    engine.py
    runner.py
    aggregate.py
    modeling.py
    ablation.py
    holdout.py
  scripts/
  tools/
  tests/
  state/
  results/
  reports/
  paper/
  docs/superpowers/specs/
  docs/superpowers/plans/
```

Modules have one responsibility. Legacy D5 code remains unmodified under `legacy/d5_v1_2/`; V2.0 adapters and corrections live under `src/evflex/`. Thin scripts expose command-line entry points and do not contain numerical logic.

The runtime is an isolated Windows virtual environment based on Python 3.12.13 because the registered local Python 3.13 executable points to an unavailable drive. V2.0 records this deliberate environment change and pins every direct dependency. The archived Linux/Python 3.13.5 environment is retained as provenance, not presented as the V2.0 runtime.

## 5. Numerical-engine design

The D5 v1.2 engine supplies the verified multi-period EV trajectory formulation, nonlinear network checks, and 15/30/60-minute constant-block service logic. V2.0 adds:

1. A clean adapter around the archived network core.
2. Scenario-level balanced and three-phase context reuse.
3. The v1.7 nested-duration feasible-schedule closure implemented against the v1.2 base.
4. A stable result schema with physical checks, provenance hashes, runtime, attempt count, and terminal status.
5. Scenario-direction work units that solve all three durations together and contain three evaluation IDs.
6. Atomic one-file-per-work-unit output and same-work-unit resumability.

For each scenario-direction, all three durations are solved together. A core work unit therefore contains three evaluation rows; 512 work units produce 1,536 evaluations, with 384 development work units producing 1,152 evaluations and 128 holdout work units producing 384 evaluations. For a requested duration, the engine may select a physically feasible schedule from that duration or a longer nested duration when it has greater capacity. Ties select the shortest source duration. This enforces the mathematical non-increasing capacity relation across 15, 30, and 60 minutes without using holdout outcomes.

OpenDSS work uses process isolation. BLAS, OpenMP, MKL, NumExpr, and scikit-learn threads are fixed at one. Numerical execution uses one process for regression and at most two processes for formal manifests on the 20-core, 32-GB local machine. V2.0 never exceeds two concurrent numerical processes.

Formal V2.0 evaluations use `0.95-1.06 pu` voltage limits, `2%` maximum VUF, and unit line/feeder loading limits. The G1 reproduction adapter alone retains the archived D5 v1.2 `1.05 pu` upper voltage limit so its numerical outputs remain directly comparable to the frozen golden rows; this compatibility mode is never used for V2.0 development, ablation, or holdout evidence.

## 6. Core data flow and sealing

1. Import inherited assets and verify hashes.
2. Create and freeze the V2.0 environment report.
3. Run 24 D5 golden regressions and repeatability tests.
4. Normalize the inherited core manifest into V2.0 run IDs while preserving scenario identity and data role.
5. Execute only the 1,152 development IDs.
6. Aggregate development results and apply physical and completeness gates.
7. Fit and freeze 12 feeder-direction-duration L2 logistic risk models using development data only.
8. Run and analyze the 336 development-only compact ablations.
9. Freeze code, configuration, model, threshold, ablation-analysis, and paper-analysis hashes.
10. Create a holdout unlock record from the freeze report.
11. Execute the 384 holdout IDs once, allowing resume only for IDs without a terminal result.
12. Apply frozen models and thresholds without refitting or rethresholding.
13. Generate final tables, figures, manuscript text, and the A4 submission PDF.

The holdout runner refuses holdout work units unless `state/holdout_unlock_v2_0.json` exists and validates the complete pre-holdout freeze report. Completed holdout work units are never recomputed. Infrastructure interruption may resume the same incomplete work unit; it may not create a replacement ID or seed.

## 7. Applicability modeling

The model family remains cell-specific L2 logistic regression because the paper requires interpretable risk maps rather than a new forecasting algorithm. There are 12 cells from two feeders, two directions, and three durations.

- Five-fold stratified out-of-fold predictions on development data.
- Frozen `C` grid: `0.03, 0.1, 0.3, 1, 3, 10, 30`.
- Hyperparameter criterion: minimum out-of-fold Brier score; ties choose the stronger regularization, meaning the smaller `C`.
- Numeric features: actual EV-nameplate/transformer ratio, native-load multiplier, phase-imbalance index, far-zone probability, median natural urgency, and sine/cosine call-time encoding.
- `dec` models additionally include realized V2G participation.
- Dominant phase is one-hot encoded with phase `a` as the reference.
- Threshold rule: maximum development OOF coverage with selected count at least 20 and empirical false-safe rate at most 5%.
- Cells without a qualifying rule remain without a formal applicability region.

Holdout evaluation reports selected count, failure count, false-safe rate, Wilson interval, and coverage. No model, feature set, coefficient, or threshold may change after the pre-holdout freeze.

## 8. Compact controlled-ablation design

The compact design contains exactly 336 development-only runs, all at 15 minutes. Duration effects are already measured in the full core experiment; the ablations isolate physical mechanisms at the shortest service interval.

Two representative call times are used: 19:00 for the evening peak and 02:00 for low-load/reverse-flow conditions. Each factor level has three preassigned seeds. The three replicates rotate dominant phase `a`, `b`, and `c` where phase identity is relevant.

| Block | Factor levels | Directions | Count |
|---|---|---:|---:|
| A1 | phase ratio `1:1:1`, `2:1:1`, `4:1:1` | inc + dec | 72 |
| A2 | far-zone probability `0.20`, `0.50`, `0.80` | inc + dec | 72 |
| A3 | native-load multiplier `0.75`, `0.90`, `1.05` | inc + dec | 72 |
| A4 | urgency quantile `0.40`, `0.65`, `0.90` | inc + dec | 72 |
| A5 | V2G participation `0.25`, `0.50`, `0.75`, `1.00` | dec | 48 |

Counts include two feeders, two call times, and three seeds. Non-varied settings are EV-nameplate/transformer ratio 0.35, native-load multiplier 0.90, phase ratio `2:1:1`, far-zone probability 0.50, V2G participation 0.50, and urgency quantile 0.65.

The analysis reports within-block level contrasts for `alpha_map`, balanced-model bias, and false-safe probability. Confidence intervals use a frozen 10,000-resample stratified bootstrap with seed `2026072001`, stratified by feeder, call time, direction, and replicate. Failed IDs are reported and never replaced.

## 9. Error handling and audit rules

- Hash mismatch, schema mismatch, duplicated run ID, duplicated seed, or role inconsistency stops the pipeline.
- Each work unit writes to a temporary file, flushes it, and atomically replaces the final JSON only after validating all contained evaluation rows.
- A per-work-unit exclusive lock prevents two processes from computing the same scenario-direction bundle.
- Completed results are immutable; corrections create a new protocol patch version and a documented supersession record.
- Expected physical domain outcomes such as three-phase baseline infeasibility receive explicit statuses and are not treated as software crashes.
- Unhandled exceptions produce a failure record with traceback, environment hash, and attempt number.
- The same ID may be retried at most twice for infrastructure failure; scientific infeasibility is terminal.
- No failed run may be replaced by a different seed or scenario.
- Paired bias metrics use only cases in which both baseline models are feasible; excluded cases are counted and reported.

## 10. Validation gates

### G0: Provenance

All authoritative inherited hashes match; the manifest has no missing or extra required assets.

### G1: Engine regression

- All 24 D5 reference cases reach the same feasibility status.
- Capacity absolute difference is at most `1e-5 kW` or relative difference at most `1e-8`.
- `alpha_map` absolute difference is at most `1e-8`.
- Departure-energy error is at most `1e-8 kWh`.
- Reserve-SOC violation is at most `1e-9 kWh`.
- Simultaneous charge/discharge count is zero.
- Repeated sequential runs are identical within the same tolerances.
- 15/30/60-minute capacity monotonicity holds after closure.

### G2: Development execution

Every development ID has a terminal record; there are no unhandled failures, physical invariants pass, and each paired analysis cell has at least 80 eligible observations.

### G3: Model and threshold freeze

Exactly 12 model records are produced, all OOF predictions cover only development IDs, and every candidate threshold satisfies the frozen selection rule.

### G4: Ablation freeze

Exactly 336 unique IDs have terminal records, all bootstrap strata and seeds match the manifest, and the fixed analysis report is complete.

### G5: Holdout unlock

Code, inputs, environment, development results, models, thresholds, ablation results, and analysis scripts have recorded hashes. The holdout has not previously been opened.

### G6: Submission evidence

The holdout contains exactly 384 terminal records. Final tables and figures are generated exclusively from V2.0 results, numerical statements in the manuscript match machine-readable summaries, and the A4 PDF uses the conference template.

## 11. Schedule

| Dates | Deliverable |
|---|---|
| Jul 18-20 | Repository, asset import, hashes, protocol, environment |
| Jul 21-25 | Engine adapter, nested-duration closure, unit tests |
| Jul 26-27 | D5 regression, determinism and concurrency gates |
| Jul 28-Aug 2 | 1,152 development evaluations and aggregation |
| Aug 3-5 | Applicability models and threshold freeze |
| Aug 6-9 | 336 compact ablations and fixed analysis |
| Aug 10 | Pre-holdout freeze and audit |
| Aug 11 | One-pass 384 holdout evaluation |
| Aug 12-16 | Final statistics, figures, and English manuscript |
| Aug 17-18 | Conference-template formatting and PDF QA |
| Aug 19 | Submission buffer and final checklist |
| Aug 20 | EasyChair submission |

The calendar contingency is predeclared. If G3 has not passed by the end of Aug 5, V2.0 continues the complete core and holdout path but omits controlled-ablation claims from the submission. This calendar-only fallback is recorded as `EV-FLEX-BIAS-V2.0-C`; it does not alter models, thresholds, core IDs, or holdout rules. Old ablation results are not substituted. The fallback records G4 as `OMITTED_BY_PREDECLARED_CALENDAR_GATE`, removes every ablation claim and figure from the paper plan, and requires all other gates to pass.

## 12. Paper-delivery rules

- Primary conference track: Electric Vehicle-Grid Integration and Smart Charging for Carbon Neutrality.
- The abstract and introduction connect reliable EV flexibility assessment to low-carbon grid operation without claiming measured carbon reduction.
- The paper remains feeder-, direction-, and duration-specific.
- The old 117-scenario, 15-minute statistics are removed.
- Manuscript numbers are inserted from generated JSON/CSV summaries, not manually retyped from console output.
- The official conference template is downloaded and hashed. If the official template cannot be obtained, formatting stops rather than substituting an unverified generic IEEE template.
- Final submission is a single English A4 PDF, visually inspected page by page.

## 13. Completion criteria

The primary project is complete for submission when G0-G6 pass, the final PDF contains only V2.0 evidence, the holdout audit proves one-pass evaluation, the paper fits the official template, and the EasyChair submission checklist is satisfied by 2026-08-20. The `V2.0-C` fallback is complete only when G0-G3 and G5-G6 pass, G4 records the predeclared calendar omission, and the manuscript contains no ablation-derived claim.
