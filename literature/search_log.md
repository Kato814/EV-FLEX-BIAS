# Literature Search Log

## 2026-08-12 — Initial structured review

### Objective

Create a current SOTA map before changing the EV-FLEX-BIAS research design. The immediate questions were:

1. Is unbalanced-network flexibility still an active 2024–2026 topic?
2. Is the distinction between nominal/aggregated flexibility and network-deliverable flexibility established in recent EV work?
3. Is phase coordination/unbalance a documented source of lost flexibility?
4. Are physics/sensitivity/linearized operating-envelope methods credible strong baselines for fast screening?
5. What prior art makes a claim of "first unbalanced flexibility study" untenable?

### Primary-source searches

- IEEE Xplore: `Aggregate Power Flexibility in Unbalanced Distribution Systems`
- IEEE Xplore: `Bayesian Active Learning-Based Soft Data Space Calibration for System-Wise Aggregate Flexibility Characterization`
- arXiv: `Quantifying Phase Unbalance and Coordination Impacts on Distribution Network Flexibility`
- arXiv: `Coordinated Deliverable Energy Flexibility from EV Aggregators in Distribution Networks`
- arXiv: robust dynamic operating envelopes + unbalanced distribution networks + sensitivity
- arXiv: phase allocation + unbalanced distribution networks + EV chargers
- arXiv: voltage unbalance sensitivity + multi-phase distribution grid
- arXiv: coordinated dynamic operating envelopes + grid-edge flexibility

### Initial conclusions

- `chen2020aggregate` is foundational prior art: aggregate flexibility in unbalanced distribution networks is not new.
- `churkin2024phase` and `jalilian2026coordinateddoe` provide strong support for treating coordination capability as a determinant of usable flexibility.
- `baharvandi2025deliverable` directly establishes recent EV-specific interest in grid-deliverable aggregator flexibility.
- `liu2024rdoe`, `gupta2025phaseallocation`, and `gupta2025vufsensitivity` justify investigating an unbalanced-network physics/sensitivity comparator for rapid screening.
- `wang2025bayesian` indicates that computationally efficient flexibility characterization remains an active methodological problem; its exact article page/DOI should be verified before manuscript citation.

### Open gaps to search next

- Exact near-duplicate prior art: balanced/positive-sequence EV schedule computed first, then replayed without reoptimization in an unbalanced three-phase feeder and converted to a transfer/derating factor.
- EV/V2G studies that preserve an aggregator-level commitment while allowing intra-fleet phase-aware redispatch.
- Recent 2024–2026 papers comparing full nonlinear unbalanced OPF against sensitivity/linearized safety screens using runtime and violation metrics.
- Whether "repairability" is established terminology; until verified, use it as a project working label only.
- Direct power-system applications of cluster/scenario-level conformal calibration; do not make it a core method claim until domain-specific precedent and statistical assumptions are adequately mapped.
