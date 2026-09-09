# EV-FLEX-BIAS

面向 IEEE PES ISGT Asia 2026 的电动汽车（EV）充电灵活性调度与三相不平衡配电网可行性研究代码仓库。

## 当前状态（2026-09-09）

论文已被 **2026 IEEE PES Innovative Smart Grid Technologies Asia (IEEE PES ISGT Asia 2026)** 正式录用：

- **Paper ID:** 9499
- **Title:** *Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks*
- **Authors:** Junxing Tan, Jun Wu, Shiting Cui, Chaofan Yang, Jiangcheng Wang
- **Conference:** Oct. 30-Nov. 1, 2026, Wuhan, China

当前仓库的论文科学证据以 `manuscript_freeze_20260813/` 中的 **V2.5B validated INC/V1G manuscript freeze** 为主。此前 V2.0-V2.4 的 V1G/V2G、PHiCTE 和筛查实验仍保留在仓库中，作为研究历史与复现实验资产，但**不再代表已录用论文的主线结论**。

> Camera-ready 尚未冻结。下一阶段先逐条处理审稿意见，再按录用通知要求切换到 **US Letter (21.59 cm × 27.94 cm)** 模板完成最终稿。

会议与 camera-ready 状态见 [`paper/conference/acceptance_status_9499.md`](paper/conference/acceptance_status_9499.md)。新对话/新工作窗口的项目交接见 [`docs/project_handoff_2026-09-09.md`](docs/project_handoff_2026-09-09.md)。

## 1. 已录用论文研究问题

实际运行中，EV 充电灵活性调度可能先由平衡或简化配电网模型生成，再下发到真实的三相不平衡网络。本文关注：

> **一个已经计算完成的车辆级 V1G 充电灵活性调度，在不重新分配车辆与充电时段的情况下，能够在详细三相不平衡网络中实施到什么程度？首先限制其继续实施的网络约束是什么？**

对车辆级基线调度 `u0` 与平衡模型目标调度 `uB` 之间的功率调整采用统一缩放因子 `alpha`：

```text
u(alpha) = u0 + alpha * (uB - u0),   0 <= alpha <= 1
```

每个候选 `alpha` 都在详细 OpenDSS 三相模型中执行非线性潮流，并检查：

- bus voltage;
- voltage-unbalance factor (VUF);
- transformer loading;
- feeder-head loading.

粗搜索步长为 0.02；首次出现网络约束违反后，将可行/不可行边界细化至相邻测试点间隔不大于 0.002。

## 2. 冻结主结果：validated INC/V1G

冻结证据位于：

[`manuscript_freeze_20260813/manuscript_freeze_20260813/`](manuscript_freeze_20260813/manuscript_freeze_20260813/)

### 调度可行性

| Scope | n | mean alpha | median alpha | alpha < 0.95 | alpha < 0.5 | alpha < 1 |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 46 | 0.681 | 0.719 | 30 (65.2%) | 16 | 32 |
| IEEE13 | 22 | 0.834 | 0.999 | 9 | 2 | 11 |
| LV906 | 24 | 0.540 | 0.446 | 21 | 14 | 21 |

IEEE13 减 LV906 的 mean-alpha difference 为 0.294，case-level bootstrap 95% interval 为 **[0.144, 0.436]**。

### 首个网络限制

32 个 `alpha < 1` 的 V1G 案例中：

- Low voltage: **20/32**
- High voltage: **2/32**
- VUF: **5/32**
- Transformer loading: **5/32**
- Voltage magnitude or VUF: **27/32 = 84.4%**

馈线分布：

- IEEE13: 11 limited cases = 5 transformer + 5 VUF + 1 low-voltage;
- LV906: 21 limited cases = 19 low-voltage + 2 high-voltage，**21/21 均首先受到电压约束**。

全部 32 个受限案例的首次网络约束违反都发生在对应的 15-min flexibility call slot。

## 3. 科学范围

已录用论文的主证据范围为 **V1G increasing-direction charging flexibility**。

以下内容仍保留在仓库中，但不作为当前论文主结论：

- 原 net-power interpolation 下的连续 DEC/V2G transferability；
- PHiCTE 的通用风险保证或全局优越性；
- 允许完整三相重新优化后的最大 EV flexibility；
- line ampacity / full line-thermal certificate；
- 超出 IEEE13 与 LV906 测试案例的普适因果结论。

原因与证据边界详见：

[`v2_5b_inc_only_manuscript_freeze.md`](manuscript_freeze_20260813/manuscript_freeze_20260813/v2_5b_inc_only_manuscript_freeze.md)

## 4. 历史研究轨迹

仓库保留 V2.0-V2.4 的完整研究历史，包括 V1G/V2G 审计、开发/留出流程、PHiCTE、诊断实验和相应结果。它们用于：

- 复现研究过程；
- 记录被淘汰或降级为 secondary/exploratory 的方法；
- 支撑方法学审计与后续扩展研究。

其中，V2.4 PHiCTE 是历史探索阶段，不应与当前已录用论文的 V1G 主结果混同。执行说明仍见 [`README_V2_5_EXECUTION.md`](README_V2_5_EXECUTION.md)。

## 5. 数据与复现

要求 Python 3.12。锁定依赖见 [`requirements.lock.txt`](requirements.lock.txt)。Windows PowerShell 示例：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install pytest==8.4.2
```

建议将数值运行限制为单线程：

```powershell
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
$env:VECLIB_MAXIMUM_THREADS='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:faulthandler
```

数据来源、冻结输入、哈希和边界说明见 [`data/README.md`](data/README.md)。

## 6. 目录导航

- `src/evflex/`：核心 EV 调度、三相网络评估、诊断与历史 PHiCTE 实现。
- `scripts/`：受控运行与汇总入口。
- `config/`, `manifests/`, `protocol/`：实验协议、场景、溯源和冻结资产。
- `data/`：调查数据、派生 EV 输入和馈线模型。
- `results/`, `reports/`：实验结果、验证报告和研究决策。
- `manuscript_freeze_20260813/`：**当前论文最重要的冻结科学证据**。
- `paper/`：论文历史资产与会议模板；当前导航见 [`paper/README.md`](paper/README.md)。
- `paper/conference/`：会议模板、模板合同、录用/camera-ready 状态。
- `tests/`：环境、数值流程和证据门测试。
- `docs/project_handoff_2026-09-09.md`：当前项目交接与下一阶段工作入口。

## 7. Camera-ready 下一步

根据录用通知：

1. 逐条处理审稿意见；
2. Camera-ready 按官方模板改为 **US Letter (21.59 cm × 27.94 cm)**；
3. 至少一位作者在 **2026-10-10（北京时间）前**完成注册和付款；
4. 最终稿在 **2026-10-20（北京时间）前**提交；
5. 最终稿提交后关注 IEEE eCopyright 邮件并完成出版协议；
6. 完成会议报告后，论文进入会议论文集流程，并提交 IEEE Xplore / Ei Compendex / Scopus。

详细信息见 [`paper/conference/acceptance_status_9499.md`](paper/conference/acceptance_status_9499.md)。

## English summary

EV-FLEX-BIAS studies the network feasibility of precomputed electric-vehicle charging-flexibility schedules in unbalanced three-phase distribution feeders. The manuscript evidence is frozen to 46 validated V1G increasing-direction cases on IEEE13 and LV906. Of these, 32 cannot implement the full balanced-model target schedule, and voltage magnitude or VUF is the first limiting constraint in 27 of the 32 limited cases. The paper *Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks* (Paper ID 9499) has been accepted by IEEE PES ISGT Asia 2026. Camera-ready revision is pending reviewer-comment processing and must use the conference's US Letter template.
