IEEE PES ISGT Asia 2026 — Paper 9499 — v1.22

文件
paper9499_camera_ready_v1_22.pdf：最终格式检查后的论文 PDF。
paper9499_v1_22_LaTeX.zip：LaTeX 源码、图件、参考文献和配套数据。

本次修改
删除正文中的仓库网址脚注及对应的仓库说明句。
调整末页参考文献的分栏位置，使两栏高度接近一致。
其余正文、公式、图表、数据与参考文献均与 v1.21 一致。保留原版本供对照。

编译
上传完整源码目录到 Overleaf，主文件选择 manuscript_v1_22.tex，编译器使用 pdfLaTeX。
本次本地实际编译使用 Tectonic 0.17.0：tectonic manuscript_v1_22.tex
采用 IEEEtran conference,letterpaper，10 pt、双栏及类文件默认版式。

源码结构
manuscript_v1_22.tex：论文主文件
references.tex：参考文献
IEEEtran.cls：会议模板类文件
figures/：正文图件
data/：绘图数据和逐例汇总结果
qa/rebuild_lv906_topology.py：图 2(b) 的 Python 绘图源
qa/fig2b_source_data/：图 2(b) 使用的原模型坐标、线路、负荷及变压器文件

来源
基于 v1.21，使用现有冻结案例及补充结果。
仓库：https://github.com/Kato814/EV-FLEX-BIAS
commit：3475301f2282b3fff6515fc77c0eb306063967c1
IEEEtran.cls 与项目中的 conference-latex-template.zip 类文件一致。
IEEEtran.cls SHA-256：c972aca108fda004c3514d63658e02816da2e54d9a1451e870b9bd970e003f55

源码包不含审稿回复。未代为提交会议系统。
