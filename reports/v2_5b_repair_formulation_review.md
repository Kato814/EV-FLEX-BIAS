# V2.5B-R2 repair-formulation review

Date: 2026-08-13

## Purpose

Assess whether the current phase-aware tie-break should be retained, generalized, or replaced before any R3 experiment. This memo separates (i) facts established by the completed R2 archive, (ii) facts established by the current code, and (iii) literature-supported design options.

## 1. What the current repair actually preserves

The current `phase_balanced_tie_break` is a lexicographic EV-trajectory redispatch. It reconstructs a feasible trajectory LP and then minimizes an L1 phase-difference objective subject to preserving the **original bus-by-time aggregate EV schedule**. The comparator also verifies the declared flexibility offer and EV invariants. It is therefore a narrow schedule-reallocation diagnostic, not a network-aware three-phase reoptimization.

This preservation rule is intentionally strong: for every bus and every 15-minute slot, the aggregate EV power at that bus is unchanged. Only allocation among EVs that share that bus can change the bus-phase injection.

## 2. What R2 establishes about this repair

For the primary 15-minute R2 sample, the archived paired-valid comparison shows small overall transferability improvement. The current tie-break is therefore not empirically supported as a strong mitigation method in its present form.

The key structural observation from the completed diagnostic is that the LV906 EV population has no bus groups with EVs spanning multiple phases. Under bus-time aggregate preservation and fixed EV phase connection, the bus-phase injection is consequently fixed at every LV906 EV bus. This makes zero LV906 transferability gain an expected consequence of the formulation's degrees of freedom; it does **not** establish that more general EV coordination cannot repair LV906 schedules.

## 3. Literature-supported alternatives

### 3.1 Aggregate flexibility followed by network-aware coordination

Yan, Ma, and Chen, *Distributed Coordination of Charging Stations Considering Aggregate EV Power Flexibility* (arXiv:2206.06834), derive aggregate EV flexibility first and then coordinate charging stations while enforcing AC power-flow constraints. This establishes a prior-art line in which aggregate commitments/flexibility are separated from network-aware disaggregation/coordination.

Primary source: https://arxiv.org/abs/2206.06834

### 3.2 Dispatch-plan tracking with EV charging-station flexibility

Gupta et al., *Grid-aware Scheduling and Control of Electric Vehicle Charging Stations for Dispatching Active Distribution Networks*, Part I/II (arXiv:2404.12863 and arXiv:2404.12870), compute a dispatch plan at the grid connection point and use EV charging-station flexibility and other controllable resources to track that plan while enforcing distribution-network constraints using a linearized OPF/MPC layer.

Primary sources:
- https://arxiv.org/abs/2404.12863
- https://arxiv.org/abs/2404.12870

### 3.3 Deliverable EV flexibility

Baharvandi and Nguyen, *Coordinated Deliverable Energy Flexibility from EV Aggregators in Distribution Networks* (arXiv:2501.06679), use a DSO stage to determine network-deliverable EV flexibility and an aggregator stage to construct fleet schedules. This is strong recent evidence that nominal aggregator flexibility and grid-deliverable flexibility are distinct objects.

Primary source: https://arxiv.org/abs/2501.06679

### 3.4 Coordination and phase-unbalance limits

Churkin et al., *Quantifying Phase Unbalance and Coordination Impacts on Distribution Network Flexibility* (arXiv:2408.06516), explicitly model phase-unbalance and phase-coordination constraints and show that coordination assumptions materially affect aggregate flexibility in LV networks.

Primary source: https://arxiv.org/abs/2408.06516

## 4. Implication for EV-FLEX-BIAS

A generalized **feeder-time commitment-preserving redispatch** is scientifically defensible: preserve the aggregator's total power trajectory at the feeder/grid-connection point while allowing EV charging/discharging to move among buses/vehicles subject to fleet constraints. However, generic network-aware redispatch is already established prior art; it should not be presented as a new optimization paradigm.

The potentially distinctive use in EV-FLEX-BIAS would be narrower: use such redispatch only as a **post-schedule repair/oracle** to decompose the loss of a schedule that was generated under a balanced-network approximation. The research question would be how much of `alpha_fixed` loss is recoverable without changing the external aggregate commitment.

## 5. Why this should not be implemented immediately

Whether a more general repair is worth the remaining implementation and validation time depends on the physical first-boundary mechanisms in R2:

- If most limited cases first violate feeder or transformer capacity, changing the spatial EV allocation while preserving the same feeder-time aggregate power may have limited benefit, especially for feeder-level loading.
- If voltage or VUF constraints dominate and the violations are spatial/phase-specific, spatial redispatch has a clearer mechanism by which it could improve transferability.
- If multiple constraints co-bind, a repair algorithm needs network sensitivity/OPF information; a global phase-balance heuristic alone would be weakly justified.

Therefore the boundary-witness diagnostic should precede any R3 repair implementation.

## 6. Conditional R3 decision rule

After boundary-witness results are available:

1. **Capacity-dominated boundary:** retain current repair only as a negative/limited diagnostic; do not spend time implementing generalized repair.
2. **Voltage/VUF-dominated boundary with spatial heterogeneity:** consider a small R3 commitment-preserving redispatch benchmark on the limited primary cases, explicitly labeled post-hoc and not independent confirmation.
3. **Mixed/co-binding boundary:** prefer a small network-aware oracle/sensitivity benchmark on representative cases rather than a new heuristic whose mechanism is unclear.

## 7. Claim boundary

Until a generalized repair is actually implemented and evaluated, the manuscript should not claim that EV flexibility losses are generally repairable by phase-aware coordination. The completed R2 supports only the narrower statement that the current bus-time-preserving tie-break has limited effectiveness, and that its LV906 result is structurally constrained by the absence of within-bus phase-reallocation freedom.
