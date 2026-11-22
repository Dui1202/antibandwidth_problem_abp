"""Measured ABP trials; every feasible value comes from a checked labeling."""

from threading import Timer
from time import monotonic

from pysat.solvers import Solver

from .encoding.common import ClauseLimitError
from .encoding.order import encode_order
from .encoding.pairwise import encode_pairwise
from .encoding.staircase_scl import encode_staircase_scl
from .solving.baselines import (optimize_cp_optimizer, optimize_cp_sat,
                               optimize_cplex, optimize_gurobi)
from .validation import validate_solution


SAT_ENCODERS = {"pairwise": encode_pairwise, "order": encode_order, "scl": encode_staircase_scl}
EXACT_SOLVERS = {"cp_sat": optimize_cp_sat, "cp_optimizer": optimize_cp_optimizer,
                 "cplex": optimize_cplex, "gurobi": optimize_gurobi}


def fallback_labeling(graph) -> dict[int, int]:
    return {vertex: vertex + 1 for vertex in range(graph.n)}


def _minimum_clause_count(graph, threshold, method, assignment_amo):
    n = graph.n
    if method == "order":
        return (n * (n - 2) + n * n * (n - 1) // 2 + len(graph.edges) * n
                if assignment_amo == "pairwise" else 0)
    assignment = (n * n * (n - 1) + 2 * n if assignment_amo == "pairwise"
                  else 2 * n * (3 * n - 3))
    if method == "pairwise":
        assignment += len(graph.edges) * (n * (2 * threshold - 1) - threshold * (threshold - 1))
    return assignment


def run_sat_decision(graph, threshold: int, method: str, timeout_seconds: float,
                     max_clauses: int, assignment_amo: str = "sequential") -> dict:
    """Return one decision trial with separate construction and solver times."""
    if method not in SAT_ENCODERS:
        raise ValueError(f"unknown SAT method: {method}")
    started = monotonic()
    trial = {"threshold": threshold, "status": None, "best_value": None,
             "proven_optimal": False, "n_primary_vars": None, "n_aux_vars": None,
             "n_clauses": None, "encode_seconds": 0.0, "solve_seconds": 0.0,
             "total_seconds": 0.0, "error": None, "labeling": None}
    if timeout_seconds <= 0:
        trial["status"] = "TIMEOUT"
        return trial
    try:
        if _minimum_clause_count(graph, threshold, method, assignment_amo) > max_clauses:
            raise ClauseLimitError(f"CNF would exceed {max_clauses} clauses")
        encoding = SAT_ENCODERS[method](graph, threshold, assignment_amo=assignment_amo,
                                        max_clauses=max_clauses)
        trial.update(n_primary_vars=encoding.n_primary_vars, n_aux_vars=encoding.n_aux_vars,
                     n_clauses=encoding.n_clauses, encode_seconds=encoding.encode_seconds)
        remaining = timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            trial["status"] = "TIMEOUT"
        else:
            solve_started = monotonic()
            with Solver(name="g3", bootstrap_with=encoding.clauses) as solver:
                remaining = timeout_seconds - (monotonic() - started)
                if remaining <= 0:
                    answer = None
                else:
                    timer = Timer(remaining, solver.interrupt)
                    timer.start()
                    try:
                        answer = solver.solve_limited(expect_interrupt=True)
                    finally:
                        timer.cancel()
                        timer.join()
                        solver.clear_interrupt()
                if answer is True:
                    labeling = encoding.decode(solver.get_model())
                    trial.update(status="FEASIBLE", best_value=validate_solution(graph, labeling, threshold),
                                 labeling=labeling)
                elif answer is False:
                    trial["status"] = "INFEASIBLE"
                else:
                    trial["status"] = "TIMEOUT"
            trial["solve_seconds"] = monotonic() - solve_started
    except (ClauseLimitError, MemoryError) as exc:
        trial.update(status="RESOURCE_LIMIT", error=str(exc))
    except Exception as exc:
        trial.update(status="ERROR", error=f"{type(exc).__name__}: {exc}")
    trial["total_seconds"] = monotonic() - started
    return trial


def run_sat_optimization(graph, method: str, timeout_seconds: float,
                         max_clauses: int, assignment_amo: str = "sequential") -> tuple[dict, list[dict]]:
    """Binary search with a verified lower bound and an UNSAT upper bound."""
    started = monotonic()
    incumbent = fallback_labeling(graph)
    lower = validate_solution(graph, incumbent)
    upper = graph.n - 1
    trials = []
    status = "OPTIMAL"
    error = None
    first_probe = True
    while lower < upper:
        remaining = timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            status = "TIMEOUT"
            break
        threshold = lower + 1 if first_probe else (lower + upper + 1) // 2
        first_probe = False
        trial = run_sat_decision(graph, threshold, method, remaining, max_clauses, assignment_amo)
        trials.append(trial)
        if trial["status"] == "FEASIBLE":
            if trial["best_value"] > lower:
                incumbent = trial["labeling"]
                lower = trial["best_value"]
        elif trial["status"] == "INFEASIBLE":
            upper = threshold - 1
        else:
            status = trial["status"]
            error = trial["error"]
            break
    summary = {"status": status, "best_value": validate_solution(graph, incumbent),
               "proven_optimal": status == "OPTIMAL", "labeling": incumbent,
               "threshold": None, "n_primary_vars": max((x["n_primary_vars"] or 0 for x in trials), default=0),
               "n_aux_vars": max((x["n_aux_vars"] or 0 for x in trials), default=0),
               "n_clauses": max((x["n_clauses"] or 0 for x in trials), default=0),
               "encode_seconds": sum(x["encode_seconds"] for x in trials),
               "solve_seconds": sum(x["solve_seconds"] for x in trials),
               "total_seconds": monotonic() - started, "error": error,
               "trial_count": len(trials)}
    return summary, trials


def run_exact_optimization(graph, method: str, timeout_seconds: float) -> dict:
    if method not in EXACT_SOLVERS:
        raise ValueError(f"unknown exact method: {method}")
    started = monotonic()
    result = EXACT_SOLVERS[method](graph, timeout_seconds)
    elapsed = monotonic() - started
    return {"status": result.status.value, "best_value": result.objective,
            "proven_optimal": result.status.value == "OPTIMAL", "labeling": result.labeling,
            "threshold": None, "n_primary_vars": None, "n_aux_vars": None,
            "n_clauses": None, "encode_seconds": None, "solve_seconds": None,
            "total_seconds": elapsed, "error": result.error, "trial_count": None}
