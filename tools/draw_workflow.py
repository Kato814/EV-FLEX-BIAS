"""Draw the final five-stage schedule assessment workflow (Figure 1).

The final wording is 'Largest verified feasible alpha'; this schematic describes
proportional schedule scaling followed by unbalanced three-phase verification.
Geometry, typography, and English labels follow the final editable SVG.
Exports: 3.5 x 3.0 inch PDF/SVG and 600 dpi PNG; Times New Roman required.
"""
from pathlib import Path
import argparse
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
STEM = 'fig1_network_feasibility_workflow'
WIDTH, HEIGHT = 3.5, 3.0
BODY_SIZE, TITLE_SIZE, EQUATION_SIZE = 9.0, 9.5, 11.5

def draw(output):
    OUT = output
    font_manager.findfont('Times New Roman', fallback_to_default=False)
    plt.rcParams.update({
        "font.family": ["Times New Roman", "serif"],
        "font.serif": ["Times New Roman", "serif"],
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
    titles = ['Vehicle-feasible baseline', 'Balanced-model target schedule', 'Proportional schedule scaling', 'Unbalanced three-phase power flow', 'Verified schedule implementation']
    bodies = [['Availability, energy demand, charging limits'], ['Precomputed vehicle-level V1G schedule'], ['$u_{i,t}(\\alpha)=u^{0}_{i,t}+\\alpha(u^{B}_{i,t}-u^{0}_{i,t}),\\;0\\leq\\alpha\\leq1$'], ['Voltage, VUF, equipment loading'], ['Largest verified feasible $\\alpha$;', 'first limiting constraint']]

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
    plt.close(fig)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'generated' / 'figures')
    args = parser.parse_args()
    output = args.output.resolve()
    protected = (ROOT / 'paper' / 'figures').resolve()
    if output == protected or protected in output.parents:
        parser.error('Use a generated output directory; paper/figures contains the final publication assets.')
    draw(output)
    print(f'Figure 1: {output}')

if __name__ == '__main__':
    main()
