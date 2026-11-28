"""Regenerate publication figures from saved benchmark CSVs only.

Run: .venv/bin/python -m visualization.publication results/benchmark_20261125T084243Z
"""

import argparse
import math
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "abp-matplotlib"))
os.environ.setdefault("MPLBACKEND", "Agg")

import cnsplots as cns
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.patches import Rectangle
import numpy as np

from .cnsplot_figures import generate as generate_revised, save
from .generate import Benchmark, LABELS, METHODS, generate, number, status_category


STOP = {"TIME_LIMIT": ("T", "#fff0cc"), "CLAUSE_LIMIT": ("C", "#e5e5e5"),
        "MEMORY_LIMIT": ("M", "#f1e0ef"), "ERROR": ("E", "#f6d4cf"),
        "INTERRUPTED": ("I", "#e2e1f2"), "UNKNOWN": ("U", "#e5ddf1")}


def _seconds(value):
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    if value >= 1:
        return f"{value:.2g}"
    return f"{value:.2f}"


def plot_optimization_runtime(benchmark, output):
    values = np.full((len(benchmark.instances), len(METHODS)), np.nan)
    measured = [number(row, "total_seconds") for row in benchmark.optimization
                if status_category(row) == "Proven optimal"
                and row.get("termination_reason") == "COMPLETED"]
    measured = [value for value in measured if value is not None and value > 0]
    low = 10 ** math.floor(math.log10(min(measured)))
    high = max(max(measured), number(benchmark.metadata.get("config", {}), "time_limit") or max(measured))
    norm = LogNorm(low, high)
    cmap = plt.get_cmap("viridis").with_extremes(bad="#eeeeee")
    annotations = {}
    fig = cns.figure(170, 232, unit="mm")
    ax = fig.add_axes((0.18, 0.15, 0.65, 0.76))
    for i, instance in enumerate(benchmark.instances):
        for j, method in enumerate(METHODS):
            row = benchmark.opt.get((instance, method))
            runtime = number(row, "total_seconds")
            complete = (row and status_category(row) == "Proven optimal"
                        and row.get("termination_reason") == "COMPLETED")
            if complete and runtime is not None and runtime > 0:
                values[i, j] = runtime
            else:
                reason = row.get("termination_reason") if row else "UNKNOWN"
                code, background = STOP.get(reason, ("O", "#eeeeee"))
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=background,
                                       edgecolor="white", linewidth=0.3, zorder=2))
                annotations[(i, j)] = (runtime, code, background)
    image = ax.imshow(np.ma.masked_invalid(values), norm=norm, cmap=cmap, aspect="auto", zorder=1)
    ax.set_xticks(range(len(METHODS)), [LABELS[m] for m in METHODS], rotation=45,
                  ha="right", fontsize=7)
    ax.set_yticks(range(len(benchmark.instances)), benchmark.instances, fontsize=7)
    ax.tick_params(length=0)
    ax.set_title("Optimization runtime and termination", fontsize=11, pad=9)
    for i, instance in enumerate(benchmark.instances):
        for j, method in enumerate(METHODS):
            runtime = values[i, j]
            if math.isfinite(runtime):
                rgba = cmap(norm(runtime))
                luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
                label, color = _seconds(runtime), "white" if luminance < 0.43 else "#222222"
            else:
                observed, code, _ = annotations[(i, j)]
                label = (f"{_seconds(observed)} " if observed is not None and observed > 0 else "") + code
                color = "#222222"
            ax.text(j, i, label, ha="center", va="center", fontsize=6.2, color=color, zorder=3)
    bar = fig.colorbar(image, cax=fig.add_axes((0.87, 0.22, 0.025, 0.58)))
    ticks = [value for value in (0.1, 1, 10, 100, 600, 1000) if low <= value <= high]
    bar.set_ticks(ticks, labels=[f"{value:g}" for value in ticks])
    bar.set_label("Certified wall time (s)", fontsize=9)
    bar.ax.tick_params(labelsize=7)
    fig.text(0.18, 0.065, "Colored = certified optimal; tinted = incomplete; numbers are observed wall seconds.", fontsize=7)
    fig.text(0.18, 0.047, "T time; C clause; M memory; E error; I interrupted; U unknown; O other stop.", fontsize=7)
    save(fig, output, "optimization_runtime_heatmap")


def plot_peak_memory(benchmark, output):
    values = np.full((len(benchmark.instances), len(METHODS)), np.nan)
    for i, instance in enumerate(benchmark.instances):
        for j, method in enumerate(METHODS):
            value = number(benchmark.opt.get((instance, method)), "peak_memory_mb")
            if value is not None and value > 0:
                values[i, j] = value
    finite = values[np.isfinite(values)]
    low = 10 ** math.floor(math.log10(float(min(finite))))
    high = float(max(finite)) * 1.05
    fig = cns.figure(170, 230, unit="mm")
    ax = fig.add_axes((0.18, 0.15, 0.65, 0.76))
    cmap = plt.get_cmap("viridis").with_extremes(bad="#eeeeee")
    image = ax.imshow(np.ma.masked_invalid(values), norm=LogNorm(low, high), cmap=cmap,
                      aspect="auto")
    ax.set_xticks(range(len(METHODS)), [LABELS[m] for m in METHODS], rotation=45,
                  ha="right", fontsize=7)
    ax.set_yticks(range(len(benchmark.instances)), benchmark.instances, fontsize=7)
    ax.tick_params(length=0)
    ax.set_title("Observed peak resident memory", fontsize=11, pad=9)
    bar = fig.colorbar(image, cax=fig.add_axes((0.87, 0.22, 0.025, 0.58)))
    ticks = [value for value in (100, 300, 1000, 3000, 10000) if low <= value <= high]
    bar.set_ticks(ticks, labels=[f"{value:g}" for value in ticks])
    bar.set_label("Sampled peak RSS (MiB)", fontsize=9)
    bar.ax.tick_params(labelsize=7)
    limit = number(benchmark.metadata.get("config", {}), "memory_mb")
    limit_note = f"; configured limit {limit:g} MiB" if limit else ""
    fig.text(0.18, 0.064, "Worker + native children, sampled from Linux VmRSS" + limit_note + ".",
             fontsize=7)
    fig.text(0.18, 0.046, "Sampling may miss short-lived memory peaks.", fontsize=7)
    save(fig, output, "peak_memory_comparison")


def generate_legacy_supplements(benchmark, output):
    from experiments.analyze import plot_scatter
    common = dict(figure_dir=output, publication=True)
    plot_scatter(benchmark.optimization, benchmark.directory, "optimization_runtime",
                 "Observed optimization runtime", "Observed wall time (s)", "total_seconds", **common)
    plot_scatter(benchmark.optimization, benchmark.directory, "optimization_best_value",
                 "Verified feasible ABP value (includes fallback)",
                 "Best verified feasible value", "best_value", **common)
    plot_scatter(benchmark.optimization, benchmark.directory, "optimization_absolute_gap",
                 "Absolute optimality gap", "Upper bound − lower bound", "absolute_gap",
                 log_y=False, **common)
    plot_scatter(benchmark.optimization, benchmark.directory, "optimization_upper_bound",
                 "Recorded upper bound", "Upper bound", "upper_bound", **common)
    plot_scatter(benchmark.fixed, benchmark.directory, "fixed_clauses",
                 "Fixed CNF size (sequential AMO; both thresholds)", "CNF clauses", "n_clauses",
                 compact_only=True, **common)


def generate_all(directory):
    directory = Path(directory)
    output = generate(directory, output_dir="new_figures")
    benchmark = Benchmark(directory, output_dir="new_figures")
    generate_legacy_supplements(benchmark, output)
    generate_revised(benchmark, output)
    plot_optimization_runtime(benchmark, output)
    plot_peak_memory(benchmark, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    print(generate_all(args.results))


if __name__ == "__main__":
    main()
