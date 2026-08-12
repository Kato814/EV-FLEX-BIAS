# EV-FLEX-BIAS

面向 IEEE PES ISGT Asia 2026 的 EV 聚合商 V1G/V2G 固定调度三相可转移性研究。当前版本为 **V2.4 PHiCTE 回顾性探索评估**；代码、数据、实验结果和论文材料均保存在本仓库中。

> 当前结论（2026-08-12）：PHiCTE 出现了有条件的探索性正信号，值得保留为后续确认实验的候选方法；现有证据不构成盲测验证、5% 风险保证、总体 kW 优势或论文录用结论。

## 1. 项目背景

平衡或相位无感知模型可以较低成本地生成 EV 聚合调度，但配电网实际具有三相不平衡、节点电压差异和设备容量约束。把平衡模型生成的逐车调度直接部署到三相馈线、且不重新优化时，原调度可能无法完整兑现。

本项目不研究“允许三相重新调度后的最大聚合能力”，而研究一个范围更窄、可验证的问题：

> 对给定 EV 状态、调用方向和持续时间，平衡近似生成的固定调度轨迹有多大比例能在不重新优化的情况下安全转移到三相不平衡网络；哪些调用前条件与转移失效有关；低成本筛查能否在控制经验失效风险的同时保留更多可用调度。

定义固定调度的三相可转移比例为：

$$
\alpha_{\mathrm{tr}}=\sup\left\{\alpha\in[0,1]:
u^0+\alpha\left(u^B-u^0\right)
\;\text{满足预声明的三相网络与车辆约束}\right\}.
$$

这里的 $u^0$ 是基线调度，$u^B$ 是平衡近似生成的固定调用调度。该定义只评价这条具体轨迹的可转移性，不代表三相重新优化后的真实最大能力。

更完整的选题审查见 [`reports/research_topic_viability_review_2026-07-28.md`](reports/research_topic_viability_review_2026-07-28.md)。

## 2. 研究思路

研究流程保持“调度固定、网络重放、证据分层”：

1. 在平衡近似下生成 V1G 增加充电、减少充电/V2G 调度。
2. 保持车辆状态和逐车轨迹不变，在 IEEE13 与 LV906 三相馈线中进行 96 时段审计。
3. 沿基线到调用调度的射线缩放，计算 $\alpha_{\mathrm{tr}}$。
4. 比较无折减、全局折减、feeder-only、direction-only、局部分组规则和 PHiCTE。
5. 分开报告机器门槛、物理证据和学术解释，不把 `PASS` 或 `VALID` 直接当作普适科学结论。

### PHiCTE

PHiCTE（Physics-guided Hierarchical Conformal Transferability Envelope，物理引导的分层保形可转移包络）预测 $\alpha_{\mathrm{tr}}$ 的保守下界，而不是平均值。当前实现包含：

- 调用前可获得的平衡报价强度、电压裕度、VUF 裕度、变压器裕度和馈线裕度；
- 具有物理方向约束的低分位数回归；
- 对馈线、方向和持续时间交互项施加强收缩；
- 按 `scenario_id` 隔离的四折交叉拟合；
- 单侧 conformal-style 有限样本校正和因子为零时的自动弃权；
- 与五种简单基线在相同风险定义下比较。

方法计划和冻结规则见 [`docs/superpowers/plans/2026-08-11-phicte-v2-4.md`](docs/superpowers/plans/2026-08-11-phicte-v2-4.md)，实现见 [`src/evflex/transferability_phicte_v2_4.py`](src/evflex/transferability_phicte_v2_4.py)。

## 3. 证据阶段与当前进度

| 阶段 | 状态 | 作用与边界 |
|---|---|---|
| V2.0 | 已归档 | 重建原始证据链、开发/留出流程和论文材料；旧宽口径结论不直接继承为当前主张。 |
| V2.1 pilot / D1 | 已完成有界审查 | 初始 D1 在目标审计前因实现合同不一致停止；该停止不属于物理机制证据。修复后的 D1-R Lite 仅支持范围收窄和案例内边界分析。 |
| V2.2 development | 已完成 | 16 个场景、96 个有效评估，用于 PHiCTE 训练、惩罚选择和行级探索校正。 |
| V2.3A external | 已完成回顾性评估 | 16 个新场景、96 个计划评估，其中 91 个有效、5 个 inactive；该队列此前已打开，不是盲留出集。 |
| V2.4 PHiCTE | 已完成 | 协议冻结、代码实现、结果生成和独立指标复算均已完成；机器状态为 `EXPLORATORY_POSITIVE_SIGNAL`。 |

当前代码冻结提交为 `285bb9f`，PHiCTE 结果提交为 `14dd034`。PHiCTE 结果归档前的全库回归验证为 **523 tests passed**。

## 4. 当前主要结果

V2.3A 的预声明主范围是 15 min，有效样本数为 31：

| 指标 | PHiCTE | feeder-only |
|---|---:|---:|
| 材料失效（`alpha_transfer < 0.95 × factor`） | 0/31 | 1/31 |
| 严格越过已验证边界 | 0/31 | 1/31 |
| 等权保留率 | 0.3323 | 0.3161 |
| 馈线宏平均 kW 保留率 | 0.3312 | 0.3063 |
| 池化 kW 保留率（敏感性） | 0.4623 | 0.5582 |

相对 feeder-only，PHiCTE 的等权保留率提高 1.62 个百分点，馈线宏平均提高 2.49 个百分点，但池化 kW 保留率下降 9.59 个百分点。它主要改善了 LV906 的可用性，同时在容量占主导的 IEEE13 上更保守，因此不能声称总体 kW 优势。

尽管主范围观察到 0/31 材料失效，其 95% Wilson 上界仍为 11.03%，不能据此证明真实风险不超过 5%。完整机器结果见 [`results/transferability_phicte_v2_4/summary.json`](results/transferability_phicte_v2_4/summary.json)，逐行因子见 [`results/transferability_phicte_v2_4/predictions.csv`](results/transferability_phicte_v2_4/predictions.csv)。

## 5. 数据

仓库已纳入当前研究使用的全部 23 个数据有效载荷文件（另含一份数据说明），包括：

- FHWA 2022 National Household Travel Survey 的官方 CSV V2.1 原始压缩包；
- 冻结的车辆日行程表、EV 群体、基础场景和原生负荷输入；
- IEEE13 与 LV906 三相馈线输入。

原始数据、派生数据、文件哈希、官方来源和数据边界见 [`data/README.md`](data/README.md)。数据完整性清单见 [`config/required_inherited_assets_v2_0.csv`](config/required_inherited_assets_v2_0.csv)。V2.0 导入时归档的 G0 溯源门记录为 27/27 文件通过；当前官方 NHTS 压缩包和冻结派生输入仍与清单逐字节一致。11 个馈线文本文件进入 Git 后由 CRLF 规范化为 LF，仅恢复源换行后 11/11 均与冻结哈希一致，因此没有发现内容漂移。该门只证明输入可追溯，不证明研究结论正确。

## 6. 复现

要求 Python 3.12。直接依赖版本见 [`requirements.lock.txt`](requirements.lock.txt)。Windows PowerShell 示例：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install pytest==8.4.2
```

测试和数值运行应限制为单线程：

```powershell
$env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:NUMEXPR_NUM_THREADS='1'; $env:VECLIB_MAXIMUM_THREADS='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:faulthandler
```

为避免覆盖已归档结果，复算 PHiCTE 时把输出写入临时目录：

```powershell
.\.venv\Scripts\python.exe -m evflex.transferability_phicte_v2_4 --repo-root . --output-directory "$env:TEMP\ev-flex-bias-phicte"
```

## 7. 目录结构

- `src/evflex/`：核心调度、三相审计、诊断和 PHiCTE 实现。
- `scripts/`：受控运行与结果汇总入口。
- `config/`、`manifests/`：冻结协议、场景和溯源清单。
- `data/`：原始调查数据、冻结派生输入和馈线模型。
- `results/`、`reports/`：机器结果、决策记录和学术审查。
- `paper/`：英文论文、中文版对照、PDF 和可编辑图件。
- `tests/`：环境、数值流程、证据门和 PHiCTE 回归测试。

## 8. 解释边界与下一步

当前证据明确不支持以下主张：

- PHiCTE 已获得盲测或确认性验证；
- 真实材料失效风险已被证明低于 5%；
- 两个馈线案例可以代表普适网络规律或馈线因果效应；
- 固定调度失效等同于允许三相重新优化后的聚合报价不可兑现；
- 已完成线路热安全审计；
- 论文已经达到会议录用要求。

下一科学阶段应预先冻结新的独立场景、数据隔离、评价权重和停止门，再进行确认性验证；在此之前，PHiCTE 只能作为有条件的探索性候选方法。

## English summary

EV-FLEX-BIAS studies how much of a fixed V1G/V2G schedule produced by a balanced or phase-agnostic model can be transferred to an unbalanced three-phase feeder without re-optimizing individual EV trajectories. V2.4 implements PHiCTE, a physics-sign-constrained, hierarchically shrunk low-quantile model with scenario-grouped cross-fitting and one-sided calibration. The opened V2.3A cohort provides a conditional exploratory signal, not blind or confirmatory evidence: PHiCTE had 0/31 material false-safe cases in the 15-minute primary scope and improved equal-case and feeder-macro retention versus feeder-only, while reducing pooled-kW retention. A new locked confirmation design is required before any deployable risk claim.
