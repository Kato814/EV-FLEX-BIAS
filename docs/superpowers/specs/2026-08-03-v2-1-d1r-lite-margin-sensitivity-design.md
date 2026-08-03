# V2.1 D1-R-Lite N0 Margin-Sensitivity Design

## Objective

Test the smallest unresolved question raised by the completed D1-R-Lite screen:

> Does the sampled `VMAX` common-candidate classification survive a minimal nonzero voltage-exceedance guard band, or is it driven by near-zero boundary crossings?

This is an artifact-only sensitivity analysis. It performs no new power-flow solve, does not alter the archived D1-R-Lite decision, and does not authorize or start formal V2.1.

## Status and interpretation

The source D1-R-Lite analysis is confirmatory with respect to its own frozen zero-margin physical-witness rule. This N0 analysis is defined after observing the D1-R-Lite result and is therefore a targeted post-result sensitivity check, not an independent confirmation experiment.

Its decision is advisory:

- `MARGIN_ROBUST_AT_1E5`: the sampled `VMAX` candidate retains the original support threshold at a `1e-5 pu` guard band; a separate tight-solver replay protocol may then be frozen.
- `HOLD_MARGIN_FRAGILE_AT_1E5`: the sampled `VMAX` candidate falls below the original support threshold; do not spend work on a solver replay or formal V2.1 until the boundary definition and acceptable engineering margin are redesigned.

Neither outcome proves causality, uniqueness, cross-feeder generality, or feasibility after three-phase reoptimization.

## Immutable inputs

The analysis reads, validates, and hashes only the completed D1-R-Lite evidence at commit `5421ec6c5b6333ba9e8426d4909b4942403b55e7`:

| Input | Frozen SHA-256 |
|---|---|
| `reports/mechanism_diagnostic_v2_1_d1r_lite.json` | `86f7c0d3498da45d01e7008eeca42b6b8265a67bf1337ea5ea569a80d5c71275` |
| `reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv` | `ed58ded0d3581d5b7afcafa23f02b53471d4866c8a1fa9becfeb90060dd1ce94` |
| `reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv` | `b936cb7d1697a0888165afc81e688fdb830e00b7236e81215c8db86b1851b46a` |
| `config/mechanism_diagnostic_v2_1_d1r_lite.json` | `ec69c26761de716ace3b65aa3ad11ff2f5afcdb39d25754a62d98fec8ccd778a` |
| `manifests/mechanism_diagnostic_cases_v2_1_d1r_lite.csv` | `c150a56e7535c09fe1cf361a32f7fd86b424912a8ad286ed8ad8b469047196de` |
| `src/evflex/mechanism_diagnostic_d1r_lite.py` | `8efaa90990225cf1ae7ac99eb2becd7df9bbae0b4271fb544038a405f6ad8fd5` |

All 12 case JSON files must match the archived case-hash CSV and pass `validate_lite_case_artifact`. Existing D1, pilot, and D1-R-Lite artifacts remain byte-identical.

## Frozen sensitivity rule

The source common candidate is exactly `VMAX`. For each guard band in the fixed order

```text
0, 1e-6, 1e-5, 1e-4 pu
```

a case supports `VMAX` when its first-failure simultaneous-violation evidence contains at least one `VMAX` row whose recorded exceedance is greater than or equal to the guard band. Multiple voltage nodes in one case count once. Scenario clusters count once regardless of the number of cases or nodes.

The original support rule is retained without modification:

```text
case_count >= 8 of 12
scenario_cluster_count >= 3 of 4
```

The decisive guard band is `1e-5 pu`, equal to 0.001% of nominal voltage. It is intentionally a very small reporting guard band. It is not an engineering safety margin and must not be equated with OpenDSS's native `1e-4` power-flow convergence setting, which has a different meaning and unit.

`VMIN` support is reported at the same voltage guard bands as a descriptive companion. `VUF`, transformer, and feeder witnesses are reported at the source zero-margin rule only because their native units are not comparable with a voltage-pu guard band.

## Validation and stopping

The analysis stops without reports if any of the following occurs:

- a frozen input hash differs;
- a case file is missing, unexpected, duplicated, malformed, or out of frozen order;
- any case is not `SUCCESS` or lacks its one `BOUNDARY_INFEASIBLE` physical witness;
- the source report is not `COMMON_CANDIDATE_CONFOUNDED` with exactly `VMAX` as its qualifying family;
- the source evidence contains a numerical failure, line thermal scope, or formal V2.1 authorization;
- a recorded constraint row is non-finite or inconsistent with its archived case artifact.

No fallback threshold, tolerance fitting, or family reselection is allowed.

## Outputs

Use a new namespace:

- Config: `config/mechanism_margin_sensitivity_v2_1_d1r_lite.json`
- Logic: `src/evflex/mechanism_margin_sensitivity_d1r_lite.py`
- Evaluator: `scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py`
- Machine report: `reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json`
- Chinese report: `reports/mechanism_margin_sensitivity_v2_1_d1r_lite.md`
- Support table: `reports/mechanism_margin_sensitivity_v2_1_d1r_lite.csv`
- Source hashes: `reports/mechanism_margin_sensitivity_hashes_v2_1_d1r_lite.csv`

Reports are deterministic, atomically written, and support byte-for-byte `--verify-existing`. They record support counts at every guard band, pair IDs, scenario clusters, retained/failing status at `1e-5 pu`, source hashes, code provenance, and the post-result sensitivity limitation.

## Resource and claim boundary

- One Python process and one worker.
- All six numerical thread environment variables equal `1`.
- Zero new power-flow solves and zero new target audits.
- No IEEE13 control, full-offer audit, alpha search, reoptimization, or formal-run path.
- `line_thermal_in_scope=false` and `formal_v2_1_run_authorized=false` under every outcome.

The strongest permitted statement is:

> Under the post-result N0 sensitivity rule, the sampled LV906 fixed-trajectory `VMAX` candidate did or did not retain the original 8/12 and 3/4-cluster support threshold at a `1e-5 pu` recorded-exceedance guard band.

## Verification standard

- Unit tests first demonstrate missing functions and fail for the expected reason.
- Tests prove case-presence counting, exact guard-band order, inclusive threshold behavior, cluster counting, source drift rejection, and the decisive decision code.
- Evaluator tests prove deterministic JSON/CSV/Chinese Markdown and byte-identical verification.
- The full test suite passes with numeric threads capped at one.
- Archived D1, pilot, and D1-R-Lite verifiers still pass, and their evidence paths have zero diff from their frozen commits.
