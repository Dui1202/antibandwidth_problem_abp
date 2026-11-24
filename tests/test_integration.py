from itertools import permutations

import pytest

from abp.graph import Graph
from abp.validation import validate_solution
from abp.encoding.order import encode_order
from abp.encoding.pairwise import encode_pairwise
from abp.encoding.staircase_scl import encode_staircase_scl
from abp.solving.sat import solve_sat, optimize_sat
from abp.solving.baselines import optimize_cp_sat, optimize_cp_optimizer, optimize_cplex, optimize_gurobi
from abp.solving.result import Status, Termination
from abp.solving.result import checked_result
from abp.solving.baselines import cp_optimizer_executable


CASES = [
    (Graph(4, [(0, 1)]), 3),
    (Graph(4, [(0, 1), (1, 2), (2, 3)]), 2),
    (Graph(4, [(u, v) for u in range(4) for v in range(u + 1, 4)]), 1),
]
ENCODERS = [encode_pairwise, encode_order, encode_staircase_scl]
BASELINES = [optimize_cp_sat, optimize_cp_optimizer, optimize_cplex, optimize_gurobi]


@pytest.mark.parametrize("graph,known_optimum", CASES)
def test_known_values_have_independent_permutation_proof(graph, known_optimum):
    assert max(min(abs(p[u] - p[v]) for u, v in graph.edges)
               for p in permutations(range(1, graph.n + 1))) == known_optimum


@pytest.mark.parametrize("graph,known_optimum", CASES)
@pytest.mark.parametrize("encoder", ENCODERS)
def test_sat_decisions_and_optimum(graph, known_optimum, encoder):
    for threshold in range(1, graph.n):
        result = solve_sat(graph, threshold, encoder, timeout_seconds=5)
        assert result.status == (Status.FEASIBLE if threshold <= known_optimum else Status.INFEASIBLE)
        if result.labeling is not None:
            assert result.objective == validate_solution(graph, result.labeling, threshold)
    result = optimize_sat(graph, encoder, timeout_seconds=5)
    assert result.status == Status.OPTIMAL
    assert result.objective == known_optimum
    assert validate_solution(graph, result.labeling) == known_optimum


@pytest.mark.parametrize("graph,known_optimum", CASES)
@pytest.mark.parametrize("baseline", BASELINES)
def test_exact_baselines(graph, known_optimum, baseline):
    result = baseline(graph, timeout_seconds=5)
    if baseline is optimize_gurobi and result.termination == Termination.ERROR and "HostID mismatch" in (result.error or ""):
        pytest.skip("Gurobi licensed HostID is unavailable inside sandbox")
    assert result.status == Status.OPTIMAL, result.error
    assert result.objective == known_optimum
    assert validate_solution(graph, result.labeling) == known_optimum


def test_cp_optimizer_discovery_does_not_depend_on_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert cp_optimizer_executable().is_file()
    monkeypatch.setenv("ABP_CP_OPTIMIZER", "/missing/cpoptimizer")
    with pytest.raises(FileNotFoundError):
        cp_optimizer_executable()


def test_invalid_incumbent_cannot_be_reported_as_optimal():
    graph = Graph(4, [(0, 1)])
    assert checked_result(graph, Status.OPTIMAL, {0: 1, 1: 2, 2: 3, 3: 4}).objective == 1
    assert checked_result(graph, Status.OPTIMAL, {0: 1, 1: 1, 2: 3, 3: 4}).termination == Termination.ERROR
    assert checked_result(graph, Status.OPTIMAL, {0: 1, 1: 4, 2: 2, 3: 3},
                          reported_objective=2).termination == Termination.ERROR


@pytest.mark.parametrize("baseline", [optimize_cp_sat, optimize_cp_optimizer,
                                     optimize_cplex, optimize_gurobi])
def test_zero_budget_is_timeout(baseline):
    assert baseline(CASES[0][0], timeout_seconds=0).termination == Termination.TIME_LIMIT
