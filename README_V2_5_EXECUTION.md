# EV-FLEX-BIAS V2.5 experiment continuation package

This package adds two experiment stages without modifying the frozen V2.4 PHiCTE implementation.

## V2.5A — retrospective robustness diagnostic

Copy:

- `scripts/analyze_phicte_robustness_v2_5a.py`

Run from the repository root:

```powershell
$env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:NUMEXPR_NUM_THREADS='1'; $env:VECLIB_MAXIMUM_THREADS='1'
.\.venv\Scripts\python.exe scripts\analyze_phicte_robustness_v2_5a.py
```

Expected output path:

`results/transferability_phicte_v2_5a_robustness/summary.json`

A precomputed summary from the currently archived V2.4 predictions is included in this package. The script independently recomputes it and rejects changed V2.4 Git blobs.

## V2.5B-R1 — expanded retrospective three-phase replication

Copy:

- `config/transferability_replication_v2_5b.json`
- `src/evflex/transferability_replication_v2_5b.py`
- `scripts/run_transferability_replication_v2_5b.py`
- `tests/test_transferability_replication_v2_5b.py`
- `scripts/verify_transferability_replication_v2_5b.py`
- `reports/v2_5b_r1_preexecution_audit.md`
- `.github/workflows/v25b_replication.yml` (optional automated runner)

The design deterministically uses the unused prior V2.0 holdout suffixes `26–31` in every feeder × call-time cell. This gives 48 scenarios, 96 paired direction work units, and 288 evaluations (15/30/60 min). The 15-min scope is primary; longer durations remain descriptive. Because the source V2.0 holdout was historically opened, the stage is explicitly retrospective and must not be called a blind or confirmatory holdout.

Before running, commit the protocol/code so the clean-worktree and provenance gates can bind the experiment to a commit:

```powershell
git add config/transferability_replication_v2_5b.json src/evflex/transferability_replication_v2_5b.py scripts/run_transferability_replication_v2_5b.py tests/test_transferability_replication_v2_5b.py scripts/analyze_phicte_robustness_v2_5a.py scripts/verify_transferability_replication_v2_5b.py reports/v2_5b_r1_preexecution_audit.md results/transferability_phicte_v2_5a_robustness/summary.json .github/workflows/v25b_replication.yml
git commit -m "analysis: freeze V2.5B-R1 expanded PHiCTE replication"
```

Run the targeted design tests and then the existing full regression suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_transferability_replication_v2_5b.py
.\.venv\Scripts\python.exe -m pytest -q -p no:faulthandler
```

Run V2.5B:

```powershell
.\.venv\Scripts\python.exe -m evflex.transferability_replication_v2_5b --workers 1 --all
```

If interrupted after at least one completed work unit:

```powershell
.\.venv\Scripts\python.exe -m evflex.transferability_replication_v2_5b --workers 1 --all --resume
```

Expected outputs:

- `results/transferability_replication_v2_5b/summary.json`
- `results/transferability_replication_v2_5b/predictions.csv`

Immediately after the run, independently recompute the archived core metrics:

```powershell
.\.venv\Scripts\python.exe scripts\verify_transferability_replication_v2_5b.py
```

This produces `reports/v2_5b_independent_verification.json`. A `PASS` is required before the V2.5B-R1 evidence is used for manuscript drafting.

Commit the outputs only after the run finishes and the metrics have been independently checked:

```powershell
git add results/transferability_replication_v2_5b/summary.json results/transferability_replication_v2_5b/predictions.csv reports/v2_5b_independent_verification.json
git commit -m "results: archive V2.5B-R1 PHiCTE replication"
```


### Optional GitHub Actions execution

If the repository permits GitHub Actions and the workflow token has `contents: write`, committing the package also triggers `.github/workflows/v25b_replication.yml`. It installs Python 3.12 and the locked dependencies, runs the targeted and full tests, executes V2.5B-R1, independently verifies the outputs, uploads the result artifacts, and then attempts to commit the completed result files back to the triggering branch. The workflow is path-filtered so the result-only commit does not trigger another experiment run. If repository policy blocks the final push, the uploaded workflow artifact still contains the generated result files.

## Frozen V2.5B-R1 evidence rules

The primary 15-min evidence is considered sufficient to begin the conference manuscript only if all predeclared checks pass:

- at least 73 active primary evaluations;
- at least 73 **prescribed/non-abstained** primary evaluations in the material-risk denominator;
- at least 24 prescribed primary evaluations within each feeder;
- zero numerical-failure audits in eligible primary evaluations;
- PHiCTE empirical material false-safe rate ≤ 5% overall **and within each feeder**;
- zero strict bound exceedances (`phicte_factor > alpha_transfer`) overall and within each feeder;
- PHiCTE is Pareto-nondominated in material-risk vs kW-retention within both feeders;
- PHiCTE kW retention exceeds global derating and direction-only within both feeders;
- the positive LV906 kW-retention delta versus feeder-only replicates.

Positive IEEE13 kW-retention delta versus feeder-only is deliberately **not** required, because V2.5A identified a feeder-specific risk-retention tradeoff. A Wilson 95% upper bound below 5% is reported but is not a mandatory gate; 0 failures require at least 73 **prescribed risk-denominator cases** for that upper bound to fall below 5%, while one failure would require 110 cases. Pooled-kW superiority is also not required and remains a sensitivity metric.


### V2.5B-R1 pre-execution amendment

Before any V2.5B work unit was executed, the evidence gate was tightened without changing scenario selection, the PHiCTE model, or any hyperparameter. The amendment replaces the statistical rationale based only on active-offer count with an explicit minimum prescribed risk denominator, adds feeder-specific material-risk checks, and requires zero strict bound exceedances because PHiCTE is interpreted as a conservative transferability envelope. The amendment metadata is stored in `config/transferability_replication_v2_5b.json`; it records that no V2.5B outcomes had been observed before the change.
