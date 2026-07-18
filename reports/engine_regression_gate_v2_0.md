# EV-FLEX-BIAS-V2.0 G1 engine regression

**Gate status: PASS**

- Golden comparisons: 24/24 status matches
- Repeats: 2 sequential runs with one numerical worker
- Capacity mismatches: 0
- `alpha_map` mismatches: 0
- Boolean/status mismatches: 0
- Maximum departure-energy error: 5.969e-13 kWh
- Maximum reserve violation: 0.000e+00 kWh
- Simultaneous charge/discharge intervals: 0
- Repeatability maximum capacity difference: 0.000e+00 kW
- Repeatability maximum `alpha_map` difference: 0.000e+00

The optional two-worker comparison was not run because the frozen low-resource policy limits G1 regression to one numerical worker. Sequential process/context reconstruction is covered by the repeated runs.
