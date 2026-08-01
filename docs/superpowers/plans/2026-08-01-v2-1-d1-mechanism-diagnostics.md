# V2.1 D1 Mechanism Diagnostics Implementation Plan

> **Execution amendment (2026-08-01):** At the user's direction, continue with `superpowers:executing-plans` in the main task only. Do not dispatch subagents. Perform separate specification, code-quality, and scientific review passes locally. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run the frozen 12-pair D1 diagnostic that reproduces the archived LV906 boundary failures, preserves explicit first-slot physical witnesses, compares matched IEEE13 design units, and emits a conservative Chinese scientific decision without starting formal V2.1.

**Architecture:** Keep `src/evflex/pilot.py` byte-identical. A new pure protocol module validates frozen inputs, reconstructs archived balanced schedules through the existing runtime, compacts targeted audit evidence, computes exact count-matching diagnostics, and validates one terminal JSON per pair. A sequential runner owns preflight, locks, resume, and atomic writes; a separate read-only evaluator rebuilds deterministic CSV/JSON/Chinese Markdown reports and supports byte-for-byte `--verify-existing`.

**Tech Stack:** Python 3.12, NumPy, pandas only where the existing scripts already require it, pytest, PowerShell, Git, and the existing `evflex.pilot` runtime. All test and production commands use one process and one numeric thread.

---

## Frozen execution rules

- Do not edit `src/evflex/pilot.py`; its required SHA-256 is `37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b`.
- Do not write under `results/pilot_v2_1/` or replace any archived pilot report.
- Do not start a formal V2.1 rerun, a new alpha search, a tie-break audit, timing work, or three-phase re-optimization.
- All commands below begin from the worktree root and set `PYTHONPATH=src` plus the six numeric-thread variables to `1`.
- A scientific contradiction produces `STOP_IMPLEMENTATION`; it is not repaired or reinterpreted during D1.
- Pair terminal status is exactly one of `SUCCESS`, `STOP_IMPLEMENTATION`, or `UNHANDLED_FAILURE`. Every terminal artifact is immutable on resume. `STOP_IMPLEMENTATION` and `UNHANDLED_FAILURE` stop all later pairs.
- Runtime state paths are exactly `results/mechanism_diagnostic_v2_1/.run.lock`, `results/mechanism_diagnostic_v2_1/.attempts/pair_XX.json`, and pair temporary files matching `results/mechanism_diagnostic_v2_1/pairs/pair_XX.json*.tmp`. Report temporaries match each frozen report path plus `*.tmp`.
- Generated reports are never hand-edited. Fix deterministic generation, rebuild, and re-verify instead.

Use this PowerShell preamble for every Python or pytest command:

```powershell
$env:Path="$(Resolve-Path -LiteralPath '.venv\Scripts');$env:Path"
$env:PYTHONPATH='src'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
$env:VECLIB_MAXIMUM_THREADS='1'
$env:BLIS_NUM_THREADS='1'
python -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version"
```

## Task 1: Freeze and strictly load the D1 protocol and pair manifest

**Files:**

- Create: `config/mechanism_diagnostic_v2_1.json`
- Create: `manifests/mechanism_diagnostic_pairs_v2_1.csv`
- Create: `src/evflex/mechanism_diagnostic.py`
- Create: `tests/test_mechanism_diagnostic.py`

- [x] **Step 1: Write failing config and manifest tests**

Add tests named:

- `test_load_config_requires_exact_frozen_contract`
- `test_load_pair_manifest_has_exact_12_pairs_and_24_sources`
- `test_manifest_matches_archived_evaluation_rows`
- `test_manifest_rejects_duplicate_or_mutated_identity`
- `test_source_hash_drift_is_rejected`

The tests must assert exact pair order `01` through `12`, exact bad/control IDs from the design, four scenario-cluster IDs, matching call time/direction/duration, all 12 bad alpha values, all control `alpha_transfer == 1.0`, archived scenario seeds, requested/source durations, schedule hashes, baseline schedule hashes, and source work-unit IDs.

- [x] **Step 2: Run the focused tests and confirm RED**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'load_config or manifest or source_hash' -q -p no:faulthandler
```

Expected: fail because the D1 module and frozen files do not exist.

- [x] **Step 3: Add the smallest strict loader**

The config must freeze:

- protocol and artifact names;
- expected pair/source/audit counts `12`, `24`, and `72`;
- all archived source paths and SHA-256 values;
- the frozen `pilot.py` SHA-256;
- audit delta `0.002` and point order;
- family order `VMIN`, `VMAX`, `VUF`, `TRANSFORMER`, `FEEDER`;
- candidate thresholds `8/12` and `3/4` scenario clusters;
- exact count thresholds `4/5` and `1/5`, minimum eligible rows `4`, and fraction-display precision `12`;
- relative-stress reason code and `null` numeric fields;
- `line_thermal_in_scope=false`, `workers=1`, and all six numeric-thread settings equal to `1`.

The CSV must have one row per pair and freeze both roles. Required columns are:

```text
pair_id,scenario_cluster,bad_evaluation_id,bad_work_unit_id,bad_scenario_id,
bad_scenario_seed,bad_feeder,bad_call_time,bad_direction,duration_min,
bad_alpha_transfer,bad_source_duration_min,bad_schedule_sha256,
bad_bus_phase_time_sha256,
bad_baseline_schedule_sha256,control_evaluation_id,control_work_unit_id,
control_scenario_id,control_scenario_seed,control_feeder,control_call_time,
control_direction,control_alpha_transfer,control_source_duration_min,
control_schedule_sha256,control_bus_phase_time_sha256,
control_baseline_schedule_sha256
```

Read the archived CSV and pair JSON files only to transcribe these values. The committed D1 manifest, not runtime row order, becomes the authority after this task.

Implement these public functions and data structures in `mechanism_diagnostic.py`:

```python
load_mechanism_config(repo_root: str | Path) -> dict[str, Any]
load_pair_manifest(repo_root: str | Path) -> list[dict[str, Any]]
verify_frozen_sources(repo_root: str | Path, config: Mapping[str, Any]) -> None
pair_members(pair: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]
```

Use `csv.DictReader`, duplicate-header/duplicate-key rejection, strict integer/finite-float parsing, exact key sets, SHA-256 regex validation, path containment checks, and deterministic pair ordering. Reject NaN, Infinity, unexpected columns, missing source IDs, and any mismatch with `results/pilot_v2_1/pilot_evaluations_v2_1.csv`.

- [x] **Step 4: Run focused tests and confirm GREEN**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'load_config or manifest or source_hash' -q -p no:faulthandler
```

- [x] **Step 5: Verify frozen pilot compatibility**

```powershell
(Get-FileHash -Algorithm SHA256 -LiteralPath 'src/evflex/pilot.py').Hash.ToLowerInvariant()
python scripts/evaluate_pilot_gate_v2_1.py --verify-existing
```

Expected: exact frozen hash; old verifier returns exit `0`, `verified=true`, and no errors.

- [x] **Step 6: Commit Task 1**

```powershell
git add config/mechanism_diagnostic_v2_1.json manifests/mechanism_diagnostic_pairs_v2_1.csv src/evflex/mechanism_diagnostic.py tests/test_mechanism_diagnostic.py
git diff --cached --check
git commit -m "feat: freeze D1 mechanism protocol"
```

## Task 2: Preserve complete first-slot physical evidence without changing physics

**Files:**

- Modify: `src/evflex/mechanism_diagnostic.py`
- Modify: `tests/test_mechanism_diagnostic.py`

- [ ] **Step 1: Write failing synthetic evidence tests**

Add tests named:

- `test_constraint_rows_emit_both_voltage_bounds_and_fixed_order`
- `test_constraint_rows_cover_all_five_families_and_exclude_lines`
- `test_compactor_retains_all_simultaneous_first_slot_violations`
- `test_compactor_uses_explicit_physical_witness_not_headroom_sign`
- `test_compactor_rejects_numerical_or_incomplete_metric_evidence`
- `test_compactor_validates_early_stop_and_96_slot_feasible_coverage`

Synthetic slot results must use the existing shape `slot_result['result']['metrics']`, `slot_result['result']['violations']`, `slot_result['audit_context']`, and `slot_result['coverage']`. Include a voltage value within `1e-7` of a limit so the test proves that explicit evaluator violations, not `signed_headroom < 0`, define `is_physical_violation`.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'constraint_rows or compactor' -q -p no:faulthandler
```

- [ ] **Step 3: Implement pure evidence extraction**

Add:

```python
constraint_rows_from_slot(slot_result: Mapping[str, Any]) -> list[dict[str, Any]]
compact_targeted_audit(
    raw: Mapping[str, Any],
    *,
    audit_point: str,
    alpha: float,
    capture_slot: int | None = None,
) -> dict[str, Any]
```

Map labels exactly:

- `V:*` -> one `VMIN/lo` row and one `VMAX/hi` row;
- `U:*` -> `VUF/hi`;
- `S:transformer:*` -> `TRANSFORMER/hi`;
- `S:feeder` -> `FEEDER/hi`.

Reject all other monitored labels, any `LINE` family, non-finite values, duplicate metric IDs within a family, inconsistent limits, incomplete formal coverage, or `line_thermal_in_scope` other than false. Sort with the frozen family order, then `metric_id`, then direction.

Derive `object_id` without normalization beyond removing the exact prefix: the suffix after `V:`, `U:`, or `S:transformer:`; use literal `feeder` for `S:feeder`. Reject empty or duplicate object IDs.

For lower bounds compute `value-limit`; for upper bounds compute `limit-value`; compute `exceedance=max(0,-signed_headroom)`. Mark violations only by matching the original evaluator's explicit `physical_constraint` records on metric ID and direction, and validate their value/limit against the metric row.

For an early-stopped physical failure require:

```text
checked_intervals == first_failure_slot + 1
last retained slot == first_failure_slot
physical witness exists and is finite
all declared metrics for that slot are present
```

For a feasible audit require 96 checked and retained trace slots. Persist only the selected first/capture-slot detailed metrics, not all 96 full slot payloads.

- [ ] **Step 4: Confirm GREEN and regression safety**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'constraint_rows or compactor' -q -p no:faulthandler
python -m pytest tests/test_pilot.py -q -p no:faulthandler
```

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/evflex/mechanism_diagnostic.py tests/test_mechanism_diagnostic.py
git diff --cached --check
git commit -m "feat: preserve D1 physical witnesses"
```

## Task 3: Implement exact count matching and conservative candidate classification

**Files:**

- Modify: `src/evflex/mechanism_diagnostic.py`
- Modify: `tests/test_mechanism_diagnostic.py`

- [ ] **Step 1: Write failing exact-probability and classification tests**

Add tests named:

- `test_exact_count_probability_preserves_fraction_and_display`
- `test_exact_count_probability_handles_n_minus_k_below_m`
- `test_count_match_uses_unique_explicit_violation_objects_only`
- `test_count_match_excludes_not_applicable_rows_from_denominator`
- `test_candidate_families_use_boundary_infeasible_and_scenario_clusters_only`
- `test_candidate_families_allow_multiple_in_fixed_order`
- `test_relative_stress_is_null_with_frozen_reason`

Freeze examples:

- `N=10, K=2, m=3` -> exact `8/15`, display `0.533333333333`;
- `N=5, K=4, m=2` -> exact `1/1` because `N-K<m`;
- threshold comparisons use exact cross multiplication against `4/5` and `1/5`, never the 12-decimal display;
- fewer than four eligible rows -> `COUNT_MATCH_NOT_APPLICABLE`;
- `NOT_APPLICABLE` rows never enter `n_eligible` or the 80% count.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'count_probability or count_match or candidate_families or relative_stress' -q -p no:faulthandler
```

- [ ] **Step 3: Implement pure diagnostics**

Add:

```python
exact_count_match_probability(N: int, K: int, m: int) -> dict[str, Any]
build_count_match_rows(pair_artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]
classify_count_match(rows: Sequence[Mapping[str, Any]], family: str) -> dict[str, Any]
candidate_families(pair_artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]
```

Use `math.comb`, integer numerator/denominator reduction, `Decimal` with `ROUND_HALF_EVEN` only for a fixed-width 12-decimal string display, and exact integer cross multiplication for thresholds. Count unique metric IDs explicitly marked as physical violations. Apply count matching only to `VMIN`, `VMAX`, and `VUF` at bad `BOUNDARY_INFEASIBLE` first-failure slots; use the paired control's object count at that same slot and fraction.

Candidate families use only explicit bad `BOUNDARY_INFEASIBLE` first-slot violations. A family qualifies at `>=8` cases and `>=3` scenario clusters, where a cluster is covered if at least one case from that scenario ID contains the family. Emit every qualifying family in the fixed five-family order and never name a primary mechanism.

- [ ] **Step 4: Confirm GREEN**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'count_probability or count_match or candidate_families or relative_stress' -q -p no:faulthandler
```

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/evflex/mechanism_diagnostic.py tests/test_mechanism_diagnostic.py
git diff --cached --check
git commit -m "feat: add exact D1 confound diagnostics"
```

## Task 4: Reconstruct frozen schedules and execute one paired diagnostic

**Files:**

- Modify: `src/evflex/mechanism_diagnostic.py`
- Modify: `tests/test_mechanism_diagnostic.py`

- [ ] **Step 1: Write failing fake-runtime tests**

Add tests named:

- `test_reconstruct_case_matches_archived_schedule_and_baseline_hashes`
- `test_reconstruct_case_rejects_bus_phase_time_hash_drift`
- `test_reconstruct_case_rejects_source_duration_or_schedule_drift`
- `test_execute_pair_uses_fixed_schedule_interpolation_without_reoptimization`
- `test_execute_pair_builds_each_truth_cache_and_baseline_once`
- `test_execute_pair_runs_exact_six_audits_and_captures_control_at_bad_slot`
- `test_execute_pair_rejects_numerical_failure_or_missing_bad_witness`

The fake runtime must expose only the existing methods and attributes used by `_RealPilotRuntime`: `fleet`, `baseline`, `load_scales`, `generate_balanced_raw`, `create_corrected_truth_cache`, and `audit_corrected`. It must fail the test if a tie-break, legacy verifier, optimizer, alpha search, timing path, or process pool is invoked.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'reconstruct_case or execute_pair' -q -p no:faulthandler
```

- [ ] **Step 3: Implement reconstruction through the frozen pilot runtime**

Add:

```python
reconstruct_case(
    repo_root: str | Path,
    member: Mapping[str, Any],
    *,
    pilot_config: Mapping[str, Any] | None = None,
    runtime_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]

execute_pair(
    repo_root: str | Path,
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    runtime_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]
```

When no test factory is injected, call only these frozen pilot APIs:

```python
pilot.load_pilot_config(repo_root)
pilot._create_real_pilot_runtime(repo_root, work_unit, pilot_config)
runtime.generate_balanced_raw(source_duration_min, 'balanced')
pilot._normalize_raw_balanced_result(...)
pilot.canonical_schedule_sha256(runtime.fleet, schedule)
pilot._canonical_bus_phase_time_sha256(runtime.fleet, schedule)
runtime.create_corrected_truth_cache()
runtime.audit_corrected(...)
```

Validate canonical schedule, bus-phase-time, and baseline hashes before any targeted audit. Audit each case baseline once with complete 96-slot coverage and retain those slot results for exact baseline reuse. Build each audit input as `baseline + alpha*(schedule-baseline)`.

Execute in the only permitted order: `BOUNDARY_FEASIBLE/bad`, `BOUNDARY_FEASIBLE/control`, `BOUNDARY_INFEASIBLE/bad`, `BOUNDARY_INFEASIBLE/control`, `FULL_OFFER/bad`, `FULL_OFFER/control`. At `BOUNDARY_INFEASIBLE`, run the bad member first and compact the control's full audit at the bad first-failure slot. Bad `BOUNDARY_INFEASIBLE` and `FULL_OFFER` may early stop at a physical witness; bad `BOUNDARY_FEASIBLE` and every control must complete 96 slots. A success mapping contains exactly two roles by three points, source identities, resource policy, schedule/audit-input hashes, and the frozen relative-stress reason with null ratios.

Freeze `audit_input_sha256` as SHA-256 over canonical UTF-8 JSON containing exactly: protocol version, pair/role/source evaluation identity, audit-point name, alpha as a fixed three-decimal string (`0.940`, `0.942`, `1.000`), baseline schedule hash, source schedule hash, audited schedule hash, load-scales hash, and the formal constraint mapping copied from the frozen pilot config. Canonical JSON uses sorted keys, separators `(',', ':')`, `ensure_ascii=False`, `allow_nan=False`, and no trailing newline. The load-scales hash is SHA-256 over the domain prefix `b'evflex.d1.load-scales.v1\0'` followed by the contiguous little-endian float64 bytes of exactly 96 values. Full nonviolating margin rows are persisted only for bad `BOUNDARY_INFEASIBLE` at its first failure slot and its control at that same slot/fraction, and only for VMIN/VMAX/VUF. Bad `BOUNDARY_INFEASIBLE` and `FULL_OFFER` still persist every explicit simultaneous witness across all five families.

- [ ] **Step 4: Confirm GREEN and check no frozen-code edit**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py -k 'reconstruct_case or execute_pair' -q -p no:faulthandler
(Get-FileHash -Algorithm SHA256 -LiteralPath 'src/evflex/pilot.py').Hash.ToLowerInvariant()
```

- [ ] **Step 5: Commit Task 4**

```powershell
git add src/evflex/mechanism_diagnostic.py tests/test_mechanism_diagnostic.py
git diff --cached --check
git commit -m "feat: execute fixed-schedule D1 pairs"
```

## Task 5: Add strict pair artifacts, sequential runner, atomic writes, and resume

**Files:**

- Modify: `src/evflex/mechanism_diagnostic.py`
- Create: `scripts/run_mechanism_diagnostic_v2_1.py`
- Modify: `tests/test_mechanism_diagnostic.py`
- Create: `tests/test_mechanism_runner.py`

- [ ] **Step 1: Write failing artifact and runner tests**

Add tests named:

- `test_validate_pair_artifact_requires_exact_identity_and_six_audits`
- `test_validate_pair_artifact_rejects_nonfinite_or_duplicate_content`
- `test_runner_is_sequential_and_enforces_six_thread_caps`
- `test_runner_atomically_writes_one_terminal_json_per_pair`
- `test_runner_resumes_only_strictly_valid_completed_pair`
- `test_runner_stops_on_invalid_existing_pair_lock_attempt_or_tmp`
- `test_runner_preflight_checks_old_gate_and_forbids_formal_outputs`
- `test_stop_artifact_contains_only_continuous_audit_prefix`
- `test_runner_stop_reason_is_first_failed_rule_and_no_later_pair_runs`

Load the script in tests with `importlib.util`, inject a fake `execute_pair`, and assert no `ProcessPoolExecutor` is created.

- [ ] **Step 2: Confirm RED**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py tests/test_mechanism_runner.py -k 'artifact or runner' -q -p no:faulthandler
```

- [ ] **Step 3: Implement strict terminal validation**

Add to the module:

```python
validate_pair_artifact(
    artifact: Mapping[str, Any],
    pair: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None
canonical_json_bytes(value: Any) -> bytes
strict_json_file(path: Path) -> dict[str, Any]
```

Reject duplicate JSON keys, NaN/Infinity, unknown/missing keys, wrong order, wrong hashes, inconsistent alpha labels, incomplete feasible audits, invalid early stops, missing simultaneous witnesses, non-null stress ratios, any line-thermal scope, and any source or resource-policy mismatch.

- [ ] **Step 4: Implement the sequential runner**

The runner must:

- set and validate all six thread variables before importing NumPy or any `evflex` scientific module;
- insert `src` into `sys.path` when invoked directly;
- expose `--preflight-only` and optional `--pair-id` for bounded recovery/testing;
- verify config/manifest/source hashes and the frozen `pilot.py` hash;
- invoke the archived gate's read-only `--verify-existing` contract with `PYTHONPATH=src`;
- reject dirty source evidence, unexpected D1 pair files, live/dead locks requiring inspection, attempt state, and temporary files;
- reuse `evflex.runner.exclusive_lock` and `evflex.runner.atomic_write_json` for one exclusive run lock and atomic terminal writes;
- execute selected pairs in manifest order in the current process;
- skip only an existing artifact that passes the full D1-specific validator;
- atomically write `results/mechanism_diagnostic_v2_1/pairs/pair_XX.json` with flush, fsync, and `os.replace`;
- never call the archived runner's three-evaluation/single-ablation expected-ID logic;
- print a strict JSON summary and return nonzero on any implementation or provenance failure.

`validate_pair_artifact` dispatches strictly by status. `SUCCESS` requires exactly all six audits and permits the next pair. `STOP_IMPLEMENTATION` records the exact first frozen-rule contradiction and may contain only a continuous prefix of the six-audit sequence, ending at the audit that exposed that contradiction; a zero-length prefix is allowed only when the frozen rule fails before the first audit. It stops before the next pair and may not omit an earlier audit or retain anything after the stop point. `UNHANDLED_FAILURE` records exact pair identity plus exception type/message after controlled handling and follows the same continuous-prefix rule, including zero length when the exception precedes auditing. Resume validates and skips `SUCCESS`; it validates then immediately re-emits the stop for either failure status. It never overwrites or recomputes any terminal status.

The runner creates `results/mechanism_diagnostic_v2_1/.attempts/pair_XX.json` immediately before pair execution and removes it only after a terminal pair JSON has been atomically written and strictly revalidated. A crash therefore leaves explicit attempt evidence and the next preflight stops for inspection. Pair and report temporary-file scans use only the frozen patterns above.

- [ ] **Step 5: Confirm GREEN**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py tests/test_mechanism_runner.py -k 'artifact or runner' -q -p no:faulthandler
python scripts/run_mechanism_diagnostic_v2_1.py --preflight-only
```

Preflight must perform no schedule solve, power flow, or output write. It rejects drift or dirtiness only in the archived source/evidence paths and frozen pilot files; it does not require the new D1 implementation files to be committed during Tasks 1-6. Task 8 separately requires a clean reviewed D1 code commit before production.

- [ ] **Step 6: Commit Task 5**

```powershell
git add src/evflex/mechanism_diagnostic.py scripts/run_mechanism_diagnostic_v2_1.py tests/test_mechanism_diagnostic.py tests/test_mechanism_runner.py
git diff --cached --check
git commit -m "feat: add resumable D1 diagnostic runner"
```

## Task 6: Build the frozen gate and read-only deterministic evaluator

**Files:**

- Modify: `src/evflex/mechanism_diagnostic.py`
- Create: `scripts/evaluate_mechanism_diagnostic_v2_1.py`
- Create: `tests/test_mechanism_evaluator.py`
- Modify: `tests/test_mechanism_diagnostic.py`

- [ ] **Step 1: Write failing gate tests**

Add tests named:

- `test_gate_stops_on_any_bad_boundary_or_full_offer_contradiction`
- `test_gate_stops_on_any_control_failure_or_numerical_failure`
- `test_gate_stops_on_early_stop_coverage_or_provenance_error`
- `test_gate_returns_valid_heterogeneous_without_candidate_family`
- `test_gate_returns_common_candidate_confounded_and_lists_all_candidates`

The structural gate must require all 11 conditions in the design. A qualifying common family can produce only `COMMON_CANDIDATE_CONFOUNDED`, because the frozen relative-stress confound is unresolved. Neither successful branch may alter the archived pilot `NO_GO` or authorize formal V2.1.

- [ ] **Step 2: Write failing evaluator tests**

Add tests named:

- `test_valid_classification_requires_exact_12_success_pairs_and_no_state_files`
- `test_evaluator_builds_deterministic_72_row_audit_csv`
- `test_evaluator_failure_prefix_report_covers_actual_rows_and_lists_missing_pairs`
- `test_evaluator_writes_conservative_chinese_markdown`
- `test_evaluator_hash_csv_covers_all_pair_artifacts`
- `test_verify_existing_is_read_only_and_detects_byte_tampering`

The Chinese Markdown assertions must include the fixed-schedule evidence boundary, `line_thermal_in_scope=false`, the unresolved relative-stress confound, candidate families or heterogeneous result, the unchanged pilot NO_GO, and an explicit statement that D1 does not authorize formal V2.1. They must also say that IEEE13 is only a time/direction/duration-matched design-unit control rather than a causal match, four groups are scenario clusters rather than independent repetitions, and count matching is only detection sensitivity after matching object counts and neither proves nor excludes a count effect. A failure-prefix report must state that D1 did not complete.

- [ ] **Step 3: Confirm RED**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py tests/test_mechanism_evaluator.py -k 'gate or evaluator or verify_existing' -q -p no:faulthandler
```

- [ ] **Step 4: Implement aggregation and deterministic reports**

Add:

```python
assess_mechanism_gate(
    pair_artifacts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]
```

The evaluator strictly reads the terminal pair files. Twelve `SUCCESS` files are required for either valid diagnostic classification; a smaller deterministic prefix ending in `STOP_IMPLEMENTATION` or `UNHANDLED_FAILURE` is sufficient to build a failure report, but never a valid classification. It emits:

- `reports/mechanism_diagnostic_audits_v2_1.csv`: exactly 72 deterministic audit rows only for 12 successful pairs; otherwise exactly the completed continuous audit prefix;
- `reports/mechanism_diagnostic_v2_1.json`: decision, all structural checks, candidate list, exact count rows/classifications, source/code provenance, resource policy, and evidence limitations;
- `reports/mechanism_diagnostic_v2_1.md`: Chinese reviewer-facing report generated from the JSON;
- `reports/mechanism_diagnostic_hashes_v2_1.csv`: SHA-256 rows for all 12 pair JSON files on success, or only the existing ordered terminal prefix on failure.

Use canonical UTF-8, `\n` line endings, stable key/row ordering, finite-only JSON, and atomic writes. A failure JSON lists all missing pair IDs and cannot carry a valid classification. Normal evaluation returns exit `0` for either structurally valid diagnostic classification and exit `1` for `STOP_IMPLEMENTATION`, `UNHANDLED_FAILURE`, or artifact invalidity. `--verify-existing` rebuilds the same success or failure-mode artifact set in memory or a system temporary directory and compares without writing any workspace file; verification returns exit `0` when existing bytes and inventory reproduce exactly even if their terminal decision is `STOP_IMPLEMENTATION` or `UNHANDLED_FAILURE`, and exit `1` only for verification/integrity failure.

- [ ] **Step 5: Confirm GREEN**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py tests/test_mechanism_evaluator.py -k 'gate or evaluator or verify_existing' -q -p no:faulthandler
```

- [ ] **Step 6: Commit Task 6**

```powershell
git add src/evflex/mechanism_diagnostic.py scripts/evaluate_mechanism_diagnostic_v2_1.py tests/test_mechanism_diagnostic.py tests/test_mechanism_evaluator.py
git diff --cached --check
git commit -m "feat: evaluate D1 mechanism gate"
```

## Task 7: Complete code verification and freeze the production commit

**Files:**

- Modify only files identified by review findings

- [ ] **Step 1: Run focused D1 tests**

```powershell
python -m pytest tests/test_mechanism_diagnostic.py tests/test_mechanism_runner.py tests/test_mechanism_evaluator.py -q -p no:faulthandler
```

- [ ] **Step 2: Run the complete suite with low resources**

```powershell
python -m pytest -q -p no:faulthandler
```

- [ ] **Step 3: Run immutable regressions and preflight**

```powershell
(Get-FileHash -Algorithm SHA256 -LiteralPath 'src/evflex/pilot.py').Hash.ToLowerInvariant()
python scripts/evaluate_pilot_gate_v2_1.py --verify-existing
python scripts/run_mechanism_diagnostic_v2_1.py --preflight-only
git diff --exit-code e1740f9 -- src/evflex/pilot.py scripts/run_pilot_gate_v2_1.py scripts/evaluate_pilot_gate_v2_1.py config/pilot_gate_v2_1.json manifests/audit_pilot_work_units_v2_1.csv results/pilot_v2_1 reports/pilot_gate_v2_1.json reports/pilot_gate_v2_1.md reports/pilot_work_unit_hashes_v2_1.csv
git diff --check
git status --short
```

Expected: frozen hash; old verifier passes; D1 preflight passes without writes; no unexpected changes.

- [ ] **Step 4: Perform separate specification and code-quality review passes**

Reviewers must verify:

- exact compliance with the frozen design and all 11 structural conditions;
- no edit to `pilot.py` or archived evidence;
- no hidden alpha search, optimization, timing, tie-break, line constraint, or process pool;
- explicit simultaneous witnesses and original `1e-7` violation semantics;
- exact rational count thresholds and conservative language;
- strict resume, atomic write, and read-only verification behavior.

- [ ] **Step 5: Address findings test-first and rerun Steps 1-3**

Every behavior fix gets a reproducing failing test first. Documentation-only corrections still run `git diff --check` and relevant tests.

- [ ] **Step 6: Commit final reviewed code and record the clean HEAD**

```powershell
git add config manifests src scripts tests docs
git diff --cached --check
git commit -m "fix: close D1 diagnostic review findings"
git status --short
git rev-parse HEAD
```

If no review changes exist, do not create an empty commit. The clean current HEAD is the frozen production code identity.

## Task 8: Run the real 12-pair diagnostic sequentially

**Files generated only:**

- `results/mechanism_diagnostic_v2_1/pairs/pair_01.json` through `pair_12.json`

- [ ] **Step 1: Re-run preflight immediately before production**

```powershell
python scripts/run_mechanism_diagnostic_v2_1.py --preflight-only
git status --short
```

Require a clean code worktree and no D1 state files before the first run.

- [ ] **Step 2: Run all pairs in manifest order**

```powershell
python scripts/run_mechanism_diagnostic_v2_1.py
```

Run in the foreground with one process and one numeric thread. Do not launch another pair runner concurrently. A valid resume may skip already verified terminal pair files after an interruption.

- [ ] **Step 3: Inspect terminal state without inferring from CPU activity**

```powershell
Get-ChildItem -LiteralPath 'results/mechanism_diagnostic_v2_1/pairs' -File | Select-Object Name,Length
Get-ChildItem -LiteralPath 'results/mechanism_diagnostic_v2_1' -Recurse -Force | Where-Object { $_.Name -match '\.(lock|tmp)$|attempt' } | Select-Object FullName
```

Require exactly 12 `SUCCESS` pair JSON files for a completed diagnostic and no lock, attempt, or temporary state. If the runner stops earlier, require an ordered successful prefix followed by exactly one immutable `STOP_IMPLEMENTATION` or `UNHANDLED_FAILURE` terminal artifact and no later pair; preserve that evidence and do not broaden the run.

## Task 9: Evaluate, independently review, and archive the D1 decision

**Files generated:**

- `reports/mechanism_diagnostic_audits_v2_1.csv`
- `reports/mechanism_diagnostic_v2_1.json`
- `reports/mechanism_diagnostic_v2_1.md`
- `reports/mechanism_diagnostic_hashes_v2_1.csv`

- [ ] **Step 1: Build the reports**

```powershell
python scripts/evaluate_mechanism_diagnostic_v2_1.py
```

An exit `1` with `STOP_IMPLEMENTATION` is a scientific/structural result to investigate; an exit `1` with `UNHANDLED_FAILURE` is an implementation/infrastructure failure to preserve and diagnose. Neither is permission to rewrite the gate.

- [ ] **Step 2: Verify report reproducibility and old evidence immutability**

```powershell
python scripts/evaluate_mechanism_diagnostic_v2_1.py --verify-existing
python scripts/evaluate_pilot_gate_v2_1.py --verify-existing
(Get-FileHash -Algorithm SHA256 -LiteralPath 'src/evflex/pilot.py').Hash.ToLowerInvariant()
```

- [ ] **Step 3: Run full tests once more**

```powershell
python -m pytest -q -p no:faulthandler
```

- [ ] **Step 4: Perform a separate read-only scientific review pass**

The reviewer must reconcile the 12 source alphas, all 72 audit rows, 12 bad brackets, 12 bad full-offer witnesses, 36 feasible control audits, simultaneous violation families, scenario-cluster coverage, exact count fractions, and relative-stress limitation. The reviewer must distinguish:

- machine validity from physical interpretation;
- a common candidate family from a causal or unique mechanism;
- fixed-schedule transfer failure from redispatch infeasibility;
- D1 completion from permission for formal V2.1.

- [ ] **Step 5: Commit only verified generated evidence**

```powershell
git add results/mechanism_diagnostic_v2_1 reports/mechanism_diagnostic_audits_v2_1.csv reports/mechanism_diagnostic_v2_1.json reports/mechanism_diagnostic_v2_1.md reports/mechanism_diagnostic_hashes_v2_1.csv
git diff --cached --check
git commit -m "results: archive V2.1 D1 mechanism diagnostic"
git status --short
```

Do not commit lock, attempt, temporary, cache, or environment files.

- [ ] **Step 6: Apply the frozen decision boundary**

- `STOP_IMPLEMENTATION`: stop, preserve evidence, diagnose the exact contradiction, and do not start formal V2.1.
- `VALID_HETEROGENEOUS`: retain the narrowed research question, report heterogeneous explicit witnesses, and decide separately whether any small confirmation design is worthwhile.
- `COMMON_CANDIDATE_CONFOUNDED`: report every qualifying family as a confounded common candidate and design, but do not execute, a separately frozen small confirmation gate.

No D1 outcome automatically starts a formal V2.1 rerun.
