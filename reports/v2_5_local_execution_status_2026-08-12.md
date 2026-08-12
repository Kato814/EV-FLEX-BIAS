# V2.5 Local Execution Status — 2026-08-12

## Scope

This record documents the local pre-execution work performed after unpacking the user-supplied GitHub archive `EV-FLEX-BIAS-main.zip`. It is an execution/status record, not paper evidence and not a substitute for the frozen V2.5B-R1 three-phase replication.

## Source identity

- User-supplied archive SHA-256: `4104fb7af366daf974ba144c9c393d069cf0835bc363a127633ba4d1a255d1a3`.
- Archive source commit recorded by the GitHub ZIP: `7fc01099769bd158fc437fe3cefe7a44cfadcc84`.
- Frozen V2.4 identities were rechecked locally before V2.5B preparation:
  - PHiCTE module Git blob: `1b42e82dcf1d1f53d9f6f5a480b3b386d13788f2`.
  - V2.4 summary Git blob: `ffe665d395416f97498d14bc3df10b70755a3c69`.
  - V2.4 predictions Git blob: `1b07e3a381718dc6bf10cc2309436016c897655a`.
- Local pre-report analysis/test HEAD: `9e05460509e100d8250898449cfecf90728d6f28`.

The local Git history was initialized only to freeze the merged experiment package and support provenance checks. These local commit IDs are not GitHub commit IDs.

## V2.5A recomputation

V2.5A was recomputed from the archived V2.4 predictions after merge into the uploaded repository. The outcome remained:

- decision: `CONTINUE_WITH_FEEDER_STRATIFIED_REPLICATION`;
- PHiCTE vs feeder-only, 15-minute primary scope:
  - equal-case retention delta: `+0.0162396879`;
  - feeder-macro kW retention delta: `+0.0248947720`;
  - pooled-kW retention delta: `-0.0958996256`;
- leave-one-scenario-out signs:
  - equal-case delta positive in `16/16` deletions;
  - feeder-macro delta positive in `16/16` deletions;
  - pooled-kW delta negative in `16/16` deletions;
- feeder-specific kW-retention delta:
  - IEEE13: `-0.1199553437`;
  - LV906: `+0.1697448877`.

The scenario-stratified bootstrap does not resolve the overall equal-case or feeder-macro gain away from zero, while it does resolve the pooled-kW loss and the opposite-sign feeder heterogeneity. These are retrospective diagnostics only.

## V2.5B-R1 pre-execution verification

The V2.5B-R1 design now resolves exactly:

- 48 scenarios: suffixes 26–31 across 2 feeders × 4 call times;
- 96 paired direction work units;
- 288 evaluations at 15/30/60 minutes;
- 96 planned rows in the 15-minute primary scope.

The V2.5B-specific test module was strengthened to exercise the full analysis pipeline on a synthetic 288-row/48-scenario dataset without external-outcome tuning. Current result in the local container:

- `3 passed` for `tests/test_transferability_replication_v2_5b.py`.

The independent output verifier was also strengthened to recompute all manuscript-readiness decision criteria, including feeder-specific retention deltas, Pareto status, empirical material-risk checks, strict-bound exceedance checks, and the final aggregate decision.

## Repository regression status in this container

The local container is not the frozen execution environment: it provides Python 3.13.5, whereas the repository requires Python 3.12.x. Within this non-authoritative environment, the broad suite excluding three separately ignored environment/network/ablation test files produced:

- 502 passed;
- 12 failed;
- 72 warnings.

All 12 failures are blocked at the OpenDSS runtime boundary because `opendssdirect.py` is not installed. The failures are in real-runtime pilot/mechanism/numerical-replay/witness paths or are downstream of the explicit missing-runtime check. This does **not** constitute a failed power-flow experiment because the OpenDSS engine was never available to execute those tests.

## Current execution blocker

`opendssdirect.py==0.9.4` and its native DSS runtime are absent from this container, and the container cannot install packages from the public Python package index. Therefore the actual V2.5B-R1 three-phase evaluations have **not** been executed locally.

No V2.0 `alpha_map`/three-phase-capacity result has been substituted for V2.5B `alpha_transfer`. The two estimands and schedules are not identical, so such substitution would violate the frozen experiment contract.

## Authorized next execution path

The prepared GitHub Actions workflow remains the authoritative execution path because it provisions Python 3.12, installs the locked requirements, runs the full regression suite, requires a clean committed worktree, executes V2.5B-R1 with one worker and one numeric thread, independently verifies the outputs, uploads artifacts, and archives successful results.

Paper drafting remains deferred until V2.5B-R1 is executed and the frozen manuscript-readiness criteria are evaluated.
