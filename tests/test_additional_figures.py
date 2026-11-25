import csv
import json

from visualization.extra import density, speedup_rows, spearman_report
from visualization.supplement import decision_with_stats, select_instances, nearby_thresholds


def test_density_and_size_selection():
    assert density(4, 3) == 0.5
    instances = [str(i) for i in range(24)]
    assert select_instances(instances) == ["5", "11", "17"]
    assert nearby_thresholds(2, 6) == [1, 2, 3, 4, 5]
    assert nearby_thresholds(5, 6) == [1, 2, 3, 4, 5]


def test_speedup_distinguishes_exact_and_censored_baseline(tmp_path):
    from visualization.generate import Benchmark
    (tmp_path / "metadata.json").write_text(json.dumps({"schema_version": 3, "config": {"time_limit": 10}}))
    (tmp_path / "manifest.csv").write_text("instance,n_vertices,n_edges\na,4,3\nb,5,4\nc,6,5\n")
    rows = [
        ["a", "pairwise", "10", "True", "OPTIMAL", "COMPLETED"],
        ["a", "order", "2", "True", "OPTIMAL", "COMPLETED"],
        ["b", "pairwise", "10", "False", "FEASIBLE", "TIME_LIMIT"],
        ["b", "order", "2", "True", "OPTIMAL", "COMPLETED"],
        ["c", "pairwise", "10", "False", "FEASIBLE", "TIME_LIMIT"],
        ["c", "order", "10", "False", "FEASIBLE", "TIME_LIMIT"],
    ]
    with (tmp_path / "optimization.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["instance", "method", "total_seconds", "proven_optimal", "solution_status", "termination_reason"])
        writer.writerows(rows)
    compared = speedup_rows(Benchmark(tmp_path))
    assert compared[("a", "order")]["kind"] == "exact"
    assert compared[("a", "order")]["speedup"] == 5
    assert compared[("b", "order")]["kind"] == "lower_bound"
    assert compared[("c", "order")]["kind"] == "excluded"


def test_spearman_reports_insufficient_and_ranked_samples():
    assert spearman_report([(1, 2), (2, 3)])["reason"] == "fewer than five completed observations"
    report = spearman_report([(i, i * i) for i in range(1, 6)])
    assert report["rho"] == 1
    assert report["n"] == 5


def test_fresh_sat_decisions_record_available_solver_counters():
    from abp.graph import Graph
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    for method in ("pairwise", "order", "scl"):
        feasible = decision_with_stats(graph, method, 2, 2, 10000)
        infeasible = decision_with_stats(graph, method, 3, 2, 10000)
        assert feasible["raw_status"] == "SAT"
        assert infeasible["raw_status"] == "UNSAT"
        assert all(isinstance(feasible[key], int) for key in ("conflicts", "decisions", "propagations", "restarts"))
