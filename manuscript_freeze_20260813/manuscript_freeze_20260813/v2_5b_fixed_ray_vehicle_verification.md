# V2.5B fixed-ray vehicle-feasibility verification

**Role:** verification-only. No three-phase network result is recomputed, no alpha is changed, and no case is dropped.

- Active eligible primary 15-min cases checked: **89**
- Exact balanced schedule SHA matches: **89/89**
- Exact baseline schedule SHA matches: **89/89**
- `alpha_fixed` vehicle-feasible under signed-net physical interpretation: **65/89**
- Cases with at least one invalid archived prefix alpha sample: **43/89**
- INC alpha-fixed vehicle-feasible: **46/46**
- DEC alpha-fixed vehicle-feasible: **19/43**

The signed-net interpretation sets charge=max(u,0) and discharge=max(-u,0), so no simultaneous charging/discharging is possible by construction. Vehicle feasibility then requires the original reserve/capacity/departure-energy/power/budget invariants to remain within 1e-6.

## Cases failing vehicle feasibility at archived alpha_fixed

| evaluation | feeder | dir | alpha_fixed | sign-cross slots | max EV error | departure error |
|---|---|---|---:|---:|---:|---:|
| `v25b_replication_ieee13_0200_27__dec__15m` | ieee13 | dec | 0.834000 | 152 | 0.0210998 | 0.0210998 |
| `v25b_replication_ieee13_0600_29__dec__15m` | ieee13 | dec | 0.896000 | 137 | 0.00592046 | 0.00592046 |
| `v25b_replication_ieee13_1900_28__dec__15m` | ieee13 | dec | 0.974000 | 83 | 0.00184347 | 0.00184347 |
| `v25b_replication_lv906_0000_26__dec__15m` | lv906 | dec | 0.804000 | 16 | 0.0109233 | 0.0109233 |
| `v25b_replication_lv906_0000_27__dec__15m` | lv906 | dec | 0.756000 | 17 | 0.0104765 | 0.0104765 |
| `v25b_replication_lv906_0000_28__dec__15m` | lv906 | dec | 0.838000 | 6 | 0.00311328 | 0.00311328 |
| `v25b_replication_lv906_0000_30__dec__15m` | lv906 | dec | 0.716000 | 7 | 0.00312325 | 0.00312325 |
| `v25b_replication_lv906_0000_31__dec__15m` | lv906 | dec | 0.356000 | 8 | 0.00861316 | 0.00861316 |
| `v25b_replication_lv906_0200_26__dec__15m` | lv906 | dec | 0.712000 | 15 | 0.0083237 | 0.0083237 |
| `v25b_replication_lv906_0200_27__dec__15m` | lv906 | dec | 0.544000 | 10 | 0.004645 | 0.004645 |
| `v25b_replication_lv906_0200_28__dec__15m` | lv906 | dec | 0.574000 | 6 | 0.00583606 | 0.00583606 |
| `v25b_replication_lv906_0200_29__dec__15m` | lv906 | dec | 0.706000 | 13 | 0.00667168 | 0.00667168 |
| `v25b_replication_lv906_0200_30__dec__15m` | lv906 | dec | 0.714000 | 23 | 0.0203129 | 0.0203129 |
| `v25b_replication_lv906_0200_31__dec__15m` | lv906 | dec | 0.616000 | 9 | 0.00731183 | 0.00731183 |
| `v25b_replication_lv906_0600_26__dec__15m` | lv906 | dec | 0.518000 | 8 | 0.00554484 | 0.00554484 |
| `v25b_replication_lv906_0600_27__dec__15m` | lv906 | dec | 0.668000 | 16 | 0.0209875 | 0.0209875 |
| `v25b_replication_lv906_0600_28__dec__15m` | lv906 | dec | 0.732000 | 14 | 0.00437355 | 0.00437355 |
| `v25b_replication_lv906_0600_29__dec__15m` | lv906 | dec | 0.570000 | 8 | 0.00556514 | 0.00556514 |
| `v25b_replication_lv906_0600_30__dec__15m` | lv906 | dec | 0.738000 | 18 | 0.0217901 | 0.0217901 |
| `v25b_replication_lv906_0600_31__dec__15m` | lv906 | dec | 0.852000 | 15 | 0.00370765 | 0.00370765 |
| `v25b_replication_lv906_1900_26__dec__15m` | lv906 | dec | 0.492000 | 10 | 0.00876108 | 0.00876108 |
| `v25b_replication_lv906_1900_27__dec__15m` | lv906 | dec | 0.556000 | 12 | 0.0126643 | 0.0126643 |
| `v25b_replication_lv906_1900_29__dec__15m` | lv906 | dec | 0.628000 | 15 | 0.00787068 | 0.00787068 |
| `v25b_replication_lv906_1900_31__dec__15m` | lv906 | dec | 0.536000 | 11 | 0.0138577 | 0.0138577 |
