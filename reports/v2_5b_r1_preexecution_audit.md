# V2.5B-R1 pre-execution audit

Date: 2026-08-12

## Status

The V2.5B three-phase replication had not started when this audit was performed. No V2.5B outcome was available or used. Scenario selection remains the complete suffix set 26–31 in every feeder × call-time cell; the frozen V2.4 PHiCTE model, penalty, quantile, and correction are unchanged.

## Audit findings and amendment

1. **Risk denominator correction.** The previous gate required at least 73 active 15-min offers. The Wilson uncertainty of the material false-safe rate, however, is determined by the number of non-abstained prescriptions. V2.5B-R1 therefore requires both at least 73 active primary rows and at least 73 prescribed primary rows.
2. **Feeder-specific coverage.** Because V2.5A found opposite kW-retention effects on IEEE13 and LV906, the primary evidence is feeder-stratified. V2.5B-R1 requires at least 24 prescribed primary rows in each feeder and an empirical material false-safe rate no larger than 5% in each feeder.
3. **Strict lower-envelope integrity.** The material false-safe event allows up to a 5% shortfall (`alpha_transfer >= 0.95 × factor`). That is suitable for the material-risk metric but not sufficient for an empirical lower-bound interpretation. V2.5B-R1 separately requires zero cases with `factor > alpha_transfer` overall and within each feeder.

## Statistical reference

For a two-sided 95% Wilson interval with zero observed events, 73 prescribed cases are the smallest sample size with an upper bound at or below 5% (approximately 0.04999). With one observed event, 110 cases would be required. This is an uncertainty reference only; V2.5B remains retrospective and does not provide a deployment guarantee.

## Unchanged scientific boundaries

- blind holdout claim: false
- confirmatory claim: false
- line thermal constraints: out of scope
- 15 min: primary
- 30/60 min: descriptive sensitivity only
- pooled-kW superiority: not required
- IEEE13 positive kW delta versus feeder-only: not required
- LV906 positive kW delta versus feeder-only: required to replicate the V2.5A signal
