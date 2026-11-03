# EV-FLEX-BIAS

IEEE PES ISGT Asia 2026，Paper 9499：**Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks**。

本仓库提供论文最终使用的 46 个案例、实验代码与结果，以及论文和海报的可编辑源文件。

[下载最终成果包](https://github.com/Kato814/EV-FLEX-BIAS/releases/tag/paper9499-final)

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

`results/cases.csv` 保存最终案例指标，`evaluations.json` 保存车辆约束、网络检查与调度哈希。`alpha_grid.zip` 包含每例 501 个 α 点的 CSV 及对应元数据，每点覆盖全部 96 个时段。逐例、边界和耗时汇总分别位于 `case_table.csv`、`boundary_comparison.csv`、`feeder_runtime_summary.csv`；绘图数据位于 `results/figures/`。

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

## 图件与排版

安装绘图依赖后，可重新生成结果图、流程图和 LV906 拓扑：

```shell
python -m pip install -r requirements-figures.txt
python tools/plot_results.py
python tools/draw_workflow.py
python tools/draw_topology.py
```

图件输出到 `generated/figures/`；定稿使用的图件位于 `paper/figures/`，其中 SVG 可直接编辑。绘图优先使用原图字体；具体可用字体选项见脚本 `--help`。

安装 pdfLaTeX（MiKTeX 或 TeX Live）后运行：

```shell
python tools/build_pdfs.py
```

新 PDF 输出到 `generated/pdfs/`。论文为 5 页 Letter 双栏，海报为单页 A0；海报复用 `paper/figures/`。中文阅读稿用于核对正文，与最终英文稿的科学内容一致，保留了阅读版的仓库脚注。

原始输入来自论文所述 NHTS 车辆日记录和 IEEE 配电网模型；`data/` 已固定最终案例的车辆参数、相别分配与负荷曲线。`SHA256SUMS.txt` 用于确认这一组最终文件的完整性。
