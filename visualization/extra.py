"""Additional empirical plots and statistics for the ABP benchmark."""

import math
from collections import defaultdict
from statistics import geometric_mean

import matplotlib.pyplot as plt

from .generate import (SAT, METHODS, COLORS, LABELS, Benchmark, integer, number,
                       read_csv, save, write_table)


def density(vertices, edges):
    return 2 * edges / (vertices * (vertices - 1)) if vertices and vertices > 1 and edges is not None else None


def certified(row):
    return bool(row and row.get("proven_optimal") == "True"
                and row.get("solution_status") == "OPTIMAL")


def speedup_rows(benchmark):
    result = {}
    for instance in benchmark.instances:
        base = benchmark.opt.get((instance, "pairwise"))
        base_time = number(base, "total_seconds")
        for method in ("order", "scl"):
            alt = benchmark.opt.get((instance, method))
            alt_time = number(alt, "total_seconds")
            kind = "excluded"
            reason = "missing or nonpositive runtime"
            ratio = None
            if base_time and base_time > 0 and alt_time and alt_time > 0:
                if certified(base) and certified(alt):
                    kind, reason, ratio = "exact", "", base_time / alt_time
                elif base.get("termination_reason") == "TIME_LIMIT" and certified(alt):
                    kind, reason, ratio = "lower_bound", "Pairwise timed out", base_time / alt_time
                else:
                    reason = "completion or certification criteria not met"
            result[(instance, method)] = {"kind": kind, "speedup": ratio, "reason": reason,
                                          "pairwise_seconds": base_time, "alternative_seconds": alt_time}
    return result


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    for start, index in enumerate(order):
        if result[index]:
            continue
        end = start + 1
        while end < len(values) and values[order[end]] == values[index]:
            end += 1
        rank = (start + 1 + end) / 2
        for i in range(start, end):
            result[order[i]] = rank
    return result


def spearman_report(pairs):
    n = len(pairs)
    report = {"n": n, "rho": None, "reason": ""}
    if n < 5:
        report["reason"] = "fewer than five completed observations"
        return report
    x, y = zip(*pairs)
    rx, ry = _ranks(x), _ranks(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    xx = sum((a - mx) ** 2 for a in rx)
    yy = sum((b - my) ** 2 for b in ry)
    if xx == 0 or yy == 0:
        report["reason"] = "constant values"
    else:
        report["rho"] = sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(xx * yy)
    return report


def plot_scalability(benchmark):
    manifest = {row["instance"]: row for row in read_csv(benchmark.directory / "manifest.csv")}
    fig, axes = plt.subplots(1, 3, figsize=(18, 5), sharey=True)
    fields = (("n_vertices", "Vertices"), ("n_edges", "Edges"), ("density", "Graph density"))
    observations = []
    for instance in benchmark.instances:
        vertices = integer(manifest[instance], "n_vertices")
        edges = integer(manifest[instance], "n_edges")
        for method in METHODS:
            row = benchmark.opt.get((instance, method))
            elapsed = number(row, "total_seconds")
            reason = row.get("termination_reason") if row else "MISSING"
            kind = "certified" if certified(row) else ("censored" if reason in ("TIME_LIMIT", "MEMORY_LIMIT", "CLAUSE_LIMIT") else "incomplete")
            observations.append({"instance": instance, "method": method, "vertices": vertices,
                                 "edges": edges, "density": density(vertices, edges),
                                 "runtime_seconds": elapsed, "kind": kind, "termination_reason": reason})
            if elapsed is None or elapsed <= 0:
                continue
            for ax, (field, _) in zip(axes, fields):
                value = observations[-1][{"n_vertices": "vertices", "n_edges": "edges", "density": "density"}[field]]
                if value is not None and value > 0:
                    marker = "o" if kind == "certified" else "v" if kind == "censored" else "x"
                    ax.scatter(value, elapsed, color=COLORS[method], marker=marker, s=35,
                               facecolors="none" if kind == "censored" else None, alpha=0.8)
    for ax, (field, label) in zip(axes, fields):
        ax.set(xlabel=label, yscale="log", title=label + " vs. observed runtime")
        ax.grid(alpha=0.2)
    axes[0].set_ylabel("End-to-end wall-clock seconds")
    handles = [plt.Line2D([], [], color=COLORS[m], marker="o", linestyle="", label=LABELS[m]) for m in METHODS]
    handles += [plt.Line2D([], [], color="black", marker="o", linestyle="", label="Certified"),
                plt.Line2D([], [], color="black", marker="v", linestyle="", fillstyle="none", label="Censored limit"),
                plt.Line2D([], [], color="black", marker="x", linestyle="", label="Other incomplete")]
    fig.legend(handles=handles, ncol=5, loc="upper center", fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    save(benchmark, fig, "scalability_analysis")
    write_table(benchmark.directory / "scalability_observations.csv",
                ["instance", "method", "vertices", "edges", "density", "runtime_seconds", "kind", "termination_reason"], observations)


def plot_clause_solving(benchmark):
    fig, ax = plt.subplots(figsize=(10, 6))
    pairs = defaultdict(list)
    exclusions = defaultdict(int)
    rows = []
    for row in benchmark.fixed:
        if row.get("method") not in SAT:
            continue
        method = row["method"]
        clause = integer(row, "n_clauses")
        seconds = number(row, "solve_seconds")
        outcome = row.get("raw_status")
        completed = row.get("termination_reason") == "COMPLETED" and outcome in ("SAT", "UNSAT")
        valid = (row.get("assignment_amo") == "sequential" and row.get("solver") == "g3"
                 and clause is not None and clause > 0 and seconds is not None and seconds > 0)
        exclusion = "" if valid and completed else ("missing or incompatible measurement" if not valid else "censored or incomplete")
        rows.append({"instance": row.get("instance"), "method": method, "threshold": row.get("threshold"),
                     "outcome": outcome, "clauses": clause, "solve_seconds": seconds,
                     "termination_reason": row.get("termination_reason"), "exclusion": exclusion})
        if not valid:
            exclusions[(method, outcome or "UNKNOWN")] += 1
            continue
        marker = "o" if outcome == "SAT" and completed else "s" if outcome == "UNSAT" and completed else "v"
        ax.scatter(clause, seconds, marker=marker, color=COLORS[method], s=40,
                   facecolors="none" if not completed else None)
        if completed:
            pairs[(method, outcome)].append((clause, seconds))
        else:
            exclusions[(method, outcome or "UNKNOWN")] += 1
    ax.set(xscale="log", yscale="log", xlabel="CNF clauses before preprocessing",
           ylabel="SAT solving time (s)", title="Clause count and SAT search time")
    if not ax.has_data():
        ax.set(xlim=(1, 10), ylim=(1e-6, 1))
        ax.text(0.5, 0.5, "No comparable fixed-threshold solving measurements yet",
                transform=ax.transAxes, ha="center", va="center")
    ax.grid(alpha=0.2)
    handles = [plt.Line2D([], [], color=COLORS[m], marker="o", linestyle="", label=LABELS[m]) for m in SAT]
    handles += [plt.Line2D([], [], color="black", marker="o", linestyle="", label="SAT"),
                plt.Line2D([], [], color="black", marker="s", linestyle="", label="UNSAT"),
                plt.Line2D([], [], color="black", marker="v", linestyle="", fillstyle="none", label="Censored / incomplete")]
    ax.legend(handles=handles, ncol=3, fontsize=8)
    fig.tight_layout()
    save(benchmark, fig, "clauses_vs_solving_time")
    write_table(benchmark.directory / "clause_time_observations.csv",
                ["instance", "method", "threshold", "outcome", "clauses", "solve_seconds",
                 "termination_reason", "exclusion"], rows)
    reports = []
    for method in SAT:
        for outcome in ("SAT", "UNSAT"):
            report = spearman_report(pairs[(method, outcome)])
            reports.append({"method": method, "outcome": outcome, **report,
                            "excluded": exclusions[(method, outcome)]})
    write_table(benchmark.directory / "clause_time_correlations.csv",
                ["method", "outcome", "n", "rho", "reason", "excluded"], reports)


def plot_speedup(benchmark):
    comparisons = speedup_rows(benchmark)
    fig, ax = plt.subplots(figsize=(max(14, len(benchmark.instances) * 0.65), 5.5))
    reports = []
    for method in ("order", "scl"):
        exact = []
        for i, instance in enumerate(benchmark.instances):
            item = comparisons[(instance, method)]
            x = i + (-0.12 if method == "order" else 0.12)
            if item["speedup"] is not None:
                ax.scatter(x, item["speedup"], marker="o" if item["kind"] == "exact" else "^",
                           color=COLORS[method], facecolors="none" if item["kind"] == "lower_bound" else None,
                           s=45)
                if item["kind"] == "exact":
                    exact.append(item["speedup"])
            else:
                ax.text(x, 0.02, "–", transform=ax.get_xaxis_transform(), ha="center", color="#777777")
        reports.append({"method": method, "geometric_mean_speedup": geometric_mean(exact) if exact else None,
                        "n_exact": len(exact), "excluded_or_censored": len(benchmark.instances) - len(exact)})
    ax.axhline(1, color="black", linestyle="--", linewidth=1)
    ax.set_yscale("log")
    if not any(item["speedup"] is not None for item in comparisons.values()):
        ax.set_ylim(0.1, 10)
        ax.text(0.5, 0.5, "No comparable certified speedups yet",
                transform=ax.transAxes, ha="center", va="center")
    ax.set_xticks(range(len(benchmark.instances)), benchmark.instances, rotation=70, ha="right", fontsize=8)
    ax.set(xlim=(-0.6, len(benchmark.instances) - 0.4), xlabel="Benchmark instances (ascending vertices)",
           ylabel="Pairwise runtime / alternative runtime", title="Optimization speedup over Pairwise")
    ax.grid(axis="y", alpha=0.2)
    handles = [plt.Line2D([], [], color=COLORS[m], marker="o", linestyle="", label=LABELS[m]) for m in ("order", "scl")]
    handles += [plt.Line2D([], [], color="black", marker="o", linestyle="", label="Exact: both certified"),
                plt.Line2D([], [], color="black", marker="^", linestyle="", fillstyle="none", label="Lower bound: Pairwise timeout")]
    ax.legend(handles=handles, ncol=2, fontsize=8)
    fig.tight_layout()
    save(benchmark, fig, "speedup_over_pairwise")
    write_table(benchmark.directory / "speedup_observations.csv",
                ["instance", "method", "kind", "speedup", "pairwise_seconds", "alternative_seconds", "reason"],
                [{"instance": instance, "method": method, **comparisons[(instance, method)]}
                 for instance in benchmark.instances for method in ("order", "scl")])
    write_table(benchmark.directory / "speedup_summary.csv",
                ["method", "geometric_mean_speedup", "n_exact", "excluded_or_censored"], reports)


def generate_saved_figures(benchmark):
    plot_scalability(benchmark)
    plot_clause_solving(benchmark)
    plot_speedup(benchmark)
