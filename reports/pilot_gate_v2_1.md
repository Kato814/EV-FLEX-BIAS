# EV-FLEX-BIAS V2.1 试运行停止门评估

- 验证器状态：`VALID`
- 总体动作：`NO_GO_REASSESS_BROAD_TOPIC`
- 工作单：16 / 16
- 评估行：48 / 48
- 正式运行状态：未启动正式 V2.1 重跑

## 分轴结论

| 评估轴 | 状态 |
|---|---|
| `validator_status` | `VALID` |
| `baseline_status` | `PASS_ALL_BASELINES` |
| `active_offer_status` | `PASS_ACTIVE_COVERAGE` |
| `core_topic_status` | `GO` |
| `scenario_dominance_status` | `DISTRIBUTED` |
| `direction_claim_status` | `KEEP_CLAIM` |
| `duration_claim_status` | `KEEP_CLAIM` |
| `feeder_replication_status` | `NO_GO_SINGLE_FEEDER_DOMINATED` |
| `tie_break_route_status` | `INDETERMINATE_REPEAT` |
| `screening_compute_status` | `REPEAT_TIMING` |
| `v2_0_reuse_status` | `DIAGNOSTIC_ONLY_NO_FLIP` |
| `overall_action` | `NO_GO_REASSESS_BROAD_TOPIC` |
| `decision_class` | `NO_GO` |

## 结构有效性

- 加载状态：`VALID`
- 未发现结构错误。

## 指标与原因

- 指标：`{"active_offer_coverage":{"denominator":48,"numerator":47,"rate":0.9791666666666666},"baseline_coverage":{"denominator":8,"numerator":8,"rate":1.0},"core_bad_alpha":{"denominator":47,"numerator":12,"rate":0.2553191489361702,"unique_bad_scenarios":4},"direction_materiality":{"denominator":23,"numerator":8,"rate":0.34782608695652173},"duration_materiality":{"denominator":15,"numerator":4,"rate":0.26666666666666666},"feeder_bad_alpha":{"by_feeder":{"ieee13":0,"lv906":12},"denominator":12,"numerator":12,"rate":1.0},"scenario_dominance":{"by_scenario":{"ieee13_0000_09":0,"ieee13_0200_17":0,"ieee13_0600_24":0,"ieee13_1900_17":0,"lv906_0000_11":4,"lv906_0200_03":3,"lv906_0600_02":3,"lv906_1900_18":2},"denominator":12,"numerator":4,"rate":0.3333333333333333},"screening_compute":{"by_feeder":{"ieee13":{"maximum_schedule_warm_cv":0.2884095276831371,"pooled_warm_cv_diagnostic":0.19538965988507978,"unique_schedules":24,"valid_unique_schedules":24,"warm_cv":0.2884095276831371,"warm_p95_s":0.04592970001976937,"warm_sample_count":72},"lv906":{"maximum_schedule_warm_cv":0.07326308892681423,"pooled_warm_cv_diagnostic":0.274194610660676,"unique_schedules":23,"valid_unique_schedules":23,"warm_cv":0.07326308892681423,"warm_p95_s":0.945880200015381,"warm_sample_count":69}},"denominator":47,"numerator":47,"rate":1.0,"unique_schedule_count":47},"tie_new_unsafe":{"denominator":35,"numerator":0,"rate":0.0},"tie_offer_retention":{"denominator":47,"minimum":0.999999999999999,"numerator":37,"rate":0.7872340425531915},"tie_post_bad":{"denominator":47,"numerator":10,"rate":0.2127659574468085},"tie_rescue":{"denominator":12,"numerator":0,"rate":0.0},"v2_0_label_flip":{"denominator":47,"numerator":0,"rate":0.0},"v2_0_legacy_diagnostic_failure":{"denominator":47,"numerator":0,"rate":0.0}}`
- 原因代码：`BAD_ALPHA_SINGLE_FEEDER_DOMINATED_NO_GO`
- 原因代码：`CORE_BAD_ALPHA_SIGNAL_PRESENT`
- 原因代码：`TIE_BREAK_EVIDENCE_INDETERMINATE`
- 原因代码：`TIMING_CV_REPEAT`
- 原因代码：`V2_0_REUSE_DIAGNOSTIC_ONLY`

## 可追溯哈希

| 证据 | 路径 | SHA-256 |
|---|---|---|
| `config` | `config/pilot_gate_v2_1.json` | `1ecc530362e5bd51f144c85156e4bae93eb9ec30137238cf7041bf9887cb122b` |
| `manifest` | `manifests/audit_pilot_work_units_v2_1.csv` | `d7d5d0424935185de2d49bf5b9aa8524ca3abf66cd23e3677b5b70e5e5936615` |
| `pilot_module` | `src/evflex/pilot.py` | `37bde81640d82bb77ae9a5bee62e02274743f3a41ef8f5ab973d8e9ba1554a9b` |
| `runner` | `scripts/run_pilot_gate_v2_1.py` | `6489a712bf1a674a7995ad6f240af25647864aa4e1c2ae95db5768770a3212ba` |
| `evaluator` | `scripts/evaluate_pilot_gate_v2_1.py` | `51dea1efb55c093e1fc368102d391c5483afef770ec27b6ad5c81caf747cd491` |
| `evaluation_csv` | `results/pilot_v2_1/pilot_evaluations_v2_1.csv` | `bfb22446390191bcbc39f4de3f9363f211a090e8022f89f91c1ef515a9cf547a` |
| `raw_hash_csv` | `reports/pilot_work_unit_hashes_v2_1.csv` | `4f801c8a169f1569dee46f3398e505a4556c92096682569095fe1aea33d4131e` |

> 本评估器只汇总 16 WU 试运行证据，不会启动任何后续重跑。
