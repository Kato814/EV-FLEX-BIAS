# V2.1 D1-R-Lite N0 Margin-Sensitivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user has explicitly prohibited subagents, so execute inline in the current task.

**Goal:** Produce a deterministic, artifact-only guard-band sensitivity decision for the archived D1-R-Lite `VMAX` candidate without running new power flows or formal V2.1.

**Architecture:** A small pure module strictly loads the frozen config and archived 12-case evidence, validates every source hash and case artifact, and counts case/cluster support at four voltage guard bands. A standalone evaluator writes JSON, CSV, Chinese Markdown, and hash reports atomically and verifies them byte-for-byte.

**Tech Stack:** Python 3.11, standard-library `csv`/`hashlib`/`json`/`statistics`, existing `evflex.mechanism_diagnostic` strict JSON helpers, pytest, Git.

---

## File responsibilities

- `config/mechanism_margin_sensitivity_v2_1_d1r_lite.json`: frozen N0 thresholds, source hashes, output paths, resource and claim boundaries.
- `src/evflex/mechanism_margin_sensitivity_d1r_lite.py`: strict loader, source validation, support counting, decision, and report validation.
- `scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py`: integrity checks, deterministic rendering, atomic writes, CLI, and `--verify-existing`.
- `tests/test_mechanism_margin_sensitivity_d1r_lite.py`: pure protocol, validation, counting, and decision tests.
- `tests/test_mechanism_margin_sensitivity_d1r_lite_evaluator.py`: output, Chinese scope, provenance, and byte-verification tests.

## Task 1: Freeze the config and strict source loader

**Files:**

- Create: `config/mechanism_margin_sensitivity_v2_1_d1r_lite.json`
- Create: `src/evflex/mechanism_margin_sensitivity_d1r_lite.py`
- Create: `tests/test_mechanism_margin_sensitivity_d1r_lite.py`

- [ ] **Step 1: Write failing config and source-integrity tests**

Add tests with these exact behaviors:

```python
def test_margin_config_freezes_candidate_bands_gate_and_zero_power_flows():
    config = load_margin_config(REPO_ROOT)
    assert config["candidate_family"] == "VMAX"
    assert config["voltage_guard_bands_pu"] == [0.0, 1e-6, 1e-5, 1e-4]
    assert config["decisive_guard_band_pu"] == 1e-5
    assert config["minimum_cases"] == 8
    assert config["minimum_clusters"] == 3
    assert config["new_power_flow_solves"] == 0
    assert config["formal_v2_1_run_authorized"] is False

def test_source_loader_accepts_exact_archived_twelve_case_evidence():
    source = load_margin_source(REPO_ROOT, load_margin_config(REPO_ROOT))
    assert len(source["cases"]) == 12
    assert len(source["artifacts"]) == 12
    assert source["report"]["qualifying_families"] == ["VMAX"]

def test_source_loader_rejects_frozen_hash_or_case_drift(tmp_path):
    # Copy only frozen inputs, mutate one byte or one case value, and assert ValueError.
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mechanism_margin_sensitivity_d1r_lite.py -q -p no:faulthandler
```

Expected: collection fails because the new module is missing.

- [ ] **Step 3: Implement the frozen config and loader**

Implement these public interfaces:

```python
def load_margin_config(repo_root: str | Path) -> dict[str, Any]: ...

def load_margin_source(
    repo_root: str | Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return validated source report, manifest cases, and 12 case artifacts."""
```

The loader must use duplicate-key-rejecting strict JSON, require the exact config tree, verify all frozen SHA-256 values, verify each case against the source case-hash CSV and `validate_lite_case_artifact`, and reject any source report other than the completed 12-case `VMAX` outcome.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mechanism_margin_sensitivity_d1r_lite.py -q -p no:faulthandler
git add config/mechanism_margin_sensitivity_v2_1_d1r_lite.json src/evflex/mechanism_margin_sensitivity_d1r_lite.py tests/test_mechanism_margin_sensitivity_d1r_lite.py
git diff --cached --check
git commit -m "feat: freeze D1-R-Lite margin sensitivity inputs"
```

## Task 2: Implement the pure guard-band sweep and decision

**Files:**

- Modify: `src/evflex/mechanism_margin_sensitivity_d1r_lite.py`
- Modify: `tests/test_mechanism_margin_sensitivity_d1r_lite.py`

- [ ] **Step 1: Write failing counting and decision tests**

Add tests proving:

```python
def test_guard_band_counts_case_presence_not_metric_rows(): ...
def test_guard_band_comparison_is_inclusive_at_exact_threshold(): ...
def test_cluster_support_counts_unique_clusters(): ...
def test_decisive_band_returns_robust_only_at_eight_cases_and_three_clusters(): ...
def test_margin_result_preserves_frozen_band_and_family_order(): ...
def test_non_voltage_families_are_not_filtered_by_voltage_guard_bands(): ...
```

Use synthetic validated row records to exercise both `MARGIN_ROBUST_AT_1E5` and `HOLD_MARGIN_FRAGILE_AT_1E5`; do not hard-code the archived outcome into the pure-function tests.

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mechanism_margin_sensitivity_d1r_lite.py -k "guard_band or decisive or non_voltage" -q -p no:faulthandler
```

Expected: imports or assertions fail because aggregation is not implemented.

- [ ] **Step 3: Implement minimal pure aggregation**

Implement:

```python
def compute_margin_sensitivity(
    source: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]: ...

def validate_margin_result(
    result: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None: ...
```

For each voltage family and guard band, build a per-case set before counting; preserve manifest pair order and first-occurrence cluster order. At the decisive band, derive the decision only from `VMAX` support and the frozen 8-case/3-cluster rule. Record `formal_v2_1_run_authorized=false`, `new_power_flow_solves=0`, and the post-result sensitivity limitation.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mechanism_margin_sensitivity_d1r_lite.py -q -p no:faulthandler
git add src/evflex/mechanism_margin_sensitivity_d1r_lite.py tests/test_mechanism_margin_sensitivity_d1r_lite.py
git diff --cached --check
git commit -m "feat: assess D1-R-Lite voltage guard bands"
```

## Task 3: Add deterministic reports and byte verification

**Files:**

- Create: `scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py`
- Create: `tests/test_mechanism_margin_sensitivity_d1r_lite_evaluator.py`

- [ ] **Step 1: Write failing evaluator tests**

Cover exact CSV row order, both decision branches, source hashes, clean code provenance, Chinese text, atomic writes, and byte verification. The Chinese report must contain:

```text
事后敏感性检查
不改变原始 COMMON_CANDIDATE_CONFOUNDED 结论
1e-5 pu
不是工程安全裕度
零次新增潮流计算
不授权正式 V2.1
```

- [ ] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mechanism_margin_sensitivity_d1r_lite_evaluator.py -q -p no:faulthandler
```

Expected: evaluator file is missing.

- [ ] **Step 3: Implement evaluator and CLI**

Expose:

```python
def evaluate_margin_sensitivity(
    repo_root: str | Path,
    *,
    integrity_verifier: Callable[..., Mapping[str, Any]] | None = None,
    verify_existing: bool = False,
) -> dict[str, Any]: ...
```

Set all numeric thread variables to `1` before importing project modules. Generate strict canonical JSON, one CSV row per `(family, guard_band)`, Chinese Markdown, and a frozen-source hash CSV. Use temporary files plus `os.replace`; in verify mode compare all four outputs byte-for-byte without writing.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_mechanism_margin_sensitivity_d1r_lite_evaluator.py -q -p no:faulthandler
git add scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py tests/test_mechanism_margin_sensitivity_d1r_lite_evaluator.py
git diff --cached --check
git commit -m "feat: report D1-R-Lite margin sensitivity"
```

## Task 4: Execute, verify, and archive N0

- [ ] **Step 1: Run focused and full tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mechanism_margin_sensitivity_d1r_lite.py tests/test_mechanism_margin_sensitivity_d1r_lite_evaluator.py -q -p no:faulthandler
.\.venv\Scripts\python.exe -m pytest -q -p no:faulthandler
```

- [ ] **Step 2: Verify predecessor immutability**

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_mechanism_diagnostic_v2_1.py --verify-existing
.\.venv\Scripts\python.exe scripts/evaluate_pilot_gate_v2_1.py --verify-existing
.\.venv\Scripts\python.exe scripts/evaluate_mechanism_diagnostic_v2_1_d1r_lite.py --verify-existing
git diff --exit-code 5421ec6 -- results/mechanism_diagnostic_v2_1_d1r_lite reports/mechanism_diagnostic_audits_v2_1_d1r_lite.csv reports/mechanism_diagnostic_hashes_v2_1_d1r_lite.csv reports/mechanism_diagnostic_v2_1_d1r_lite.json reports/mechanism_diagnostic_v2_1_d1r_lite.md
```

- [ ] **Step 3: Generate and verify N0 outputs**

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py
.\.venv\Scripts\python.exe scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py --verify-existing
```

Require zero new result-case files and `new_power_flow_solves=0` in the report.

- [ ] **Step 4: Archive only the new N0 evidence**

```powershell
git add config/mechanism_margin_sensitivity_v2_1_d1r_lite.json src/evflex/mechanism_margin_sensitivity_d1r_lite.py scripts/evaluate_mechanism_margin_sensitivity_v2_1_d1r_lite.py tests/test_mechanism_margin_sensitivity_d1r_lite.py tests/test_mechanism_margin_sensitivity_d1r_lite_evaluator.py reports/mechanism_margin_sensitivity_v2_1_d1r_lite.json reports/mechanism_margin_sensitivity_v2_1_d1r_lite.md reports/mechanism_margin_sensitivity_v2_1_d1r_lite.csv reports/mechanism_margin_sensitivity_hashes_v2_1_d1r_lite.csv docs/superpowers/plans/2026-08-03-v2-1-d1r-lite-margin-sensitivity.md
git diff --cached --check
git commit -m "results: archive D1-R-Lite margin sensitivity"
```

- [ ] **Step 5: Apply the decision boundary**

If the decision is `HOLD_MARGIN_FRAGILE_AT_1E5`, stop without implementing tight-solver replay or formal V2.1. If it is `MARGIN_ROBUST_AT_1E5`, freeze a separate tight-solver replay design before any new power-flow execution.
