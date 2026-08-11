# V2.1 D1-R-Lite N1 Numerical-Certainty Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user prohibited subagents, so execute inline in this isolated worktree.

**Goal:** Build and execute a deterministic four-case, three-setting witness-slot replay that distinguishes reproducible near-boundary voltage crossings from OpenDSS final-solve tolerance sensitivity.

**Architecture:** A strict pure module freezes source hashes, derives the four representatives from archived evidence, validates per-setting observations, and computes the case and aggregate decisions. A sequential runner reconstructs each fixed schedule, creates one independent three-phase network per solver setting, writes immutable case artifacts, and resumes safely. A separate evaluator produces deterministic JSON, Chinese Markdown, CSV, and hash evidence.

**Tech Stack:** Python 3.11, `opendssdirect.py==0.9.4`, standard-library `csv`/`hashlib`/`json`/`tempfile`, existing EV-FLEX-BIAS reconstruction/runtime, pytest, Git.

---

## File responsibilities

- `config/numerical_certainty_replay_v2_1_d1r_lite.json`: exact source hashes, selection rule, solver settings, thresholds, paths, and scope.
- `src/evflex/numerical_certainty_replay_d1r_lite.py`: strict loading, representative selection, target-input construction, setting application, observation validation, and decisions.
- `scripts/run_numerical_certainty_replay_v2_1_d1r_lite.py`: preflight, sequential execution, lock, atomic case persistence, immutable resume, and controlled stops.
- `scripts/evaluate_numerical_certainty_replay_v2_1_d1r_lite.py`: deterministic aggregate reports, code/source provenance, hashes, and `--verify-existing`.
- `tests/test_numerical_certainty_replay_d1r_lite.py`: source, selection, pure observation, drift, and decision rules.
- `tests/test_numerical_certainty_replay_d1r_lite_integration.py`: one real in-memory pair-01 setting/readback and witness-slot replay.
- `tests/test_numerical_certainty_replay_d1r_lite_runner.py`: persistence, locking, resume, and stop behavior.
- `tests/test_numerical_certainty_replay_d1r_lite_evaluator.py`: deterministic outputs, Chinese scope, provenance, and byte verification.

## Task 1: Freeze source integrity and representative selection

**Files:**

- Create: `config/numerical_certainty_replay_v2_1_d1r_lite.json`
- Create: `src/evflex/numerical_certainty_replay_d1r_lite.py`
- Create: `tests/test_numerical_certainty_replay_d1r_lite.py`

- [ ] **Step 1: Write failing config and selection tests**

Create tests with these exact assertions:

```python
def test_replay_config_freezes_three_settings_and_scope():
    config = load_replay_config(REPO_ROOT)
    assert config["selected_pair_ids"] == ["01", "05", "08", "12"]
    assert [item["label"] for item in config["solver_settings"]] == [
        "NATIVE_1E4", "TIGHT_1E6", "ULTRA_1E8"
    ]
    assert [item["convergence_tolerance"] for item in config["solver_settings"]] == [
        1e-4, 1e-6, 1e-8
    ]
    assert config["target_replay_evaluations"] == 12
    assert config["formal_v2_1_run_authorized"] is False

def test_source_selection_rederives_exact_four_representatives():
    source = load_replay_source(REPO_ROOT, load_replay_config(REPO_ROOT))
    assert [item["pair_id"] for item in source["selected"]] == ["01", "05", "08", "12"]
    assert [item["selected_slot"] for item in source["selected"]] == [28, 48, 56, 75]
    assert [item["metric_id"] for item in source["selected"]] == [
        "V:860.1", "V:563.1", "V:900.1", "V:780.3"
    ]

def test_selection_uses_closest_exceedance_then_pair_id():
    rows = synthetic_rows_with_an_exact_distance_tie()
    assert select_replay_cases(rows, cluster_order, guard_band=1e-5)[0]["pair_id"] == "01"

def test_source_loader_rejects_n0_or_case_hash_drift(tmp_path):
    copy_frozen_replay_inputs(tmp_path)
    mutate_one_byte(tmp_path / "reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json")
    with pytest.raises(ValueError, match="frozen source hash drift"):
        load_replay_source(tmp_path, load_replay_config(tmp_path))
```

- [ ] **Step 2: Run RED**

```powershell
$env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:NUMEXPR_NUM_THREADS='1'; $env:VECLIB_MAXIMUM_THREADS='1'; $env:BLIS_NUM_THREADS='1'; .\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite.py -q -p no:faulthandler
```

Expected: collection fails because `evflex.numerical_certainty_replay_d1r_lite` does not exist.

- [ ] **Step 3: Implement the frozen config and source loader**

Expose:

```python
def load_replay_config(repo_root: str | Path) -> dict[str, Any]: ...

def select_replay_cases(
    audit_rows: Sequence[Mapping[str, Any]],
    cluster_order: Sequence[str],
    *,
    guard_band: float,
) -> list[dict[str, Any]]: ...

def load_replay_source(
    repo_root: str | Path,
    config: Mapping[str, Any],
) -> dict[str, Any]: ...
```

The config must freeze protocol `EV-FLEX-BIAS-V2.1-D1R-LITE-N1-NUMERICAL`, source hashes from the design, pair order `01/05/08/12`, three solver settings, `1e-9/1e-6/1e-7` drift thresholds, the existing `1e-7` physical margin, independent paths, single-worker resource policy, and false formal/line-thermal scope. Use duplicate-key-rejecting strict JSON and rooted-path checks.

The loader must call the existing D1-R-Lite source validator, verify N0 is exactly `HOLD_MARGIN_FRAGILE_AT_1E5`, parse the archived audit CSV with exact headers, derive the selection rather than trusting manual pair IDs, and require the derived witness slot/metric/value/limit/direction/exceedance table to equal the frozen config.

- [ ] **Step 4: Run GREEN and commit**

```powershell
$env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:NUMEXPR_NUM_THREADS='1'; $env:VECLIB_MAXIMUM_THREADS='1'; $env:BLIS_NUM_THREADS='1'; .\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite.py -q -p no:faulthandler
git add config/numerical_certainty_replay_v2_1_d1r_lite.json src/evflex/numerical_certainty_replay_d1r_lite.py tests/test_numerical_certainty_replay_d1r_lite.py
git diff --cached --check
git commit -m "feat: freeze D1-R-Lite numerical replay inputs"
```

## Task 2: Implement pure observation and decision rules

**Files:**

- Modify: `src/evflex/numerical_certainty_replay_d1r_lite.py`
- Modify: `tests/test_numerical_certainty_replay_d1r_lite.py`

- [ ] **Step 1: Write failing observation and decision tests**

Add real-value-shaped synthetic observations proving:

```python
def test_native_identity_accepts_exact_archive_and_rejects_over_1e_minus_9_drift(): ...
def test_tight_witness_requires_same_metric_hi_direction_and_physical_margin(): ...
def test_case_is_stable_at_both_tight_settings_with_frozen_drifts(): ...
def test_case_detects_native_to_tight_drift_over_1e_minus_6(): ...
def test_case_detects_tight_plateau_drift_over_1e_minus_7(): ...
def test_gate_requires_all_four_cases_stable(): ...
def test_gate_distinguishes_identity_mismatch_and_solver_failure(): ...
def test_case_artifact_rejects_nonfinite_unexpected_or_scope_expanding_fields(): ...
```

Test all four aggregate decisions exactly:

```text
NUMERICALLY_STABLE_SELECTED_WITNESSES
NUMERICAL_SENSITIVITY_DETECTED
STOP_REPLAY_IDENTITY_MISMATCH
STOP_SOLVER_FAILURE
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite.py -k "identity or witness or drift or gate or artifact" -q -p no:faulthandler
```

Expected: imports or assertions fail because the assessment functions are missing.

- [ ] **Step 3: Implement minimal pure assessment**

Expose:

```python
def assess_case_replay(
    selection: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]: ...

def assess_replay_gate(
    case_artifacts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]: ...

def validate_replay_case_artifact(
    artifact: Mapping[str, Any],
    selection: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None: ...
```

Validate exact setting order/readback, finite metrics, convergence, no numerical failures, archived metric identity, physical `hi` witness presence, native identity drift, native-to-tight drift, tight-to-ultra plateau drift, false formal authorization, and false line-thermal scope. Do not infer full-trajectory or 12-case status.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite.py -q -p no:faulthandler
git add src/evflex/numerical_certainty_replay_d1r_lite.py tests/test_numerical_certainty_replay_d1r_lite.py
git diff --cached --check
git commit -m "feat: assess numerical witness stability"
```

## Task 3: Add real single-slot execution and safe sequential runner

**Files:**

- Modify: `src/evflex/numerical_certainty_replay_d1r_lite.py`
- Create: `scripts/run_numerical_certainty_replay_v2_1_d1r_lite.py`
- Create: `tests/test_numerical_certainty_replay_d1r_lite_integration.py`
- Create: `tests/test_numerical_certainty_replay_d1r_lite_runner.py`

- [ ] **Step 1: Write failing setting application and runner tests**

Use a fake OpenDSS-like network to prove the real setting API contract:

```python
def test_apply_solver_setting_sets_and_reads_convergence_and_max_iterations():
    network = FakeNetwork()
    observed = apply_solver_setting(network, {"convergence_tolerance": 1e-6, "max_iterations": 100})
    assert observed == {"convergence_tolerance": 1e-6, "max_iterations": 100, "max_control_iterations": 100}

def test_execute_replay_case_uses_fresh_network_for_each_setting(): ...
def test_execute_replay_case_reconstructs_exact_boundary_schedule_and_slot(): ...
def test_runner_processes_01_05_08_12_sequentially(): ...
def test_runner_resumes_only_valid_immutable_prefix(): ...
def test_runner_stops_on_attempt_lock_unexpected_file_or_formal_output(): ...
def test_runner_atomically_persists_validated_case_before_advancing(): ...
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite_runner.py tests\test_numerical_certainty_replay_d1r_lite_integration.py -q -p no:faulthandler
```

Expected: runner and execution interfaces are absent.

- [ ] **Step 3: Implement target execution**

Expose:

```python
def apply_solver_setting(network: Any, setting: Mapping[str, Any]) -> dict[str, Any]: ...

def execute_replay_case(
    repo_root: str | Path,
    selection: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    reconstruct_fn: Callable[..., Mapping[str, Any]] | None = None,
    network_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]: ...
```

Use existing `reconstruct_case` first, before any solver intervention, so archived schedule hashes remain authoritative. For each setting create a new `runtime.corrected_core.Network`; under native settings replay the archived baseline solves and earlier changed boundary-prefix solves that touched the selected load-scale context; then apply and read back the requested `Solution.Convergence`, `Solution.MaxIterations`, and `Solution.MaxControlIterations` only for the target solve. Aggregate the exact witness-slot fleet power, evaluate once with controls already off, and record the archived metric plus solver/convergence metadata. Release each context before the next setting and each case before the next case. The deterministic pre-target setup solves reproduce identity and are not counted among the 12 target replay evaluations.

- [ ] **Step 4: Implement runner persistence**

The runner must set numeric thread variables before project imports; verify all predecessor sources and clean replay code paths; reject formal V2.1 paths; use an exclusive lock; write `.attempts/case_{pair_id}.json`; convert controlled replay exceptions into strict terminal stop artifacts; atomically persist and reread each case; remove the attempt only after validated persistence; and stop at the first non-success artifact.

- [ ] **Step 5: Add one real in-memory integration check**

Run pair `01` through one independent `NATIVE_1E4` target replay without production writes. Assert exact setting readback, convergence, metric `V:860.1`, slot 28, schedule hash identity, and native replay difference at most `1e-9 pu`.

- [ ] **Step 6: Run GREEN and commit**

```powershell
$env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:NUMEXPR_NUM_THREADS='1'; $env:VECLIB_MAXIMUM_THREADS='1'; $env:BLIS_NUM_THREADS='1'; .\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite.py tests\test_numerical_certainty_replay_d1r_lite_runner.py tests\test_numerical_certainty_replay_d1r_lite_integration.py -q -p no:faulthandler
git add src/evflex/numerical_certainty_replay_d1r_lite.py scripts/run_numerical_certainty_replay_v2_1_d1r_lite.py tests/test_numerical_certainty_replay_d1r_lite.py tests/test_numerical_certainty_replay_d1r_lite_runner.py tests/test_numerical_certainty_replay_d1r_lite_integration.py
git diff --cached --check
git commit -m "feat: replay selected voltage witnesses"
```

## Task 4: Add deterministic evaluator and reports

**Files:**

- Create: `scripts/evaluate_numerical_certainty_replay_v2_1_d1r_lite.py`
- Create: `tests/test_numerical_certainty_replay_d1r_lite_evaluator.py`

- [ ] **Step 1: Write failing evaluator tests**

Cover all aggregate decisions, exact case/setting CSV order, source and case hashes, clean code provenance, atomic writes, and byte verification. Require these Chinese phrases:

```text
4个代表见证点
只复核归档失效时刻
不是完整96时段重跑
求解容差不是电压误差界
不改变N0的6/12计数
不授权正式V2.1
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite_evaluator.py -q -p no:faulthandler
```

Expected: evaluator script is missing.

- [ ] **Step 3: Implement evaluator**

Expose:

```python
def evaluate_numerical_certainty_replay(
    repo_root: str | Path,
    *,
    integrity_verifier: Callable[..., Mapping[str, Any]] | None = None,
    verify_existing: bool = False,
) -> dict[str, Any]: ...
```

Require a nonempty valid terminal prefix in frozen order. A prefix shorter than four is reportable only when its last artifact is a controlled `STOP_*`; stable or sensitivity decisions require all four artifacts. Generate canonical JSON, Chinese Markdown, one CSV row per completed case/setting, and a hash CSV containing frozen sources and the completed case artifacts. Record requested/observed settings, metric values, exceedances, iteration counts, every drift, case decisions, aggregate decision, the actual target-evaluation count (12 for a complete four-case replay), unknown internal setup-solve count, false formal authorization, and scope limitations. Use temporary files plus `os.replace`; verify mode must compare all four outputs byte-for-byte without writing.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_numerical_certainty_replay_d1r_lite_evaluator.py -q -p no:faulthandler
git add scripts/evaluate_numerical_certainty_replay_v2_1_d1r_lite.py tests/test_numerical_certainty_replay_d1r_lite_evaluator.py
git diff --cached --check
git commit -m "feat: report numerical witness replay"
```

## Task 5: Verify, execute four cases, and archive

- [ ] **Step 1: Run full pre-execution verification**

```powershell
$env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:NUMEXPR_NUM_THREADS='1'; $env:VECLIB_MAXIMUM_THREADS='1'; $env:BLIS_NUM_THREADS='1'; .\.venv\Scripts\python.exe -m pytest -q -p no:faulthandler
.\.venv\Scripts\python.exe scripts/evaluate_mechanism_diagnostic_v2_1.py --verify-existing
.\.venv\Scripts\python.exe scripts/evaluate_pilot_gate_v2_1.py --verify-existing
.\.venv\Scripts\python.exe scripts/evaluate_mechanism_diagnostic_v2_1_d1r_lite.py --verify-existing
.\.venv\Scripts\python.exe scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py --verify-existing
```

Require all commands to exit zero and the worktree to be clean before production execution.

- [ ] **Step 2: Run the four selected cases sequentially**

```powershell
$env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:NUMEXPR_NUM_THREADS='1'; $env:VECLIB_MAXIMUM_THREADS='1'; $env:BLIS_NUM_THREADS='1'; .\.venv\Scripts\python.exe scripts\run_numerical_certainty_replay_v2_1_d1r_lite.py
```

Require terminal artifacts only for `01`, `05`, `08`, and `12`, no formal output, and no old evidence modification. A controlled stop is a valid terminal result but must not be described as a completed scientific replay.

- [ ] **Step 3: Evaluate and byte-verify**

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_numerical_certainty_replay_v2_1_d1r_lite.py
.\.venv\Scripts\python.exe scripts\evaluate_numerical_certainty_replay_v2_1_d1r_lite.py --verify-existing
```

- [ ] **Step 4: Re-run full verification and old-evidence immutability**

Run the full suite and all four predecessor verifiers again. Require zero diff from commit `5421ec6` for D1-R-Lite result/report paths and zero diff from commit `73518d9` for the four N0 report paths.

- [ ] **Step 5: Archive only N1 evidence**

```powershell
git add results/numerical_certainty_replay_v2_1_d1r_lite reports/numerical_certainty_replay_v2_1_d1r_lite.json reports/numerical_certainty_replay_v2_1_d1r_lite.md reports/numerical_certainty_replay_v2_1_d1r_lite.csv reports/numerical_certainty_replay_hashes_v2_1_d1r_lite.csv
git diff --cached --check
git commit -m "results: archive numerical witness replay"
```

- [ ] **Step 6: Apply the decision boundary**

If `NUMERICALLY_STABLE_SELECTED_WITNESSES`, retain the current research direction but revise the academic interpretation: the N0 hold is guard-band-definition sensitivity, not demonstrated solver noise for the four selected points. If `NUMERICAL_SENSITIVITY_DETECTED`, `STOP_REPLAY_IDENTITY_MISMATCH`, or `STOP_SOLVER_FAILURE`, stop without expanding the run and document the exact failed rule. Under every result, keep formal V2.1 unauthorized.
