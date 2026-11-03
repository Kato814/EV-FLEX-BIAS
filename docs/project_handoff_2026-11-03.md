# Paper 9499：封存交接（2026-11-03）

当前入口：[封存索引](../paper/archive/2026-11-03-paper9499/README.md)。固定 Git 标签：`paper9499-archive-2026-11-03`。

## 当前版本

- 英文终稿：v1.22，5 页 IEEE Letter；PDF 与完整 LaTeX 源码已封存。
- 中文阅读稿：v1.21，Word 与 PDF，用于阅读核对。
- 最新本地海报：v5，一页 A0 PDF 与 LaTeX；v1 PPTX 只作编辑历史。
- 补充实验：reviewer-alpha-grid-v3，46 案例 × 501 点，原始 ZIP、2 个脚本和 6 个小型汇总文件已封存。
- 历史基线：v1.18 源码 ZIP 与相同 PDF，以及 IEEE LaTeX 模板原件。

## 接续工作

后续论文修改从 v1.22 源码包另建版本，保留本次标签与归档目录。中文稿尚未同步英文 v1.22 的网址脚注删除。不要用 V2.0/V2G/PHiCTE 的旧生成脚本覆盖当前论文。

研究代码基点为 `3475301f2282b3fff6515fc77c0eb306063967c1`；本次仅新增交付物与导航，模型代码、冻结科学结果不变。原实验依据仍在 `manuscript_freeze_20260813/`。本档没有确认会议系统内的上传、注册、版权或发表状态。

## 完整性与恢复

完整封存 ZIP 位于 [Release](https://github.com/Kato814/EV-FLEX-BIAS/releases/tag/paper9499-archive-2026-11-03)。归档内 `MANIFEST.json` 记录本地相对来源、用途、大小和 SHA-256；`SHA256SUMS.txt` 覆盖除自身外的归档文件，运行 `python verify_archive.py` 即可校验。

本地英文 PDF / ZIP 曾改名为 `paper9499终稿.pdf` / `paper9499.zip`，归档恢复带版本号的文件名，哈希与 2026-10-15 交付记录一致。录用通知原信、软件缓存、重复渲染和旧海报 v2–v4 未新增上传。历史生成脚本依赖的本机目录与 Office 工具已在封存 README 说明。
