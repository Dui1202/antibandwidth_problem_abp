"""Generate reproducible tables and cnsplots figures from benchmark CSV files."""

import argparse
from collections import Counter, defaultdict
import csv
import os
from pathlib import Path
from statistics import median
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "abp-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cnsplots as cns


METHODS = ["pairwise", "order", "scl", "cp_sat", "cp_optimizer", "cplex", "gurobi"]
MARKERS = {"OPTIMAL": "o", "FEASIBLE": "^", "INFEASIBLE": "v", "TIMEOUT": "x",
           "RESOURCE_LIMIT": "s", "ERROR": "D"}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def summarize(rows, output):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["method"]].append(row)
    fields = ["method", "instances", "optimal", "feasible", "timeout", "resource_limit",
              "error", "median_completed_seconds"]
    table = []
    for method in METHODS:
        group = grouped[method]
        statuses = Counter(row["status"] for row in group)
        completed = [float(row["total_seconds"]) for row in group
                     if row["status"] in {"OPTIMAL", "FEASIBLE"} and row["total_seconds"]]
        table.append({"method": method, "instances": len(group), "optimal": statuses["OPTIMAL"],
                      "feasible": statuses["FEASIBLE"], "timeout": statuses["TIMEOUT"],
                      "resource_limit": statuses["RESOURCE_LIMIT"], "error": statuses["ERROR"],
                      "median_completed_seconds": median(completed) if completed else ""})
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(table)
    lines = ["# Benchmark summary", "", "Medians use completed runs only; timeout and resource-limit durations are excluded.",
             "Duplicate unweighted graphs remain separate named instances in the raw data.", "",
             "| Method | Instances | Optimal | Feasible | Timeout | Resource limit | Error | Median completed (s) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in table:
        lines.append("| " + " | ".join(str(row[field]) for field in fields) + " |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_scatter(rows, output, filename, title, ylabel, value_field, compact_only=False):
    cns.setup_matplotlib(color_cycle="OkabeIto")
    colors = dict(zip(METHODS, cns.get_palette_colors(range(len(METHODS)), "OkabeIto")))
    fig, ax = plt.subplots(figsize=(9, 5.4))
    for method in METHODS:
        for status, marker in MARKERS.items():
            subset = [row for row in rows if row["method"] == method and row["status"] == status
                      and row[value_field] and (not compact_only or row["assignment_amo"] == "sequential")]
            if not subset:
                continue
            ax.scatter([int(row["n_vertices"]) for row in subset],
                       [float(row[value_field]) for row in subset],
                       color=colors[method], marker=marker, s=32, alpha=0.8,
                       label=f"{method} ({status})")
    ax.set(xlabel="Vertices", ylabel=ylabel, title=title)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.grid(True, which="major", alpha=0.2)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7)
    fig.tight_layout()
    figure_dir = output / "figures"
    figure_dir.mkdir(exist_ok=True)
    for suffix in ("svg", "pdf"):
        cns.savefig(figure_dir / f"{filename}.{suffix}", fig=fig)
    plt.close(fig)


def analyze(output):
    optimization = read_csv(output / "optimization.csv")
    fixed = read_csv(output / "fixed.csv")
    if not optimization:
        raise ValueError("optimization.csv is missing or empty")
    summarize(optimization, output)
    plot_scatter(optimization, output, "optimization_runtime", "ABP optimization runtime",
                 "Wall time (s)", "total_seconds")
    plot_scatter(optimization, output, "optimization_best_value", "Verified best ABP value",
                 "Best feasible value", "best_value")
    if fixed:
        plot_scatter(fixed, output, "fixed_clauses", "Fixed-threshold CNF size",
                     "Clauses", "n_clauses", compact_only=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="benchmark results directory")
    analyze(parser.parse_args().output)
