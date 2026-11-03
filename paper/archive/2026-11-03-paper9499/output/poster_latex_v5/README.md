# Paper 9499 A0 Poster v5

This revision keeps the supplied IEEE template as a visual reference but restructures the page into four readable narrative blocks: Why balanced offers can fail; From a planned schedule to a safe dispatch; Study design; and What changes at dispatch?

The design increases body-text size and explanatory prose, removes the two tiny scheduled-versus-verified inset plots, and gives the verified-scaling and limiting-constraint figures comparable visual weight. The result block also includes a feeder-comparison table and an explicit explanation of how to read alpha-star.

## Build

From the project root run:

```powershell
& .\output\poster_latex_v5\build_poster.ps1
```

The final PDF is written to `output\pdf\paper9499_A0_poster_v5.pdf`. The build record is written to `output\poster_latex_v5\qa\build_info.txt`.

## Scientific scope

The poster reports evidence from 46 evaluated cases (22 IEEE13 and 24 LV906). Thirty-two target schedules require derating; mean verified scaling factors are 0.834 for IEEE13 and 0.540 for LV906. Voltage magnitude or VUF is the first limiting constraint in 27 of the 32 limited cases. The reported alpha-star is the largest verified value on a 0.002 grid over all 96 slots; these are case-study results, not a universal guarantee. Continuous V1G interpolation preserves the vehicle constraints stated in the paper; discrete charging allocations still require implementability checks.

## Figure provenance

The seven files under `figures\` are copied without modification from the camera-ready source package. Their SHA-256 values are recorded in `SHA256SUMS.txt`. The explanatory pipeline and alpha-star callout are drawn directly in the LaTeX source.

## QA

The final build is a one-page A0 PDF. The rendered preview was inspected for clipping, overflow, and internal blank regions. The original v1 PPTX and camera-ready PDF remain unchanged.

Latest verified build: MiKTeX-pdfTeX 4.23 (MiKTeX 25.12), one-page A0 PDF, SHA-256 `B2F8A26736EFDE64FE93963CE0ED7452D297285982F44C9405603E8E7B17B556`.
