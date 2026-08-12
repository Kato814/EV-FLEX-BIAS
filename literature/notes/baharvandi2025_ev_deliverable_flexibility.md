# Baharvandi & Nguyen (2025) — Deliverable EV Aggregator Flexibility

**Status:** CORE  
**Primary record:** arXiv:2501.06679  
**Last checked:** 2026-08-12

## What the paper explicitly addresses

The paper proposes a coordinated framework for EV charging in which a distribution system operator first optimizes the amount of EV-aggregator energy flexibility that is deliverable under grid constraints and uncertainty, and each EV aggregator subsequently optimizes its own charging schedule. The abstract reports validation on a modified IEEE 33-bus distribution network.

## Why it matters to EV-FLEX-BIAS

This is direct recent evidence that "aggregator flexibility" and "grid-deliverable flexibility" are distinct objects in EV research. It supports the motivation for studying whether an aggregator-level flexibility schedule/offer remains feasible after distribution-network constraints are considered.

## Project inference — not a claim made by the paper

EV-FLEX-BIAS can still occupy a different operating sequence if it studies a schedule computed first under a balanced approximation and then asks how much of that exact schedule transfers to an unbalanced three-phase network without reoptimization, followed by optional repair/screening. The novelty claim must be verified against additional near-duplicate literature before use in the paper.

## Claim supported

- Distribution-network constraints can determine how much EV-aggregator flexibility is actually deliverable.

## Claim not supported

- This paper does not prove that fixed balanced-to-three-phase replay is novel.
- The abstract alone does not establish the detailed phase-unbalance modeling used in its network formulation.
