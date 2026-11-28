"""Regression checks for selections and metrics in the paper figures."""

from collections import Counter
import math
from pathlib import Path
from statistics import median
from types import SimpleNamespace

import pytest

from visualization.generate import Benchmark, METHODS, SAT
from visualization.publication_data import (amo_observations, fixed_counts, fixed_outcome,
                                            fixed_rows, optimization_gaps, optimization_outcome)


RESULTS = Path(__file__).resolve().parents[1] / "results/benchmark_20261125T084243Z"


def test_complete_fixed_workload_and_matched_amo_statistics():
    benchmark = Benchmark(RESULTS)
    rows = fixed_rows(benchmark, require_complete=True)
    assert len(rows) == 24 * 2 * 3 * 2
    assert Counter(key[1] for key in rows) == {0: 144, 1: 144}
    assert Counter((key[2], key[3]) for key in rows) == {
        (method, amo): 48 for method in SAT for amo in ("pairwise", "sequential")}

    clauses, runtimes = amo_observations(rows)
    expected = {"pairwise": (24, 45.20246, 21, 0.88956),
                "order": (24, 69.19301, 24, 1.83464),
                "scl": (24, 73.03053, 24, 1.40715)}
    for method, (n_clauses, reduction, n_runtime, speedup) in expected.items():
        c = [row["reduction_pct"] for row in clauses if row["method"] == method]
        r = [row["speedup"] for row in runtimes if row["method"] == method]
        assert (len(c), len(r)) == (n_clauses, n_runtime)
        assert median(c) == pytest.approx(reduction, abs=0.00001)
        assert median(r) == pytest.approx(speedup, abs=0.00001)

    counts = fixed_counts(rows)
    assert sum(sum(count.values()) for count in counts.values()) == 288
    outcomes = sum(counts.values(), Counter())
    assert outcomes == {"SAT": 139, "UNSAT": 45, "CLAUSE_LIMIT": 96, "TIME_LIMIT": 8}


def test_amo_pairs_reject_mismatched_outcomes_and_incomplete_runs():
    def run(status, reason="COMPLETED", seconds="2", clauses="100"):
        return {"raw_status": status, "termination_reason": reason, "total_seconds": seconds,
                "n_clauses": clauses, "n_primary_vars": "4", "n_aux_vars": "4"}
    rows = {
        ("a", 0, "order", "pairwise"): run("SAT"),
        ("a", 0, "order", "sequential"): run("UNSAT", seconds="1", clauses="50"),
        ("a", 1, "order", "pairwise"): run("SAT", "TIME_LIMIT"),
        ("a", 1, "order", "sequential"): run("SAT", seconds="1", clauses="50"),
        ("b", 0, "order", "pairwise"): run("SAT", seconds="4"),
        ("b", 0, "order", "sequential"): run("SAT", seconds="2", clauses="50"),
    }
    clauses, runtimes = amo_observations(rows)
    assert len(clauses) == 3
    assert runtimes == [{"instance": "b", "offset": 0, "method": "order", "speedup": 2}]
    assert fixed_outcome(rows[("a", 1, "order", "pairwise")]) == "TIME_LIMIT"


def test_fallback_and_checkpoint_classification_uses_incumbent_provenance():
    base = {"best_value": "5", "solution_status": "FEASIBLE", "proven_optimal": "False"}
    assert optimization_outcome({**base, "solution_source": "FALLBACK",
                                 "has_solver_incumbent": "False"}) == "Fallback only"
    assert optimization_outcome({**base, "solution_source": "CHECKPOINT",
                                 "has_solver_incumbent": "True"}) == "Solver feasible"
    assert optimization_outcome({**base, "solution_source": "CHECKPOINT",
                                 "has_solver_incumbent": "False"}) == "Missing / invalid"


def test_gap_metrics_use_distinct_denominators_and_validate_recorded_units():
    rows = [{"instance": "g", "method": "pairwise", "best_value": "8", "lower_bound": "8",
             "upper_bound": "10", "relative_gap": "0.2", "solution_source": "SOLVER",
             "has_solver_incumbent": "True", "proven_optimal": "False", "solution_status": "FEASIBLE"},
            {"instance": "g", "method": "order", "best_value": "10", "lower_bound": "10",
             "upper_bound": "10", "relative_gap": "0", "solution_source": "SOLVER",
             "has_solver_incumbent": "True", "proven_optimal": "True", "solution_status": "OPTIMAL"}]
    benchmark = SimpleNamespace(instances=["g"], optimization=rows,
                                opt={(row["instance"], row["method"]): row for row in rows})
    gaps = optimization_gaps(benchmark)
    assert gaps[("g", "pairwise")]["best_known_gap_pct"] == 20
    assert gaps[("g", "pairwise")]["relative_optimality_gap_pct"] == 20
    assert gaps[("g", "order")]["certified"]
    rows[0]["relative_gap"] = "20"
    with pytest.raises(ValueError, match="Inconsistent relative gap"):
        optimization_gaps(benchmark)


def test_missing_measurements_remain_missing_and_small_gaps_are_not_rounded_to_zero():
    benchmark = SimpleNamespace(instances=["g"], optimization=[], opt={})
    gaps = optimization_gaps(benchmark)
    assert math.isnan(gaps[("g", "pairwise")]["best_known_gap_pct"])
    assert math.isnan(gaps[("g", "pairwise")]["relative_optimality_gap_pct"])
    from visualization.cnsplot_figures import gap_annotation
    assert gap_annotation(0.2, False, False) == "<1"
    assert gap_annotation(0, False, False) == "0"


def test_current_optimization_coverage_and_certification_counts():
    benchmark = Benchmark(RESULTS)
    assert len(benchmark.optimization) == 24 * 7
    expected = {"pairwise": (9, 15, 0), "order": (12, 12, 0), "scl": (10, 10, 4),
                "cp_sat": (8, 16, 0), "cp_optimizer": (8, 16, 0),
                "cplex": (3, 9, 12), "gurobi": (4, 18, 2)}
    for method in METHODS:
        counts = Counter(optimization_outcome(benchmark.opt[(instance, method)])
                         for instance in benchmark.instances)
        assert (counts["Proven optimal"], counts["Solver feasible"], counts["Fallback only"]) == expected[method]
