# Manuscript Evidence Freeze — 2026-08-13

This directory is the compact, durable evidence bundle for the IEEE PES ISGT Asia 2026 manuscript.

## Frozen scientific scope

Primary continuous-transferability scope:
- Direction: INC
- Physical mode: V1G charging flexibility
- Primary duration: 15 min
- Feeders: IEEE13 and LV906
- Primary active cases: 46

DEC/V2G continuous-ray results are excluded from primary transferability claims because the post-hoc vehicle-feasibility verification showed that the original net-power alpha ray is not vehicle-feasible for partial-alpha DEC cases.

Formal R3 is cancelled for this conference submission. No post-hoc redesign of the V2G ray or new three-phase simulation is part of the frozen manuscript evidence.

## Source experiment artifacts

R2 complete:
- Run ID: 31671974049
- Artifact ID: 9170561358
- Artifact name: ev-flex-bias-v25-r2-complete-31671974049
- SHA-256: c3ed929bf9e63abfab67fa1807103a6069707e93dd44eeb672abdbff1f5760e3

R2 boundary witness:
- Run ID: 31676835878
- Artifact ID: 9172627041
- Artifact name: v25b-r2-boundary-witness-31676835878
- SHA-256: 9fa2a62f298fefc2625e6e1861cccb08c5c875fa79b1e58805523851095e850e

Fixed-ray vehicle verification:
- Run ID: 31688883154
- Artifact ID: 9177837288
- Artifact name: v25b-fixed-ray-vehicle-verification-31688883154
- SHA-256: c08fe325ff23ad974d0b697a9a8bad48ac412a77b1c03153ad9ffe58b5b740d3

## Files

- `v2_5b_inc_only_manuscript_freeze.md`: human-readable final evidence and claim boundary.
- `v2_5b_inc_only_manuscript_freeze.json`: machine-readable frozen metrics and provenance.
- `v2_5b_inc_only_cases.csv`: compact 46-case manuscript table.
- `v2_5b_inc_only_predictions_full.csv`: all archived prediction/policy columns for the 46 validated INC cases.
- `v2_5b_inc_only_raw_evaluations.json`: full archived raw evaluation objects for the 46 validated INC cases.
- `v2_5b_inc_only_boundary_witness.csv`: full 32-case INC boundary-witness rows.
- `v2_5b_independent_verification_corrected.json`: corrected independent R2 verification.
- `v2_5b_fixed_ray_vehicle_verification.{md,csv,json}`: full post-hoc vehicle-feasibility verification evidence.
- `SHA256SUMS.txt`: content hashes for this directory.

## Usage rule

For the conference manuscript, use this directory as the authoritative analysis layer. Do not silently replace values with older R2 mixed-direction summaries. Raw R2 and boundary artifacts remain provenance sources; manuscript figures and tables should be derived from the validated INC/V1G freeze.
