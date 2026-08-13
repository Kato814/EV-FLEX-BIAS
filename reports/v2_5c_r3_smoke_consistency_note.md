# V2.5C-R3 smoke implementation consistency note

Date: 2026-08-13

## Status

The first successful V2.5C smoke run (`31680768793`) is retained only as an implementation-development record and is **not** manuscript evidence.

## Consistency issue identified after the run

The preregistered R3 design requires the following construction at a failed slot:

1. use the existing three-phase point optimizer and finite-difference sensitivity;
2. obtain a nonlinear-feasible pointwise spatial injection;
3. interpolate that injection to the exact feeder aggregate required by the fixed ray;
4. verify the interpolated spatial target nonlinearly;
5. impose that bus-phase injection as an **equality target** in the EV trajectory LP.

The first smoke implementation instead inserted finite-difference network inequalities directly into the trajectory LP. Although its guardrails and nonlinear audits executed, that implementation was not identical to the frozen preregistration.

## Resolution

No R3 scientific result was produced from the first smoke. Its four case outcomes are not used for method selection, threshold tuning, case selection, or manuscript claims.

The corrected smoke implementation restores the preregistered method identity:

> point optimizer -> nonlinear-feasible spatial target -> fixed bus-phase equality -> feeder-time commitment-preserving trajectory LP -> full nonlinear audit.

The target set, network constraints, EV constraints, preservation level, alpha definition, and final nonlinear truth audit remain unchanged.

## Stop rule

If the corrected implementation smoke cannot execute this preregistered method without changing its scientific definition, formal R3 is cancelled. If it passes, the method is frozen and may be run once on the preregistered 56-case target set. No R4 is planned.
