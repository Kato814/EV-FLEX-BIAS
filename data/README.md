# 数据与溯源 | Data and provenance

本目录保存 EV-FLEX-BIAS 当前实验所需的原始调查数据、冻结派生输入和三相馈线模型。它们全部由普通 Git 对象管理，不依赖 Git LFS。

## 1. 同步状态

- 本地数据有效载荷文件数：23（不计本说明文件）。
- Git 跟踪的数据有效载荷文件数：23。
- 未跟踪的数据有效载荷文件数：0。
- 总大小：约 12.65 MiB。
- 最大文件：`formal_ev_populations_v1_2.csv`，约 7.84 MB，低于 GitHub 单文件限制。

这意味着当前实验使用的数据文件均包含在仓库提交中。这里的“全部”限定为本研究冻结输入，不表示镜像了 NHTS 网站上的所有产品、文档或历史版本。

## 2. 官方原始数据

| 文件 | 内容 | 大小 | SHA-256 |
|---|---|---:|---|
| `inherited/2022_NHTS_V2.1_CSV.zip` | FHWA 2022 National Household Travel Survey，CSV V2.1 官方下载包 | 4,533,528 bytes | `64530c396d5f164d2259a22f7042f27bee5147babcd367568ddbfafe6c8bf34c` |

压缩包按原字节保留，包含：

- `Citation.pdf`
- `hhv2pub.csv`
- `ldtv2pub.csv`
- `perv2pub.csv`
- `tripv2pub.csv`
- `vehv2pub.csv`

官方来源：<https://nhts.ornl.gov/downloads>

建议引用：Federal Highway Administration. (2022). *2022 National Household Travel Survey*. U.S. Department of Transportation, Washington, DC. Available at <https://nhts.ornl.gov>.

本仓库保留官方公开下载文件用于可复现研究，不对该数据重新授权。使用者应遵守官方数据说明、引用要求和适用的数据使用条件。

## 3. 冻结派生输入

| 文件 | 作用 | SHA-256 |
|---|---|---|
| `inherited/nhts2022_vehicle_days.csv` | 从 NHTS 公共使用文件整理的车辆日行程与停车窗口 | `7f33da4432999c437cb0bd1106a0e58ad2a1e91d8f27379b230040d5f822e293` |
| `inherited/formal_ev_populations_v1_2.csv` | 冻结的逐 EV 场景、能量状态、功率边界、相位和节点映射 | `283749ed9baf8460ba877b41d5d3266d8dc5405a824ba1110de00c4236e1d92d` |
| `inherited/formal_ev_population_summary_v1_2.csv` | 冻结 EV 群体摘要 | 见溯源清单 |
| `inherited/base_scenarios_v1_2.csv` | 基础场景与网络压力参数 | 见溯源清单 |
| `inherited/controlled_native_load_profile_v1_2.csv` | 受控 96 时段原生负荷曲线 | 见溯源清单 |
| `inherited/core_run_manifest_v1_2.csv` | 冻结核心运行清单 | 见溯源清单 |

这些文件是实验输入，不是未经处理的原始 NHTS 数据。`source_vehicle_id` 和 `source_houseid` 用于溯源和数据隔离审查，不应被解释为姓名、地址或现场用户身份。

## 4. 馈线输入

- `feeders/ieee13/`：IEEE13 三相馈线文件与节点坐标。
- `feeders/lv906_core/`：LV906 核心馈线、负荷、负荷曲线、监视器和变压器文件。

当前正式约束集合包括全时域节点电压、VUF、具有明确额定值的变压器和馈线容量。线路文件缺少完整、可追溯的热额定值，因此 `line_thermal_in_scope=false`；不能把这些数据描述为已经完成线路热安全验证。

## 5. 完整性与溯源

[`../config/required_inherited_assets_v2_0.csv`](../config/required_inherited_assets_v2_0.csv) 为27项冻结资产记录来源类型、归档位置、目标路径和预期 SHA-256。归档报告 [`../reports/provenance_gate_v2_0.json`](../reports/provenance_gate_v2_0.json) 记录：

- `required_assets = 27`
- `verified_assets = 27`
- `gate_status = PASS`

这是 V2.0 导入时的归档门记录。对当前 Git 工作树重新核对得到：

- 27 项目标路径全部存在；
- 其中 16 项与冻结 SHA-256 逐字节一致，包括官方 NHTS 压缩包和冻结派生数据；
- 其余 11 项全部是馈线文本文件：源归档使用 CRLF，Git 工作树统一为 LF；仅把换行恢复为 CRLF 后，11/11 的 SHA-256 均与清单一致；
- 因而没有发现数据内容漂移，但不能把归档的 27/27 直接表述为当前工作树未经规范化的 27/27 字节哈希通过。

该 PASS 只证明指定输入在相应导入阶段可追溯。它不证明潮流模型物理充分、数据划分独立、方法具有统计保证或论文论点成立。

## 6. 数据与统计边界

- NHTS 文件为公共使用调查数据，但仍应避免尝试重新识别家庭或个人。
- V2.2 与 V2.3A 的 `scenario_id` 不重叠；目前没有建立 household-disjoint 独立性，因此不能把场景隔离写成家庭层面的独立外部验证。
- V2.3A 在本次 PHiCTE 评估前已经打开，不是盲留出集。
- 30 min 和 60 min 的 V2.3A 结果在协议修订后仅作描述性敏感性分析。
- 原始数据同步、哈希通过和实验结果有效属于不同证据层，必须分别报告。
