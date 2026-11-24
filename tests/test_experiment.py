from abp.experiment import run_sat_decision, run_sat_optimization, fallback_labeling
from abp.graph import Graph


def test_profiled_sat_decisions_match_known_optimum():
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    for method in ("pairwise", "order", "scl"):
        feasible = run_sat_decision(graph, 2, method, 5, 100000)
        impossible = run_sat_decision(graph, 3, method, 5, 100000)
        assert feasible["solution_status"] == "FEASIBLE"
        assert feasible["best_value"] >= 2
        assert impossible["solution_status"] == "INFEASIBLE"
        assert feasible["n_clauses"] > 0


def test_profiled_search_certifies_optimum_and_keeps_trials():
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    summary, trials = run_sat_optimization(graph, "scl", 5, 100000)
    assert summary["solution_status"] == "OPTIMAL"
    assert summary["best_value"] == 2
    assert summary["proven_optimal"] is True
    assert trials
    assert trials[0]["threshold"] == 2
    assert fallback_labeling(graph) == {0: 1, 1: 2, 2: 3, 3: 4}


def test_clause_cap_records_resource_limit():
    graph = Graph(5, [(0, 1)])
    trial = run_sat_decision(graph, 2, "pairwise", 5, 10)
    assert trial["solution_status"] == "UNKNOWN"
    assert trial["termination_reason"] == "CLAUSE_LIMIT"
