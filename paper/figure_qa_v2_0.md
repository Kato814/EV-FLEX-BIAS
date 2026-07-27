# V2.0 figure quality-assurance record

- Backend: Python/Matplotlib only.
- Source policy: every quantitative figure is generated from frozen V2.0 CSV/JSON evidence; each figure metadata file records the source artifact path and SHA-256 digest.
- Export contract: editable SVG and PDF plus 600 dpi PNG and TIFF at 180 mm publication width.
- Typography and axes: black Times New Roman text, no grid, four-sided frames, and inward ticks.
- Panel policy: no automatically inserted `(a)`/`(b)` labels.
- Structural QA: all six export bundles exist, exceed the minimum file-size check, and all raster exports report at least 590 dpi.
- Visual QA: all six PNG previews were inspected at high detail. Text, legends, axes, and annotations are legible; no material clipping or overlap remains.
- Revision note: Figures 5 and 6 were regenerated after separating their titles and legends from the plotting regions; both revised previews passed visual inspection.
- Status: PASS.
