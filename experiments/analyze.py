"""Generate reproducible tables and cnsplots figures from benchmark CSV files."""

import argparse
from collections import Counter, defaultdict
import csv
import json
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
MARKERS = {"COMPLETED": "o", "TIME_LIMIT": "x", "MEMORY_LIMIT": "s",
           "CLAUSE_LIMIT": "v", "INTERRUPTED": "P", "ERROR": "D", "UNKNOWN": "^"}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def number(row, field):
    value = row.get(field)
    return float(value) if value not in (None, "") else None


def summarize(rows, output):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["method"]].append(row)
    fields = ["method", "instances", "proven_optimal", "solver_feasible",
              "fallback_only", "time_limit", "memory_limit", "clause_limit",
              "backend_error", "median_observed_seconds", "median_completed_seconds",
              "median_absolute_gap", "median_relative_gap"]
    table = []
    for method in METHODS:
        group = grouped[method]
        reasons = Counter(row["termination_reason"] for row in group)
        observed = [number(row, "total_seconds") for row in group]
        completed = [number(row, "total_seconds") for row in group
                     if row["termination_reason"] == "COMPLETED"]
        gaps = [number(row, "absolute_gap") for row in group]
        relative = [number(row, "relative_gap") for row in group]
        valid = lambda values: [x for x in values if x is not None]
        table.append({"method": method, "instances": len(group),
                      "proven_optimal": sum(row["proven_optimal"] == "True" for row in group),
                      "solver_feasible": sum(row["has_solver_incumbent"] == "True" for row in group),
                      "fallback_only": sum(row["has_solver_incumbent"] != "True" for row in group),
                      "time_limit": reasons["TIME_LIMIT"], "memory_limit": reasons["MEMORY_LIMIT"],
                      "clause_limit": reasons["CLAUSE_LIMIT"], "backend_error": reasons["ERROR"],
                      "median_observed_seconds": median(valid(observed)) if valid(observed) else "",
                      "median_completed_seconds": median(valid(completed)) if valid(completed) else "",
                      "median_absolute_gap": median(valid(gaps)) if valid(gaps) else "",
                      "median_relative_gap": median(valid(relative)) if valid(relative) else ""})
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(table)
    lines = ["# Benchmark summary", "",
             "Observed runtimes include interrupted and limited runs; these are censored observations, not completion times.",
             "Completed-run medians are shown separately. Fallback-only rows are not solver-feasible counts.",
             "Duplicate unweighted graphs remain separate named instances in the raw data.", "",
             "| " + " | ".join(fields) + " |",
             "|" + "|".join("---" if i == 0 else "---:" for i in range(len(fields))) + "|"]
    for row in table:
        lines.append("| " + " | ".join(str(row[field]) for field in fields) + " |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_scatter(rows, output, filename, title, ylabel, value_field,
                 compact_only=False, log_y=True):
    cns.setup_matplotlib(color_cycle="OkabeIto")
    colors = dict(zip(METHODS, cns.get_palette_colors(range(len(METHODS)), "OkabeIto")))
    fig, ax = plt.subplots(figsize=(9, 5.4))
    for method in METHODS:
        for reason, marker in MARKERS.items():
            subset = [row for row in rows if row["method"] == method
                      and row["termination_reason"] == reason
                      and number(row, value_field) is not None
                      and (not log_y or number(row, value_field) > 0)
                      and (not compact_only or row["assignment_amo"] == "sequential")]
            if subset:
                ax.scatter([int(row["n_vertices"]) for row in subset],
                           [number(row, value_field) for row in subset],
                           color=colors[method], marker=marker, s=32, alpha=0.8,
                           label=f"{method} ({reason})")
    ax.set(xlabel="Vertices", ylabel=ylabel, title=title)
    ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    ax.grid(True, which="major", alpha=0.2)
    if ax.has_data():
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7)
    else:
        ax.text(0.5, 0.5, "No available measurements", transform=ax.transAxes,
                ha="center", va="center")
    fig.tight_layout()
    figure_dir = output / "figures"
    figure_dir.mkdir(exist_ok=True)
    for suffix in ("svg", "pdf"):
        cns.savefig(figure_dir / f"{filename}.{suffix}", fig=fig)
    plt.close(fig)


def analyze(output):
    metadata = json.loads((output / "metadata.json").read_text())
    if metadata.get("schema_version") != 3:
        raise ValueError("analysis requires benchmark result schema version 3")
    optimization = read_csv(output / "optimization.csv")
    fixed = read_csv(output / "fixed.csv")
    if not optimization:
        raise ValueError("optimization.csv is missing or empty")
    summarize(optimization, output)
    plot_scatter(optimization, output, "optimization_runtime", "ABP optimization runtime",
                 "Observed wall time (s)", "total_seconds")
    plot_scatter(optimization, output, "optimization_best_value", "Verified best ABP value",
                 "Best verified feasible value", "best_value")
    plot_scatter(optimization, output, "optimization_absolute_gap", "ABP optimality gap",
                 "Upper bound − lower bound", "absolute_gap", log_y=False)
    plot_scatter(optimization, output, "optimization_upper_bound", "ABP upper bounds",
                 "Certified upper bound", "upper_bound")
    if fixed:
        plot_scatter(fixed, output, "fixed_clauses", "Fixed-threshold CNF size",
                     "Clauses", "n_clauses", compact_only=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="benchmark results directory")
    analyze(parser.parse_args().output)
