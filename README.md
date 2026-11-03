# EV-FLEX-BIAS

IEEE PES ISGT Asia 2026，Paper 9499：**Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks**。

本仓库实现平衡模型 EV 充电调度在不平衡三相配电网中的可行性评估与按比例降额，提供最终 46 个案例、可运行代码、实验结果，以及论文和海报的可编辑源文件。

[下载最终成果包](https://github.com/Kato814/EV-FLEX-BIAS/releases/tag/paper9499-final)

## 研究问题与实现方法

平衡网络模型给出的充电灵活性调度，落实到车辆所在的实际节点和相别后，可能造成电压越限、三相不平衡或设备过载。本研究回答：**给定一份平衡模型生成的车辆级调度，它能在真实三相馈线上实施到什么程度，首先受到哪一类网络约束限制？**

程序使用车辆可用时段、能量需求、充电功率限值、节点与相别分配，以及馈线模型和全天负荷作为输入，完成以下计算：

1. 构造满足车辆能量要求的均匀充电基线 `u0`，并用平衡规划模型生成目标调度 `uB`。
2. 保持原有车辆—时段调整方向，生成 `u(α) = u0 + α × (uB − u0)`；`α=0` 对应基线，`α=1` 对应完整目标调度。
3. 使用 OpenDSS 非线性三相潮流，检查全天 **96 个 15 分钟时段**的电压、VUF、变压器负载和馈线首端负载。网络可行的基线是评估前提。
4. 在 **0–1、步长 0.002** 的网格上核验全部 501 个系数，得到最大已核验可行系数，以及相邻不可行点对应的限制约束。代码同时保留论文的粗扫描与局部细化搜索。

输出是给定调度的可实施比例、可实施灵活性功率、限制约束和计算耗时。例如，若计划增量为 100 kW、核验系数为 0.6，则沿原调度方向可实施的增量为 60 kW。这里的缩放作用于相对基线的调度调整量。

## 文件入口

| 内容 | 路径 |
|---|---|
| 英文终稿 | [paper/final.pdf](paper/final.pdf) |
| 论文 LaTeX | [paper/manuscript.tex](paper/manuscript.tex)，同目录含参考文献、IEEE 类文件和图件 |
| 中文阅读稿 | [Word](paper/chinese/reading.docx) · [PDF](paper/chinese/reading.pdf) |
| A0 海报 | [PDF](poster/final.pdf) · [LaTeX](poster/poster.tex) |
| 最终实验结果 | [results/](results/)；概览见 [summary.json](results/summary.json) |
| 计算代码 | [src/evflex/](src/evflex/) |
| 46 个案例输入 | [data/](data/) 与 [config/](config/) |
| 运行、汇总和绘图 | [tools/](tools/) |

## 主要结果

在 IEEE13 的 22 个案例与 LV906 的 24 个案例中，32 个目标调度需降额。两馈线的平均核验缩放因子分别为 **0.834** 和 **0.540**；32 个受限案例中，27 个首先受到电压幅值或电压不平衡度约束。

`results/cases.csv` 保存最终案例指标：`scenario_id` 是案例标识，`f_bal_kw` 是计划充电增量，`alpha_transfer` 是最大已核验可行系数，二者乘积为可实施增量。`evaluations.json` 保存车辆约束、网络检查与调度哈希。`alpha_grid.zip` 包含每例 501 个 α 点的 CSV 及对应元数据，每点覆盖全部 96 个时段。逐例、边界和耗时汇总分别位于 `case_table.csv`、`boundary_comparison.csv`、`feeder_runtime_summary.csv`；绘图数据位于 `results/figures/`，图 3、4 可通过 `scenario_id` 与案例表对应。

## 使用

使用 **Python 3.12**，在仓库根目录安装依赖：

```shell
python -m pip install -r requirements.txt
```

核对已保存结果与文件完整性，不运行潮流：

```shell
python tools/verify.py
python tools/summarize.py
```

查看案例或重新计算：

```shell
python tools/evaluate.py --mode list
python tools/evaluate.py --mode single --case ieee13_1900_28
python tools/evaluate.py --mode full
```

快速检查求解环境可运行 `python tools/smoke.py`，或 `python tools/smoke.py --case lv906_1900_28`，重建调度并检查基线、可行边界、相邻不可行点和目标调度。

单案例和完整运行均逐点核验 501 个 α 值；完整运行依次计算全部 46 个案例。新计算及汇总默认写入 `generated/`，保留 `results/` 中的最终实验数据。

完成全部 46 个案例的重新计算后，用以下命令汇总**新运行结果**：

```shell
python tools/summarize.py --input generated/evaluation --output generated/rerun_summary
```

不带 `--input` 的汇总命令读取 `results/alpha_grid.zip` 中的已保存结果。完整重算耗时较长；核对交付物用 `verify.py`，检查求解环境用 `smoke.py` 即可。

## 图件与排版

安装绘图依赖后，可重新生成结果图、流程图和 LV906 拓扑：

```shell
python -m pip install -r requirements-figures.txt
python tools/plot_results.py
python tools/draw_workflow.py
python tools/draw_topology.py
```

图件输出到 `generated/figures/`；定稿使用的图件位于 `paper/figures/`，其中 SVG 可直接编辑。图 1 和图 2(b) 需要系统安装 **Times New Roman**；图 3–5 优先使用 **Tinos**，可用 `--font` 指定其他已安装字体。Python 依赖安装不会安装这些字体。拓扑图和潮流计算共用 `LoadsStaticAudit.txt` 中的负荷节点与相别。

安装 pdfLaTeX（MiKTeX 或 TeX Live）后运行：

```shell
python tools/build_pdfs.py
```

新 PDF 输出到 `generated/pdfs/`。论文为 5 页 Letter 双栏，海报为单页 A0；海报复用 `paper/figures/`。中文阅读稿用于核对正文，与最终英文稿的科学内容一致，保留了阅读版的仓库脚注。

原始输入来自论文所述 NHTS 车辆日记录和 IEEE 配电网模型；`data/` 已固定最终案例的车辆参数、相别分配与负荷曲线。`SHA256SUMS.txt` 用于确认这一组最终文件的完整性。

## English overview

This repository assesses how much of a balanced-model EV charging schedule can be implemented in an unbalanced three-phase feeder. It scales the vehicle-level adjustment from a feasible baseline, checks all 96 time slots with nonlinear OpenDSS power flow, and reports the largest verified feasible factor and the limiting network constraint. The final experiment contains 46 cases on IEEE13 and LV906, together with the inputs, computation and plotting tools, final results, manuscript and poster sources.
