"""Reproduce the revised five-stage schedule-assessment schematic.

Contract: a precomputed vehicle-feasible schedule is proportionally derated
and checked with unbalanced power flow. The reported alpha is the largest
verified feasible sampled value, not a continuous or global optimum.
Archetype: single schematic. Backend: Python/matplotlib only.
Exports: one-column 3.5 in PDF/SVG and 600 dpi PNG, black Times New Roman text.
"""
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
STEM = "fig1_network_feasibility_workflow"
WIDTH, HEIGHT = 3.5, 3.0
BODY_SIZE, TITLE_SIZE, EQUATION_SIZE = 9.0, 9.5, 11.5

plt.rcParams.update({
    "font.family": ["Times New Roman", "SimSun"],
    "font.serif": ["Times New Roman", "SimSun"],
    "font.size": BODY_SIZE,
    "text.color": "black",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "mathtext.fontset": "custom",
    "mathtext.rm": "Times New Roman",
    "mathtext.it": "Times New Roman:italic",
    "mathtext.bf": "Times New Roman:bold",
})

fig = plt.figure(figsize=(WIDTH, HEIGHT), facecolor="white")
ax = fig.add_axes([0, 0, 1, 1])
ax.set(xlim=(0, WIDTH), ylim=(0, HEIGHT))
ax.set_axis_off()

# Coordinates are in inches, so the lettering retains its stated point size.
left, right, text_x = 0.045, 3.455, 0.40
box_heights = [0.46, 0.46, 0.54, 0.46, 0.59]
gap, top = 0.085, 2.93
titles = [
    "满足车辆约束的基线调度",
    "平衡模型目标调度",
    "调度按比例缩放",
    "不平衡三相潮流校验",
    "经验证的调度实施水平",
]
bodies = [
    ["可用时窗、能量需求、充电功率限制"],
    ["预先生成的车辆级 V1G 调度"],
    [r"$u_{i,t}(\alpha)=u^{0}_{i,t}+\alpha(u^{B}_{i,t}-u^{0}_{i,t}),\;0\leq\alpha\leq1$"],
    ["电压、VUF、设备负载率"],
    [r"经验证的最大可行缩放因子 α；", "首个限制性网络约束"],
]

text_checks = []
boxes = []
for number, (title, body, box_h) in enumerate(zip(titles, bodies, box_heights), 1):
    bottom = top - box_h
    patch = FancyBboxPatch(
        (left, bottom), right-left, box_h,
        boxstyle="round,pad=0.004,rounding_size=0.037",
        linewidth=0.85, edgecolor="black", facecolor="white",
    )
    ax.add_patch(patch)
    boxes.append((left, bottom, right, top))
    number_text = ax.text(0.215, (top+bottom)/2, str(number),
                         fontsize=TITLE_SIZE, fontweight="bold",
                         ha="center", va="center")
    title_text = ax.text(text_x, top-0.105, title,
                        fontsize=TITLE_SIZE, fontweight="bold", va="center")
    items = [number_text, title_text]
    for line_index, line in enumerate(body):
        equation = number == 3
        items.append(ax.text(
            text_x, top-(0.345 if equation else 0.300)-line_index*0.155, line,
            fontsize=EQUATION_SIZE if equation else BODY_SIZE,
            va="center", ha="left",
        ))
    text_checks.append((number, items))
    if number < 5:
        ax.add_patch(FancyArrowPatch(
            ((left+right)/2, bottom-0.005),
            ((left+right)/2, bottom-gap+0.005),
            arrowstyle="-|>", mutation_scale=9.0, linewidth=0.8,
            facecolor="black", edgecolor="black", shrinkA=0, shrinkB=0,
        ))
    top = bottom-gap

# Validate every label against its enclosing box before export.
fig.canvas.draw()
renderer = fig.canvas.get_renderer()
qa = []
for number, texts in text_checks:
    x0, y0, x1, y1 = boxes[number-1]
    extents = []
    for text in texts:
        extent = text.get_window_extent(renderer).transformed(ax.transData.inverted())
        assert extent.x0 >= x0 and extent.x1 <= x1, (number, text.get_text(), extent)
        assert extent.y0 >= y0 and extent.y1 <= y1, (number, text.get_text(), extent)
        extents.append(extent)
    for before, after in zip(extents[1:], extents[2:]):
        assert before.y0 > after.y1, (number, "overlapping lines")
    qa.append({"step": number, "text_within_box": True, "no_line_overlap": True})

OUT.mkdir(parents=True, exist_ok=True)
for extension in ("pdf", "svg", "png"):
    fig.savefig(OUT / f"{STEM}.{extension}", dpi=600, facecolor="white")
report = {
    "figure": STEM,
    "size_inches": [WIDTH, HEIGHT],
    "pdf_size_points": [WIDTH*72, HEIGHT*72],
    "png_dpi": 600,
    "font": "SimSun (Chinese), Times New Roman (Latin and math)",
    "font_path": font_manager.findfont("Times New Roman"),
    "body_font_points": BODY_SIZE,
    "title_font_points": TITLE_SIZE,
    "equation_font_points": EQUATION_SIZE,
    "scientific_change": "Largest feasible alpha -> Largest verified feasible alpha",
    "last_step_title": titles[-1],
    "continuous_or_global_optimum_claimed": False,
    "checks": qa,
}
(ROOT / "qa" / "fig1_qa.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
plt.close(fig)
