# EV-FLEX-BIAS-V2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable V2.0 pipeline that regenerates the complete 1,536-evaluation core experiment, 336 compact ablations, one-pass 384-evaluation holdout validation, and the A4 conference submission by 2026-08-20.

**Architecture:** Preserve archived inputs and D5 code as immutable provenance, then wrap them with focused V2.0 modules for manifests, numerical execution, validation, modeling, ablation analysis, holdout sealing, and paper generation. Scenario-direction work units solve 15/30/60 minutes together; all formal outputs are atomic, resumable, hash-addressed, and gated before the next stage.

**Tech Stack:** Python 3.12.13, NumPy 2.3.5, pandas 2.2.3, SciPy 1.17.0, scikit-learn 1.7.2, OpenDSSDirect.py 0.9.4, matplotlib 3.10.7, seaborn 0.13.2, PowerShell, Git, Word/IEEE A4 template, Poppler PDF QA.

**Resource policy:** Set `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, and `VECLIB_MAXIMUM_THREADS` to `1`. Use one process for regression and no more than two processes for formal execution. Do not raise these limits without a new explicit user instruction.

---

## File map

The implementation creates these responsibility boundaries:

- `src/evflex/provenance.py`: SHA-256 computation, manifest writing, and verification.
- `src/evflex/schema.py`: protocol enums and validated work-unit/evaluation records.
- `src/evflex/manifests.py`: core and compact-ablation manifest construction.
- `src/evflex/network.py`: immutable adapter around archived OpenDSS network code.
- `src/evflex/fleet.py`: archived formal-population loading and baseline construction.
- `src/evflex/engine.py`: three-duration comparison and nested-duration closure.
- `src/evflex/runner.py`: locking, atomic output, retries, process isolation, and resume.
- `src/evflex/aggregate.py`: terminal-status checks, result flattening, and physical gates.
- `src/evflex/modeling.py`: 12 cell-specific OOF logistic models and frozen thresholds.
- `src/evflex/ablation.py`: 336-run fixed design and stratified bootstrap analysis.
- `src/evflex/holdout.py`: pre-holdout freeze verification and unlock record.
- `scripts/`: thin command-line entry points.
- `tests/`: unit, integration, regression, determinism, and seal tests.

## Task 1: Bootstrap the repository and locked environment

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `pyproject.toml`
- Create: `requirements.lock.txt`
- Create: `config/resource_limits_v2_0.json`
- Create: `src/evflex/__init__.py`
- Create: `tests/test_environment.py`

- [ ] **Step 1: Verify the isolated feature branch**

Run:

```powershell
git branch --show-current
git rev-parse --show-toplevel
```

Expected: Git reports branch `build/v2-pipeline` and the linked `.worktrees/build-v2-pipeline` root.

- [ ] **Step 2: Write the failing environment test**

Create `tests/test_environment.py`:

```python
import importlib.metadata
import sys
import unittest


EXPECTED = {
    "numpy": "2.3.5",
    "pandas": "2.2.3",
    "scipy": "1.17.0",
    "scikit-learn": "1.7.2",
    "opendssdirect.py": "0.9.4",
    "matplotlib": "3.10.7",
    "seaborn": "0.13.2",
}


class EnvironmentTest(unittest.TestCase):
    def test_python_minor(self):
        self.assertEqual(sys.version_info[:2], (3, 12))

    def test_locked_packages(self):
        actual = {name: importlib.metadata.version(name) for name in EXPECTED}
        self.assertEqual(actual, EXPECTED)

    def test_numeric_thread_caps(self):
        import os
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            self.assertEqual(os.environ.get(name), "1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test and confirm the unlocked environment fails**

Run:

```powershell
python -m unittest tests.test_environment -v
```

Expected: FAIL because the V2.0 virtual environment and packages do not yet exist.

- [ ] **Step 4: Create the lock files**

Create `requirements.lock.txt` with exactly:

```text
numpy==2.3.5
pandas==2.2.3
scipy==1.17.0
scikit-learn==1.7.2
opendssdirect.py==0.9.4
matplotlib==3.10.7
seaborn==0.13.2
requests==2.32.4
python-docx==1.2.0
```

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "ev-flex-bias-v2"
version = "2.0.0"
requires-python = "==3.12.*"
dependencies = []

[tool.setuptools.packages.find]
where = ["src"]
```

Create `.gitignore`:

```text
.worktrees/
.venv/
__pycache__/
*.pyc
*.tmp
*.lock
state/runtime/
results/work_units/
reports/rendered/
paper/rendered/
```

Create `src/evflex/__init__.py`:

```python
"""Auditable EV flexibility-bias experiments, protocol V2.0."""

import os

for _name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_name] = "1"

__version__ = "2.0.0"
```

Create `config/resource_limits_v2_0.json`:

```json
{
  "numeric_threads": 1,
  "regression_workers": 1,
  "formal_workers_max": 2
}
```

Create `README.md`:

```markdown
# EV-FLEX-BIAS-V2.0

This repository regenerates the formal evidence for the IEEE PES ISGT Asia 2026 paper on directional bias in balanced-network estimates of EV-aggregator V1G/V2G deliverable flexibility.

Formal stages are gated in order: provenance, engine regression, development, model freeze, compact ablations, pre-holdout freeze, one-pass holdout, and paper QA. Holdout execution is prohibited before the signed pre-holdout freeze.
```

- [ ] **Step 5: Create and install the isolated environment**

Run:

```powershell
$py='C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

Expected: all locked packages install successfully and the editable project is importable.

- [ ] **Step 6: Run the environment test**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_environment -v
```

Expected: 3 tests PASS.

- [ ] **Step 7: Record the bootstrap commit**

Run:

```powershell
git add .gitignore README.md pyproject.toml requirements.lock.txt config/resource_limits_v2_0.json src tests
git commit -m "build: lock V2.0 Python environment"
```

## Task 2: Import and verify authoritative archived assets

**Files:**
- Create: `src/evflex/provenance.py`
- Create: `tools/import_inherited_assets.py`
- Create: `config/required_inherited_assets_v2_0.csv`
- Create: `tests/test_provenance.py`
- Generate: `manifests/inherited_asset_manifest_v2_0.csv`
- Generate: `reports/provenance_gate_v2_0.json`

- [ ] **Step 1: Write the failing hash-verification tests**

Create `tests/test_provenance.py`:

```python
from pathlib import Path
import tempfile
import unittest

from evflex.provenance import sha256_file, verify_rows


class ProvenanceTest(unittest.TestCase):
    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.bin"
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_verify_rows_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.bin"
            path.write_bytes(b"abc")
            rows = [{"path": str(path), "sha256": "0" * 64}]
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_rows(rows)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm the tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_provenance -v
```

Expected: FAIL because `evflex.provenance` does not exist.

- [ ] **Step 3: Implement deterministic hashing and verification**

Create `src/evflex/provenance.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Mapping


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_rows(rows: Iterable[Mapping[str, str]]) -> None:
    errors: list[str] = []
    for row in rows:
        path = Path(row["path"])
        if not path.is_file():
            errors.append(f"missing: {path}")
            continue
        actual = sha256_file(path)
        expected = row["sha256"].lower()
        if actual != expected:
            errors.append(f"hash mismatch: {path}: {actual} != {expected}")
    if errors:
        raise ValueError("\n".join(errors))
```

- [ ] **Step 4: Define the required asset ledger**

Create `config/required_inherited_assets_v2_0.csv` with columns:

```text
asset_id,source_kind,source_path,archive_entry,destination_path,expected_sha256,authority
```

Populate rows for the NHTS archive, four known frozen CSV hashes, core manifest, native-load profile, IEEE13 DSS tree, LV906 DSS tree, D5 engine, D5 network core, and D5 regression CSV. For files without a previously published hash, compute the archive-entry hash during import and freeze that value in the generated manifest before G0 is signed.

- [ ] **Step 5: Implement archive import with no silent overwrite**

`tools/import_inherited_assets.py` must:

```python
def copy_checked(source, destination, expected_sha256):
    if destination.exists():
        actual = sha256_file(destination)
        if actual != expected_sha256:
            raise FileExistsError(f"destination differs: {destination}")
        return actual
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    actual = sha256_file(destination)
    if actual != expected_sha256:
        destination.unlink()
        raise ValueError(f"copied hash mismatch: {destination}")
    return actual
```

For ZIP entries, stream bytes from `zipfile.ZipFile.open()` into a temporary file in the destination directory, hash the temporary file, and call `os.replace()` only after the expected hash matches.

- [ ] **Step 6: Import assets and run G0**

Run:

```powershell
.\.venv\Scripts\python.exe tools/import_inherited_assets.py `
  --project-parent .. `
  --requirements config/required_inherited_assets_v2_0.csv `
  --manifest manifests/inherited_asset_manifest_v2_0.csv `
  --report reports/provenance_gate_v2_0.json
```

Expected: `gate_status` is `PASS`; known hashes include the NHTS archive and the four frozen CSV hashes recorded in the v1.8.1 handoff.

- [ ] **Step 7: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_provenance -v
git add config data legacy manifests reports src tools tests
git commit -m "feat: import and verify archived V2.0 assets"
```

Expected: tests PASS and the commit contains only immutable inherited assets plus their provenance records.

## Task 3: Define protocol schemas and construct frozen manifests

**Files:**
- Create: `protocol/protocol_v2_0.json`
- Create: `src/evflex/schema.py`
- Create: `src/evflex/manifests.py`
- Create: `scripts/build_manifests_v2_0.py`
- Create: `tests/test_manifests.py`
- Generate: `manifests/core_evaluations_v2_0.csv`
- Generate: `manifests/core_work_units_v2_0.csv`
- Generate: `manifests/compact_ablation_v2_0.csv`

- [ ] **Step 1: Write manifest-count and sealing tests**

Create `tests/test_manifests.py`:

```python
import unittest

import pandas as pd

from evflex.manifests import build_ablation_manifest, validate_core_manifests


class ManifestTest(unittest.TestCase):
    def test_core_counts_and_roles(self):
        evaluations = pd.read_csv("manifests/core_evaluations_v2_0.csv")
        work = pd.read_csv("manifests/core_work_units_v2_0.csv")
        validate_core_manifests(evaluations, work)
        self.assertEqual(len(evaluations), 1536)
        self.assertEqual((evaluations.data_role == "development").sum(), 1152)
        self.assertEqual((evaluations.data_role == "holdout").sum(), 384)
        self.assertEqual(len(work), 512)
        self.assertEqual((work.data_role == "development").sum(), 384)
        self.assertEqual((work.data_role == "holdout").sum(), 128)

    def test_compact_ablation_count(self):
        frame = build_ablation_manifest()
        self.assertEqual(len(frame), 336)
        self.assertEqual(frame.ablation_id.nunique(), 336)
        self.assertEqual(frame.seed.nunique(), 336)
        self.assertTrue((frame.data_role == "development_ablation").all())
        self.assertTrue((frame.holdout_access == "prohibited").all())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_manifests -v
```

Expected: FAIL because schema and manifest builders do not exist.

- [ ] **Step 3: Implement strict protocol enums**

Create `src/evflex/schema.py` with frozen values:

```python
from enum import StrEnum


class DataRole(StrEnum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"
    DEVELOPMENT_ABLATION = "development_ablation"


class Direction(StrEnum):
    INC = "inc"
    DEC = "dec"


DURATIONS = (15, 30, 60)
CALL_TIMES = ("19:00", "00:00", "02:00", "06:00")
FEEDERS = ("ieee13", "lv906")
```

- [ ] **Step 4: Write the frozen protocol JSON**

Create `protocol/protocol_v2_0.json` with these exact top-level values:

```json
{
  "protocol_id": "EV-FLEX-BIAS-V2.0",
  "lineage": "new_major_version_from_archived_authoritative_inputs",
  "submission_deadline": "2026-08-20",
  "time_grid": {"start": "12:00", "interval_minutes": 15, "intervals": 96},
  "call_times": ["19:00", "00:00", "02:00", "06:00"],
  "durations_min": [15, 30, 60],
  "directions": ["inc", "dec"],
  "feeders": ["ieee13", "lv906"],
  "core": {"scenarios": 256, "evaluations": 1536, "development": 1152, "holdout": 384},
  "risk": {"target": "alpha_map_lt_0p95", "selected_n_min": 20, "false_safe_rate_max": 0.05},
  "ablation": {"evaluations": 336, "duration_min": 15, "call_times": ["19:00", "02:00"], "replicates": 3},
  "holdout": {"status": "SEALED", "refit": false, "rethreshold": false}
}
```

- [ ] **Step 5: Normalize inherited core identities**

`normalize_core_manifest()` must preserve inherited scenario ID, seed, feeder, call time, and data role. It creates evaluation IDs as:

```python
evaluation_id = f"v20_core_{scenario_id}__{direction}__{duration_min}m"
work_unit_id = f"v20_work_{scenario_id}__{direction}"
```

Validation rejects any work unit whose three evaluation rows differ in scenario, seed, feeder, call time, or data role.

- [ ] **Step 6: Implement the exact 336-row ablation grid**

Use:

```python
BLOCK_LEVELS = {
    "A1_phase": ("phase_ratio", ("1:1:1", "2:1:1", "4:1:1"), ("inc", "dec")),
    "A2_location": ("far_zone_probability", (0.20, 0.50, 0.80), ("inc", "dec")),
    "A3_load": ("native_load_multiplier", (0.75, 0.90, 1.05), ("inc", "dec")),
    "A4_urgency": ("urgency_quantile", (0.40, 0.65, 0.90), ("inc", "dec")),
    "A5_v2g": ("v2g_participation", (0.25, 0.50, 0.75, 1.00), ("dec",)),
}
ABLATION_CALL_TIMES = ("19:00", "02:00")
REPLICATES = (0, 1, 2)
SEED_BASE = 2026072001
```

Iterate in the fixed order block, feeder, call time, direction, factor level, replicate. Assign sequential seeds from `SEED_BASE` and dominant phases `a`, `b`, `c` by replicate.

- [ ] **Step 7: Build, validate, and freeze manifests**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/build_manifests_v2_0.py `
  --inherited-core data/inherited/core_run_manifest_v1_2.csv `
  --output-dir manifests
.\.venv\Scripts\python.exe -m unittest tests.test_manifests -v
```

Expected: all tests PASS; counts are 1,536 evaluations, 512 work units, and 336 ablations.

- [ ] **Step 8: Commit protocol and manifests**

Run:

```powershell
git add protocol manifests scripts src tests
git commit -m "feat: freeze V2.0 core and ablation manifests"
```

## Task 4: Wrap the archived OpenDSS network core

**Files:**
- Create: `src/evflex/network.py`
- Create: `tests/test_network.py`
- Use unchanged: `legacy/d5_v1_2/network_core_v1_2.py`
- Use unchanged: `data/feeders/ieee13/`
- Use unchanged: `data/feeders/lv906_core/`

- [ ] **Step 1: Write feeder compile tests**

Create `tests/test_network.py`:

```python
from pathlib import Path
import unittest

from evflex.network import load_legacy_core, validate_feeder_tree


class NetworkTest(unittest.TestCase):
    def test_feeder_dependencies_exist(self):
        validate_feeder_tree(Path("data/feeders/ieee13"), "IEEE13Nodeckt.dss")
        validate_feeder_tree(Path("data/feeders/lv906_core"), "Master.dss")

    def test_legacy_core_loads(self):
        core = load_legacy_core(Path("legacy/d5_v1_2/network_core_v1_2.py"))
        self.assertTrue(hasattr(core, "Network"))
        self.assertTrue(hasattr(core, "EV"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_network -v
```

Expected: FAIL because `evflex.network` does not exist.

- [ ] **Step 3: Implement safe legacy loading**

Create `src/evflex/network.py`:

```python
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_legacy_core(path: Path):
    name = "evflex_legacy_network_core_v1_2"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load legacy core: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_feeder_tree(root: Path, master_name: str) -> None:
    master = root / master_name
    if not master.is_file():
        raise FileNotFoundError(master)
    for line in master.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text or text.startswith("!"):
            continue
        lowered = text.lower()
        if "redirect" in lowered or "compile" in lowered:
            token = text.split(maxsplit=1)[1].strip().strip("()\"'")
            dependency = root / token
            if not dependency.exists():
                raise FileNotFoundError(dependency)
```

- [ ] **Step 4: Add compile-and-solve smoke checks**

Use separate OpenDSS contexts for each feeder. Assert `Solution.Converged()` and record bus count, node count, and source voltage in `reports/network_smoke_v2_0.json`. Do not alter DSS source files during the smoke test.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_network -v
git add src tests reports
git commit -m "feat: validate and wrap archived feeder models"
```

## Task 5: Port the trajectory engine and nested-duration closure

**Files:**
- Create: `src/evflex/fleet.py`
- Create: `src/evflex/engine.py`
- Create: `scripts/run_smoke_v2_0.py`
- Create: `tests/test_engine.py`
- Use unchanged: `legacy/d5_v1_2/duration_aware_engine_v1_2.py`

- [ ] **Step 1: Write nested-candidate unit tests**

Create `tests/test_engine.py`:

```python
import unittest

from evflex.engine import select_nested_candidate


class EngineTest(unittest.TestCase):
    def test_longer_feasible_candidate_promotes_shorter_duration(self):
        raw = {
            15: {"flex_kw": 8.0, "physical_feasible": True},
            30: {"flex_kw": 9.0, "physical_feasible": True},
            60: {"flex_kw": 7.0, "physical_feasible": True},
        }
        selected = select_nested_candidate(raw, 15)
        self.assertEqual(selected["source_duration_min"], 30)
        self.assertEqual(selected["flex_kw"], 9.0)

    def test_infeasible_candidate_is_rejected(self):
        raw = {
            15: {"flex_kw": 8.0, "physical_feasible": True},
            30: {"flex_kw": 20.0, "physical_feasible": False},
            60: {"flex_kw": 7.0, "physical_feasible": True},
        }
        selected = select_nested_candidate(raw, 15)
        self.assertEqual(selected["source_duration_min"], 15)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_engine -v
```

Expected: FAIL because `evflex.engine` does not exist.

- [ ] **Step 3: Implement the closure exactly**

Create this function in `src/evflex/engine.py`:

```python
def select_nested_candidate(raw_by_duration, requested_duration):
    candidates = []
    for source_duration, result in raw_by_duration.items():
        if int(source_duration) < int(requested_duration):
            continue
        if not bool(result.get("physical_feasible", True)):
            continue
        candidates.append(
            (float(result["flex_kw"]), -int(source_duration), int(source_duration), result)
        )
    if not candidates:
        raise RuntimeError(f"no feasible nested candidate for {requested_duration}")
    _, _, source, result = max(candidates, key=lambda item: (item[0], item[1]))
    selected = dict(result)
    selected["requested_duration_min"] = int(requested_duration)
    selected["source_duration_min"] = int(source)
    selected["monotonic_closure_promoted"] = source != requested_duration
    return selected
```

- [ ] **Step 4: Implement the V2.0 engine adapter**

`compare_all_durations()` loads the archived engine once, solves raw balanced and three-phase results for `(15, 30, 60)`, applies `select_nested_candidate`, computes `alpha_map`, and returns exactly three evaluation dictionaries. Each dictionary includes evaluation ID, requested/source duration, capacities, bias, `alpha_map`, mapped capacity, physical checks, status, and provenance hashes.

Create `scripts/run_smoke_v2_0.py` as a thin CLI that selects the first requested number of development scenario-direction work units with both feeders represented, calls `compare_all_durations()`, validates the three-row result bundle, and writes a JSON report containing scientific fields plus runtime. The CLI exits with code 1 when either feeder is absent, a result bundle has a duration other than 15/30/60, or a physical invariant fails.

- [ ] **Step 5: Run unit tests and a two-scenario smoke test**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_engine -v
.\.venv\Scripts\python.exe scripts/run_smoke_v2_0.py --scenarios 2 --workers 1 --output reports/engine_smoke_v2_0.json
```

Expected: unit tests PASS; both feeders, both directions, and all three durations produce schema-valid records with zero SOC/reserve violations and zero simultaneous charge/discharge intervals.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src scripts tests reports
git commit -m "feat: add V2.0 multi-duration engine"
```

## Task 6: Implement and pass the D5 regression gate

**Files:**
- Create: `src/evflex/regression.py`
- Create: `scripts/validate_engine_regression_v2_0.py`
- Create: `tests/test_regression_gate.py`
- Generate: `reports/engine_regression_gate_v2_0.json`
- Generate: `reports/engine_regression_gate_v2_0.md`

- [ ] **Step 1: Write tolerance tests**

Create `tests/test_regression_gate.py`:

```python
import unittest

from evflex.regression import close_capacity, close_scalar


class RegressionGateTest(unittest.TestCase):
    def test_capacity_tolerance(self):
        self.assertTrue(close_capacity(100.0, 100.000001))
        self.assertFalse(close_capacity(100.0, 100.1))

    def test_alpha_tolerance(self):
        self.assertTrue(close_scalar(0.95, 0.950000001, 1e-8))
        self.assertFalse(close_scalar(0.95, 0.951, 1e-8))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement comparison functions**

Create in `src/evflex/regression.py`:

```python
def close_capacity(expected: float, actual: float) -> bool:
    absolute = abs(expected - actual)
    relative = absolute / max(abs(expected), 1e-12)
    return absolute <= 1e-5 or relative <= 1e-8


def close_scalar(expected: float, actual: float, tolerance: float) -> bool:
    return abs(expected - actual) <= tolerance
```

- [ ] **Step 3: Run the 24 golden cases twice sequentially**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/validate_engine_regression_v2_0.py `
  --golden data/inherited/duration_engine_regression_results.csv `
  --repeats 2 `
  --workers 1 `
  --output-json reports/engine_regression_gate_v2_0.json `
  --output-md reports/engine_regression_gate_v2_0.md
```

Expected: G1 PASS with 24/24 status matches, all numerical tolerances satisfied, and repeat differences within tolerance.

- [ ] **Step 4: Test process-count determinism**

Run the same golden set with two workers. Compare canonicalized evaluation rows after excluding runtime and attempt metadata.

Expected: worker counts 1 and 2 produce identical scientific fields within G1 tolerances.

- [ ] **Step 5: Run tests and commit the gate**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_regression_gate -v
git add src scripts tests reports
git commit -m "test: pass V2.0 D5 regression gate"
```

Do not proceed unless `reports/engine_regression_gate_v2_0.json` records `gate_status: PASS`.

## Task 7: Build the atomic resumable work-unit runner

**Files:**
- Create: `src/evflex/runner.py`
- Create: `scripts/run_manifest_v2_0.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Write atomic-write and lock tests**

Create `tests/test_runner.py` with tests that:

```python
with exclusive_lock(lock_path):
    self.assertTrue(lock_path.exists())
self.assertFalse(lock_path.exists())

atomic_write_json(result_path, {"status": "SUCCESS"})
self.assertEqual(json.loads(result_path.read_text())["status"], "SUCCESS")
```

Add a second test that pre-creates the lock and asserts `exclusive_lock()` raises `FileExistsError`. Add a third test that pre-creates a valid completed result and asserts the runner returns `SKIPPED_COMPLETED` without invoking the engine.

- [ ] **Step 2: Implement exclusive locking and atomic JSON**

Create in `src/evflex/runner.py`:

```python
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        fd = -1
        yield
    finally:
        if fd >= 0:
            os.close(fd)
        path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
```

- [ ] **Step 3: Implement retry semantics**

Allow attempts 1-3 only for unhandled infrastructure exceptions. Physical terminal statuses are written once and never retried. A completed work-unit JSON must contain exactly three core evaluations or one ablation evaluation and must pass schema validation before it is treated as complete.

- [ ] **Step 4: Implement the manifest CLI**

The CLI accepts `--role development`, `--role development_ablation`, or `--role holdout`. It rejects holdout unless the verified unlock record exists. It supports `--workers 1..2`, `--resume`, and `--max-work-units` for smoke tests. It rejects worker counts above the frozen resource limit and never accepts a seed override.

- [ ] **Step 5: Test crash-and-resume behavior**

Inject a test engine that raises on attempt 1 and succeeds on attempt 2. Assert the same work-unit ID and seed are reused, `attempt_count` equals 2, and no second result filename appears.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_runner -v
git add src scripts tests
git commit -m "feat: add atomic resumable V2.0 runner"
```

## Task 8: Execute and aggregate the development set

**Files:**
- Create: `src/evflex/aggregate.py`
- Create: `scripts/aggregate_results_v2_0.py`
- Create: `tests/test_aggregate.py`
- Generate: `results/development_v2_0/development_evaluations_v2_0.csv`
- Generate: `reports/development_gate_v2_0.json`
- Generate: `reports/development_gate_v2_0.md`

- [ ] **Step 1: Write aggregation-gate tests**

Tests must assert that duplicate evaluation IDs, missing durations, unhandled failures, nonzero simultaneous charging/discharging, and negative SOC margins each cause a gate failure. A fixture with one explicit `THREE_PHASE_BASELINE_INFEASIBLE` status must remain terminal and reportable rather than being classified as a crash.

- [ ] **Step 2: Implement canonical aggregation**

Flatten work-unit JSONs into one evaluation row per duration. Sort by inherited scenario order, direction order `inc, dec`, and duration order `15, 30, 60`. Write CSV with UTF-8 and `lineterminator="\n"`. Compute a SHA-256 after writing.

- [ ] **Step 3: Run a 12-evaluation development smoke**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/run_manifest_v2_0.py `
  --manifest manifests/core_work_units_v2_0.csv `
  --role development --workers 1 --max-work-units 4 --resume
.\.venv\Scripts\python.exe scripts/aggregate_results_v2_0.py `
  --input results/work_units/development `
  --expected-evaluations 12 `
  --report reports/development_smoke_gate_v2_0.json
```

Expected: 12 evaluation rows and a PASS smoke report.

- [ ] **Step 4: Execute all 384 development work units**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/run_manifest_v2_0.py `
  --manifest manifests/core_work_units_v2_0.csv `
  --role development --workers 2 --resume
```

Monitor terminal counts and fresh modification times. Never infer completion from CPU activity alone.

- [ ] **Step 5: Aggregate and apply G2**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/aggregate_results_v2_0.py `
  --input results/work_units/development `
  --expected-evaluations 1152 `
  --output results/development_v2_0/development_evaluations_v2_0.csv `
  --report reports/development_gate_v2_0.json `
  --report-md reports/development_gate_v2_0.md
```

Expected: 1,152 terminal evaluations, no unhandled failure, all physical gates PASS, and at least 80 paired eligible observations in every feeder-direction-duration cell.

- [ ] **Step 6: Commit development summaries**

Run:

```powershell
git add src scripts tests results/development_v2_0 reports
git commit -m "data: freeze V2.0 development results"
```

Raw work-unit JSON remains outside Git but is included in the freeze hash manifest.

## Task 9: Fit and freeze the 12 applicability models

**Files:**
- Create: `src/evflex/modeling.py`
- Create: `scripts/fit_applicability_v2_0.py`
- Create: `tests/test_modeling.py`
- Generate: `results/modeling_v2_0/applicability_models_v2_0.json`
- Generate: `results/modeling_v2_0/development_oof_predictions_v2_0.csv`
- Generate: `reports/modeling_gate_v2_0.json`

- [ ] **Step 1: Write threshold-selection tests**

Create a fixture whose risk scores and labels yield two qualifying thresholds. Assert the selected threshold gives maximum coverage, selected count is at least 20, empirical false-safe rate is at most 0.05, and equal-coverage ties choose the lower risk threshold.

- [ ] **Step 2: Implement deterministic OOF modeling**

Use `StratifiedKFold(n_splits=5, shuffle=True, random_state=2026072000)`. Use `StandardScaler`, `OneHotEncoder(drop="first", handle_unknown="error")`, and `LogisticRegression(penalty="l2", solver="lbfgs", max_iter=5000)`. Search `C = (0.03, 0.1, 0.3, 1, 3, 10, 30)`. Select minimum mean OOF Brier score; ties select the smaller `C`.

- [ ] **Step 3: Implement threshold selection**

Create:

```python
def choose_threshold(scores, labels, minimum_n=20, maximum_rate=0.05):
    candidates = []
    for threshold in sorted(set(float(value) for value in scores)):
        mask = scores <= threshold
        count = int(mask.sum())
        if count < minimum_n:
            continue
        rate = float(labels[mask].mean())
        if rate <= maximum_rate:
            candidates.append((count, -threshold, threshold, rate))
    if not candidates:
        return None
    count, _, threshold, rate = max(candidates)
    return {"risk_threshold": threshold, "selected_n": count, "false_safe_rate": rate}
```

- [ ] **Step 4: Fit all cells and run G3**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/fit_applicability_v2_0.py `
  --development results/development_v2_0/development_evaluations_v2_0.csv `
  --models results/modeling_v2_0/applicability_models_v2_0.json `
  --oof results/modeling_v2_0/development_oof_predictions_v2_0.csv `
  --report reports/modeling_gate_v2_0.json
```

Expected: exactly 12 fitted model records; every OOF row belongs to development; candidate regions satisfy the frozen rule.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_modeling -v
git add src scripts tests results/modeling_v2_0 reports
git commit -m "model: freeze V2.0 applicability rules"
```

## Task 10: Execute and analyze the 336 compact ablations

**Files:**
- Create: `src/evflex/ablation.py`
- Create: `scripts/analyze_ablations_v2_0.py`
- Create: `tests/test_ablation.py`
- Generate: `results/ablation_v2_0/compact_ablation_results_v2_0.csv`
- Generate: `results/ablation_v2_0/ablation_contrasts_v2_0.csv`
- Generate: `reports/ablation_gate_v2_0.json`
- Generate: `reports/ablation_analysis_v2_0.md`

- [ ] **Step 1: Write fixed-design tests**

Assert block counts are 72, 72, 72, 72, and 48; all durations equal 15; call times are exactly 19:00 and 02:00; seeds are unique; and holdout access is prohibited.

- [ ] **Step 2: Write bootstrap determinism tests**

Use a 12-row fixture and assert two calls with seed `2026072001` return identical median contrasts and confidence limits. Assert changing the seed changes at least one resampled index sequence.

- [ ] **Step 3: Execute all ablations**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/run_manifest_v2_0.py `
  --manifest manifests/compact_ablation_v2_0.csv `
  --role development_ablation --workers 2 --resume
```

Expected: 336 terminal work-unit records and no replacement IDs.

- [ ] **Step 4: Analyze fixed contrasts**

For each block, feeder, call time, and direction, report level-wise median `alpha_map`, median bias, false-safe rate, and contrast against the middle/reference level. Use 10,000 stratified bootstrap resamples with seed `2026072001`.

- [ ] **Step 5: Run G4 and commit**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/analyze_ablations_v2_0.py `
  --manifest manifests/compact_ablation_v2_0.csv `
  --work-units results/work_units/development_ablation `
  --output-dir results/ablation_v2_0 `
  --report reports/ablation_gate_v2_0.json `
  --report-md reports/ablation_analysis_v2_0.md
.\.venv\Scripts\python.exe -m unittest tests.test_ablation -v
git add src scripts tests results/ablation_v2_0 reports
git commit -m "data: freeze V2.0 compact ablations"
```

Expected: G4 PASS and exactly 336 unique result IDs.

## Task 11: Freeze pre-holdout state and create the unlock record

**Files:**
- Create: `src/evflex/holdout.py`
- Create: `tools/freeze_pre_holdout_v2_0.py`
- Create: `tools/open_holdout_v2_0.py`
- Create: `tests/test_holdout_seal.py`
- Generate: `reports/pre_holdout_freeze_v2_0.json`
- Generate: `state/holdout_unlock_v2_0.json`

- [ ] **Step 1: Write seal rejection tests**

Tests must reject unlock when any of G0-G4 is not PASS, when a required hash differs, when holdout result files already exist, or when an unlock record already records a prior opening.

- [ ] **Step 2: Implement the freeze manifest**

Hash Git HEAD, dirty status, protocol, environment lock, inherited assets, manifests, engine code, development CSV, model JSON, OOF CSV, ablation CSV, and analysis scripts. Require a clean working tree before signing the freeze.

- [ ] **Step 3: Commit the complete pre-holdout source state**

Run:

```powershell
git status --short
git add -A
git commit -m "chore: establish V2.0 pre-holdout source anchor"
$sourceCommit=git rev-parse HEAD
```

Expected: the working tree is clean and `$sourceCommit` identifies the immutable code/result anchor used by the freeze report.

- [ ] **Step 4: Create the pre-holdout freeze**

Run:

```powershell
.\.venv\Scripts\python.exe tools/freeze_pre_holdout_v2_0.py `
  --source-commit $sourceCommit `
  --output reports/pre_holdout_freeze_v2_0.json
```

Expected: G5 preconditions PASS and `holdout_opened` is false.

- [ ] **Step 5: Commit the freeze report without changing the source anchor**

Run:

```powershell
git add reports/pre_holdout_freeze_v2_0.json
git commit -m "chore: freeze V2.0 before holdout"
```

The report records `$sourceCommit`, not its own later audit commit, which avoids a circular self-hash. The unlock verifier requires the source anchor to be an ancestor of the audit commit and verifies every recorded file hash against the current clean tree.

- [ ] **Step 6: Open the holdout once**

Run:

```powershell
.\.venv\Scripts\python.exe tools/open_holdout_v2_0.py `
  --freeze reports/pre_holdout_freeze_v2_0.json `
  --output state/holdout_unlock_v2_0.json
```

Expected: the unlock record contains freeze-report SHA-256, opening timestamp, protocol ID, and `holdout_open_count: 1`.

## Task 12: Run the holdout once and generate final statistical evidence

**Files:**
- Create: `scripts/evaluate_holdout_v2_0.py`
- Create: `tests/test_holdout_analysis.py`
- Generate: `results/holdout_v2_0/holdout_evaluations_v2_0.csv`
- Generate: `results/final_analysis_v2_0/directional_summary_v2_0.csv`
- Generate: `results/final_analysis_v2_0/applicability_validation_v2_0.csv`
- Generate: `reports/holdout_gate_v2_0.json`
- Generate: `reports/final_analysis_v2_0.json`

- [ ] **Step 1: Write no-refit tests**

Load the frozen model JSON, apply it to a fixture, and assert model coefficients and thresholds have identical hashes before and after evaluation. Test Wilson intervals at 0 failures, 1 failure, and all failures.

- [ ] **Step 2: Execute 128 holdout work units**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/run_manifest_v2_0.py `
  --manifest manifests/core_work_units_v2_0.csv `
  --role holdout --workers 2 --resume `
  --unlock state/holdout_unlock_v2_0.json
```

Expected: 128 completed work units containing exactly 384 evaluation rows. Completed work units are skipped on a resume check.

- [ ] **Step 3: Aggregate and apply frozen models**

Run:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_holdout_v2_0.py `
  --work-units results/work_units/holdout `
  --models results/modeling_v2_0/applicability_models_v2_0.json `
  --holdout-csv results/holdout_v2_0/holdout_evaluations_v2_0.csv `
  --output-dir results/final_analysis_v2_0 `
  --gate reports/holdout_gate_v2_0.json `
  --summary reports/final_analysis_v2_0.json
```

Expected: 384 terminal evaluations; every applicability row reports selected count, false-safe count/rate, Wilson interval, and coverage; no model hash changes.

- [ ] **Step 4: Run tests and freeze final evidence**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_holdout_analysis -v
git add src scripts tests results/holdout_v2_0 results/final_analysis_v2_0 reports
git commit -m "data: freeze one-pass V2.0 holdout evidence"
```

## Task 13: Generate paper tables, figures, and machine-linked prose values

**Files:**
- Create: `paper/build_paper_assets_v2_0.py`
- Create: `paper/validate_manuscript_numbers_v2_0.py`
- Create: `tests/test_paper_assets.py`
- Generate: `paper/data/`
- Generate: `paper/figures/fig1_framework_v2_0.png`
- Generate: `paper/figures/fig2_alpha_map_v2_0.png`
- Generate: `paper/figures/fig3_false_safe_v2_0.png`
- Generate: `paper/figures/fig4_applicability_v2_0.png`
- Generate: `paper/figures/fig5_ablation_v2_0.png`
- Generate: `paper/figures/fig6_holdout_v2_0.png`
- Generate: `paper/generated_values_v2_0.json`

- [ ] **Step 1: Write source-lineage tests**

Assert every generated table and figure metadata file names its source CSV and SHA-256. Assert `generated_values_v2_0.json` contains only values derived from V2.0 development, ablation, or holdout outputs.

- [ ] **Step 2: Generate assets deterministically**

Use a fixed plotting style, explicit figure dimensions, 300 DPI, and sorted categorical orders. Save both PNG and source CSV for every quantitative figure. Framework Fig. 1 contains no experimental values.

- [ ] **Step 3: Build the value ledger**

Create JSON keys for sample counts, median capacities, directional differences, confidence intervals, false-safe rates, selected counts, coverage, and ablation contrasts. The manuscript validator scans the DOCX-extracted text for marked value keys and compares displayed values to the ledger.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe paper/build_paper_assets_v2_0.py `
  --final-analysis results/final_analysis_v2_0 `
  --ablation results/ablation_v2_0 `
  --output-dir paper
.\.venv\Scripts\python.exe -m unittest tests.test_paper_assets -v
git add paper tests
git commit -m "paper: generate V2.0 figures and value ledger"
```

## Task 14: Rebuild the manuscript in the official A4 template and submit

**Files:**
- Create: `paper/conference/template_source_manifest.json`
- Create: `paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0.docx`
- Generate: `paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0.pdf`
- Create: `tools/verify_all_gates_v2_0.py`
- Create: `reports/submission_checklist_v2_0.md`
- Create: `reports/final_reproducibility_manifest_v2_0.csv`

- [ ] **Step 1: Obtain and hash the official template**

Download only from `https://attend.ieee.org/isgt-asia-2026/submission/`. Record source URL, retrieval timestamp, filename, byte count, and SHA-256 in `paper/conference/template_source_manifest.json`. If the official file cannot be retrieved, stop formatting and contact `isgta2026@youngac.cn`; do not substitute a generic IEEE template.

- [ ] **Step 2: Rewrite the old working draft against V2.0 evidence**

Retain the locked research question and same-input comparison framework. Replace the old 117-scenario/15-minute abstract, results, figures, limitations, and conclusion. Keep claims feeder-, direction-, and duration-specific. Connect reliable EV flexibility assessment to low-carbon operation without claiming measured carbon reduction.

- [ ] **Step 3: Validate every numeric statement**

Run:

```powershell
.\.venv\Scripts\python.exe paper/validate_manuscript_numbers_v2_0.py `
  --docx paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0.docx `
  --values paper/generated_values_v2_0.json
```

Expected: zero missing keys, zero mismatched values, and zero old-result phrases.

- [ ] **Step 4: Render and inspect the complete paper**

Render the DOCX with the bundled document renderer, export the final PDF, then render every PDF page to PNG with Poppler. Inspect every page at 100% for clipped text, broken equations, unreadable figures, table overflow, missing glyphs, reference defects, and page-limit compliance.

- [ ] **Step 5: Build the final reproducibility manifest**

Hash the protocol, environment, inherited assets, code, manifests, all frozen result CSV/JSON files, figures, DOCX, and PDF. Record Git commit and clean status.

Create `tools/verify_all_gates_v2_0.py`. It loads the seven G0-G6 gate reports in order, requires each `gate_status` to equal `PASS`, checks the final holdout evaluation count equals 384, verifies the final reproducibility-manifest hashes, and writes `reports/all_gates_v2_0.json`. For protocol `EV-FLEX-BIAS-V2.0-C`, it instead requires G0-G3 and G5-G6 to pass, requires G4 to equal `OMITTED_BY_PREDECLARED_CALENDAR_GATE`, and verifies the paper asset manifest contains no ablation figure or table. It exits with code 1 and lists every failed condition when any check fails.

- [ ] **Step 6: Complete the submission checklist**

`reports/submission_checklist_v2_0.md` must confirm English language, originality, correct EV-grid integration track, A4 template, single PDF, author metadata, affiliations, references, figure readability, final filename, EasyChair account readiness, and 2026-08-20 deadline.

- [ ] **Step 7: Commit the submission candidate**

Run:

```powershell
git add paper reports
git commit -m "paper: prepare ISGT Asia 2026 submission candidate"
git status --short --branch
```

Expected: clean working tree. Do not upload to EasyChair without explicit user authorization because submission is an external state change.

## Calendar gates

- **2026-07-27:** G1 engine regression must PASS.
- **2026-08-02:** G2 development execution must PASS.
- **2026-08-05:** G3 model freeze must PASS.
- **2026-08-09:** G4 compact ablation freeze should PASS.
- **2026-08-10:** G5 pre-holdout freeze must PASS.
- **2026-08-11:** holdout evaluation and G6 evidence generation must complete.
- **2026-08-18:** final template PDF must pass page-by-page QA.
- **2026-08-19:** submission buffer; no new scientific analysis.
- **2026-08-20:** EasyChair submission after user authorization.

If G3 has not passed by the end of 2026-08-05, record the predeclared `EV-FLEX-BIAS-V2.0-C` calendar branch, omit controlled-ablation claims, and continue the unchanged core/holdout validation path. Do not import v1.8 ablation statistics into the paper.

## Final verification command set

Run before declaring the package submission-ready:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/verify_all_gates_v2_0.py --reports reports --output reports/all_gates_v2_0.json
.\.venv\Scripts\python.exe paper/validate_manuscript_numbers_v2_0.py --docx paper/EV_V1G_V2G_ISGT_Asia_2026_v2_0.docx --values paper/generated_values_v2_0.json
git status --short --branch
```

Expected: all tests PASS, G0-G6 PASS, zero manuscript-number mismatches, and a clean Git working tree.
