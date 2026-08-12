# Churkin et al. (2024) — Phase Unbalance and Coordination Impacts

**Status:** CORE  
**Primary record:** arXiv:2408.06516  
**Last checked:** 2026-08-12

## What the paper explicitly addresses

The paper studies aggregate DER flexibility in low-voltage distribution networks while explicitly considering voltage unbalance and coordination constraints. Its stated motivation is that prior flexibility aggregation work often assumes perfect coordination and commonly uses single-phase power-flow representations that can hide phase-unbalance effects.

The reported case studies include an illustrative 5-bus network and a real 221-bus UK LV network. The abstract reports that more than 30% of aggregate DER flexibility potential may be unavailable because of voltage unbalance and lack of coordination between DER connected to different phases.

## Why it matters to EV-FLEX-BIAS

This is strong evidence against interpreting every low `alpha_transfer` of a fixed balanced schedule as a hard network-capacity limit. A fixed schedule can fail because of the way flexible devices are coordinated or distributed across phases even if a different disaggregation could deliver more aggregate service.

## Project inference — not a claim made by the paper

A useful extension of EV-FLEX-BIAS is to compare:

- `alpha_fixed`: transferable fraction of the original balanced schedule without internal redispatch;
- a phase-aware repaired/redispatched counterpart that preserves the externally relevant service as closely as possible.

The difference would estimate the share of apparent transferability loss that is coordination-repairable. The exact definition and the term "repairability" remain project choices and should not be attributed to Churkin et al.

## Claim supported

- Phase unbalance and coordination assumptions can materially reduce usable aggregate distribution-network flexibility.

## Claim not supported

- This paper does not establish that the EV-FLEX-BIAS fixed-schedule transferability formulation is novel.
- It does not establish a specific EV repair algorithm for our setting.
