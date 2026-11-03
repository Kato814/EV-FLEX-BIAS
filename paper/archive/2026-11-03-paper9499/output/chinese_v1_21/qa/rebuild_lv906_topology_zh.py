"""Rebuild the LV906 topology directly from the supplied OpenDSS input files.

The figure locates the 55 native single-phase loads on the 906-bus feeder.
Python/matplotlib only; no power-flow simulation is run. Numbered markers are
native load IDs, not bus IDs. Geographically coincident loads retain their
coordinates and share a marker with a combined ID label.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.transforms import Bbox
import numpy as np


def parse_inputs(source: Path):
    coordinates = {}
    for line in (source / "Buscoords.txt").read_text().splitlines():
        row = line.replace(",", " ").split()
        if row:
            coordinates[row[0]] = tuple(map(float, row[1:3]))
    lines = []
    for row in (source / "Lines.txt").read_text().splitlines():
        match = re.search(r"New\s+Line\.(\S+)\s+Bus1=(\d+)\s+Bus2=(\d+)", row, re.I)
        if match:
            lines.append(match.groups())
    loads = []
    for row in (source / "Loads.txt").read_text().splitlines():
        match = re.search(r"New\s+Load\.LOAD(\d+)\s+Phases=1\s+Bus1=(\d+)\.(\d+)", row, re.I)
        if match:
            load_id, bus, phase = match.groups()
            loads.append({"load_id": int(load_id), "bus": bus, "phase": int(phase), "xy": coordinates[bus]})
    transformer_text = (source / "Transformers.txt").read_text()
    match = re.search(r"Buses=\[SourceBus\s+(\d+)\]", transformer_text, re.I)
    assert match, "Substation secondary bus not found."
    source_bus = match.group(1)
    graph = defaultdict(set)
    for _, a, b in lines:
        graph[a].add(b)
        graph[b].add(a)
    reached = set()
    pending = [source_bus]
    while pending:
        bus = pending.pop()
        if bus not in reached:
            reached.add(bus)
            pending.extend(graph[bus] - reached)
    assert len(coordinates) == 906 and len(lines) == 905
    assert set(graph) == set(coordinates) == reached
    assert sum(map(len, graph.values())) // 2 == len(coordinates) - 1
    assert sorted(x["load_id"] for x in loads) == list(range(1, 56))
    assert Counter(x["phase"] for x in loads) == {1: 21, 2: 19, 3: 15}
    return coordinates, lines, loads, source_bus


def segment_hits_box(segments: np.ndarray, box: Bbox) -> int:
    """Count line segments intersecting an axis-aligned label box."""
    lo = np.array([box.x0, box.y0]); hi = np.array([box.x1, box.y1])
    starts = segments[:, 0]; delta = segments[:, 1] - starts
    lower = np.zeros(len(segments)); upper = np.ones(len(segments))
    valid = np.ones(len(segments), dtype=bool)
    for dim in range(2):
        moving = np.abs(delta[:, dim]) > 1e-12
        valid &= moving | ((starts[:, dim] >= lo[dim]) & (starts[:, dim] <= hi[dim]))
        denom = np.where(moving, delta[:, dim], 1.0)
        t1 = (lo[dim] - starts[:, dim]) / denom
        t2 = (hi[dim] - starts[:, dim]) / denom
        lower = np.maximum(lower, np.where(moving, np.minimum(t1, t2), -np.inf))
        upper = np.minimum(upper, np.where(moving, np.maximum(t1, t2), np.inf))
    return int(np.count_nonzero(valid & (lower <= upper)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    qa = Path(__file__).resolve().parent
    root = qa.parent
    source = args.source_dir or qa / "fig2b_source_data"
    default_output = root / "manuscript" / "figures" if (root / "manuscript").exists() else root / "figures"
    output = args.output_dir or default_output
    output.mkdir(parents=True, exist_ok=True)
    coordinates, lines, loads, source_bus = parse_inputs(source)
    font_path = font_manager.findfont("Times New Roman", fallback_to_default=False)
    plt.rcParams.update({"font.family": ["Times New Roman", "SimSun"], "font.size": 5.6,
                         "text.color": "black", "pdf.fonttype": 42,
                         "svg.fonttype": "none", "axes.unicode_minus": False})
    colors = {1: "#d73027", 2: "#29913a", 3: "#2364c4"}
    markers = {1: "o", 2: "s", 3: "^"}
    phase_names = {1: "A", 2: "B", 3: "C"}
    origin = np.min(np.array(list(coordinates.values())), axis=0)
    xy = {k: np.array(v) - origin for k, v in coordinates.items()}
    edge_points = np.array([[xy[a], xy[b]] for _, a, b in lines])
    groups = defaultdict(list)
    for load in loads:
        groups[(load["xy"], load["phase"])].append(load)
    grouped = sorted(groups.values(), key=lambda group: min(x["load_id"] for x in group))

    fig = plt.figure(figsize=(2.87, 2.99), dpi=200)
    ax = fig.add_axes([0.035, 0.025, 0.94, 0.955])
    ax.set_aspect("equal")
    ax.add_collection(LineCollection(edge_points, colors="0.23", linewidths=0.38, zorder=1))
    extent = np.max(np.array(list(xy.values())), axis=0)
    ax.set_xlim(-5.0, extent[0] + 5.0)
    ax.set_ylim(-5.0, extent[1] + 5.0)
    ax.axis("off")
    for group in grouped:
        node = group[0]
        ax.scatter(*xy[node["bus"]], marker=markers[node["phase"]], s=8.8,
                   facecolor=colors[node["phase"]], edgecolor="black", linewidth=0.35, zorder=3)
    ax.scatter(*xy[source_bus], s=19.5, marker="s", color="black", zorder=4)
    handles = [Line2D([], [], color="none", marker=markers[p], markersize=3.2,
                      markerfacecolor=colors[p], markeredgecolor="black", markeredgewidth=0.35,
                      label=f"{phase_names[p]}相负荷") for p in (1, 2, 3)]
    handles.append(Line2D([], [], color="none", marker="s", markersize=3.6,
                          markerfacecolor="black", markeredgecolor="black", label="变电站"))
    legend = ax.legend(handles=handles, loc="lower right", bbox_to_anchor=(1.01, 0.005),
                       frameon=False, fontsize=5.6, handletextpad=0.4, labelspacing=0.4,
                       borderaxespad=0.0, borderpad=0.1)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    pt = fig.dpi / 72.0
    plot_box = ax.get_window_extent(renderer)
    legend_box = legend.get_window_extent(renderer).expanded(1.03, 1.04)
    screen_segments = ax.transData.transform(edge_points.reshape(-1, 2)).reshape(-1, 2, 2)
    marker_centers = np.array([ax.transData.transform(xy[g[0]["bus"]]) for g in grouped] + [ax.transData.transform(xy[source_bus])])
    marker_boxes = [Bbox.from_extents(x-2.2*pt, y-2.2*pt, x+2.2*pt, y+2.2*pt) for x, y in marker_centers]
    placed = []
    labels = []
    offsets = [(0, 5), (5, 0), (-5, 0), (0, -5), (5, 5), (-5, 5), (5, -5), (-5, -5)]
    offsets += [(r*np.cos(a), r*np.sin(a)) for r in (7, 9, 11, 14, 18) for a in np.linspace(0, 2*np.pi, 16, endpoint=False)]
    # Place groups with the fewest unobstructed near-node options first.
    candidates_by_id = {}
    for group in grouped:
        label = ",".join(str(x["load_id"]) for x in group)
        pos = xy[group[0]["bus"]]
        center = ax.transData.transform(pos)
        probe = ax.text(*pos, label, ha="center", va="center", fontsize=5.6)
        bbox = probe.get_window_extent(renderer)
        probe.remove()
        width, height = bbox.width + 0.6*pt, bbox.height + 0.3*pt
        candidates = []
        for dx, dy in offsets:
            x, y = center + pt * np.array([dx, dy])
            box = Bbox.from_bounds(x-width/2, y-height/2, width, height)
            outside = not (plot_box.x0 <= box.x0 and box.x1 <= plot_box.x1 and plot_box.y0 <= box.y0 and box.y1 <= plot_box.y1)
            marker_hits = int(sum(box.overlaps(b) for b in marker_boxes))
            line_hits = segment_hits_box(screen_segments, box)
            base = 100000*outside + 100000*box.overlaps(legend_box) + 3000*marker_hits + 25*line_hits + np.hypot(dx, dy)
            candidates.append((base, dx, dy, box, line_hits, marker_hits))
        candidates_by_id[label] = (group, candidates)
    ordering = sorted(candidates_by_id, key=lambda key: sum(c[0] < 25 for c in candidates_by_id[key][1]))
    for label in ordering:
        group, candidates = candidates_by_id[label]
        chosen = min(candidates, key=lambda c: c[0] + 10000*sum(c[3].overlaps(b) for b in placed))
        _, dx, dy, box, line_hits, marker_hits = chosen
        placed.append(box)
        annotation = ax.annotate(label, xy=xy[group[0]["bus"]], xytext=(dx, dy),
                                 textcoords="offset points", ha="center", va="center", fontsize=5.6,
                                 color="black", zorder=5,
                                 arrowprops=dict(arrowstyle="-", color="0.45", linewidth=0.32,
                                                 shrinkA=1.0, shrinkB=3.0) if np.hypot(dx, dy) > 9 else None)
        labels.append({"label": label, "load_ids": [x["load_id"] for x in group],
                       "bus_ids": [x["bus"] for x in group], "phase": group[0]["phase"],
                       "offset_points": [float(dx), float(dy)],
                       "line_intersections": line_hits, "marker_intersections": marker_hits,
                       "bbox_px": list(map(float, box.extents))})
    overlap_pairs = [(labels[i]["label"], labels[j]["label"]) for i in range(len(placed)) for j in range(i) if placed[i].overlaps(placed[j])]
    assert not overlap_pairs, f"Label overlaps: {overlap_pairs}"
    assert all(row["marker_intersections"] == 0 for row in labels)
    assert sorted(i for row in labels for i in row["load_ids"]) == list(range(1, 56))
    fig.canvas.draw()
    tight_bbox = fig.get_tightbbox(fig.canvas.get_renderer())
    exported_inches = [float(tight_bbox.width + 0.03), float(tight_bbox.height + 0.03)]
    stem = output / "fig2b_lv906_topology"
    for extension in ("pdf", "svg", "png"):
        fig.savefig(stem.with_suffix("." + extension), dpi=600, facecolor="white", bbox_inches="tight", pad_inches=0.015)
    plt.close(fig)
    with (source / "load_phase_map.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["load_id", "bus_id", "phase", "x", "y"])
        for load in loads:
            writer.writerow([load["load_id"], load["bus"], phase_names[load["phase"]], *load["xy"]])
    record = {"bus_count": len(coordinates), "line_count": len(lines), "is_connected_tree": True,
              "load_count": len(loads), "phase_counts": {phase_names[k]: v for k, v in Counter(x["phase"] for x in loads).items()},
              "unique_load_marker_count": len(grouped), "source_secondary_bus": source_bus,
              "coordinates_changed": False, "canvas_inches": [2.87, 2.99],
              "exported_inches": exported_inches, "label_font_pt": 5.6,
              "font_name": "Times New Roman", "font_file": Path(font_path).name,
              "all_55_ids_labeled_once": True, "label_overlap_pairs": overlap_pairs,
              "marker_label_intersections": sum(x["marker_intersections"] for x in labels),
              "line_label_intersections": sum(x["line_intersections"] for x in labels),
              "labels": labels,
              "source_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in source.iterdir() if f.is_file()},
              "output_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in output.glob("fig2b_lv906_topology.*")}}
    (qa / "fig2b_validation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({key: record[key] for key in ("bus_count", "line_count", "load_count", "phase_counts", "unique_load_marker_count", "all_55_ids_labeled_once", "label_overlap_pairs", "marker_label_intersections", "line_label_intersections")}, indent=2))


if __name__ == "__main__":
    main()
