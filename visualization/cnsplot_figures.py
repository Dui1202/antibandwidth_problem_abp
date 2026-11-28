"""Generate four CNSPlots figures from an existing benchmark directory.

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
import numpy as np
import pandas as pd

from .generate import Benchmark, LABELS, METHODS, SAT, integer, number


def save(fig, output, name):
    path = output / f"{name}.pdf"
    cns.savefig(path, fig=fig)
    plt.close(fig)
    print(path)


def matrix(benchmark, rows, methods, field, transform=lambda value: value):
    values = pd.DataFrame(index=benchmark.instances,
                          columns=[LABELS[method] for method in methods], dtype=float)
    for row in rows:
        value = number(row, field)
        if row["method"] in methods and value is not None:
            values.loc[row["instance"], LABELS[row["method"]]] = transform(value)
    return values


def draw_heatmap(values, title, legend, output, filename, *, cmap, vmin=None, vmax=None):
    fig = cns.figure(180, 235, unit="mm")
    ax = fig.add_axes((0.19, 0.12, 0.64, 0.79))
    colors = plt.get_cmap(cmap).copy()
    colors.set_bad("#eeeeee")
    image = ax.imshow(np.ma.masked_invalid(values.to_numpy(dtype=float)),
                      cmap=colors, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(values.columns)), values.columns, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(values.index)), values.index, fontsize=7)
    ax.tick_params(length=0)
    ax.set_title(title, fontsize=11, pad=12)
    colorbar = fig.colorbar(image, cax=fig.add_axes((0.87, 0.23, 0.025, 0.58)))
    colorbar.set_label(legend, fontsize=8)
    colorbar.ax.tick_params(labelsize=7)
    save(fig, output, filename)


def generate(benchmark):
    output = benchmark.output
    pilot = [row for row in benchmark.fixed
             if row["method"] in SAT
             and integer(row, "threshold") == benchmark.thresholds.get(row["instance"])]
    sequential = [row for row in pilot if row["assignment_amo"] == "sequential"]

    completed = [row for row in sequential
                 if row["termination_reason"] == "COMPLETED"
                 and row["raw_status"] in ("SAT", "UNSAT")
                 and (number(row, "total_seconds") or 0) > 0]
    runtime = matrix(benchmark, completed, SAT, "total_seconds", math.log10)
    draw_heatmap(runtime, "Fixed-threshold runtime (completed runs)",
                 "log10 seconds", output, "fixed_runtime_heatmap", cmap="viridis")

    paired = []
    by_key = {(row["instance"], row["method"], row["assignment_amo"]): row
              for row in pilot}
    for instance in benchmark.instances:
        for method in SAT:
            pair = by_key.get((instance, method, "pairwise"))
            seq = by_key.get((instance, method, "sequential"))
            if not pair or not seq or any(
                row["termination_reason"] != "COMPLETED" or row["raw_status"] not in ("SAT", "UNSAT")
                for row in (pair, seq)
            ) or pair["raw_status"] != seq["raw_status"]:
                continue
            pair_seconds, seq_seconds = number(pair, "total_seconds"), number(seq, "total_seconds")
            if pair_seconds and seq_seconds and min(pair_seconds, seq_seconds) > 0:
                paired.append({"method": LABELS[method],
                               "log2_speedup": math.log2(pair_seconds / seq_seconds)})
    if not paired:
        raise ValueError("No matched completed AMO runs")
    counts = Counter(row["method"] for row in paired)
    fig = cns.figure(160, 100, unit="mm")
    ax = cns.boxplot(pd.DataFrame(paired), x="method", y="log2_speedup",
                     order=[LABELS[method] for method in SAT], color="#5189BB",
                     showfliers=True)
    ax.axhline(0, color="#555555", linewidth=0.9, linestyle="--")
    ax.set(title="Assignment AMO ablation at the fixed threshold",
           xlabel="Encoding", ylabel="log2(pairwise AMO / sequential AMO runtime)")
    ax.set_xticks(range(len(SAT)),
                  [f"{LABELS[method]}\n(n={counts[LABELS[method]]})" for method in SAT])
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    save(fig, output, "assignment_amo_ablation")

    statuses = []
    for row in sequential:
        reason = row["termination_reason"]
        status = row["raw_status"] if reason == "COMPLETED" else reason or "UNKNOWN"
        statuses.append({"method": LABELS[row["method"]], "status": status})
    fig = cns.figure(175, 105, color_cycle=["#009E73", "#E69F00", "#999999"], unit="mm")
    ax = cns.stackplot(pd.DataFrame(statuses), x="method", stack="status",
                       order=[LABELS[method] for method in SAT],
                       stack_order=["SAT", "TIME_LIMIT", "CLAUSE_LIMIT"],
                       normalize=False, add_count=True)
    ax.set(title="Fixed-threshold termination status (sequential AMO)",
           xlabel="Encoding", ylabel="Number of runs")
    ax.legend(title="Termination", bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    save(fig, output, "fixed_termination_status")

    gaps = matrix(benchmark, benchmark.optimization, METHODS, "relative_gap",
                  lambda value: 100 * value)
    draw_heatmap(gaps, "Relative optimality gap from recorded bounds",
                 "(UB - LB) / UB (%)", output, "relative_optimality_gap_heatmap",
                 cmap="YlOrRd", vmin=0, vmax=100)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path, help="Benchmark result directory")
    args = parser.parse_args()
    generate(Benchmark(args.benchmark))


if __name__ == "__main__":
    main()
