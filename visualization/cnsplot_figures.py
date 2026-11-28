"""Revised CNSPlots figures for the saved ABP benchmark.

Run: .venv/bin/python -m visualization.cnsplot_figures results/benchmark_20261125T084243Z
"""

import argparse
from collections import Counter
import math
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "abp-matplotlib"))
os.environ.setdefault("MPLBACKEND", "Agg")

import cnsplots as cns
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize
import numpy as np
import pandas as pd

from .generate import Benchmark, LABELS, METHODS, SAT, number
from .publication_data import (AMOS, FIXED_OUTCOMES, amo_observations, fixed_counts,
                               fixed_outcome, fixed_rows, optimization_gaps)


STATUS_COLORS = {"SAT": "#009E73", "UNSAT": "#0072B2", "CLAUSE_LIMIT": "#999999",
                 "TIME_LIMIT": "#E69F00", "MEMORY_LIMIT": "#CC79A7", "ERROR": "#D55E00",
                 "INTERRUPTED": "#7F3C8D", "UNKNOWN": "#555555"}
STOP_CODES = {"TIME_LIMIT": "T", "CLAUSE_LIMIT": "C", "MEMORY_LIMIT": "M",
              "ERROR": "E", "INTERRUPTED": "I", "UNKNOWN": "U"}
SHORT = {"pairwise": "Pairwise", "order": "Order", "scl": "SCL"}


def save(fig, output, name):
    output.mkdir(parents=True, exist_ok=True)
    for extension in ("pdf", "svg"):
        path = output / f"{name}.{extension}"
        cns.savefig(path, fig=fig)
        print(path)
    plt.close(fig)


def plot_fixed_runtime(benchmark, rows, output):
    configurations = [(method, amo) for method in SAT for amo in AMOS]
    measured = [number(row, "total_seconds") for row in rows.values()
                if fixed_outcome(row) in ("SAT", "UNSAT")]
    measured = [value for value in measured if value is not None and value > 0]
    if not measured:
        raise ValueError("No completed fixed-threshold runtime measurements")
    time_limits = [number(row, "timeout_seconds") for row in rows.values()]
    high = max(max(measured), *(value for value in time_limits if value is not None))
    low = 10 ** math.floor(math.log10(min(measured)))
    norm = LogNorm(vmin=low, vmax=high)
    cmap = plt.get_cmap("viridis").with_extremes(bad="#e8e8e8")
    fig = cns.figure(170, 225, unit="mm")
    observed_stops = set()
    for panel, offset in enumerate((0, 1)):
        values = np.full((len(benchmark.instances), len(configurations)), np.nan)
        marks = {}
        for i, instance in enumerate(benchmark.instances):
            for j, (method, amo) in enumerate(configurations):
                row = rows[(instance, offset, method, amo)]
                outcome = fixed_outcome(row)
                seconds = number(row, "total_seconds")
                if outcome in ("SAT", "UNSAT") and seconds is not None and seconds > 0:
                    values[i, j] = seconds
                else:
                    observed_stops.add(outcome)
                    marks[(i, j)] = STOP_CODES.get(outcome, "O")
        ax = fig.add_axes((0.13 + panel * 0.39, 0.16, 0.34, 0.73))
        im = ax.imshow(np.ma.masked_invalid(values), norm=norm, cmap=cmap, aspect="auto")
        ax.set_xticks(range(6), [f"{SHORT[m][0]}/{a[0].upper()}" for m, a in configurations],
                      rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(benchmark.instances)),
                      benchmark.instances if panel == 0 else [""] * len(benchmark.instances), fontsize=7)
        ax.tick_params(length=0)
        ax.set_title("(a) Reference threshold $t_G$" if panel == 0 else
                     "(b) $t_G + 1$", fontsize=10, pad=8)
        for (i, j), code in marks.items():
            ax.text(j, i, code, ha="center", va="center", color="#222222", fontsize=7,
                    fontweight="bold")
    colorbar = fig.colorbar(im, cax=fig.add_axes((0.92, 0.24, 0.02, 0.56)))
    ticks = [value for value in (0.01, 0.1, 1, 10, 100, 300, 1000)
             if low <= value <= high]
    colorbar.set_ticks(ticks, labels=[f"{value:g}" for value in ticks])
    colorbar.set_label("Completed wall time (s)", fontsize=9)
    colorbar.ax.tick_params(labelsize=7)
    fig.suptitle("Fixed-threshold feasibility runtime", fontsize=11, y=0.96)
    labels = [f"{STOP_CODES.get(reason, 'O')}={reason.replace('_', ' ').lower()}"
              for reason in FIXED_OUTCOMES if reason in observed_stops]
    labels += [f"O={reason.lower()}" for reason in sorted(observed_stops - set(FIXED_OUTCOMES))]
    fig.text(0.13, 0.065, "Columns: distance / AMO (P=Pairwise, O=Order, S=SCL; P=Pairwise, S=Sequential).",
             fontsize=7)
    fig.text(0.13, 0.043, "Gray cells = incomplete: " + "; ".join(labels), fontsize=7)
    save(fig, output, "fixed_runtime_heatmap")


def plot_amo_ablation(benchmark, rows, output):
    clause_rows, runtime_rows = amo_observations(rows)
    if not clause_rows or not runtime_rows:
        raise ValueError("No matched AMO observations")
    fig = cns.figure(170, 100, unit="mm")
    for panel, (observations, field, title, ylabel, color) in enumerate((
        (clause_rows, "reduction_pct", "(a) Clause reduction", "Clause reduction (%)", "#0072B2"),
        (runtime_rows, "speedup", "(b) Completed-run speedup", "Pairwise / sequential runtime", "#009E73"),
    )):
        ax = fig.add_axes((0.10 + panel * 0.46, 0.25, 0.37, 0.63))
        data = pd.DataFrame({"method": [SHORT[row["method"]] for row in observations],
                             field: [row[field] for row in observations]})
        cns.boxplot(data, x="method", y=field, order=[SHORT[m] for m in SAT],
                    color=color, showoutliers=True, ax=ax)
        counts = Counter(data["method"])
        ax.set_xticks(range(3), [f"{SHORT[m]}\n(n={counts[SHORT[m]]})" for m in SAT], fontsize=7)
        ax.set(title=title, xlabel="Distance encoding", ylabel=ylabel)
        ax.title.set_fontsize(10)
        ax.xaxis.label.set_fontsize(9)
        ax.yaxis.label.set_fontsize(9)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(axis="y", alpha=0.2)
        if panel == 1:
            ax.set_yscale("log", base=2)
            lo, hi = min(data[field]), max(data[field])
            ticks = [2 ** exponent for exponent in range(math.floor(math.log2(lo)),
                                                          math.ceil(math.log2(hi)) + 1)]
            ax.set_yticks(ticks, [f"{value:g}×" for value in ticks])
            ax.axhline(1, color="#444444", linestyle="--", linewidth=0.9)
        else:
            ax.axhline(0, color="#444444", linestyle="--", linewidth=0.8)
    save(fig, output, "assignment_amo_ablation")


def plot_fixed_status(benchmark, rows, output):
    counts = fixed_counts(rows)
    outcomes = [outcome for outcome in FIXED_OUTCOMES
                if any(count[outcome] for count in counts.values())]
    outcomes += sorted({outcome for count in counts.values() for outcome in count}
                       - set(FIXED_OUTCOMES))
    configurations = [(method, amo) for method in SAT for amo in AMOS]
    data = [
        {"configuration": f"{SHORT[method]} / {'Pairwise' if amo == 'pairwise' else 'Sequential'}",
         "outcome": outcome}
        for method, amo in configurations
        for outcome, count in counts[(method, amo)].items() for _ in range(count)
    ]
    labels = [f"{SHORT[method]} / {'Pairwise' if amo == 'pairwise' else 'Sequential'}"
              for method, amo in configurations]
    fig = cns.figure(170, 105, color_cycle=[STATUS_COLORS.get(outcome, "#555555")
                                             for outcome in outcomes], unit="mm")
    ax = fig.add_axes((0.27, 0.16, 0.69, 0.68))
    cns.stackplot(pd.DataFrame(data), y="configuration", stack="outcome", order=labels,
                  stack_order=outcomes, normalize=False, ax=ax)
    ax.invert_yaxis()
    ax.set_xlim(0, 48)
    ax.set_xlabel("Runs per configuration", fontsize=9)
    ax.set_ylabel("Distance encoding / assignment AMO", fontsize=9)
    ax.set_title("Fixed-threshold outcomes, both thresholds", fontsize=11, pad=40)
    ax.tick_params(labelsize=8)
    ax.grid(axis="x", alpha=0.2)
    for bar in ax.patches:
        if bar.get_width() >= 2:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height() / 2,
                    f"{bar.get_width():.0f}", ha="center", va="center", fontsize=8,
                    color="white" if bar.get_facecolor()[0] < 0.4 else "#222222")
    handles, legend_labels = ax.get_legend_handles_labels()
    ax.legend(handles, [label.replace("_", " ").title() for label in legend_labels],
              ncol=min(4, len(outcomes)), loc="lower center", bbox_to_anchor=(0.5, 1.01),
              fontsize=8, frameon=False)
    save(fig, output, "fixed_termination_status")


def gap_annotation(value, certified, fallback):
    if not math.isfinite(value):
        return "–"
    label = "0" if value == 0 else "<1" if value < 0.5 else f"{value:.0f}"
    return label + ("*" if certified else "f" if fallback else "")


def plot_gap_heatmap(benchmark, gaps, output, metric, name, title, note):
    values = np.full((len(benchmark.instances), len(METHODS)), np.nan)
    fig = cns.figure(170, 232, unit="mm")
    ax = fig.add_axes((0.18, 0.14, 0.65, 0.77))
    cmap = plt.get_cmap("YlOrRd").with_extremes(bad="#eeeeee")
    norm = Normalize(0, 100)
    for i, instance in enumerate(benchmark.instances):
        for j, method in enumerate(METHODS):
            values[i, j] = gaps[(instance, method)][metric]
    im = ax.imshow(np.ma.masked_invalid(values), cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(len(METHODS)), [LABELS[m] for m in METHODS], rotation=45,
                  ha="right", fontsize=7)
    ax.set_yticks(range(len(benchmark.instances)), benchmark.instances, fontsize=7)
    ax.tick_params(length=0)
    ax.set_title(title, fontsize=11, pad=9)
    for i, instance in enumerate(benchmark.instances):
        for j, method in enumerate(METHODS):
            value = values[i, j]
            item = gaps[(instance, method)]
            label = gap_annotation(value, item["certified"], item["fallback_only"])
            rgba = cmap(norm(value)) if math.isfinite(value) else (0.9, 0.9, 0.9, 1)
            luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
            ax.text(j, i, label, ha="center", va="center", fontsize=6.5,
                    color="white" if luminance < 0.43 else "#222222")
    cbar = fig.colorbar(im, cax=fig.add_axes((0.87, 0.21, 0.025, 0.59)))
    cbar.set_ticks((0, 20, 40, 60, 80, 100))
    cbar.set_label("Gap (%)", fontsize=9)
    cbar.ax.tick_params(labelsize=7)
    fig.text(0.18, 0.05, note, fontsize=7)
    fig.text(0.18, 0.032, "* certified optimum; f fallback only; unmarked 0 is not proof.", fontsize=7)
    save(fig, output, name)


def generate(benchmark, output=None):
    output = Path(output) if output is not None else benchmark.directory / "new_figures"
    rows = fixed_rows(benchmark, require_complete=True)
    plot_fixed_runtime(benchmark, rows, output)
    plot_amo_ablation(benchmark, rows, output)
    plot_fixed_status(benchmark, rows, output)
    gaps = optimization_gaps(benchmark)
    plot_gap_heatmap(benchmark, gaps, output, "best_known_gap_pct", "best_known_solution_gap_heatmap",
                     "Best-observed solution gap", "Reference: best feasible value observed in this benchmark.")
    plot_gap_heatmap(benchmark, gaps, output, "relative_optimality_gap_pct",
                     "relative_optimality_gap_heatmap", "Relative optimality gap from bounds",
                     "Computed as 100 × (UB − LB) / UB from recorded verified bounds.")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output-dir", default="new_figures")
    args = parser.parse_args()
    generate(Benchmark(args.benchmark), args.benchmark / args.output_dir)


if __name__ == "__main__":
    main()
