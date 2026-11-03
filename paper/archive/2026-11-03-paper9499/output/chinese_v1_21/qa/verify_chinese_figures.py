"""Read-only checks of scientific inputs plus a matplotlib QA contact sheet."""
from pathlib import Path
import hashlib
import json
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
ENGLISH = ROOT.parent / "camera_ready_v1_21"
QA = ROOT / "qa"
FIGURES = ROOT / "figures"
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
data_checks = {}
for name in ("fig3_scheduled_offer_data.csv", "fig4_feasible_scaling_data.csv", "fig5_boundary_data.csv"):
    data_checks[name] = sha(QA / "figure_data" / name) == sha(ENGLISH / "manuscript" / "figures" / name)
for name in ("Buscoords.txt", "Lines.txt", "Loads.txt", "Transformers.txt", "load_phase_map.csv"):
    data_checks[name] = sha(QA / "fig2b_source_data" / name) == sha(ENGLISH / "qa" / "fig2b_source_data" / name)
assert all(data_checks.values())
assert sha(FIGURES / "fig2a_ieee13_topology.png") == sha(ENGLISH / "manuscript/figures/fig2a_ieee13_topology.png")
old_labels = json.loads((ENGLISH / "qa/fig2b_validation.json").read_text())["labels"]
new_labels = json.loads((QA / "fig2b_validation.json").read_text())["labels"]
fig1_checks = json.loads((QA / "fig1_qa.json").read_text())["checks"]
assert all(x["text_within_box"] and x["no_line_overlap"] for x in fig1_checks)
keys = ("label", "load_ids", "bus_ids", "phase", "offset_points")
assert [{k: x[k] for k in keys} for x in old_labels] == [{k: x[k] for k in keys} for x in new_labels]
pdfs = sorted(FIGURES.glob("*.pdf"))
fonts = {}
for pdf in pdfs:
    result = subprocess.run(["pdffonts", str(pdf)], capture_output=True, check=True)
    text = result.stdout.decode("utf-8", errors="replace")
    assert "Type 3" not in text
    assert "SimSun" in text and "TimesNewRoman" in text, (pdf.name, text)
    fonts[pdf.name] = text
stems = ["fig1_network_feasibility_workflow", "fig2b_lv906_topology",
         "fig3_ieee13_scheduled_vs_feasible_offer", "fig3_lv906_scheduled_vs_feasible_offer",
         "fig4_feasible_scaling_distribution", "fig5_limiting_network_constraints"]
fig, axes = plt.subplots(3, 2, figsize=(12, 12), dpi=150, facecolor="white")
for ax, stem in zip(axes.ravel(), stems):
    ax.imshow(plt.imread(FIGURES / (stem + ".png")))
    ax.axis("off")
fig.tight_layout(pad=0.4)
fig.savefig(QA / "chinese_figures_contact_sheet.png", dpi=150, facecolor="white")
plt.close(fig)
report = {"input_hashes_match_english_v1_21": data_checks,
          "ieee13_png_unchanged": True, "lv906_all_label_positions_and_mappings_unchanged": True,
          "figure1_text_fits": all(x["text_within_box"] and x["no_line_overlap"] for x in fig1_checks),
          "pdf_count": len(pdfs), "embedded_font_lists": fonts,
          "outputs": {path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
                      for path in sorted(FIGURES.iterdir()) if path.is_file()}}
(QA / "chinese_figures_verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({k: report[k] for k in ("input_hashes_match_english_v1_21", "ieee13_png_unchanged", "lv906_all_label_positions_and_mappings_unchanged", "pdf_count")}, indent=2))
