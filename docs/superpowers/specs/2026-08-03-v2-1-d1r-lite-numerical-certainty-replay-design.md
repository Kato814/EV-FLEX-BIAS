# V2.1 D1-R-Lite N1 Numerical-Certainty Replay Design

## Objective

Determine whether four representative archived `VMAX` boundary witnesses are stable to materially tighter OpenDSS convergence settings, while preserving the original fixed EV trajectories, topology, controls, physical limits, and selected witness slots.

This is a targeted numerical-certainty replay, not formal V2.1, not a new alpha search, and not an independent scenario validation. It addresses one question only:

> At the same archived failure slot and voltage node, does the positive voltage exceedance persist when the final no-control power-flow solve is repeated at `1e-4`, `1e-6`, and `1e-8` convergence tolerances in independent OpenDSS contexts?

## Why this replay is necessary

The artifact-only N0 check returned `HOLD_MARGIN_FRAGILE_AT_1E5` because the `VMAX` support count fell from 10/12 to 6/12 after applying a `1e-5 pu` reporting guard band. That result proves sensitivity to the chosen reporting margin, but it does not distinguish a real near-boundary crossing from a solver-convergence artifact.

The D1-R-Lite cases deliberately evaluate `alpha_transfer + 0.002`, immediately beyond an archived feasible boundary. Small physical exceedances are therefore expected by design. N1 must test numerical reproducibility directly before the N0 hold is given a stronger academic interpretation.

## Alternatives considered

1. **Four witness-slot replays, one per scenario cluster — selected.** This directly tests the questioned voltage values with 12 target evaluations and minimal repeated network construction.
2. **Four complete 96-slot boundary replays.** This would also re-establish first-failure ordering, but would repeat hundreds of power flows that are not required to answer the solver-tolerance question.
3. **All ten archived `VMAX` cases.** This offers greater sample coverage but is disproportionate before the smallest numerical-certainty gate is known.

The selected design minimizes runtime without treating a slot replay as full-trajectory evidence.

## Immutable source evidence

N1 verifies the following archived inputs before any new power-flow evaluation:

| Input | Frozen SHA-256 |
|---|---|
| `reports/mechanism_diagnostic_v2_1_d1r_lite.json` | `86f7c0d3498da45d01e7008eeca42b6b8265a67bf1337ea5ea569a80d5c71275` |
| `reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv` | `ed58ded0d3581d5b7afcafa23f02b53471d4866c8a1fa9becfeb90060dd1ce94` |
| `reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv` | `b936cb7d1697a0888165afc81e688fdb830e00b7236e81215c8db86b1851b46a` |
| `config/mechanism_diagnostic_v2_1_d1r_lite.json` | `ec69c26761de716ace3b65aa3ad11ff2f5afcdb39d25754a62d98fec8ccd778a` |
| `manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv` | `c150a56e7535c09fe1cf361a32f7fd86b424912a8ad286ed8ad8b469047196de` |
| `src/evflex/mechanism_diagnostic_d1r_lite.py` | `8efaa90990225cf1ae7ac99eb2becd7df9bbae0b4271fb544038a405f6ad8fd5` |
| `reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json` | `d7da6a5d00c6d44cc994300844be0b69bfeef47e43d45549f32961778e93dfff` |
| `config/mechanism_margin_sensitivity_v2_1_d1r_lite.json` | `5f188613783ae10d5d53ff5b06a62ce57b52a9c61d66bef56f16b19aedf84d31` |

All 12 archived D1-R-Lite case JSON files must still match the archived case-hash CSV and pass the existing strict validator. The D1, pilot, D1-R-Lite, and N0 `--verify-existing` checks must pass before production execution.

The runtime remains `opendssdirect.py==0.9.4`. The replay records the observed solution settings returned by the active OpenDSS context; a requested setting that cannot be read back exactly is a controlled stop.

## Frozen representative selection

Selection is computed from the archived D1-R-Lite boundary-infeasible audit rows before execution:

1. retain only physical `VMAX` witnesses;
2. group by the four frozen scenario clusters in first-manifest-occurrence order;
3. within each cluster, choose the case whose archived exceedance is closest to the N0 decisive guard band `1e-5 pu`;
4. break an exact distance tie by ascending two-digit `pair_id`.

The resulting immutable cases are:

| Pair | Scenario cluster | Boundary alpha | Slot | Metric | Archived value | Limit | Archived exceedance |
|---|---|---:|---:|---|---:|---:|---:|
| `01` | `lv906_1900_18` | 0.942 | 28 | `V:860.1` | 1.0600621154646155 | 1.06 | 6.211546461543094e-05 |
| `05` | `lv906_0000_11` | 0.708 | 48 | `V:563.1` | 1.0600027494562219 | 1.06 | 2.7494562218066676e-06 |
| `08` | `lv906_0200_03` | 0.688 | 56 | `V:900.1` | 1.0600063998269251 | 1.06 | 6.399826925074237e-06 |
| `12` | `lv906_0600_02` | 0.612 | 75 | `V:780.3` | 1.0600434424802179 | 1.06 | 4.3442480217814605e-05 |

The order is the first occurrence of each cluster in the frozen 12-case manifest: `01`, `05`, `08`, `12`.

## Replay construction

For each selected case, processed sequentially:

1. Reconstruct the archived balanced source schedule through the existing runtime and require the schedule, bus-phase-time, and baseline hashes to match the archived member.
2. Form the exact D1-R-Lite boundary-infeasible schedule using `baseline + (alpha_transfer + 0.002) * (source_schedule - baseline)`.
3. Extract only the archived witness slot and its frozen native load scale.
4. Build three independent corrected three-phase network objects using the same feeder, static fleet frame, topology, load scale, formal constraints, and archived control initialization.
5. In each fresh context, reproduce the archived pre-target solve state under the native solver settings: replay every baseline slot sharing the selected load scale, then replay only earlier changed boundary-schedule slots sharing that scale. Exact baseline columns remain reused without a solve, matching the archived audit.
6. Keep controls off for the target evaluation, as in the archived audit. After the common pre-target state is reconstructed, change only the final solve convergence tolerance and maximum iteration cap.
7. Aggregate the same fleet-by-slot EV powers to the network groups and evaluate the same target power vector.
8. Read the same archived voltage metric, global voltage extrema, convergence flag, numerical-failure evidence, iteration count, and observed solver settings.

No schedule optimization, phase reassignment, alpha refinement, control redesign, IEEE13 evaluation, or full-trajectory classification is permitted.

Each tolerance receives a fresh OpenDSS context so a tighter evaluation cannot warm-start a later one. The three contexts receive the same deterministic archived pre-target history under `NATIVE_1E4`; the sensitivity intervention is deliberately limited to the final controls-off target solve. This pre-target reconstruction is required because a direct cold-context replay of pair 01 differed from the archive by `4.360789773727447e-08 pu`, while reproducing the archived context history reduced the difference to `4.440892098500626e-16 pu`. The setup solves are identity reconstruction, not additional target evaluations.

## Solver settings

The three settings are frozen in this order:

| Label | Convergence tolerance | Maximum iterations |
|---|---:|---:|
| `NATIVE_1E4` | 1e-4 | 15 |
| `TIGHT_1E6` | 1e-6 | 100 |
| `ULTRA_1E8` | 1e-8 | 100 |

`MaxControlIterations` remains 100, but controls remain off during the target evaluation. The convergence tolerance is a power-flow solver setting and must not be described as a voltage-pu error bound.

There are exactly 12 target replay evaluations: four cases times three solver settings. Independent network initialization requires additional setup solves; reports must call 12 the target-evaluation count, not the total internal OpenDSS solve-call count.

## Numerical decision rules

The existing pilot physical classifier uses a `1e-7` margin before recording a voltage violation. N1 preserves that rule.

For each selected case:

1. **Native replay identity:** the `NATIVE_1E4` voltage at the archived metric must differ from the archived value by at most `1e-9 pu`; the metric, limit, direction, schedule hash, slot, and load scale must match exactly.
2. **Convergence:** all three target evaluations must converge without numerical-failure evidence.
3. **Witness persistence:** at both tighter settings, the same metric must remain above `limit + 1e-7` and must appear as a physical `hi` violation.
4. **Native-to-tight drift:** the absolute metric-value difference between each tighter setting and the native replay must not exceed `1e-6 pu`, one tenth of the N0 reporting guard band.
5. **Tight-setting plateau:** the absolute difference between `TIGHT_1E6` and `ULTRA_1E8` must not exceed `1e-7 pu`.

The drift thresholds are numerical-audit thresholds, not engineering safety margins.

Aggregate decisions:

- `NUMERICALLY_STABLE_SELECTED_WITNESSES`: all four cases satisfy all five rules.
- `NUMERICAL_SENSITIVITY_DETECTED`: native identity and convergence succeed, but at least one tighter replay loses the witness or exceeds a drift threshold.
- `STOP_REPLAY_IDENTITY_MISMATCH`: a native single-slot replay does not reproduce its archive within the frozen identity tolerance; stop without interpreting tighter settings.
- `STOP_SOLVER_FAILURE`: a requested setting is not applied exactly, a solve does not converge, or formal metric coverage is incomplete.

No fallback tolerance, case substitution, or threshold fitting is allowed.

## Interpretation boundary

If the result is `NUMERICALLY_STABLE_SELECTED_WITNESSES`, the permitted statement is:

> For the four selected LV906 fixed-trajectory witness slots, the archived voltage-limit crossings persisted under independent final-solve convergence settings of `1e-4`, `1e-6`, and `1e-8` within the frozen numerical drift thresholds.

This would show that the selected sub-`1e-5 pu` crossings are reproducible physical-boundary witnesses under the tested solver settings. It would not change the N0 arithmetic: the `1e-5 pu` guard-band support remains 6/12. Instead, it would show that N0 measured sensitivity to a reporting-margin definition rather than establishing solver noise for the selected points.

If numerical sensitivity is detected, the solver/audit method must be revised before any larger experiment.

Neither outcome proves all 12 cases, cross-feeder causality, unique mechanism, line-thermal safety, or feasibility after three-phase reoptimization. `formal_v2_1_run_authorized=false` under every outcome.

## Independent namespace and outputs

- Config: `config/numerical_certainty_replay_v2_1_d1r_lite.json`
- Logic: `src/evflex/numerical_certainty_replay_d1r_lite.py`
- Runner: `scripts/run_numerical_certainty_replay_v2_1_d1r_lite.py`
- Evaluator: `scripts/evaluate_numerical_certainty_replay_v2_1_d1r_lite.py`
- Case artifacts: `results/numerical_certainty_replay_v2_1_d1r_lite/cases/case_{pair_id}.json`
- Machine report: `reports/numerical_certainty_replay_v2_1_d1r_lite.json`
- Chinese report: `reports/numerical_certainty_replay_v2_1_d1r_lite.md`
- Replay table: `reports/numerical_certainty_replay_v2_1_d1r_lite.csv`
- Evidence hashes: `reports/numerical_certainty_replay_hashes_v2_1_d1r_lite.csv`

Case artifacts are written atomically and support immutable-prefix resume. The evaluator requires all four artifacts for a stable/sensitivity result, but can report a shorter continuous prefix only when its last artifact is a controlled `STOP_*`. It is deterministic and supports byte-for-byte `--verify-existing` without writing.

## Resource and failure policy

- One Python process, one worker, and all six numeric thread variables set to `1`.
- One case is held in memory at a time; contexts are released before the next case.
- A run lock prevents concurrent execution.
- Existing D1, pilot, D1-R-Lite, and N0 files are read-only and must remain byte-identical.
- Any unexpected existing result, attempt file, temporary, duplicate case, malformed JSON, or source-hash drift causes a controlled stop.
- Formal V2.1 directories or reports remain forbidden.

## Verification standard

- Tests are written and observed failing before production functions are added.
- Unit tests cover exact selection, tie-breaking, source drift, solver-setting readback, metric extraction, every decision branch, and strict artifact validation.
- Integration tests use the real runtime for a minimal in-memory setting/readback check without writing production results.
- Runner tests cover sequential execution, lock handling, atomic persistence, immutable resume, and controlled stops.
- Evaluator tests cover deterministic JSON/CSV/Chinese Markdown, source/code provenance, and byte verification.
- Before execution, the full existing test suite and all four predecessor verifiers pass.
- After execution, the new evaluator verifies byte-for-byte, the full suite passes, predecessor verifiers still pass, old evidence has zero diff, and the worktree is clean.
