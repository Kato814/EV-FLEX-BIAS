from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

for variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[variable] = "1"

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd

from evflex.aggregate import write_csv_atomic
from evflex.provenance import sha256_file
from evflex.runner import atomic_write_json


PROTOCOL_ID = "EV-FLEX-BIAS-V2.0"
FIGURE_WIDTH_MM = 180.0
RASTER_DPI = 600
INC_COLOR = "#386CB0"
DEC_COLOR = "#C75B4B"
GREEN = "#3E7C59"
RED = "#B44B4B"
AMBER = "#B27A2B"
GRAY = "#777777"
LIGHT_GRAY = "#D9D9D9"
BLACK = "#111111"

FIGURE_CONTRACTS = {
    "fig1_framework_v2_0": {
        "core_conclusion": (
            "A same-input balanced-versus-three-phase comparison can be developed, "
            "frozen, and validated once without holdout-driven refitting."
        ),
        "archetype": "schematic-led composite",
        "height_mm": 68.0,
        "reviewer_risk": "Any path that could leak holdout outcomes into fitting.",
    },
    "fig2_alpha_map_v2_0": {
        "core_conclusion": (
            "Balanced-model deliverability mapping depends on feeder, service "
            "direction, and requested duration."
        ),
        "archetype": "quantitative grid",
        "height_mm": 88.0,
        "reviewer_risk": "Pooling cells could hide feeder- or direction-specific bias.",
    },
    "fig3_false_safe_v2_0": {
        "core_conclusion": (
            "Development false-safe prevalence is cell-specific and cannot be "
            "summarized by one global reliability rate."
        ),
        "archetype": "quantitative grid",
        "height_mm": 82.0,
        "reviewer_risk": "Rates must show eligible n and use a common color scale.",
    },
    "fig4_applicability_v2_0": {
        "core_conclusion": (
            "Only development cells satisfying the frozen count and false-safe "
            "criteria define candidate applicability regions."
        ),
        "archetype": "quantitative grid",
        "height_mm": 104.0,
        "reviewer_risk": "A missing rule must not be displayed as zero risk.",
    },
    "fig5_ablation_v2_0": {
        "core_conclusion": (
            "Predeclared upper physical factor levels alter balanced-to-three-phase "
            "mapping in a feeder-, time-, and direction-dependent manner."
        ),
        "archetype": "quantitative grid",
        "height_mm": 92.0,
        "reviewer_risk": "Factor levels must be predeclared rather than outcome-selected.",
    },
    "fig6_holdout_v2_0": {
        "core_conclusion": (
            "Frozen applicability rules validate only in specific feeder-direction-"
            "duration cells on the one-pass holdout."
        ),
        "archetype": "quantitative grid",
        "height_mm": 104.0,
        "reviewer_risk": "Insufficient n and absent development rules must remain explicit.",
    },
}


def _configure_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "font.size": 7.0,
            "axes.titlesize": 8.0,
            "axes.labelsize": 7.5,
            "xtick.labelsize": 6.5,
            "ytick.labelsize": 6.5,
            "legend.fontsize": 6.5,
            "axes.edgecolor": BLACK,
            "axes.linewidth": 0.7,
            "axes.grid": False,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "legend.frameon": False,
            "svg.fonttype": "none",
            "svg.hashsalt": PROTOCOL_ID,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )


def _style_axis(axis: plt.Axes) -> None:
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_color(BLACK)
        spine.set_linewidth(0.7)
    axis.tick_params(
        axis="both",
        which="both",
        direction="in",
        top=True,
        right=True,
        labeltop=False,
        labelright=False,
        colors=BLACK,
    )
    axis.grid(False)


def _resolve(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def _relative(repo: Path, path: Path) -> str:
    return str(path.resolve(strict=False).relative_to(repo)).replace("\\", "/")


def _source_record(repo: Path, path: Path) -> dict:
    return {"path": _relative(repo, path), "sha256": sha256_file(path)}


def _write_frame(path: Path, frame: pd.DataFrame) -> str:
    return write_csv_atomic(path, frame.to_dict("records"))


def _save_one(fig: plt.Figure, path: Path, *, kind: str, dpi: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=path.suffix, dir=path.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        kwargs = {"format": kind, "facecolor": "white"}
        if dpi is not None:
            kwargs["dpi"] = dpi
        if kind == "svg":
            kwargs["metadata"] = {
                "Date": None,
                "Creator": PROTOCOL_ID,
                "Title": path.stem,
            }
        elif kind == "pdf":
            kwargs["metadata"] = {
                "CreationDate": None,
                "ModDate": None,
                "Creator": PROTOCOL_ID,
                "Title": path.stem,
            }
        elif kind == "png":
            kwargs["metadata"] = {"Software": PROTOCOL_ID}
        elif kind == "tiff":
            kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(temporary, **kwargs)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _save_figure_bundle(
    repo: Path, fig: plt.Figure, figure_directory: Path, stem: str
) -> list[dict]:
    paths = [
        (figure_directory / f"{stem}.svg", "svg", None),
        (figure_directory / f"{stem}.pdf", "pdf", None),
        (figure_directory / f"{stem}.png", "png", RASTER_DPI),
        (figure_directory / f"{stem}.tiff", "tiff", RASTER_DPI),
    ]
    for path, kind, dpi in paths:
        _save_one(fig, path, kind=kind, dpi=dpi)
    plt.close(fig)
    return [
        {
            "path": _relative(repo, path),
            "sha256": sha256_file(path),
            "bytes": int(path.stat().st_size),
        }
        for path, _, _ in paths
    ]


def _write_asset_metadata(
    *,
    repo: Path,
    data_directory: Path,
    asset_id: str,
    asset_type: str,
    source_data_path: Path | None,
    source_artifacts: list[Path],
    contains_experimental_values: bool,
    exports: list[dict] | None = None,
    statistics: str,
) -> None:
    contract = FIGURE_CONTRACTS.get(asset_id)
    payload = {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "protocol_id": PROTOCOL_ID,
        "source_data_csv": (
            _relative(repo, source_data_path) if source_data_path is not None else None
        ),
        "source_data_sha256": (
            sha256_file(source_data_path) if source_data_path is not None else None
        ),
        "source_artifacts": [
            _source_record(repo, path) for path in source_artifacts
        ],
        "contains_experimental_values": contains_experimental_values,
        "statistics": statistics,
        "exports": exports or [],
    }
    if contract is not None:
        payload.update(
            {
                "core_conclusion": contract["core_conclusion"],
                "figure_archetype": contract["archetype"],
                "backend": "Python/matplotlib",
                "final_size_mm": [
                    FIGURE_WIDTH_MM,
                    float(contract["height_mm"]),
                ],
                "raster_dpi": RASTER_DPI,
                "font": "Times New Roman with serif fallback",
                "gridlines": False,
                "ticks": "inward on four sides; top/right labels suppressed",
                "reviewer_risk": contract["reviewer_risk"],
            }
        )
    atomic_write_json(data_directory / f"{asset_id}_metadata.json", payload)


def _figure_size(stem: str) -> tuple[float, float]:
    contract = FIGURE_CONTRACTS[stem]
    return FIGURE_WIDTH_MM / 25.4, float(contract["height_mm"]) / 25.4


def _successful_core_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_columns = ["data_role", "feeder", "direction", "duration_min"]
    for keys, group in frame.groupby(group_columns, sort=True):
        eligible = group.loc[group["status"].eq("SUCCESS")].copy()
        alpha = pd.to_numeric(eligible["alpha_map"], errors="raise")
        rows.append(
            {
                "data_role": str(keys[0]),
                "feeder": str(keys[1]),
                "direction": str(keys[2]),
                "duration_min": int(keys[3]),
                "n_total": int(len(group)),
                "n_success": int(len(eligible)),
                "n_terminal_non_success": int(len(group) - len(eligible)),
                "median_f_3ph_kw": float(
                    pd.to_numeric(eligible["f_3ph_kw"], errors="raise").median()
                ),
                "median_f_bal_kw": float(
                    pd.to_numeric(eligible["f_bal_kw"], errors="raise").median()
                ),
                "median_alpha_map": float(alpha.median()),
                "alpha_q25": float(alpha.quantile(0.25)),
                "alpha_q75": float(alpha.quantile(0.75)),
                "median_bias_pct": float(
                    pd.to_numeric(eligible["bias_pct"], errors="raise").median()
                ),
                "false_safe_n": int(alpha.lt(0.95).sum()),
                "false_safe_rate": float(alpha.lt(0.95).mean()),
            }
        )
    return pd.DataFrame(rows)


def _development_applicability(oof: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (feeder, direction, duration), group in oof.groupby(
        ["feeder", "direction", "duration_min"], sort=True
    ):
        if group["candidate_selected"].dtype == bool:
            selected = group["candidate_selected"].fillna(False)
        else:
            selected = (
                group["candidate_selected"]
                .astype(str)
                .str.strip()
                .str.lower()
                .eq("true")
            )
        thresholds = pd.to_numeric(group["risk_threshold"], errors="coerce").dropna()
        has_rule = not thresholds.empty
        selected_n = int(selected.sum()) if has_rule else 0
        false_safe_n = (
            int(group.loc[selected, "false_safe"].astype(bool).sum())
            if selected_n
            else 0
        )
        rows.append(
            {
                "cell_id": f"{feeder}|{direction}|{int(duration)}",
                "feeder": str(feeder),
                "direction": str(direction),
                "duration_min": int(duration),
                "eligible_development_n": int(len(group)),
                "has_development_rule": bool(has_rule),
                "risk_threshold": (
                    float(thresholds.iloc[0]) if has_rule else None
                ),
                "selected_n": selected_n,
                "selected_false_safe_n": false_safe_n,
                "selected_false_safe_rate": (
                    float(false_safe_n / selected_n) if selected_n else None
                ),
                "selected_coverage": float(selected_n / len(group)) if has_rule else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _predeclared_ablation_extremes(contrasts: pd.DataFrame) -> pd.DataFrame:
    levels = {
        "A1_phase": ("4:1:1", "2:1:1"),
        "A2_location": ("0.8", "0.5"),
        "A3_load": ("1.05", "0.9"),
        "A4_urgency": ("0.9", "0.65"),
        "A5_v2g": ("1.0", "0.5"),
    }
    selected_parts = []
    for block, (level, reference) in levels.items():
        selected_parts.append(
            contrasts.loc[
                contrasts["block"].eq(block)
                & contrasts["factor_level"].astype(str).eq(level)
                & contrasts["reference_level"].astype(str).eq(reference)
            ].copy()
        )
    selected = pd.concat(selected_parts, ignore_index=True)
    if len(selected) != 36:
        raise ValueError(
            f"predeclared ablation extremes must contain 36 rows, found {len(selected)}"
        )
    selected["selection_rule"] = (
        "predeclared upper factor level versus block reference"
    )
    return selected.sort_values(
        ["block", "direction", "feeder", "call_time"], kind="stable"
    ).reset_index(drop=True)


def _draw_framework() -> plt.Figure:
    fig, axis = plt.subplots(figsize=_figure_size("fig1_framework_v2_0"))
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    def box(x, y, width, height, title, subtitle, face):
        patch = FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=0.9,
            edgecolor=BLACK,
            facecolor=face,
        )
        axis.add_patch(patch)
        axis.text(
            x + width / 2,
            y + height * 0.63,
            title,
            ha="center",
            va="center",
            fontsize=7.6,
            fontweight="bold",
            color=BLACK,
        )
        axis.text(
            x + width / 2,
            y + height * 0.32,
            subtitle,
            ha="center",
            va="center",
            fontsize=6.2,
            color=BLACK,
            linespacing=1.05,
        )

    def arrow(start, end):
        axis.add_patch(
            FancyArrowPatch(
                start,
                end,
                arrowstyle="-|>",
                mutation_scale=9,
                linewidth=0.9,
                color=BLACK,
                shrinkA=2,
                shrinkB=2,
            )
        )

    box(
        0.015,
        0.36,
        0.15,
        0.28,
        "Same EV inputs",
        "fleet, load, phase,\nsiting and call",
        "#EEF2F7",
    )
    box(
        0.22,
        0.62,
        0.16,
        0.24,
        "Balanced model",
        "aggregate network\nestimate",
        "#E7EEF8",
    )
    box(
        0.22,
        0.14,
        0.16,
        0.24,
        "Three-phase model",
        "unbalanced physical\nreference",
        "#F8ECE8",
    )
    box(
        0.44,
        0.36,
        0.15,
        0.28,
        "Deliverability map",
        "capacity ratio and\nfalse-safe label",
        "#F3F0E5",
    )
    box(
        0.65,
        0.36,
        0.15,
        0.28,
        "Development freeze",
        "OOF risk model and\nfixed threshold",
        "#EAF3EC",
    )
    box(
        0.85,
        0.36,
        0.135,
        0.28,
        "One-pass holdout",
        "no refit, no new ID,\ncell-specific claim",
        "#F4EAEA",
    )
    arrow((0.165, 0.53), (0.22, 0.73))
    arrow((0.165, 0.47), (0.22, 0.25))
    arrow((0.38, 0.74), (0.44, 0.56))
    arrow((0.38, 0.26), (0.44, 0.44))
    arrow((0.59, 0.50), (0.65, 0.50))
    arrow((0.80, 0.50), (0.85, 0.50))
    axis.text(
        0.5,
        0.965,
        "Auditable V1G/V2G flexibility-bias evidence chain",
        ha="center",
        va="top",
        fontsize=8.6,
        fontweight="bold",
    )
    axis.text(
        0.725,
        0.29,
        "sealed split",
        ha="center",
        va="center",
        fontsize=6.0,
        color=GRAY,
    )
    return fig


def _draw_alpha_map(source: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(
        1,
        2,
        figsize=_figure_size("fig2_alpha_map_v2_0"),
        sharey=True,
    )
    durations = [15, 30, 60]
    for axis, feeder in zip(axes, ["ieee13", "lv906"]):
        feeder_data = source.loc[source["feeder"].eq(feeder)]
        for direction, color, marker in (
            ("inc", INC_COLOR, "o"),
            ("dec", DEC_COLOR, "s"),
        ):
            cell = (
                feeder_data.loc[feeder_data["direction"].eq(direction)]
                .set_index("duration_min")
                .loc[durations]
            )
            medians = cell["median_alpha_map"].to_numpy(dtype=float)
            lower = medians - cell["alpha_q25"].to_numpy(dtype=float)
            upper = cell["alpha_q75"].to_numpy(dtype=float) - medians
            axis.errorbar(
                durations,
                medians,
                yerr=np.vstack([lower, upper]),
                color=color,
                marker=marker,
                markersize=4.2,
                linewidth=1.1,
                capsize=2.2,
                label="Increase" if direction == "inc" else "Decrease",
            )
        axis.axhline(0.95, color=GRAY, linestyle="--", linewidth=0.8)
        axis.set_title("IEEE 13-node" if feeder == "ieee13" else "LV 906-node")
        axis.set_xlabel("Requested service duration (min)")
        axis.set_xticks(durations)
        axis.set_xlim(10, 65)
        axis.set_ylim(0, 1.06)
        _style_axis(axis)
    axes[0].set_ylabel(r"Deliverability mapping, $\alpha_{\mathrm{map}}$")
    axes[1].legend(loc="lower right")
    fig.subplots_adjust(left=0.085, right=0.98, bottom=0.18, top=0.88, wspace=0.12)
    return fig


def _draw_false_safe(source: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(
        1,
        2,
        figsize=_figure_size("fig3_false_safe_v2_0"),
        sharey=True,
    )
    directions = ["inc", "dec"]
    durations = [15, 30, 60]
    image = None
    for axis, feeder in zip(axes, ["ieee13", "lv906"]):
        cell = source.loc[source["feeder"].eq(feeder)]
        matrix = np.empty((2, 3), dtype=float)
        counts = np.empty((2, 3), dtype=int)
        for row_index, direction in enumerate(directions):
            for column_index, duration in enumerate(durations):
                row = cell.loc[
                    cell["direction"].eq(direction)
                    & cell["duration_min"].eq(duration)
                ].iloc[0]
                matrix[row_index, column_index] = float(row["false_safe_rate"])
                counts[row_index, column_index] = int(row["n_success"])
        image = axis.imshow(
            matrix,
            vmin=0,
            vmax=1,
            cmap=mpl.colors.LinearSegmentedColormap.from_list(
                "false_safe", ["#F7F7F7", "#D8E4F2", "#7DA0C8", "#315D8A"]
            ),
            aspect="auto",
        )
        for i in range(2):
            for j in range(3):
                color = "white" if matrix[i, j] >= 0.55 else BLACK
                axis.text(
                    j,
                    i,
                    f"{100 * matrix[i, j]:.1f}%\n(n={counts[i, j]})",
                    ha="center",
                    va="center",
                    color=color,
                    fontsize=6.4,
                )
        axis.set_xticks(range(3), durations)
        axis.set_yticks(range(2), ["Increase", "Decrease"])
        axis.set_xlabel("Requested service duration (min)")
        axis.set_title("IEEE 13-node" if feeder == "ieee13" else "LV 906-node")
        _style_axis(axis)
        axis.tick_params(top=False, right=False)
    color_axis = fig.add_axes([0.92, 0.20, 0.015, 0.62])
    color_bar = fig.colorbar(image, cax=color_axis)
    color_bar.set_label("Development false-safe rate")
    color_bar.ax.tick_params(direction="in", labelsize=6.2)
    fig.subplots_adjust(left=0.10, right=0.89, bottom=0.20, top=0.86, wspace=0.16)
    return fig


def _cell_label(row: pd.Series) -> str:
    feeder = "IEEE13" if row["feeder"] == "ieee13" else "LV906"
    direction = "Inc" if row["direction"] == "inc" else "Dec"
    return f"{feeder} · {direction} · {int(row['duration_min'])} min"


def _draw_development_applicability(source: pd.DataFrame) -> plt.Figure:
    ordered = source.sort_values(
        ["feeder", "direction", "duration_min"], kind="stable"
    ).reset_index(drop=True)
    fig, axis = plt.subplots(figsize=_figure_size("fig4_applicability_v2_0"))
    y = np.arange(len(ordered))
    colors = [GREEN if bool(value) else LIGHT_GRAY for value in ordered["has_development_rule"]]
    axis.barh(
        y,
        100 * ordered["selected_coverage"].to_numpy(dtype=float),
        color=colors,
        edgecolor=BLACK,
        linewidth=0.45,
        height=0.66,
    )
    for index, row in ordered.iterrows():
        if bool(row["has_development_rule"]):
            rate = 100 * float(row["selected_false_safe_rate"])
            text = f"n={int(row['selected_n'])}; false-safe={rate:.1f}%"
        else:
            text = "no qualifying development rule"
        axis.text(
            101.5,
            index,
            text,
            ha="left",
            va="center",
            fontsize=6.1,
            color=BLACK if bool(row["has_development_rule"]) else GRAY,
        )
    axis.set_yticks(y, [_cell_label(row) for _, row in ordered.iterrows()])
    axis.invert_yaxis()
    axis.set_xlim(0, 155)
    axis.set_xticks([0, 20, 40, 60, 80, 100])
    axis.set_xlabel("Selected development OOF coverage (%)")
    axis.set_title(
        "Candidate applicability regions frozen before holdout",
        loc="left",
        fontweight="bold",
    )
    _style_axis(axis)
    fig.subplots_adjust(left=0.27, right=0.98, bottom=0.13, top=0.90)
    return fig


def _draw_ablation(source: pd.DataFrame) -> plt.Figure:
    labels = {
        ("A1_phase", "inc"): "Phase\nInc",
        ("A1_phase", "dec"): "Phase\nDec",
        ("A2_location", "inc"): "Siting\nInc",
        ("A2_location", "dec"): "Siting\nDec",
        ("A3_load", "inc"): "Load\nInc",
        ("A3_load", "dec"): "Load\nDec",
        ("A4_urgency", "inc"): "Urgency\nInc",
        ("A4_urgency", "dec"): "Urgency\nDec",
        ("A5_v2g", "dec"): "V2G\nDec",
    }
    order = list(labels)
    fig, axis = plt.subplots(figsize=_figure_size("fig5_ablation_v2_0"))
    offsets = {
        ("ieee13", "19:00"): -0.18,
        ("ieee13", "02:00"): -0.06,
        ("lv906", "19:00"): 0.06,
        ("lv906", "02:00"): 0.18,
    }
    markers = {"ieee13": "o", "lv906": "s"}
    for x, key in enumerate(order):
        cell = source.loc[
            source["block"].eq(key[0]) & source["direction"].eq(key[1])
        ]
        color = INC_COLOR if key[1] == "inc" else DEC_COLOR
        for _, row in cell.iterrows():
            axis.scatter(
                x + offsets[(row["feeder"], row["call_time"])],
                float(row["alpha_contrast"]),
                s=22,
                marker=markers[row["feeder"]],
                facecolor=color if row["call_time"] == "19:00" else "white",
                edgecolor=color,
                linewidth=0.8,
                zorder=3,
            )
        median = float(pd.to_numeric(cell["alpha_contrast"], errors="raise").median())
        axis.plot([x - 0.28, x + 0.28], [median, median], color=BLACK, linewidth=1.2)
    axis.axhline(0, color=BLACK, linewidth=0.8)
    axis.set_xticks(range(len(order)), [labels[key] for key in order])
    axis.set_ylabel(r"Contrast in $\alpha_{\mathrm{map}}$ (upper − reference)")
    fig.suptitle(
        "Predeclared upper-level ablation contrasts",
        x=0.08,
        y=0.97,
        ha="left",
        fontweight="bold",
        fontsize=8.0,
    )
    axis.set_xlim(-0.55, len(order) - 0.45)
    _style_axis(axis)
    handles = [
        mpl.lines.Line2D(
            [], [], marker="o", linestyle="none", markerfacecolor=INC_COLOR,
            markeredgecolor=INC_COLOR, markersize=4.2, label="Increase"
        ),
        mpl.lines.Line2D(
            [], [], marker="o", linestyle="none", markerfacecolor=DEC_COLOR,
            markeredgecolor=DEC_COLOR, markersize=4.2, label="Decrease"
        ),
        mpl.lines.Line2D(
            [], [], marker="o", linestyle="none", markerfacecolor=BLACK,
            markeredgecolor=BLACK, markersize=4.2, label="IEEE13"
        ),
        mpl.lines.Line2D(
            [], [], marker="s", linestyle="none", markerfacecolor=BLACK,
            markeredgecolor=BLACK, markersize=4.2, label="LV906"
        ),
        mpl.lines.Line2D(
            [], [], marker="o", linestyle="none", markerfacecolor=BLACK,
            markeredgecolor=BLACK, markersize=4.2, label="19:00"
        ),
        mpl.lines.Line2D(
            [], [], marker="o", linestyle="none", markerfacecolor="white",
            markeredgecolor=BLACK, markersize=4.2, label="02:00"
        ),
    ]
    fig.legend(
        handles=handles,
        ncol=6,
        loc="upper center",
        bbox_to_anchor=(0.55, 0.90),
        columnspacing=1.2,
        handletextpad=0.5,
    )
    fig.subplots_adjust(left=0.09, right=0.985, bottom=0.22, top=0.76)
    return fig


def _draw_holdout(source: pd.DataFrame) -> plt.Figure:
    ordered = source.sort_values(
        ["feeder", "direction", "duration_min"], kind="stable"
    ).reset_index(drop=True)
    colors = {
        "VALIDATED": GREEN,
        "NOT_VALIDATED_FALSE_SAFE": RED,
        "INSUFFICIENT_HOLDOUT_N": AMBER,
        "NO_DEVELOPMENT_RULE": GRAY,
    }
    fig, axis = plt.subplots(figsize=_figure_size("fig6_holdout_v2_0"))
    for index, row in ordered.iterrows():
        status = str(row["claim_status"])
        color = colors[status]
        if status == "NO_DEVELOPMENT_RULE":
            axis.scatter(-2.0, index, marker="x", color=color, s=24, linewidth=1.0)
            axis.text(
                1.0,
                index,
                "no development rule",
                va="center",
                ha="left",
                color=GRAY,
                fontsize=6.0,
            )
            continue
        rate = 100 * float(row["holdout_false_safe_rate"])
        lower = 100 * float(row["wilson_95_lower"])
        upper = 100 * float(row["wilson_95_upper"])
        axis.errorbar(
            rate,
            index,
            xerr=np.asarray([[rate - lower], [upper - rate]]),
            fmt="o",
            color=color,
            markerfacecolor=color,
            markeredgecolor=BLACK,
            markeredgewidth=0.4,
            markersize=4.5,
            capsize=2.1,
            linewidth=0.9,
        )
        axis.text(
            min(upper + 1.0, 28.0),
            index,
            f"n={int(row['holdout_selected_n'])}/{int(row['eligible_holdout_n'])}",
            va="center",
            ha="left",
            color=BLACK,
            fontsize=6.0,
        )
    axis.axvline(5.0, color=BLACK, linestyle="--", linewidth=0.8)
    axis.text(
        5.25,
        0.985,
        "5% criterion",
        ha="left",
        va="top",
        fontsize=6.0,
        color=BLACK,
        transform=axis.get_xaxis_transform(),
    )
    axis.set_yticks(
        range(len(ordered)), [_cell_label(row) for _, row in ordered.iterrows()]
    )
    axis.invert_yaxis()
    axis.set_xlim(-5, 30)
    axis.set_xlabel("Holdout false-safe rate with Wilson 95% interval (%)")
    fig.suptitle(
        "One-pass validation of frozen applicability rules",
        x=0.27,
        y=0.97,
        ha="left",
        fontweight="bold",
        fontsize=8.0,
    )
    _style_axis(axis)
    handles = [
        mpl.lines.Line2D([], [], marker="o", linestyle="none", color=color,
                         label=label, markersize=4.5)
        for label, color in (
            ("Validated", GREEN),
            ("False-safe criterion not met", RED),
            ("Selected n < 20", AMBER),
            ("No development rule", GRAY),
        )
    ]
    fig.legend(
        handles=handles,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.63, 0.90),
        columnspacing=1.6,
        handletextpad=0.5,
    )
    fig.subplots_adjust(left=0.27, right=0.985, bottom=0.13, top=0.72)
    return fig


def _token(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _display_count(value: int | float) -> str:
    return f"{int(value):,}"


def _display_number(value: int | float, decimals: int = 2) -> str:
    return f"{float(value):.{decimals}f}"


def _display_percent(value: int | float) -> str:
    return f"{100.0 * float(value):.1f}%"


def _build_ledger(
    *,
    repo: Path,
    development_path: Path,
    ablation_path: Path,
    holdout_path: Path,
    directional_path: Path,
    applicability_path: Path,
    core_summary: pd.DataFrame,
    directional: pd.DataFrame,
    applicability: pd.DataFrame,
    ablation_extremes: pd.DataFrame,
) -> dict:
    values: dict[str, dict] = {}
    hashes = {
        path: sha256_file(path)
        for path in (
            development_path,
            ablation_path,
            holdout_path,
            directional_path,
            applicability_path,
        )
    }

    def add(
        key: str,
        value: int | float,
        display: str,
        unit: str,
        source_path: Path,
        definition: str,
    ) -> None:
        if not math.isfinite(float(value)):
            raise ValueError(f"ledger value is non-finite: {key}")
        if key in values:
            raise ValueError(f"duplicate ledger key: {key}")
        values[key] = {
            "value": int(value) if isinstance(value, (int, np.integer)) else float(value),
            "display": display,
            "unit": unit,
            "definition": definition,
            "source_path": _relative(repo, source_path),
            "source_sha256": hashes[source_path],
        }

    development = pd.read_csv(development_path)
    holdout = pd.read_csv(holdout_path)
    ablation = pd.read_csv(ablation_path)
    for role, frame, path in (
        ("development", development, development_path),
        ("holdout", holdout, holdout_path),
        ("ablation", ablation, ablation_path),
    ):
        add(
            f"v2.sample.{role}_evaluations",
            len(frame),
            _display_count(len(frame)),
            "evaluations",
            path,
            f"Number of frozen V2.0 {role} evaluation rows.",
        )
        add(
            f"v2.sample.{role}_success",
            int(frame["status"].eq("SUCCESS").sum()),
            _display_count(frame["status"].eq("SUCCESS").sum()),
            "evaluations",
            path,
            f"Number of successful frozen V2.0 {role} evaluation rows.",
        )

    source_by_role = {
        "development": development_path,
        "holdout": holdout_path,
    }
    for _, row in core_summary.iterrows():
        prefix = (
            f"v2.core.{_token(row['data_role'])}.{_token(row['feeder'])}."
            f"{_token(row['direction'])}.{int(row['duration_min'])}m"
        )
        path = source_by_role[str(row["data_role"])]
        for suffix, value, display, unit, definition in (
            ("n_total", row["n_total"], _display_count(row["n_total"]), "evaluations", "Total cell evaluations."),
            ("n_success", row["n_success"], _display_count(row["n_success"]), "evaluations", "Successful cell evaluations."),
            ("median_f_3ph_kw", row["median_f_3ph_kw"], _display_number(row["median_f_3ph_kw"], 1), "kW", "Median three-phase deliverable capacity."),
            ("median_f_bal_kw", row["median_f_bal_kw"], _display_number(row["median_f_bal_kw"], 1), "kW", "Median balanced-model deliverable capacity."),
            ("median_alpha_map", row["median_alpha_map"], _display_number(row["median_alpha_map"], 3), "ratio", "Median mapped-to-balanced deliverability ratio."),
            ("median_bias_pct", row["median_bias_pct"], _display_number(row["median_bias_pct"], 1), "%", "Median balanced-versus-three-phase capacity bias."),
            ("false_safe_rate", row["false_safe_rate"], _display_percent(row["false_safe_rate"]), "proportion", "Empirical alpha_map < 0.95 rate among successful evaluations."),
        ):
            add(f"{prefix}.{suffix}", value, display, unit, path, definition)

    for _, row in directional.iterrows():
        prefix = (
            f"v2.holdout.directional.{_token(row['feeder'])}."
            f"{int(row['duration_min'])}m"
        )
        for suffix, value, display, unit, definition in (
            ("paired_n", row["paired_n"], _display_count(row["paired_n"]), "pairs", "Same-scenario inc-dec holdout pairs."),
            ("median_alpha_diff", row["median_alpha_difference_inc_minus_dec"], _display_number(row["median_alpha_difference_inc_minus_dec"], 3), "ratio", "Median paired alpha_map difference, increase minus decrease."),
            ("alpha_ci_low", row["alpha_difference_ci95_lower"], _display_number(row["alpha_difference_ci95_lower"], 3), "ratio", "Stratified bootstrap lower 95% bound for paired alpha difference."),
            ("alpha_ci_high", row["alpha_difference_ci95_upper"], _display_number(row["alpha_difference_ci95_upper"], 3), "ratio", "Stratified bootstrap upper 95% bound for paired alpha difference."),
            ("median_bias_diff", row["median_bias_difference_inc_minus_dec"], _display_number(row["median_bias_difference_inc_minus_dec"], 1), "percentage points", "Median paired bias difference, increase minus decrease."),
            ("bias_ci_low", row["bias_difference_ci95_lower"], _display_number(row["bias_difference_ci95_lower"], 1), "percentage points", "Stratified bootstrap lower 95% bound for paired bias difference."),
            ("bias_ci_high", row["bias_difference_ci95_upper"], _display_number(row["bias_difference_ci95_upper"], 1), "percentage points", "Stratified bootstrap upper 95% bound for paired bias difference."),
            ("median_capacity_diff_kw", row["median_capacity_difference_inc_minus_dec_kw"], _display_number(row["median_capacity_difference_inc_minus_dec_kw"], 1), "kW", "Median paired three-phase capacity difference, increase minus decrease."),
            ("capacity_ci_low_kw", row["capacity_difference_ci95_lower_kw"], _display_number(row["capacity_difference_ci95_lower_kw"], 1), "kW", "Stratified bootstrap lower 95% bound for paired capacity difference."),
            ("capacity_ci_high_kw", row["capacity_difference_ci95_upper_kw"], _display_number(row["capacity_difference_ci95_upper_kw"], 1), "kW", "Stratified bootstrap upper 95% bound for paired capacity difference."),
        ):
            add(
                f"{prefix}.{suffix}",
                value,
                display,
                unit,
                directional_path,
                definition,
            )

    for _, row in applicability.iterrows():
        prefix = (
            f"v2.holdout.applicability.{_token(row['feeder'])}."
            f"{_token(row['direction'])}.{int(row['duration_min'])}m"
        )
        always = (
            ("eligible_n", row["eligible_holdout_n"], _display_count(row["eligible_holdout_n"]), "evaluations", "Successful holdout observations eligible for frozen scoring."),
            ("selected_n", row["holdout_selected_n"], _display_count(row["holdout_selected_n"]), "evaluations", "Holdout observations selected by the frozen threshold."),
            ("false_safe_n", row["holdout_false_safe_n"], _display_count(row["holdout_false_safe_n"]), "evaluations", "False-safe observations among frozen-threshold selections."),
            ("coverage", row["holdout_coverage"], _display_percent(row["holdout_coverage"]), "proportion", "Frozen-threshold selected holdout coverage."),
        )
        for suffix, value, display, unit, definition in always:
            add(
                f"{prefix}.{suffix}",
                value,
                display,
                unit,
                applicability_path,
                definition,
            )
        for suffix, column, definition in (
            ("false_safe_rate", "holdout_false_safe_rate", "False-safe rate among selected holdout observations."),
            ("wilson_low", "wilson_95_lower", "Wilson lower 95% bound for selected holdout false-safe rate."),
            ("wilson_high", "wilson_95_upper", "Wilson upper 95% bound for selected holdout false-safe rate."),
        ):
            value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
            if pd.notna(value):
                add(
                    f"{prefix}.{suffix}",
                    value,
                    _display_percent(value),
                    "proportion",
                    applicability_path,
                    definition,
                )

    for _, row in ablation_extremes.iterrows():
        prefix = (
            f"v2.ablation.{_token(row['block'])}.{_token(row['feeder'])}."
            f"{_token(row['call_time'])}.{_token(row['direction'])}."
            f"{_token(row['factor_level'])}"
        )
        for suffix, column, decimals, unit, definition in (
            ("alpha_contrast", "alpha_contrast", 3, "ratio", "Paired alpha_map contrast, upper factor level minus reference."),
            ("alpha_ci_low", "alpha_contrast_ci_low", 3, "ratio", "Bootstrap lower 95% bound for paired alpha contrast."),
            ("alpha_ci_high", "alpha_contrast_ci_high", 3, "ratio", "Bootstrap upper 95% bound for paired alpha contrast."),
            ("bias_contrast", "bias_contrast", 1, "percentage points", "Paired capacity-bias contrast, upper factor level minus reference."),
            ("bias_ci_low", "bias_contrast_ci_low", 1, "percentage points", "Bootstrap lower 95% bound for paired bias contrast."),
            ("bias_ci_high", "bias_contrast_ci_high", 1, "percentage points", "Bootstrap upper 95% bound for paired bias contrast."),
        ):
            add(
                f"{prefix}.{suffix}",
                row[column],
                _display_number(row[column], decimals),
                unit,
                ablation_path,
                definition,
            )
    return {
        "artifact": "machine_linked_manuscript_values",
        "protocol_id": PROTOCOL_ID,
        "marker_syntax": "<displayed numeric value> [[V2:<ledger key>]]",
        "value_count": len(values),
        "values": dict(sorted(values.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-analysis", type=Path, required=True)
    parser.add_argument("--ablation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    _configure_style()
    repo = Path(__file__).resolve().parents[1]
    final_analysis = _resolve(repo, args.final_analysis)
    ablation_directory = _resolve(repo, args.ablation)
    output_directory = _resolve(repo, args.output_dir)
    data_directory = output_directory / "data"
    figure_directory = output_directory / "figures"
    data_directory.mkdir(parents=True, exist_ok=True)
    figure_directory.mkdir(parents=True, exist_ok=True)

    development_path = (
        repo / "results" / "development_v2_0" / "development_evaluations_v2_0.csv"
    )
    holdout_path = (
        repo / "results" / "holdout_v2_0" / "holdout_evaluations_v2_0.csv"
    )
    oof_path = (
        repo
        / "results"
        / "modeling_v2_0"
        / "development_oof_predictions_v2_0.csv"
    )
    applicability_path = final_analysis / "applicability_validation_v2_0.csv"
    directional_path = final_analysis / "directional_summary_v2_0.csv"
    ablation_results_path = (
        ablation_directory / "compact_ablation_results_v2_0.csv"
    )
    ablation_contrasts_path = ablation_directory / "ablation_contrasts_v2_0.csv"

    development = pd.read_csv(development_path)
    holdout = pd.read_csv(holdout_path)
    oof = pd.read_csv(oof_path)
    applicability = pd.read_csv(applicability_path)
    directional = pd.read_csv(directional_path)
    ablation_contrasts = pd.read_csv(
        ablation_contrasts_path,
        dtype={"factor_level": str, "reference_level": str},
    )

    core_summary = _successful_core_summary(
        pd.concat([development, holdout], ignore_index=True, sort=False)
    )
    development_summary = core_summary.loc[
        core_summary["data_role"].eq("development")
    ].reset_index(drop=True)
    development_applicability = _development_applicability(oof)
    ablation_extremes = _predeclared_ablation_extremes(ablation_contrasts)

    table_specs = [
        (
            "table1_core_summary_v2_0",
            core_summary,
            [development_path, holdout_path],
            "Medians and empirical rates among successful evaluations; terminal counts retained.",
        ),
        (
            "table2_applicability_v2_0",
            applicability,
            [applicability_path],
            "Frozen-rule selected counts, empirical false-safe rates, Wilson intervals, and coverage.",
        ),
        (
            "table3_ablation_summary_v2_0",
            ablation_extremes,
            [ablation_contrasts_path],
            "Predeclared upper factor level versus reference; fixed paired bootstrap outputs.",
        ),
    ]
    for asset_id, frame, sources, statistics in table_specs:
        table_path = data_directory / f"{asset_id}.csv"
        _write_frame(table_path, frame)
        _write_asset_metadata(
            repo=repo,
            data_directory=data_directory,
            asset_id=asset_id,
            asset_type="table",
            source_data_path=table_path,
            source_artifacts=sources,
            contains_experimental_values=True,
            statistics=statistics,
        )

    _write_asset_metadata(
        repo=repo,
        data_directory=data_directory,
        asset_id="fig1_framework_v2_0",
        asset_type="figure",
        source_data_path=None,
        source_artifacts=[],
        contains_experimental_values=False,
        exports=_save_figure_bundle(
            repo,
            _draw_framework(),
            figure_directory,
            "fig1_framework_v2_0",
        ),
        statistics="Conceptual framework only; no experimental values.",
    )

    quantitative_figures: list[
        tuple[str, pd.DataFrame, list[Path], Callable[[pd.DataFrame], plt.Figure], str]
    ] = [
        (
            "fig2_alpha_map_v2_0",
            development_summary,
            [development_path],
            _draw_alpha_map,
            "Median and interquartile range among successful development evaluations.",
        ),
        (
            "fig3_false_safe_v2_0",
            development_summary,
            [development_path],
            _draw_false_safe,
            "Empirical alpha_map < 0.95 rate among successful development evaluations.",
        ),
        (
            "fig4_applicability_v2_0",
            development_applicability,
            [oof_path],
            _draw_development_applicability,
            "Frozen five-fold OOF selection coverage and empirical selected false-safe rate.",
        ),
        (
            "fig5_ablation_v2_0",
            ablation_extremes,
            [ablation_contrasts_path],
            _draw_ablation,
            "Predeclared upper-level paired contrasts; medians shown across feeder-time strata.",
        ),
        (
            "fig6_holdout_v2_0",
            applicability,
            [applicability_path],
            _draw_holdout,
            "One-pass selected false-safe rate with two-sided Wilson 95% interval.",
        ),
    ]
    for asset_id, frame, sources, draw, statistics in quantitative_figures:
        source_path = data_directory / f"{asset_id}_source.csv"
        _write_frame(source_path, frame)
        exports = _save_figure_bundle(
            repo, draw(frame), figure_directory, asset_id
        )
        _write_asset_metadata(
            repo=repo,
            data_directory=data_directory,
            asset_id=asset_id,
            asset_type="figure",
            source_data_path=source_path,
            source_artifacts=sources,
            contains_experimental_values=True,
            exports=exports,
            statistics=statistics,
        )

    ledger = _build_ledger(
        repo=repo,
        development_path=development_path,
        ablation_path=ablation_results_path,
        holdout_path=holdout_path,
        directional_path=directional_path,
        applicability_path=applicability_path,
        core_summary=core_summary,
        directional=directional,
        applicability=applicability,
        ablation_extremes=ablation_extremes,
    )
    ledger_path = output_directory / "generated_values_v2_0.json"
    atomic_write_json(ledger_path, ledger)
    print(
        json.dumps(
            {
                "protocol_id": PROTOCOL_ID,
                "figures": len(FIGURE_CONTRACTS),
                "tables": len(table_specs),
                "ledger_values": ledger["value_count"],
                "output_directory": _relative(repo, output_directory),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
