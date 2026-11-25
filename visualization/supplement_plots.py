"""Plots backed by the focused supplemental experiment."""

from collections import defaultdict
import math

import matplotlib.pyplot as plt
import numpy as np

from .generate import SAT, METHODS, COLORS, LABELS, integer, number, read_csv, save


def plot_thresholds(benchmark, rows):
    instances = list(dict.fromkeys(row["instance"] for row in rows))
    if not instances:
        return
    fig, axes = plt.subplots(len(instances), 1, figsize=(10, 3.8 * len(instances)), squeeze=False)
    for ax, instance in zip(axes[:, 0], instances):
        subset = [row for row in rows if row["instance"] == instance]
        for method in SAT:
            series = sorted((row for row in subset if row["method"] == method),
                            key=lambda row: integer(row, "threshold") or 0)
            # Connect only adjacent completed thresholds; unknown and missing values break the line.
            segment = []
            previous = None
            for row in series + [None]:
                threshold = integer(row, "threshold")
                seconds = number(row, "solve_seconds")
                complete = bool(row and row.get("termination_reason") == "COMPLETED"
                                and row.get("raw_status") in ("SAT", "UNSAT")
                                and seconds is not None and seconds > 0)
                if not complete or previous is not None and threshold != previous + 1:
                    if len(segment) > 1:
                        ax.plot([x for x, _ in segment], [y for _, y in segment],
                                color=COLORS[method], linewidth=1)
                    segment = []
                if row is None:
                    break
                if complete:
                    ax.scatter(threshold, seconds, color=COLORS[method],
                               marker="o" if row["raw_status"] == "SAT" else "s", s=42)
                    segment.append((threshold, seconds))
                elif seconds is not None and seconds > 0:
                    ax.scatter(threshold, seconds, color=COLORS[method], marker="v",
                               facecolors="none", s=50)
                elif threshold is not None:
                    ax.text(threshold, 0.02, "T" if row.get("termination_reason") == "TIME_LIMIT" else "U",
                            transform=ax.get_xaxis_transform(), ha="center", fontsize=8,
                            color=COLORS[method])
                previous = threshold
        centers = {(row.get("center_source"), integer(row, "center_threshold")) for row in subset}
        if len(centers) == 1:
            source, center = next(iter(centers))
            if source == "certified_optimum" and center is not None:
                ax.axvline(center + 0.5, linestyle="--", color="black", linewidth=1)
                ax.text(center + 0.5, 0.95, f"k*={center}", transform=ax.get_xaxis_transform(),
                        ha="left", va="top", fontsize=8)
            elif center is not None:
                ax.text(0.02, 0.95, f"Pilot k={center}; optimum unverified",
                        transform=ax.transAxes, va="top", fontsize=8)
        ax.set(title=instance, xlabel="Antibandwidth threshold k", ylabel="SAT solving time (s)", yscale="log")
        ax.grid(alpha=0.2)
    handles = [plt.Line2D([], [], marker="o", color=COLORS[m], linestyle="", label=LABELS[m]) for m in SAT]
    handles += [plt.Line2D([], [], marker="o", color="black", linestyle="", label="SAT"),
                plt.Line2D([], [], marker="s", color="black", linestyle="", label="UNSAT"),
                plt.Line2D([], [], marker="v", color="black", fillstyle="none", linestyle="", label="Unknown / timed out")]
    fig.legend(handles=handles, loc="upper center", ncol=6, fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save(benchmark, fig, "threshold_sensitivity_analysis")


def plot_stats(benchmark, rows):
    selected = []
    for instance in dict.fromkeys(row["instance"] for row in rows):
        subset = [row for row in rows if row["instance"] == instance]
        center = integer(subset[0], "center_threshold")
        if center is not None:
            selected.extend(row for row in subset if integer(row, "threshold") == center)
    if not selected:
        return
    instances = list(dict.fromkeys(row["instance"] for row in selected))
    fig, axes = plt.subplots(2, 2, figsize=(max(11, len(instances) * 2.5), 8))
    for ax, statistic in zip(axes.flat, ("conflicts", "decisions", "propagations", "restarts")):
        observed = []
        for i, instance in enumerate(instances):
            for j, method in enumerate(SAT):
                row = next((row for row in selected if row["instance"] == instance and row["method"] == method), None)
                value = integer(row, statistic)
                x = i + (j - 1) * 0.25
                if value is None:
                    ax.text(x, 0.02, "–", transform=ax.get_xaxis_transform(), ha="center")
                elif value == 0:
                    ax.text(x, 0.02, "0", transform=ax.get_xaxis_transform(), ha="center")
                else:
                    observed.append(value)
                    ax.bar(x, value, 0.25, color=COLORS[method],
                           hatch="//" if row.get("raw_status") == "UNSAT" else None,
                           alpha=0.45 if row.get("termination_reason") != "COMPLETED" else 1)
        ax.set(title=statistic.capitalize(), xticks=range(len(instances)), xticklabels=instances,
               ylabel="Solver counter")
        if observed and max(observed) / min(observed) >= 100:
            ax.set_yscale("log")
        ax.grid(axis="y", alpha=0.2)
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[m], label=LABELS[m]) for m in SAT]
    handles += [plt.Rectangle((0, 0), 1, 1, color="gray", hatch="//", label="UNSAT"),
                plt.Rectangle((0, 0), 1, 1, color="gray", alpha=0.45, label="Incomplete counter")]
    fig.legend(handles=handles, loc="upper center", ncol=5, fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save(benchmark, fig, "sat_solver_statistics")


def plot_variability(benchmark, rows):
    groups = defaultdict(list)
    censored = defaultdict(int)
    for row in rows:
        key = row["instance"], row["method"]
        seconds = number(row, "total_seconds")
        if (row.get("proven_optimal") == "True" and row.get("solution_status") == "OPTIMAL"
                and row.get("termination_reason") == "COMPLETED" and seconds is not None and seconds > 0):
            groups[key].append(seconds)
        else:
            censored[key] += 1
    instances = list(dict.fromkeys(row["instance"] for row in rows))
    if not any(len(values) >= 2 for values in groups.values()):
        return
    fig, axes = plt.subplots(len(instances), 1, figsize=(12, 3.6 * len(instances)), squeeze=False)
    for ax, instance in zip(axes[:, 0], instances):
        for i, method in enumerate(METHODS):
            values = groups[(instance, method)]
            if len(values) >= 2:
                box = ax.boxplot(values, positions=[i], widths=0.55, patch_artist=True,
                                 showfliers=True, manage_ticks=False)
                box["boxes"][0].set(facecolor=COLORS[method], alpha=0.35)
                ax.scatter(np.full(len(values), i), values, color=COLORS[method], s=15, zorder=3)
            elif values:
                ax.scatter(i, values[0], color=COLORS[method], marker="x", s=35)
            if censored[(instance, method)]:
                ax.text(i, 0.02, f"{censored[(instance, method)]} limited",
                        transform=ax.get_xaxis_transform(), ha="center", rotation=90, fontsize=7)
        ax.set(title=instance, ylabel="Certified end-to-end runtime (s)", yscale="log",
               xticks=range(len(METHODS)), xticklabels=[LABELS[m] for m in METHODS])
        ax.grid(axis="y", alpha=0.2)
    repetitions = max(integer(row, "repetition") or 0 for row in rows)
    fig.suptitle(f"Runtime variability: {repetitions} repetitions per instance; fixed seed 42 where supported", y=1.01)
    fig.tight_layout()
    save(benchmark, fig, "runtime_variability")


def generate_supplemental_figures(benchmark):
    directory = benchmark.directory / "supplemental"
    if not directory.exists():
        return
    sweep = read_csv(directory / "sweep.csv")
    repeats = read_csv(directory / "repeat.csv")
    if sweep:
        plot_thresholds(benchmark, sweep)
        plot_stats(benchmark, sweep)
    if repeats:
        plot_variability(benchmark, repeats)
