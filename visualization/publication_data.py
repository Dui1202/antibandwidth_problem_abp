"""Validated data selections for the publication figures."""

from collections import Counter
import math

from .generate import (METHODS, SAT, STATUS_CATEGORIES, integer, number,
                       reference_values, status_category, valid_cnf)


AMOS = ("pairwise", "sequential")
FIXED_OUTCOMES = ("SAT", "UNSAT", "CLAUSE_LIMIT", "TIME_LIMIT", "MEMORY_LIMIT",
                  "ERROR", "INTERRUPTED", "UNKNOWN")
OPT_OUTCOMES = STATUS_CATEGORIES


def fixed_rows(benchmark, *, require_complete=False):
    """Index fixed runs by graph, threshold offset, distance encoding, and AMO."""
    rows = {}
    for row in benchmark.fixed:
        instance = row.get("instance")
        base = benchmark.thresholds.get(instance)
        threshold = integer(row, "threshold")
        method, amo = row.get("method"), row.get("assignment_amo")
        if base is None or threshold is None or method not in SAT or amo not in AMOS:
            raise ValueError(f"Invalid fixed-run key: {instance}, {method}, {amo}, {threshold}")
        key = (instance, threshold - base, method, amo)
        if key in rows:
            raise ValueError(f"Duplicate fixed run: {key}")
        rows[key] = row
    if require_complete:
        expected = {(instance, offset, method, amo)
                    for instance in benchmark.instances for offset in (0, 1)
                    for method in SAT for amo in AMOS}
        if rows.keys() != expected:
            raise ValueError(f"Fixed workload coverage: {len(rows)} of {len(expected)} runs; "
                             f"missing={len(expected - rows.keys())}, extra={len(rows.keys() - expected)}")
    return rows


def fixed_outcome(row):
    reason = row.get("termination_reason") if row else "UNKNOWN"
    if reason == "COMPLETED":
        return row["raw_status"] if row.get("raw_status") in ("SAT", "UNSAT") else "UNKNOWN"
    return reason or "UNKNOWN"


def amo_observations(rows):
    """Return matched clause reductions and completed runtime ratios."""
    clauses, runtimes = [], []
    for (instance, offset, method, amo), pair in rows.items():
        if amo != "pairwise":
            continue
        seq = rows.get((instance, offset, method, "sequential"))
        if seq is None:
            continue
        pair_clauses, seq_clauses = integer(pair, "n_clauses"), integer(seq, "n_clauses")
        if valid_cnf(pair) and valid_cnf(seq) and pair_clauses > 0:
            clauses.append({"instance": instance, "offset": offset, "method": method,
                            "reduction_pct": 100 * (pair_clauses - seq_clauses) / pair_clauses})
        pair_time, seq_time = number(pair, "total_seconds"), number(seq, "total_seconds")
        if (fixed_outcome(pair) in ("SAT", "UNSAT")
                and fixed_outcome(pair) == fixed_outcome(seq)
                and pair_time is not None and seq_time is not None
                and pair_time > 0 and seq_time > 0):
            runtimes.append({"instance": instance, "offset": offset, "method": method,
                             "speedup": pair_time / seq_time})
    return clauses, runtimes


def fixed_counts(rows):
    counts = {(method, amo): Counter() for method in SAT for amo in AMOS}
    for (_, _, method, amo), row in rows.items():
        counts[(method, amo)][fixed_outcome(row)] += 1
    return counts


def optimization_outcome(row):
    return status_category(row)


def optimization_gaps(benchmark):
    """Return best-observed and bound gaps as percentages, preserving provenance."""
    references = reference_values(benchmark.optimization)
    result = {}
    for instance in benchmark.instances:
        reference = references.get(instance)
        for method in METHODS:
            row = benchmark.opt.get((instance, method))
            lower, upper, stored = (number(row, field) for field in
                                    ("lower_bound", "upper_bound", "relative_gap"))
            source = row.get("solution_source") if row else None
            best = (100 * (reference["value"] - lower) / reference["value"]
                    if reference and lower is not None and 0 < lower <= reference["value"] else math.nan)
            if lower is not None and upper is not None and upper > 0 and stored is not None:
                computed = (upper - lower) / upper
                if lower < 0 or upper < lower or not math.isclose(stored, computed, abs_tol=1e-8):
                    raise ValueError(f"Inconsistent relative gap: {instance}, {method}")
                relative = 100 * stored
            else:
                relative = math.nan
            result[(instance, method)] = {
                "best_known_gap_pct": best, "relative_optimality_gap_pct": relative,
                "certified": optimization_outcome(row) == OPT_OUTCOMES[0],
                "fallback_only": optimization_outcome(row) == OPT_OUTCOMES[2],
                "reference_certified": bool(reference and reference["certified"]),
                "source": source,
            }
    return result
