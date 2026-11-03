# Paper 9499：终稿与研究资料封存

封存日期：**2026-11-03（Asia/Shanghai）**  
固定标签：**paper9499-archive-2026-11-03**  
论文：*Feasibility Assessment of Balanced-Model Electric Vehicle Charging-Flexibility Schedules in Unbalanced Three-Phase Distribution Networks*

## 先从这里找

| 需要的内容 | 文件 / 目录 | 版本与用途 |
|---|---|---|
| 英文终稿 PDF | [打开 PDF](output/camera_ready_v1_22/paper9499_camera_ready_v1_22.pdf) | v1.22，5 页 Letter，正式英文交付版本 |
| 英文 LaTeX 压缩包 | [下载源码包](output/camera_ready_v1_22/paper9499_v1_22_LaTeX.zip) | 含图件、参考文献、绘图数据 |
| 在线查看 / 修改 LaTeX | [展开的源码](output/camera_ready_v1_22/source_package/) | 主文件 manuscript_v1_22.tex |
| 中文阅读稿 | [Word](output/chinese_v1_21/paper9499_v1_21_中文阅读稿.docx) · [PDF](output/chinese_v1_21/paper9499_v1_21_中文阅读稿.pdf) | 对应英文 v1.21，8 页，用于阅读核对 |
| A0 海报 | [PDF](output/pdf/paper9499_A0_poster_v5.pdf) · [LaTeX](output/poster_latex_v5/) | 最新本地海报 v5，1 页 |
| 补充实验 | [脚本、原始结果 ZIP 和汇总](experiments/reviewer_alpha_v3/) | v3，46 案例，23,046 个 α 网格点 |
| 修改前稿件 | [v1.18 源码及 PDF](history/accepted_v1_18/) | 历史基线，不作当前终稿 |
| 原可编辑海报 | [v1 PPTX](history/poster_v1/paper9499_A0_poster_v1.pptx) | 历史版，不对应 v5 排版 |
| 官方 LaTeX 模板 | [保留的模板 ZIP](templates/conference-latex-template.zip) | 本地留存原件 |
| 文件来源 / 校验 | [MANIFEST.json](MANIFEST.json) · [SHA256SUMS.txt](SHA256SUMS.txt) | 原路径、归档路径、大小及 SHA-256 |

## 版本关系

- 科学主线为仓库 `manuscript_freeze_20260813/` 的 V2.5B validated INC/V1G；原代码基点为 `3475301f2282b3fff6515fc77c0eb306063967c1`。
- 英文 v1.22 在已核对图表的 v1.21 上删除仓库网址说明及脚注，调整末页参考文献分栏；其余内容保持不变。
- 中文阅读稿保留 v1.21 状态，因此仍可能出现英文 v1.22 已删去的仓库说明；中文稿不是独立更新的英文终稿。
- 海报 v5 为当前本地最高版本；海报 v1 PPTX 仅保留编辑历史。
- 46 个案例中 32 个目标调度需降额；IEEE13 / LV906 平均核验系数为 0.834 / 0.540。补充实验核验 501 点 × 46 案例，网格内未观察到不可行后恢复可行。

## 取回和使用

1. 推荐通过 [GitHub Release](https://github.com/Kato814/EV-FLEX-BIAS/releases/tag/paper9499-archive-2026-11-03) 下载完整封存 ZIP；也可在仓库切换到同名标签。
2. 在本目录运行 `python verify_archive.py`，检查所有归档文件的 SHA-256、ZIP 完整性及展开源码与源码包的一致性。
3. 编译英文稿：解压英文 LaTeX ZIP，以 `manuscript_v1_22.tex` 为主文件，在完整 TeX 环境使用 pdfLaTeX，或上传 Overleaf。构建输出写入另外的工作目录，以保留封存原件。
4. 海报构建脚本及全部图件在 `output/poster_latex_v5/`；依赖见其 README，构建同样使用封存的副本。
5. 补充实验原始 ZIP 包含逐案例 CSV/JSON 和整网格记录。若只重新汇总，应先解压到新的工作目录，再运行 `analyze_reviewer_alpha_v3.py --repo <仓库路径> --output <解压结果目录>`；本次封存未重新运行潮流实验。

## 留存记录

英文终稿文件在本机被改名为 `paper9499终稿.pdf` 和 `paper9499.zip`；本档恢复带 v1.22 的明确版本名，字节与 2026-10-15 校验记录一致。具体映射见 MANIFEST.json。

英文原有 QA 报告记录 5 页 Letter、5 图、3 表、5 个公式、14 条参考文献、全部字体嵌入及源码包独立编译通过。本次封存增加文件完整性校验，不改变论文与数据。`records/archive_validation.json` 记录本次核验结果。

部分历史 QA / 中文生成脚本引用本机 Office、渲染工具及已移走的 v1.19/v1.21 目录；这些脚本保留作来源记录，跨机器重建需配置对应依赖。英文完整 LaTeX 包、中文可编辑 Word、海报 LaTeX 均独立留存。

本档记录已生成的交付物；会议上传、注册、版权与出版状态以相应系统凭证为准。录用信仅保留仓库已有的摘要与哈希，不新增上传原信。未收录软件运行时、缓存、重复预览及海报 v2–v4；本地原件不变。
