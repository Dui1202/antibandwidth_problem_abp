"""Generate comparison figures from a benchmark result directory."""

import argparse
import csv
import json
import math
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "abp-matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize
from matplotlib.patches import Patch
import numpy as np


SAT = ("pairwise", "order", "scl")
METHODS = SAT + ("cp_sat", "cp_optimizer", "cplex", "gurobi")
LABELS = {"pairwise": "Pairwise", "order": "Order", "scl": "Staircase SCL",
          "cp_sat": "CP-SAT", "cp_optimizer": "CP Optimizer", "cplex": "CPLEX", "gurobi": "Gurobi"}
COLORS = dict(zip(METHODS, ("#0072B2", "#D55E00", "#009E73", "#CC79A7",
                            "#56B4E9", "#E69F00", "#555555")))
STATUS_CATEGORIES = ("Optimal", "Feasible but uncertified", "No feasible solution found",
                     "Missing or invalid experiment")
STATUS_COLORS = ("#009E73", "#E69F00", "#D55E00", "#999999")
STOP_CODES = {"TIME_LIMIT": "T", "MEMORY_LIMIT": "M", "CLAUSE_LIMIT": "C",
              "ERROR": "E", "INTERRUPTED": "I", "UNKNOWN": "?"}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def number(row, field):
    if row is None:
        return None
    try:
        value = float(row.get(field, ""))
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def integer(row, field):
    value = number(row, field)
    return int(value) if value is not None and value.is_integer() else None


class Benchmark:
    def __init__(self, directory):
        self.directory = Path(directory)
        metadata = json.loads((self.directory / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("schema_version") != 3:
            raise ValueError("comparison figures require result schema version 3")
        self.metadata = metadata
        self.instances = [row["instance"] for row in sorted(
            read_csv(self.directory / "manifest.csv"),
            key=lambda row: (int(row["n_vertices"]), row["instance"]))]
        if not self.instances:
            raise ValueError("manifest.csv has no benchmark instances")
        self.optimization = read_csv(self.directory / "optimization.csv")
        self.fixed = read_csv(self.directory / "fixed.csv")
        self.thresholds = {row["instance"]: integer(row, "threshold")
                           for row in read_csv(self.directory / "thresholds.csv")}
        self.opt = {(row["instance"], row["method"]): row for row in self.optimization}
        self.output = self.directory / "figures"
        self.output.mkdir(exist_ok=True)


def valid_cnf(row):
    return all(integer(row, field) is not None and integer(row, field) >= 0
               for field in ("n_clauses", "n_primary_vars", "n_aux_vars"))


def fixed_comparison(benchmark):
    matching = {}
    for row in benchmark.fixed:
        key = (row.get("instance"), row.get("method"))
        if (row.get("method") in SAT and row.get("assignment_amo") == "sequential"
                and integer(row, "threshold") == benchmark.thresholds.get(row.get("instance"))
                and benchmark.thresholds.get(row.get("instance")) is not None and valid_cnf(row)):
            if key in matching:
                raise ValueError(f"duplicate fixed comparison: {key}")
            matching[key] = row
    result = {}
    for instance in benchmark.instances:
        baseline = matching.get((instance, "pairwise"))
        baseline_count = integer(baseline, "n_clauses")
        for method in SAT:
            row = matching.get((instance, method))
            count = integer(row, "n_clauses")
            result[(instance, method)] = {
                "threshold": benchmark.thresholds.get(instance),
                "clauses": count, "primary": integer(row, "n_primary_vars"),
                "auxiliary": integer(row, "n_aux_vars"),
                "reduction_pct": (100 * (baseline_count - count) / baseline_count
                                  if baseline_count and count is not None else None),
                "termination_reason": row.get("termination_reason") if row else "MISSING",
            }
    return result


def runtime_parts(row):
    total = number(row, "total_seconds")
    encode = number(row, "encode_seconds")
    solve = number(row, "solve_seconds")
    if total is None or encode is None or solve is None or min(total, encode, solve) < 0:
        return None
    residual = total - encode - solve
    if residual < -max(0.01, total * 0.01):
        return None
    return encode, solve, max(0, residual), row.get("termination_reason") != "COMPLETED"


def status_category(row):
    if row is None:
        return STATUS_CATEGORIES[3]
    value = integer(row, "best_value")
    if row.get("proven_optimal") == "True" and row.get("solution_status") == "OPTIMAL" and value is not None:
        return STATUS_CATEGORIES[0]
    if value is not None and value > 0 and row.get("solution_source") in ("SOLVER", "FALLBACK", "CHECKPOINT"):
        return STATUS_CATEGORIES[1]
    if row.get("termination_reason") in ("ERROR", "INTERRUPTED"):
        return STATUS_CATEGORIES[3]
    if row.get("termination_reason"):
        return STATUS_CATEGORIES[2]
    return STATUS_CATEGORIES[3]


def reference_values(rows):
    references = {}
    for row in rows:
        value = integer(row, "best_value")
        if value is None or value <= 0 or row.get("solution_source") not in ("SOLVER", "FALLBACK", "CHECKPOINT"):
            continue
        instance = row["instance"]
        previous = references.get(instance)
        certified = row.get("proven_optimal") == "True" and row.get("solution_status") == "OPTIMAL"
        if previous is None or value > previous["value"] or value == previous["value"] and certified and not previous["certified"]:
            references[instance] = {"value": value, "source": row["method"], "certified": certified}
    for row in rows:
        if row.get("proven_optimal") == "True" and row.get("solution_status") == "OPTIMAL":
            certified_value = integer(row, "best_value")
            ref = references.get(row["instance"])
            if ref and certified_value != ref["value"]:
                raise ValueError(f"certified optimum conflicts with best-known value: {row['instance']}")
    return references


def save(benchmark, fig, name):
    fig.savefig(benchmark.output / f"{name}.svg", bbox_inches="tight")
    fig.savefig(benchmark.output / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def axis_instances(ax, benchmark):
    ax.set_xticks(range(len(benchmark.instances)), benchmark.instances, rotation=70, ha="right", fontsize=8)
    ax.set_xlim(-0.6, len(benchmark.instances) - 0.4)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)


def mark_missing(ax, x, label="–"):
    ax.text(x, 0.02, label, transform=ax.get_xaxis_transform(), ha="center", va="bottom",
            fontsize=8, color="#666666", rotation=90)


def write_table(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plot_cnf(benchmark, compared):
    width = 0.25
    positions = np.arange(len(benchmark.instances))
    totals = [item["primary"] + item["auxiliary"] for item in compared.values()
              if item["primary"] is not None and item["auxiliary"] is not None]
    split_variables = bool(totals and min(totals) > 0 and max(totals) / min(totals) >= 1000)
    for metric, name, title, ylabel in (
        ("clauses", "clause_count_comparison", "CNF clause counts at shared pilot threshold", "Clauses before preprocessing"),
        ("variables", "variable_count_comparison", "CNF variable counts at shared pilot threshold", "Boolean variables before preprocessing"),
    ):
        if metric == "variables" and split_variables:
            fig, axes = plt.subplots(2, 1, figsize=(max(14, len(positions) * 0.65), 9), sharex=True)
        else:
            fig, ax = plt.subplots(figsize=(max(14, len(positions) * 0.65), 6))
            axes = [ax]
        for j, method in enumerate(SAT):
            xs = positions + (j - 1) * width
            for i, instance in enumerate(benchmark.instances):
                item = compared[(instance, method)]
                if metric == "clauses":
                    count = item["clauses"]
                    if count is not None and count > 0:
                        axes[0].bar(xs[i], count, width, color=COLORS[method],
                               label=LABELS[method] if i == 0 else None)
                    else:
                        mark_missing(axes[0], xs[i])
                else:
                    primary, auxiliary = item["primary"], item["auxiliary"]
                    if primary is not None and auxiliary is not None and primary + auxiliary > 0:
                        axes[0].bar(xs[i], primary, width, color=COLORS[method])
                        if split_variables:
                            if auxiliary:
                                axes[1].bar(xs[i], auxiliary, width, color=COLORS[method], hatch="///")
                            else:
                                mark_missing(axes[1], xs[i], "0")
                        elif auxiliary:
                            axes[0].bar(xs[i], auxiliary, width, bottom=primary, color=COLORS[method],
                                        hatch="///", edgecolor="white", linewidth=0.3)
                    else:
                        for panel in axes:
                            mark_missing(panel, xs[i])
        for panel in axes:
            axis_instances(panel, benchmark)
        axes[0].set(title=title, ylabel=ylabel if len(axes) == 1 else "Primary variables")
        axes[-1].set_xlabel("Benchmark instances (ascending vertices)")
        available = any(item["clauses"] is not None for item in compared.values()) if metric == "clauses" else bool(totals)
        if not available:
            axes[0].text(0.5, 0.55, "No fixed-threshold CNF measurements yet",
                         transform=axes[0].transAxes, ha="center", va="center", fontsize=12)
        if metric == "clauses":
            axes[0].set_yscale("log")
        elif split_variables:
            axes[0].set_yscale("log")
            axes[1].set_yscale("log")
            axes[1].set_ylabel("Auxiliary variables")
            axes[0].set_title(title + " (separate logarithmic panels)")
        handles = [Patch(facecolor=COLORS[m], label=LABELS[m]) for m in SAT]
        if metric == "variables":
            handles += [Patch(facecolor="#888888", label="Primary"),
                        Patch(facecolor="#888888", hatch="///", label="Auxiliary")]
        handles.append(Patch(facecolor="none", edgecolor="none", label="– unavailable"))
        axes[0].legend(handles=handles, ncol=3, fontsize=8, loc="upper left")
        fig.tight_layout()
        save(benchmark, fig, name)
    write_table(benchmark.directory / "cnf_comparison.csv",
                ["instance", "threshold", "method", "clauses", "primary_variables",
                 "auxiliary_variables", "reduction_vs_pairwise_pct", "termination_reason"],
                [{"instance": instance, "threshold": item["threshold"], "method": method,
                  "clauses": item["clauses"], "primary_variables": item["primary"],
                  "auxiliary_variables": item["auxiliary"],
                  "reduction_vs_pairwise_pct": item["reduction_pct"],
                  "termination_reason": item["termination_reason"]}
                 for instance in benchmark.instances for method in SAT
                 for item in [compared[(instance, method)]]])


def plot_runtime_breakdown(benchmark):
    rows = {(instance, method): runtime_parts(benchmark.opt.get((instance, method)))
            for instance in benchmark.instances for method in SAT}
    positive = [part for values in rows.values() if values for part in values[:3] if part > 0]
    wide = bool(positive and max(positive) / min(positive) >= 1000)
    components = [("Construction", "#0072B2"), ("SAT solving", "#D55E00"),
                  ("Unattributed / unmeasured", "#999999")]
    if wide:
        fig, axes = plt.subplots(3, 1, figsize=(max(14, len(benchmark.instances) * 0.65), 12), sharex=True)
    else:
        fig, ax = plt.subplots(figsize=(max(14, len(benchmark.instances) * 0.65), 6))
        axes = [ax]
    width = 0.25
    for j, method in enumerate(SAT):
        for i, instance in enumerate(benchmark.instances):
            x = i + (j - 1) * width
            parts = rows[(instance, method)]
            if parts is None:
                mark_missing(axes[-1], x)
                continue
            bottom = 0
            for k, (label, color) in enumerate(components):
                value = parts[k]
                if value <= 0:
                    continue
                ax = axes[k] if wide else axes[0]
                bar = ax.bar(x, value, width, bottom=0 if wide else bottom,
                             color=color, edgecolor=COLORS[method], linewidth=0.7,
                             hatch="//" if parts[3] else None)
                if not wide:
                    bottom += value
                if parts[3] and k == 2:
                    ax.annotate("†", (x, (value if wide else bottom)), ha="center", va="bottom", fontsize=8)
    for k, ax in enumerate(axes):
        ax.set_ylabel("Wall-clock seconds" if not wide else components[k][0] + " (s)")
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
        if wide:
            ax.set_yscale("log")
            ax.set_ylim(bottom=max(min(positive) / 2, 1e-6) if positive else 1e-6)
    axis_instances(axes[-1], benchmark)
    axes[-1].set_xlabel("Benchmark instances (ascending vertices)")
    axes[0].set_title("SAT optimization runtime composition" + (" (separate logarithmic panels)" if wide else ""))
    legend = [Patch(facecolor=color, label=label) for label, color in components]
    legend += [Patch(facecolor="white", edgecolor=COLORS[m], label=LABELS[m]) for m in SAT]
    legend.append(Patch(facecolor="white", hatch="//", label="Incomplete; † residual may include unfinished work"))
    axes[0].legend(handles=legend, fontsize=7, ncol=3)
    fig.tight_layout()
    save(benchmark, fig, "runtime_breakdown")
    write_table(benchmark.directory / "runtime_breakdown.csv",
                ["instance", "method", "construction_seconds", "solving_seconds",
                 "unattributed_seconds", "incomplete", "total_seconds"],
                [{"instance": instance, "method": method,
                  "construction_seconds": parts[0] if parts else None,
                  "solving_seconds": parts[1] if parts else None,
                  "unattributed_seconds": parts[2] if parts else None,
                  "incomplete": parts[3] if parts else None,
                  "total_seconds": number(benchmark.opt.get((instance, method)), "total_seconds")}
                 for instance in benchmark.instances for method in SAT
                 for parts in [rows[(instance, method)]]])


def plot_memory(benchmark):
    fig, ax = plt.subplots(figsize=(max(14, len(benchmark.instances) * 0.7), 6))
    width = 0.11
    values = []
    for j, method in enumerate(METHODS):
        for i, instance in enumerate(benchmark.instances):
            x = i + (j - 3) * width
            row = benchmark.opt.get((instance, method))
            value = number(row, "peak_memory_mb")
            if value is None or value <= 0:
                mark_missing(ax, x)
                continue
            values.append(value)
            ax.bar(x, value, width, color=COLORS[method],
                   hatch="xx" if row.get("termination_reason") == "MEMORY_LIMIT" else None)
            if row.get("termination_reason") == "MEMORY_LIMIT":
                ax.plot(x, value, marker="X", color="black", markersize=5)
    limit = number(benchmark.metadata.get("config", {}), "memory_mb")
    if limit and limit > 0:
        ax.axhline(limit, color="black", linestyle="--", linewidth=1, label=f"Memory limit ({limit:g} MB)")
    if values and max(values) / min(values) >= 100:
        ax.set_yscale("log")
    axis_instances(ax, benchmark)
    ax.set(title="Peak worker-plus-child resident memory", xlabel="Benchmark instances (ascending vertices)",
           ylabel="Peak observed RSS (MB)")
    handles = [Patch(facecolor=COLORS[m], label=LABELS[m]) for m in METHODS]
    handles.append(Patch(facecolor="white", hatch="xx", label="Memory limit"))
    ax.legend(handles=handles, ncol=4, fontsize=8)
    fig.tight_layout()
    save(benchmark, fig, "peak_memory_comparison")


def heatmap(benchmark, values, annotations, title, color_label, filename, *, log=False,
            minimum=None, maximum=None, cmap="viridis"):
    matrix = np.array(values, dtype=float)
    finite = matrix[np.isfinite(matrix)]
    if log:
        low = max(float(min(finite)), 1e-6) if finite.size else 1
        high = max(float(max(finite)), low * 1.01) if finite.size else 10
        norm = LogNorm(vmin=low, vmax=high)
    else:
        norm = Normalize(vmin=minimum, vmax=maximum)
    fig, ax = plt.subplots(figsize=(max(16, len(benchmark.instances) * 0.72), 6))
    palette = plt.get_cmap(cmap).with_extremes(bad="#eeeeee")
    image = ax.imshow(np.ma.masked_invalid(matrix), aspect="auto", cmap=palette, norm=norm)
    ax.set_xticks(range(len(benchmark.instances)), benchmark.instances, rotation=70, ha="right", fontsize=8)
    ax.set_yticks(range(len(METHODS)), [LABELS[m] for m in METHODS])
    ax.set(title=title, xlabel="Benchmark instances (ascending vertices)")
    ax.set_xticks(np.arange(-0.5, len(benchmark.instances), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(METHODS), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.8)
    ax.tick_params(which="minor", bottom=False, left=False)
    for y, line in enumerate(annotations):
        for x, label in enumerate(line):
            if label:
                color = "white" if math.isfinite(matrix[y, x]) and norm(matrix[y, x]) > 0.58 else "black"
                ax.text(x, y, label, ha="center", va="center", fontsize=6.5, color=color)
    fig.colorbar(image, ax=ax, label=color_label, pad=0.01)
    fig.tight_layout()
    save(benchmark, fig, filename)


def plot_runtime_heatmap(benchmark):
    values, labels = [], []
    for method in METHODS:
        values.append([])
        labels.append([])
        for instance in benchmark.instances:
            row = benchmark.opt.get((instance, method))
            runtime = number(row, "total_seconds")
            if runtime is None or runtime <= 0:
                values[-1].append(math.nan)
                labels[-1].append("–" if row is None else "E")
                continue
            values[-1].append(runtime)
            reason = row.get("termination_reason")
            suffix = ("*" if status_category(row) == "Feasible but uncertified" else "")
            suffix += STOP_CODES.get(reason, "")
            labels[-1].append(f"{runtime:.2g}{suffix}")
    heatmap(benchmark, values, labels, "End-to-end optimization runtime (* feasible, uncertified; T/M/C/E/I stop reason)",
            "Observed wall-clock seconds", "optimization_runtime_heatmap", log=True)


def plot_cactus(benchmark):
    fig, ax = plt.subplots(figsize=(9, 5.5))
    any_certified = False
    for method in METHODS:
        times = sorted(time for instance in benchmark.instances
                       for row in [benchmark.opt.get((instance, method))]
                       for time in [number(row, "total_seconds")]
                       if row and row.get("proven_optimal") == "True" and row.get("solution_status") == "OPTIMAL"
                       and time is not None and time > 0)
        if times:
            any_certified = True
            ax.plot(range(1, len(times) + 1), times, marker="o", markersize=3,
                    color=COLORS[method], label=f"{LABELS[method]} ({len(times)})")
        else:
            ax.plot([], [], color=COLORS[method], label=f"{LABELS[method]} (0)")
    limit = number(benchmark.metadata.get("config", {}), "time_limit")
    if limit and limit > 0:
        ax.axhline(limit, color="black", linestyle="--", linewidth=1, label=f"Timeout ({limit:g} s)")
    ax.set(xlim=(0, len(benchmark.instances)), xticks=range(0, len(benchmark.instances) + 1, max(1, len(benchmark.instances) // 12)),
           xlabel="Instances certified optimal", ylabel="End-to-end wall-clock seconds",
           title="Optimality certification cactus plot")
    ax.set_yscale("log")
    if not any_certified:
        if not limit:
            ax.set_ylim(1, 10)
        ax.text(0.5, 0.55, "No certified optimal runs yet", transform=ax.transAxes,
                ha="center", va="center")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    save(benchmark, fig, "optimality_cactus_plot")


def plot_quality(benchmark):
    references = reference_values(benchmark.optimization)
    values, labels, rows = [], [], []
    for method in METHODS:
        values.append([])
        labels.append([])
        for instance in benchmark.instances:
            row = benchmark.opt.get((instance, method))
            ref = references.get(instance)
            found = integer(row, "best_value")
            source = row.get("solution_source") if row else None
            gap = 100 * (ref["value"] - found) / ref["value"] if ref and ref["value"] > 0 and found is not None and found > 0 else None
            if gap is not None and gap < 0:
                raise ValueError(f"negative gap requires reference validation: {instance}, {method}")
            values[-1].append(gap if gap is not None else math.nan)
            labels[-1].append((f"{gap:.0f}%" + ("f" if source == "FALLBACK" else "")) if gap is not None else "–")
            rows.append({"instance": instance, "method": method,
                         "reference_value": ref["value"] if ref else None,
                         "reference_method": ref["source"] if ref else None,
                         "reference_certified_optimal": ref["certified"] if ref else None,
                         "found_value": found, "solution_source": source,
                         "best_known_gap_pct": gap})
    finite = [v for line in values for v in line if math.isfinite(v)]
    heatmap(benchmark, values, labels, "Best-known solution gap (f = verified fallback; 0% is not proof)",
            "Gap against run best-known (%)", "relative_solution_gap_heatmap",
            minimum=0, maximum=max(finite + [1]), cmap="magma_r")
    write_table(benchmark.directory / "best_known_solution_gaps.csv",
                ["instance", "method", "reference_value", "reference_method",
                 "reference_certified_optimal", "found_value", "solution_source", "best_known_gap_pct"], rows)


def plot_status(benchmark):
    fig, ax = plt.subplots(figsize=(11, 5))
    counts = []
    for method in METHODS:
        categories = [status_category(benchmark.opt.get((instance, method))) for instance in benchmark.instances]
        counts.append([categories.count(category) for category in STATUS_CATEGORIES])
    for i, method in enumerate(METHODS):
        offset = 0
        for j, category in enumerate(STATUS_CATEGORIES):
            count = counts[i][j]
            ax.barh(i, count, left=offset, color=STATUS_COLORS[j], label=category if i == 0 else None)
            if count >= 2:
                ax.text(offset + count / 2, i, str(count), ha="center", va="center", fontsize=9)
            offset += count
    ax.set_yticks(range(len(METHODS)), [LABELS[m] for m in METHODS])
    ax.invert_yaxis()
    ax.set(xlim=(0, len(benchmark.instances)), xlabel="Benchmark instances",
           title="Optimality certification and solution status")
    ax.legend(ncol=2, fontsize=8, loc="lower right")
    fig.tight_layout()
    save(benchmark, fig, "solution_status_comparison")
    write_table(benchmark.directory / "solution_status_counts.csv",
                ["method", *STATUS_CATEGORIES],
                [dict(zip(["method", *STATUS_CATEGORIES], [method, *count]))
                 for method, count in zip(METHODS, counts)])


def generate(directory):
    benchmark = Benchmark(directory)
    compared = fixed_comparison(benchmark)
    plot_cnf(benchmark, compared)
    plot_runtime_breakdown(benchmark)
    plot_memory(benchmark)
    plot_runtime_heatmap(benchmark)
    plot_cactus(benchmark)
    plot_quality(benchmark)
    plot_status(benchmark)
    from .extra import generate_saved_figures
    from .supplement_plots import generate_supplemental_figures
    generate_saved_figures(benchmark)
    generate_supplemental_figures(benchmark)
    return benchmark.output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    print(generate(parser.parse_args().results))
