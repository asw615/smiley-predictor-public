"""Figures for the Results section.

Reads metrics.json and per_flag_univariate.json from data/processed/.
Writes PDF + PNG pairs to paper/figures/ (per-class PR-AUC forest,
not-happy forest, per-flag forest).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from matplotlib import rcParams
from matplotlib.legend_handler import HandlerBase

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "paper" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif", "Liberation Serif"],
    "font.size": 10,
    "axes.labelsize": 10,
    "axes.titlesize": 11,
    "axes.titleweight": "regular",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.8,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "legend.frameon": False,
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
})

COLOR_BASELINE = "#444444"
COLOR_SUMMARY  = "#0072B2"
COLOR_FLAGS    = "#009E73"
COLOR_NEUTRAL  = "#0072B2"
COLOR_SAD      = "#D55E00"
COLOR_OR_NULL  = "#888888"


MODEL_ORDER = [
    # Bottom-up: forest plots read from the bottom.
    ("xgb_summary_llm",     "Summary + LLM flags, XGB", COLOR_FLAGS),
    ("lr_summary_llm",      "Summary + LLM flags, LR",  COLOR_FLAGS),
    ("xgb_summary",         "Summary, XGB",             COLOR_SUMMARY),
    ("lr_summary",          "Summary, LR",              COLOR_SUMMARY),
    ("baseline_prevalence", "Class-frequency baseline", COLOR_BASELINE),
]


def savefig(fig, name: str) -> None:
    pdf = FIG_DIR / f"{name}.pdf"
    png = FIG_DIR / f"{name}.png"
    fig.savefig(pdf)
    fig.savefig(png)
    plt.close(fig)
    print(f"  wrote {pdf.relative_to(ROOT)} and {png.relative_to(ROOT)}")


def fig_pr_auc_forest():
    data = json.loads((ROOT / "data" / "processed" / "metrics.json").read_text())["summary"]
    class_names = ["happy", "neutral", "sad"]

    # Vertical stack so each panel renders at full A4 width instead of being
    # squeezed to a third when the figure scales to page width.
    fig, axes = plt.subplots(3, 1, figsize=(6.8, 6.8), sharey=True)
    fig.subplots_adjust(left=0.30, right=0.97, top=0.96, bottom=0.10, hspace=0.42)
    n_panels = len(class_names)
    for c, (ax, cname) in enumerate(zip(axes, class_names)):
        labels, points, lows, highs, colors = [], [], [], [], []
        for key, label, color in MODEL_ORDER:
            m = data[key]
            labels.append(label)
            points.append(m["pr_auc_per_class"][c])
            lows.append(m["pr_auc_per_class_ci95"][c][0])
            highs.append(m["pr_auc_per_class_ci95"][c][1])
            colors.append(color)
        baseline_pr = data["baseline_prevalence"]["pr_auc_per_class"][c]
        ys = np.arange(len(labels))
        for x, lo, hi, y, col in zip(points, lows, highs, ys, colors):
            if col == COLOR_BASELINE:
                # Hollow diamond so the baseline row reads as a reference floor,
                # not as a candidate model on the same footing as the four fits.
                ax.errorbar(
                    x, y,
                    xerr=[[x - lo], [hi - x]],
                    fmt="D", ms=7.0,
                    elinewidth=1.2, capsize=3.5,
                    color=col, ecolor=col, mfc="white", mec=col, mew=1.2,
                )
            else:
                ax.errorbar(
                    x, y,
                    xerr=[[x - lo], [hi - x]],
                    fmt="o", ms=6.5,
                    elinewidth=1.4, capsize=3.5,
                    color=col, ecolor=col, mfc=col, mec="black", mew=0.6,
                )
        ax.axvline(baseline_pr, color=COLOR_BASELINE, linestyle=":", lw=1.2)
        ax.set_yticks(ys)
        ax.set_yticklabels(labels)
        # Extra headroom above the top row so the hollow-diamond baseline marker
        # is not clipped by the panel border.
        ax.set_ylim(-0.6, len(labels) - 0.4)
        # Only label the x-axis on the bottom panel; shared metric otherwise.
        if c == n_panels - 1:
            ax.set_xlabel("PR-AUC (95% CI)")
        ax.set_title(f"{cname.capitalize()} class", loc="left")
        ax.grid(axis="x", alpha=0.25, linewidth=0.5)
        ax.set_axisbelow(True)
    # Single thin legend below the stack. The handle draws a vertical dotted
    # line top-to-bottom with the hollow diamond centered on it, mirroring how
    # the baseline appears in the panels themselves.
    class _VerticalDottedDiamondHandler(HandlerBase):
        def create_artists(self, legend, orig_handle, xdescent, ydescent,
                           width, height, fontsize, trans):
            x = width / 2 - xdescent
            y_center = (height - ydescent) / 2
            line = plt.Line2D(
                [x, x], [y_center - 0.75 * height, y_center + 0.75 * height],
                linestyle=":", color=COLOR_BASELINE, lw=1.2,
            )
            marker = plt.Line2D(
                [x], [y_center],
                marker="D", linestyle="None",
                mfc="white", mec=COLOR_BASELINE, mew=1.2, ms=7,
            )
            line.set_transform(trans)
            marker.set_transform(trans)
            return [line, marker]

    baseline_handle = plt.Line2D([0], [0], color=COLOR_BASELINE)
    fig.legend(
        handles=[baseline_handle],
        labels=["Class-frequency baseline"],
        handler_map={baseline_handle: _VerticalDottedDiamondHandler()},
        loc="lower center", bbox_to_anchor=(0.5, 0.0),
        ncol=1, frameon=False, fontsize=9,
        handleheight=2.4, handlelength=1.2,
    )
    savefig(fig, "fig_pr_auc_forest")


def fig_per_flag_forest():
    data = json.loads((ROOT / "data" / "processed" / "per_flag_univariate.json").read_text())
    label_map = {
        "pest_or_vermin":         "Pest or vermin",
        "foreign_object_in_food": "Foreign object in food",
        "food_safety_concern":    "Food-safety concern",
        "visible_dirtness":       "Visible dirt",
        "staff_hygiene":          "Staff hygiene",
        "illness_after_eating":   "Illness after eating",
    }
    flags_sorted = sorted(data["flags"], key=lambda r: r["contrasts"]["sad"]["or_adjusted"])
    labels = [f"{label_map[f['flag']]} ({f['n_windows_flagged']:,} windows)" for f in flags_sorted]
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    ys = np.arange(len(labels))
    offset = 0.18
    for series_idx, (contrast, color, marker) in enumerate(
        [("neutral", COLOR_NEUTRAL, "o"), ("sad", COLOR_SAD, "s")]
    ):
        points = [f["contrasts"][contrast]["or_adjusted"] for f in flags_sorted]
        lows = [f["contrasts"][contrast]["or_ci95"][0] for f in flags_sorted]
        highs = [f["contrasts"][contrast]["or_ci95"][1] for f in flags_sorted]
        err_low = np.asarray(points) - np.asarray(lows)
        err_high = np.asarray(highs) - np.asarray(points)
        y_offset = ys + (offset if series_idx == 0 else -offset)
        ax.errorbar(
            points, y_offset, xerr=[err_low, err_high],
            fmt=marker, ms=5.5, lw=0,
            elinewidth=1.2, capsize=3,
            color=color, ecolor=color, mfc=color, mec="black", mew=0.6,
            label=f"{contrast.capitalize()} vs. happy",
        )
    ax.axvline(1.0, color=COLOR_OR_NULL, linestyle="--", lw=1.1, label="OR = 1 (no association)")

    ax.set_yticks(ys)
    ax.set_yticklabels(labels)
    ax.set_xscale("log")
    ax.set_xlabel("Adjusted odds ratio (log scale, 95% CI)")
    ticks = [0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0]
    ax.xaxis.set_major_locator(mticker.FixedLocator(ticks))
    ax.xaxis.set_minor_locator(mticker.NullLocator())
    ax.xaxis.set_major_formatter(mticker.FixedFormatter([f"{t:g}" for t in ticks]))
    ax.set_xlim(0.35, 5.0)
    ax.grid(axis="x", which="major", alpha=0.25, linewidth=0.5)
    ax.set_axisbelow(True)
    # Legend above the plot so it does not overlap the pest/vermin row.
    ax.legend(
        loc="lower center", bbox_to_anchor=(0.5, 1.02),
        ncol=3, frameon=False, fontsize=8.5,
    )
    fig.tight_layout()
    savefig(fig, "fig_per_flag_forest")


def main() -> None:
    print(f"Writing figures to {FIG_DIR.relative_to(ROOT)}/")
    fig_pr_auc_forest()
    fig_per_flag_forest()
    print("Done.")


if __name__ == "__main__":
    main()
