# V2.5B manuscript evidence freeze — validated INC/V1G scope

**Decision date:** 2026-08-13  
**Status:** experiment scope frozen for manuscript drafting. No additional three-phase experiments are planned.

## 1. Validity decision

The post-hoc fixed-ray vehicle-feasibility gate reproduced all **89/89** balanced-schedule hashes and all **89/89** baseline hashes. It found:

- INC/V1G: **46/46** archived `alpha_fixed` values are vehicle-feasible under the signed-net physical interpretation.
- DEC/V2G: **19/43** archived `alpha_fixed` values are vehicle-feasible; **24/43** are not.
- Every DEC case has at least one vehicle-infeasible archived intermediate alpha sample.

Therefore the continuous schedule-ray transferability claim is frozen to **INC/V1G charging flexibility**. DEC/V2G continuous-ray results are not used as primary transferability evidence.

Formal R3 is **cancelled**. Its preregistered 56-case set mixes validated INC cases with DEC cases whose continuous ray is not vehicle-feasible. Redesigning the V2G ray after observing this would reopen the scientific method and is outside the frozen plan.

## 2. Independent R2 verification

The corrected independent verifier uses the intended analysis-eligibility semantics: scientifically valid active rows plus `INACTIVE_OFFER` rows are retained for coverage, while invalid baseline/schedule rows are excluded. It independently reproduces the archived overall and feeder policy metrics with **0 mismatches**.

- Primary planned analysis-eligible rows: **92**
- Active rows: **89**
- Inactive-offer rows: **3**
- Scientifically noneligible primary rows: **4**
- Numerical-failure audits: **0**
- Phase-repair paired-valid count: **79**
- Corrected verifier status: **PASS**

## 3. Frozen primary transferability results — INC/V1G

| Scope | n | mean alpha | median alpha | alpha < 0.95 | alpha < 0.5 | alpha < 1 |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 46 | 0.681 | 0.719 | 30 (65.2%) | 16 | 32 |
| IEEE13 | 22 | 0.834 | 0.999 | 9 | 2 | 11 |
| LV906 | 24 | 0.540 | 0.446 | 21 | 14 | 21 |

The bootstrap 95% interval for the **IEEE13 minus LV906 mean-alpha difference** is
**[0.144, 0.436]**, with median difference 0.295. This supports strong feeder heterogeneity within the tested cases.

The offer-weighted overall alpha is **0.726**.

## 4. Frozen physical boundary evidence — INC/V1G

There are **32** INC cases with `alpha_fixed < 1`; all **32/32** boundaries reproduce, with **0** numerical failures and **0** nonconverged checks. The first physical failure occurs in the flexibility call slot for **32/32** cases.

Constraint classes:

- Low voltage: **20/32**
- High voltage: **2/32**
- VUF: **5/32**
- Transformer loading: **5/32**
- Voltage or VUF combined: **27/32 = 84.4%**

Feeder split:

- IEEE13: **11** limited cases = 5 transformer, 5 VUF, 1 low-voltage.
- LV906: **21** limited cases = 19 low-voltage, 2 high-voltage; **21/21 are voltage-limited**.

This supports the paper statement that the loss mechanism is feeder-dependent and, in LV906, local voltage feasibility rather than feeder-level loading in the declared constraint set.

## 5. PHiCTE screening — secondary/exploratory only

On the validated INC scope, frozen PHiCTE gives:

- Prescribed: **44/46**, abstentions: **2**
- Material false-safe: **3/44 = 6.82%**
- Wilson 95% interval: **[2.35%, 18.23%]**
- Pooled-kW retention: **0.379**

Thus PHiCTE **does not meet a <=5% empirical-risk claim on the validated INC scope** and must not be presented as a risk guarantee.

Feeder behavior remains reversed:

- IEEE13 PHiCTE: risk **9.1%**, pooled retention **0.417**.
  Local feeder-direction-duration comparator: risk **4.5%**, retention **0.480**. PHiCTE is dominated here.
- LV906 PHiCTE: risk **4.5%**, pooled retention **0.166**, with 2 abstentions.
  Feeder-only/local/global comparators have zero observed false-safe risk but much lower retention (0.004/0.002/0.034). PHiCTE remains a feeder-specific risk-retention tradeoff, not a universal winner.

The three material false-safe cases are unchanged and all belong to INC:

- `v25b_replication_ieee13_0200_27__inc__15m`: alpha=0.554, PHiCTE=0.695, balanced offer=1671.2 kW.
- `v25b_replication_ieee13_0600_27__inc__15m`: alpha=0.496, PHiCTE=0.566, balanced offer=1220.5 kW.
- `v25b_replication_lv906_1900_28__inc__15m`: alpha=0.156, PHiCTE=0.211, balanced offer=221.5 kW.

## 6. Existing bus-time-preserving repair — diagnostic only

For validated INC cases:

- Paired-valid: **40/46 (87.0%)**
- Mean gain: **0.0054**
- Median gain: **0.0000**
- Positive gain: **7**
- Material gain >=0.05: **1**
- Worsened: **2**
- LV906 paired cases: mean gain **0.0000**

This remains a negative/structural diagnostic, not a main proposed repair method.

## 7. Manuscript claim boundary

### Claims supported

1. Balanced V1G charging-flexibility schedules can materially overstate deliverable flexibility when replayed without reoptimization in unbalanced three-phase feeders.
2. Transferability is strongly feeder-dependent: IEEE13 is substantially more transferable than LV906 in the tested INC cases.
3. The first fixed-schedule feasibility boundary is predominantly voltage/VUF-related (27/32), and all 21 limited LV906 INC cases are voltage-limited.
4. Frozen PHiCTE exhibits feeder-dependent screening tradeoffs but no validated universal risk guarantee.
5. The restricted bus-time-preserving repair provides little recovery, especially on LV906.

### Claims not supported / excluded

- No continuous DEC/V2G transferability claim based on the original net-power alpha ray.
- No claim that `alpha_fixed` is the maximum achievable EV flexibility under full three-phase reoptimization.
- No claim of PHiCTE global superiority or <=5% risk guarantee.
- No formal R3 spatial-recovery result.
- No line-thermal claim; line thermal remains outside the formal constraint set.
- No universal generalization beyond IEEE13 and LV906.

## 8. Stop rule and next step

**Experimental work is frozen here.** No new three-phase simulation, R3b, R4, or result-driven redesign is authorized for this conference submission.

The next work is manuscript production only: figures/tables from the frozen INC dataset, Introduction/Methods/Results/Discussion/Conclusion, citation audit, and 6-page IEEE formatting.
