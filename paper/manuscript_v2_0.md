<!--
MINI OUTLINE
1. Motivation: balanced-network screening is fast, but deliverability can be direction-, duration-, and feeder-specific.
2. Method: same-input balanced estimate, multi-period nonlinear three-phase verification, alpha_map and false-safe labels.
3. Protocol: development-only model/threshold selection, compact mechanistic ablation, immutable one-pass holdout.
4. Evidence: paired directional effects, ablation mechanisms, and formal applicability outcomes.
5. Boundary: claims are cell-specific; no carbon reduction is measured.

CLAIM-EVIDENCE MAP
C1 Balanced approximations can overstate deliverable flexibility -> development/holdout alpha_map maps and Fig. 2.
C2 Directional asymmetry is feeder- and duration-dependent -> paired holdout bootstrap and Fig. 4.
C3 Phase imbalance and V2G participation are mechanisms, not universal effects -> compact ablation and Fig. 3.
C4 Only two predeclared applicability cells validate -> one-pass holdout table and Fig. 4.
-->

# Direction- and Duration-Specific Validity of Balanced-Network EV Flexibility Estimates

Author Name(s) — replace before submission

Affiliation(s) and corresponding-author email — replace before submission

## Abstract

Balanced-network models enable fast electric-vehicle (EV) flexibility screening, but their offers may not remain deliverable in an unbalanced feeder and their validity can change with regulation direction and service duration. This paper introduces a same-input applicability assessment that maps each balanced offer to the largest fraction feasible under full multi-period nonlinear three-phase verification. Cell-specific, abstaining risk rules are selected using development-only out-of-fold predictions and frozen before a one-pass holdout audit. The protocol evaluates V1G charging increases and V1G/V2G decreases for 15-, 30-, and 60-min calls on IEEE13 and a 906-bus European low-voltage feeder. In the holdout, 15-min median deliverability fractions are {{v2.core.holdout.ieee13.inc.15m.median_alpha_map}} versus {{v2.core.holdout.ieee13.dec.15m.median_alpha_map}} for IEEE13 increasing and decreasing calls, and {{v2.core.holdout.lv906.inc.15m.median_alpha_map}} versus {{v2.core.holdout.lv906.dec.15m.median_alpha_map}} for LV906. Only two of twelve feeder–direction–duration cells satisfy the predeclared minimum sample and 5% false-safe criterion. The results show that balanced estimates can support fast screening, but their applicability should be validated locally rather than represented by a universal derating factor.

**Index Terms—**electric vehicles, distribution-system flexibility, unbalanced networks, V1G, V2G, applicability assessment.

## I. Introduction

Electric-vehicle (EV) aggregators can provide charging increases, charging reductions, and vehicle-to-grid export for distribution-system and system-level services. Their offered flexibility, however, is deliverable only when vehicle energy constraints and network limits remain feasible throughout the requested service interval. Balanced-network approximations are attractive for rapid screening, yet phase asymmetry and location-dependent voltage or thermal constraints can make a balanced estimate optimistic when it is mapped back to a nonlinear three-phase feeder.

Existing aggregate-flexibility models characterize feasible power regions or schedule plug-in EV populations under energy and power limits [1]–[4]. Related distribution-grid studies explicitly model unbalance and quantify how phase allocation, charging control, or V2G participation alters grid hosting conditions [5]–[7]. These lines establish the value of tractable aggregation and the importance of phase-aware verification, but they do not identify when a balanced-network flexibility estimate can be trusted for a particular feeder, regulation direction, and service duration. A pooled average error is insufficient for this purpose because a practically unsafe case is directional: the balanced model declares a call feasible while the same call fails under three-phase verification.

This paper develops a same-input applicability-assessment pipeline for balanced EV-flexibility estimates. The balanced model first computes an offered call under identical EV states, native load, call time, and duration. A full multi-period nonlinear three-phase model then searches for the largest deliverable fraction, denoted by \(\alpha_{\mathrm{map}}\). Cell-specific logistic risk models use only observable scenario descriptors and select the widest development-set coverage satisfying a predeclared false-safe constraint. Models and thresholds are frozen before a single holdout unlock. Figure 1 summarizes the resulting path from a fast estimate to a validated, abstaining applicability rule.

The contributions are threefold. First, the study defines a direction-aware deliverability metric and false-safe event that preserve the operational meaning of a balanced offer. Second, it evaluates V1G and V2G calls over multiple service durations on two structurally different unbalanced feeders, with a compact development-only ablation of phase allocation, electrical location, native load, charging urgency, and V2G participation. Third, it separates model development from a one-pass holdout audit and reports validated, failed, insufficient-sample, and no-rule outcomes rather than converting every fitted cell into a claim. Across the formal holdout, only two of twelve feeder–direction–duration cells meet the predeclared applicability rule, demonstrating that applicability should be stated locally rather than assumed from aggregate accuracy.

[FIGURE:fig1_framework_v2_0.png|Fig. 1. Same-input assessment and one-pass validation pipeline. The balanced offer is screened by nonlinear multi-period three-phase verification; development data alone determine cell-specific abstaining rules.]

## II. Same-Input Applicability Assessment

### A. Balanced Offer and Three-Phase Deliverability

For each scenario \(s\), direction \(d\), and duration \(T\), the balanced model returns a constant-block flexibility offer \(F_{\mathrm{bal}}(s,d,T)\). The increasing direction represents additional charging; the decreasing direction represents charging reduction and, where participating vehicles permit, V2G export. Both the balanced and three-phase models receive the same EV arrivals, departures, state of charge, charging limits, phase and location assignments, native-load trajectory, call time, and service duration. This same-input design isolates the network representation rather than changes in fleet availability or scheduling assumptions.

The three-phase verifier searches the largest scale of the balanced offer that remains feasible over every 15-min interval in the service window. Its output is

[EQUATION:\alpha_{\mathrm{map}}(s,d,T) = F_3ph(s,d,T) / F_bal(s,d,T),   0 <= \alpha_{\mathrm{map}} <= 1.]

Here, \(\alpha_{\mathrm{map}}=1\) means that the full balanced offer is deliverable, whereas a smaller value quantifies the retained fraction. A false-safe event is declared when \(\alpha_{\mathrm{map}}<0.95\): the fast model offers a call for which at least 5% must be removed after nonlinear three-phase verification. The verifier enforces 0.95–1.06 p.u. bus-voltage bounds, a 2% voltage-unbalance-factor limit, and unit line and feeder loading limits.

### B. Multi-Period and Nested-Duration Closure

Deliverability is checked over complete EV and network trajectories rather than at a single snapshot. Vehicle energy balance, connection status, charging or export power, and departure-energy requirements are enforced for the noon-to-noon horizon. For each scenario–direction work unit, the 15-, 30-, and 60-min calls are solved together. A requested duration may use a physically feasible schedule from the same or a longer nested duration when the latter provides greater capacity, with ties assigned to the shortest source duration. This closure enforces non-increasing service capacity with duration without consulting holdout outcomes.

### C. Cell-Specific Abstaining Rules

Applicability is modeled separately for the 12 combinations of two feeders, two directions, and three durations. Each L2-logistic model predicts false-safe risk from the EV-nameplate-to-transformer ratio, native-load multiplier, phase-imbalance index, far-zone probability, median charging urgency, sine and cosine call-time encoding, and dominant-phase indicators; decreasing-direction models also include realized V2G participation. These descriptors are available before three-phase verification and therefore support prospective screening.

Numeric features are standardized within each training fold, and dominant phase is one-hot encoded with phase a as the reference. Model regularization is selected by the minimum five-fold stratified out-of-fold Brier score over \(C\in\{0.03,0.1,0.3,1,3,10,30\}\), with the smaller \(C\) used for ties. Within each cell, the risk threshold maximizes development-set coverage subject to at least 20 selected cases and an empirical false-safe rate no greater than 5%. A cell with no qualifying threshold remains without a rule. All feature definitions, coefficients, and thresholds are hashed and frozen before the holdout set is opened.

## III. Experimental Protocol

### A. Feeders, Scenarios, and Quality Gates

The experiments use the IEEE 13-node feeder and a 906-bus European low-voltage feeder, retaining their three-phase topology and phase-specific loads [8], [9]. EV travel and connection trajectories are derived from the 2022 U.S. National Household Travel Survey [10]. Each noon-to-noon scenario is evaluated at calls beginning at 19:00, 00:00, 02:00, and 06:00 for 15, 30, and 60 min. The core design contains 256 scenarios and 1,536 direction–duration evaluations: {{v2.sample.development_evaluations}} are assigned to development and 384 are sealed for holdout.

The development gate accepts {{v2.sample.development_success}} of {{v2.sample.development_evaluations}} evaluations. The remaining six rows are explicit baseline-infeasible outcomes from one LV906 scenario across both directions and three durations, not software failures; paired summaries therefore use 96 IEEE13 and 95 LV906 scenarios. The compact mechanistic experiment adds {{v2.sample.ablation_evaluations}} development-only 15-min evaluations and completes {{v2.sample.ablation_success}}. Every numerical work unit runs in a fresh single-threaded process and writes an atomic, hash-audited artifact.

### B. Compact Mechanistic Ablation

The ablation varies one factor at a time around a common reference at 19:00 and 02:00. Phase allocation uses 1:1:1, 2:1:1, and 4:1:1 ratios; far-zone probability, native-load multiplier, and charging urgency each use three levels; V2G participation uses four levels for the decreasing direction. Each level has three preassigned seeds, and dominant phase is rotated where applicable. Contrasts are paired within feeder, call time, direction, and replicate. Frozen 95% intervals use 10,000 stratified bootstrap resamples with seed 2026072001. Because each elementary contrast contains only three paired replicates, these results diagnose mechanisms rather than estimate universal effect sizes.

### C. One-Pass Holdout Audit

The holdout is opened once after code, features, models, thresholds, statistical procedures, and manuscript-value generation are frozen. All {{v2.sample.holdout_success}} of {{v2.sample.holdout_evaluations}} evaluations terminate successfully. No model is refitted, no threshold is changed, and no scenario ID or seed is replaced. Directional contrasts use 10,000 call-time-stratified bootstrap resamples with seed 2026072002. A formal applicability claim requires at least 20 selected holdout cases and an observed selected false-safe rate no greater than 5%; Wilson intervals are reported to expose uncertainty rather than used as a second tuning criterion.

## IV. Results

### A. Balanced Estimates Are Direction- and Feeder-Specific

Development results show that balanced estimates are frequently optimistic, but the severity is not uniform. At 15 min, median \(\alpha_{\mathrm{map}}\) is {{v2.core.development.ieee13.inc.15m.median_alpha_map}} for IEEE13 increasing calls and {{v2.core.development.lv906.inc.15m.median_alpha_map}} for LV906 increasing calls. The corresponding false-safe rates are {{v2.core.development.ieee13.inc.15m.false_safe_rate}} and {{v2.core.development.lv906.inc.15m.false_safe_rate}}. IEEE13 decreasing calls have a median of {{v2.core.development.ieee13.dec.15m.median_alpha_map}}, whereas LV906 decreasing calls retain only {{v2.core.development.lv906.dec.15m.median_alpha_map}}. Thus, neither “increasing is always harder” nor “decreasing is always safe” transfers across feeders.

[FIGURE:fig2_alpha_map_v2_0.png|Fig. 2. Development-set mapping from balanced flexibility to nonlinear three-phase deliverability. Each cell is feeder-, direction-, duration-, and call-time-specific; \(\alpha_{\mathrm{map}}<0.95\) is false-safe.]

The sealed holdout preserves the same heterogeneity. At 15 min, the IEEE13 median is {{v2.core.holdout.ieee13.inc.15m.median_alpha_map}} for increasing calls and {{v2.core.holdout.ieee13.dec.15m.median_alpha_map}} for decreasing calls; LV906 gives {{v2.core.holdout.lv906.inc.15m.median_alpha_map}} and {{v2.core.holdout.lv906.dec.15m.median_alpha_map}}, respectively. In paired IEEE13 cases, the increasing-minus-decreasing median \(\alpha_{\mathrm{map}}\) difference is {{v2.holdout.directional.ieee13.15m.median_alpha_diff}} with a 95% interval [{{v2.holdout.directional.ieee13.15m.alpha_ci_low}}, {{v2.holdout.directional.ieee13.15m.alpha_ci_high}}]. For LV906 the 15-min difference is {{v2.holdout.directional.lv906.15m.median_alpha_diff}} [{{v2.holdout.directional.lv906.15m.alpha_ci_low}}, {{v2.holdout.directional.lv906.15m.alpha_ci_high}}], whose interval crosses zero. The IEEE13 contrasts at 30 and 60 min are {{v2.holdout.directional.ieee13.30m.median_alpha_diff}} and {{v2.holdout.directional.ieee13.60m.median_alpha_diff}}, while LV906 gives {{v2.holdout.directional.lv906.30m.median_alpha_diff}} and {{v2.holdout.directional.lv906.60m.median_alpha_diff}}. Duration is therefore part of the claim rather than a plotting detail.

### B. Phase Allocation and V2G Participation Expose Mechanisms

The compact ablation identifies conditions under which the balanced mapping changes sharply. For increasing IEEE13 calls at 19:00, changing the phase ratio from 2:1:1 to 4:1:1 reduces median \(\alpha_{\mathrm{map}}\) by {{v2.ablation.a1_phase.ieee13.19_00.inc.4_1_1.alpha_contrast}} [{{v2.ablation.a1_phase.ieee13.19_00.inc.4_1_1.alpha_ci_low}}, {{v2.ablation.a1_phase.ieee13.19_00.inc.4_1_1.alpha_ci_high}}]. The analogous LV906 contrast is {{v2.ablation.a1_phase.lv906.19_00.inc.4_1_1.alpha_contrast}} [{{v2.ablation.a1_phase.lv906.19_00.inc.4_1_1.alpha_ci_low}}, {{v2.ablation.a1_phase.lv906.19_00.inc.4_1_1.alpha_ci_high}}]. By contrast, for LV906 decreasing calls at 02:00, raising V2G participation from 0.5 to 1.0 increases \(\alpha_{\mathrm{map}}\) by {{v2.ablation.a5_v2g.lv906.02_00.dec.1_0.alpha_contrast}} [{{v2.ablation.a5_v2g.lv906.02_00.dec.1_0.alpha_ci_low}}, {{v2.ablation.a5_v2g.lv906.02_00.dec.1_0.alpha_ci_high}}]. These paired results support phase concentration and V2G availability as mechanisms, while the small replicate count and setting-specific sign changes preclude universal causal magnitudes.

[FIGURE:fig5_ablation_v2_0.png|Fig. 3. Development-only paired ablations at 15 min. Points show upper-level-minus-reference contrasts in \(\alpha_{\mathrm{map}}\); intervals are frozen stratified-bootstrap 95% intervals.]

### C. Applicability Rules Validate in Only Two Cells

[TABLE:applicability|TABLE I. One-pass holdout applicability. Validated: selected \(n\geq20\) and false-safe rate \(\leq5\%\).]

Only IEEE13 decreasing calls at 15 and 60 min satisfy the formal criterion. The 15-min rule selects {{v2.holdout.applicability.ieee13.dec.15m.selected_n}} of 32 cases, with {{v2.holdout.applicability.ieee13.dec.15m.false_safe_n}} false-safe outcome, a rate of {{v2.holdout.applicability.ieee13.dec.15m.false_safe_rate}}, and {{v2.holdout.applicability.ieee13.dec.15m.coverage}} coverage. The 60-min rule selects {{v2.holdout.applicability.ieee13.dec.60m.selected_n}} cases with {{v2.holdout.applicability.ieee13.dec.60m.false_safe_n}} false-safe outcomes and {{v2.holdout.applicability.ieee13.dec.60m.coverage}} coverage. IEEE13 decreasing at 30 min fails because its selected false-safe rate is {{v2.holdout.applicability.ieee13.dec.30m.false_safe_rate}}. Three cells are sample-insufficient despite fitted development rules, and six have no qualifying development rule. The validated claim is therefore restricted to the two named cells.

[FIGURE:fig6_holdout_v2_0.png|Fig. 4. Frozen-model holdout applicability outcomes, reported without refitting, rethresholding, or replacement.]

## V. Practical Implications and Limitations

A balanced flexibility estimate remains useful as a fast upper-level screening signal, but it should not be interpreted as a feeder-independent guarantee. The proposed rule adds an abstaining layer: it either identifies a locally validated operating region or declines to make a claim. This structure is compatible with aggregator workflows in which a fast offer must be screened before detailed three-phase validation, particularly for smart charging and V2G services that may support low-carbon operation.

The evidence has four boundaries. First, it covers two benchmark feeders and synthetic EV populations derived from one travel survey, not field deployments. Second, phase connectivity, load profiles, and V2G participation are modeled inputs; telemetry, communication failures, market response, and battery degradation are outside scope. Third, some holdout cells contain too few selected cases to support a formal claim, and even the validated cells retain wide Wilson intervals. Fourth, the study measures flexibility deliverability rather than emissions, renewable curtailment, or carbon reduction. The results therefore establish where balanced-network estimates were reliable under the stated protocol, not a universal derating factor or a quantified carbon benefit.

## VI. Conclusion

This paper addresses the operational validity of balanced-network EV-flexibility offers through same-input, multi-period nonlinear three-phase verification and frozen cell-specific abstaining rules. The core insight is that deliverability is jointly conditioned on feeder, regulation direction, and duration; an aggregate error statistic cannot replace this local structure. Development and mechanistic-ablation evidence show substantial, setting-dependent losses under phase concentration and changing V2G participation. In the one-pass holdout, only IEEE13 decreasing calls at 15 and 60 min meet the predeclared applicability criterion, while the remaining cells fail, lack a rule, or are sample-insufficient. These outcomes support conservative local screening rather than universal derating. Extending the audit to field-calibrated feeders, larger independent holdouts, uncertain telemetry, and joint flexibility–emissions objectives is the next step.

## References

[1] X. Chen, E. Dall’Anese, C. Zhao, and N. Li, “Aggregate power flexibility in unbalanced distribution systems,” IEEE Trans. Smart Grid, vol. 11, no. 1, pp. 258–269, Jan. 2020, doi: 10.1109/TSG.2019.2920991.

[2] F. Al Taha, T. L. Vincent, and E. Bitar, “An efficient method for quantifying the aggregate flexibility of plug-in electric vehicle populations,” IEEE Trans. Smart Grid, vol. 16, no. 4, pp. 3142–3154, Jul. 2025, doi: 10.1109/TSG.2024.3384871.

[3] D. Yan, C. Ma, and Y. Chen, “Distributed coordination of charging stations considering aggregate EV power flexibility,” IEEE Trans. Sustain. Energy, vol. 14, no. 1, pp. 356–370, Jan. 2023, doi: 10.1109/TSTE.2022.3213173.

[4] X. Shi, Y. Xu, Q. Guo, and H. Sun, “Optimal dispatch based on aggregated operation region of EV considering spatio-temporal distribution,” IEEE Trans. Sustain. Energy, vol. 13, no. 2, pp. 715–731, Apr. 2022, doi: 10.1109/TSTE.2021.3130547.

[5] A. Churkin, W. Kong, P. Mancarella, and E. A. Martínez Ceseña, “Quantifying phase unbalance and coordination impacts on distribution network flexibility,” arXiv:2408.06516, 2024.

[6] N. I. Nimalsiri, E. L. Ratnam, D. Smith, C. Mediwaththe, and S. Halgamuge, “A distributed coordination approach for the charge and discharge of electric vehicles in unbalanced distribution grids,” IEEE Trans. Ind. Informat., vol. 20, no. 3, pp. 3551–3562, Mar. 2024, doi: 10.1109/TII.2023.3310741.

[7] F. Verbist, N. K. Panda, P. P. Vergara, and P. Palensky, “Impact of dynamic tariffs for smart EV charging on LV distribution network operation,” in Proc. IEEE Power & Energy Soc. Gen. Meeting, 2023, pp. 1–5.

[8] Electric Power Research Institute, “OpenDSS: The Open Distribution System Simulator,” software and documentation. [Online]. Available: https://opendss.epri.com/

[9] IEEE PES AMPS Distribution System Analysis Subcommittee, “IEEE distribution test feeders.” [Online]. Available: https://cmte.ieee.org/pes-testfeeders/resources/

[10] S. Bricka, T. Reuscher, P. Schroeder, M. Fisher, J. Beard, and L. Sun, “Summary of travel trends: 2022 National Household Travel Survey,” U.S. Federal Highway Administration, Rep. FHWA-HPL-24-009, Jan. 2024.
