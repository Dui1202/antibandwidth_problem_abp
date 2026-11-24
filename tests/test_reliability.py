from copy import deepcopy

import pytest

from abp.checkpoint import read_checkpoint, write_checkpoint
from abp.experiment import EXACT_SOLVERS, run_exact_optimization, run_sat_optimization
from abp.graph import Graph
from abp.solving.result import (Result, Status, Termination, bound_metrics,
                                checked_result, integer_upper_bound)
from experiments.run import recover_worker


def test_bound_metrics_use_verified_integer_bounds():
    assert bound_metrics(2, 3, 4)["absolute_gap"] == 1
    assert bound_metrics(2, 3, 4)["relative_gap"] == pytest.approx(1 / 3)
    assert bound_metrics(3, 3, 4)["proven_optimal"] is True
    with pytest.raises(ValueError):
        bound_metrics(3, 2, 4)
    assert integer_upper_bound(2.00000001, 5) == 2
    assert integer_upper_bound(0, 5) is None
    assert integer_upper_bound(float("inf"), 5) is None


def test_checkpoint_is_atomic_and_bound_to_workload(tmp_path):
    graph = Graph(4, [(0, 1)])
    identity = {"run": "one", "instance": "path", "method": "pairwise", "workload": "optimization"}
    path = tmp_path / "checkpoint.json"
    state = {"labeling": {0: 1, 1: 4, 2: 2, 3: 3}, "lower_bound": 3,
             "upper_bound": 3, "trials": []}
    write_checkpoint(path, identity, state)
    assert read_checkpoint(path, identity, graph)["lower_bound"] == 3
    assert read_checkpoint(path, {**identity, "method": "scl"}, graph) is None
    assert read_checkpoint(path, identity, Graph(4, [(0, 1), (1, 2)])) is None
    path.write_text('{bad json')
    assert read_checkpoint(path, identity, graph) is None


def test_invalid_solver_labeling_is_error_not_feasible():
    graph = Graph(3, [(0, 1)])
    result = checked_result(graph, Status.FEASIBLE, {0: 1, 1: 1, 2: 3})
    assert result.status == Status.UNKNOWN
    assert result.termination == Termination.ERROR


def test_feasible_solver_objective_may_have_slack():
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    labeling = {0: 2, 1: 4, 2: 1, 3: 3}
    feasible = checked_result(graph, Status.FEASIBLE, labeling, reported_objective=1)
    assert feasible.status == Status.FEASIBLE
    assert feasible.objective == 2
    assert feasible.reported_objective == 1
    assert checked_result(graph, Status.FEASIBLE, labeling,
                          reported_objective=3).termination == Termination.ERROR
    assert checked_result(graph, Status.OPTIMAL, labeling,
                          reported_objective=1).termination == Termination.ERROR


def test_exact_summary_keeps_reported_and_validated_objectives(monkeypatch):
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    labeling = {0: 2, 1: 4, 2: 1, 3: 3}
    monkeypatch.setitem(EXACT_SOLVERS, "cp_sat", lambda graph, timeout, progress=None:
                        checked_result(graph, Status.FEASIBLE, labeling,
                                       reported_objective=1, upper_bound=3))
    summary = run_exact_optimization(graph, "cp_sat", 1)
    assert summary["solver_reported_objective"] == 1
    assert summary["solver_best_value"] == summary["best_value"] == 2


def test_forced_worker_recovery_preserves_sat_incumbent_and_trials(tmp_path):
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    shots = []
    run_sat_optimization(graph, "pairwise", 5, 100_000,
                         checkpoint=lambda state: shots.append(deepcopy(state)))
    state = next(s for s in shots if s["lower_bound"] == 2 and s["upper_bound"] == 3
                 and len(s["trials"]) == 1)
    identity = {"run": "one", "instance": "path", "method": "pairwise"}
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, identity, state)
    recovered = recover_worker({"workload": "optimization", "checkpoint_path": str(path),
                                "identity": identity}, graph, Termination.MEMORY_LIMIT, 2.0, 50.0)
    summary = recovered["summary"]
    assert summary["best_value"] == 2
    assert summary["solver_best_value"] == 2
    assert summary["solution_source"] == "CHECKPOINT"
    assert summary["termination_reason"] == "MEMORY_LIMIT"
    assert summary["lower_bound"] == 2 and summary["upper_bound"] == 3
    assert len(recovered["trials"]) == 1
    assert summary["proven_optimal"] is False


def test_all_exact_methods_keep_backend_error_and_same_fallback(monkeypatch):
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    for method in EXACT_SOLVERS:
        monkeypatch.setitem(EXACT_SOLVERS, method,
                            lambda graph, timeout, progress=None:
                            Result(Status.UNKNOWN, error="backend failure",
                                   termination=Termination.ERROR))
        summary = run_exact_optimization(graph, method, 1)
        assert summary["fallback_value"] == summary["best_value"] == 1
        assert summary["solver_best_value"] is None
        assert summary["solution_source"] == "FALLBACK"
        assert summary["solution_status"] == "UNKNOWN"
        assert summary["termination_reason"] == "ERROR"


def test_invalid_backend_labeling_never_becomes_solver_incumbent(monkeypatch):
    graph = Graph(4, [(0, 1)])
    monkeypatch.setitem(EXACT_SOLVERS, "cp_sat", lambda graph, timeout, progress=None:
                        checked_result(graph, Status.FEASIBLE, {0: 1, 1: 1, 2: 3, 3: 4}))
    summary = run_exact_optimization(graph, "cp_sat", 1)
    assert summary["has_solver_incumbent"] is False
    assert summary["solution_source"] == "FALLBACK"
    assert summary["termination_reason"] == "ERROR"


def test_sat_lower_bound_uses_actual_verified_objective(monkeypatch):
    graph = Graph(5, [(0, 1)])
    labeling = {0: 1, 1: 5, 2: 2, 3: 3, 4: 4}
    def decision(graph, threshold, method, remaining, limit, amo):
        assert threshold == 2
        return {"threshold": threshold, "solution_status": "FEASIBLE",
                "termination_reason": "COMPLETED", "best_value": 4,
                "labeling": labeling, "n_primary_vars": 1, "n_aux_vars": 0,
                "n_clauses": 1, "encode_seconds": 0.01, "solve_seconds": 0.01,
                "error": None}
    monkeypatch.setattr("abp.experiment.run_sat_decision", decision)
    summary, trials = run_sat_optimization(graph, "pairwise", 5, 100)
    assert len(trials) == 1
    assert summary["lower_bound"] == summary["upper_bound"] == 4
    assert summary["solution_status"] == "OPTIMAL"


def test_unresolved_sat_decision_does_not_tighten_bounds(monkeypatch):
    graph = Graph(5, [(0, 1)])
    monkeypatch.setattr("abp.experiment.run_sat_decision", lambda *args:
                        {"threshold": 2, "solution_status": "UNKNOWN",
                         "termination_reason": "CLAUSE_LIMIT", "error": "too many clauses",
                         "n_primary_vars": None, "n_aux_vars": None, "n_clauses": None,
                         "encode_seconds": 0, "solve_seconds": 0, "labeling": None})
    summary, _ = run_sat_optimization(graph, "pairwise", 5, 10)
    assert summary["lower_bound"] == 1 and summary["upper_bound"] == 4
    assert summary["termination_reason"] == "CLAUSE_LIMIT"
    assert summary["proven_optimal"] is False


@pytest.mark.parametrize("reason", [Termination.TIME_LIMIT, Termination.MEMORY_LIMIT,
                                     Termination.UNKNOWN])
def test_exact_stop_with_valid_incumbent_retains_reason(monkeypatch, reason):
    graph = Graph(4, [(0, 1), (1, 2), (2, 3)])
    labeling = {0: 2, 1: 4, 2: 1, 3: 3}
    monkeypatch.setitem(EXACT_SOLVERS, "cp_sat", lambda graph, timeout, progress=None:
                        Result(Status.FEASIBLE, 2, labeling, termination=reason,
                               raw_status="backend_feasible", upper_bound=3))
    summary = run_exact_optimization(graph, "cp_sat", 1)
    assert summary["solution_status"] == "FEASIBLE"
    assert summary["termination_reason"] == reason.value
    assert summary["raw_status"] == "backend_feasible"
    assert summary["solver_best_value"] == 2
    assert summary["absolute_gap"] == 1
    assert summary["relative_gap"] == pytest.approx(1 / 3)
