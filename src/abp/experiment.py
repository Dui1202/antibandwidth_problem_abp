"""Measured ABP trials; every feasible value comes from a checked labeling."""

from threading import Lock, Timer
from time import monotonic

from pysat.solvers import Solver

from .encoding.common import ClauseLimitError
from .encoding.order import encode_order
from .encoding.pairwise import encode_pairwise
from .encoding.staircase_scl import encode_staircase_scl
from .solving.baselines import (optimize_cp_optimizer, optimize_cp_sat,
                               optimize_cplex, optimize_gurobi)
from .validation import validate_solution
from .solving.result import Status, Termination, bound_metrics


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
    """Return a fixed-threshold decision with no optimization fallback."""
    if method not in SAT_ENCODERS:
        raise ValueError(f"unknown SAT method: {method}")
    started = monotonic()
    trial = {"threshold": threshold, "solution_status": "UNKNOWN",
             "termination_reason": "UNKNOWN", "raw_status": None,
             "best_value": None, "n_primary_vars": None, "n_aux_vars": None,
             "n_clauses": None, "encode_seconds": 0.0, "solve_seconds": 0.0,
             "total_seconds": 0.0, "error": None, "labeling": None}
    if timeout_seconds <= 0:
        trial["termination_reason"] = "TIME_LIMIT"
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
            trial["termination_reason"] = "TIME_LIMIT"
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
                    trial.update(solution_status="FEASIBLE", termination_reason="COMPLETED",
                                 raw_status="SAT", best_value=validate_solution(graph, labeling, threshold),
                                 labeling=labeling)
                elif answer is False:
                    trial.update(solution_status="INFEASIBLE", termination_reason="COMPLETED",
                                 raw_status="UNSAT")
                else:
                    trial.update(termination_reason="TIME_LIMIT", raw_status="INTERRUPTED")
            trial["solve_seconds"] = monotonic() - solve_started
    except ClauseLimitError as exc:
        trial.update(termination_reason="CLAUSE_LIMIT", error=str(exc))
    except MemoryError as exc:
        trial.update(termination_reason="MEMORY_LIMIT", error=str(exc))
    except Exception as exc:
        trial.update(termination_reason="ERROR", error=f"{type(exc).__name__}: {exc}")
    trial["total_seconds"] = monotonic() - started
    return trial


def _summary(graph, state, status, termination, raw_status=None, error=None, elapsed=None):
    lower, upper = state["lower_bound"], state["upper_bound"]
    metrics = bound_metrics(lower, upper, graph.n)
    if status == Status.OPTIMAL and not metrics["proven_optimal"]:
        status, termination, error = Status.UNKNOWN, Termination.ERROR, "backend optimality conflicts with verified bounds"
    if metrics["proven_optimal"]:
        status = Status.OPTIMAL
    elif state["has_solver_incumbent"]:
        status = Status.FEASIBLE
    elif status != Status.INFEASIBLE:
        status = Status.UNKNOWN
    trials = state["trials"]
    return {**state, **metrics, "solution_status": status.value,
            "termination_reason": termination.value, "raw_status": raw_status,
            "error": error, "threshold": None,
            "n_primary_vars": max((x["n_primary_vars"] or 0 for x in trials), default=0) if trials else None,
            "n_aux_vars": max((x["n_aux_vars"] or 0 for x in trials), default=0) if trials else None,
            "n_clauses": max((x["n_clauses"] or 0 for x in trials), default=0) if trials else None,
            "encode_seconds": sum(x["encode_seconds"] for x in trials) if trials else None,
            "solve_seconds": sum(x["solve_seconds"] for x in trials) if trials else None,
            "total_seconds": elapsed, "trial_count": len(trials) if trials else None}


def _initial_state(graph):
    labeling = fallback_labeling(graph)
    value = validate_solution(graph, labeling)
    return {"labeling": labeling, "best_value": value, "fallback_value": value,
            "solver_reported_objective": None,
            "solver_best_value": None, "solver_labeling": None,
            "has_solver_incumbent": False,
            "solution_source": "FALLBACK",
            "lower_bound": value, "upper_bound": graph.n - 1,
            "lower_bound_source": "FALLBACK", "upper_bound_source": "THEORETICAL",
            "trials": []}


def run_sat_optimization(graph, method: str, timeout_seconds: float,
                         max_clauses: int, assignment_amo: str = "sequential",
                         checkpoint=None) -> tuple[dict, list[dict]]:
    """Binary search with verified feasible and UNSAT bounds."""
    started = monotonic()
    state = _initial_state(graph)
    def save():
        if checkpoint is not None:
            checkpoint({**state, "elapsed_seconds": monotonic() - started,
                        "proven_optimal": state["lower_bound"] == state["upper_bound"]})
    save()
    first_probe = True
    termination = Termination.COMPLETED
    error = None
    while state["lower_bound"] < state["upper_bound"]:
        remaining = timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            termination = Termination.TIME_LIMIT
            break
        lower, upper = state["lower_bound"], state["upper_bound"]
        threshold = lower + 1 if first_probe else (lower + upper + 1) // 2
        first_probe = False
        trial = run_sat_decision(graph, threshold, method, remaining, max_clauses, assignment_amo)
        state["trials"].append(trial)
        if trial["solution_status"] == "FEASIBLE":
            value = validate_solution(graph, trial["labeling"], threshold)
            if state["solver_best_value"] is None or value > state["solver_best_value"]:
                state["solver_labeling"] = trial["labeling"]
            state["solver_best_value"] = max(state["solver_best_value"] or 0, value)
            state["has_solver_incumbent"] = True
            if value > state["lower_bound"]:
                state.update(labeling=trial["labeling"], best_value=value,
                             lower_bound=value, lower_bound_source="SOLVER",
                             solution_source="SOLVER")
                save()
        elif trial["solution_status"] == "INFEASIBLE":
            state["upper_bound"] = min(state["upper_bound"], threshold - 1)
            state["upper_bound_source"] = "SAT_UNSAT"
            save()
        else:
            termination = Termination(trial["termination_reason"])
            error = trial["error"]
        save()
        if termination != Termination.COMPLETED:
            break
    raw_status = state["trials"][-1].get("raw_status") if state["trials"] else "not_started"
    summary = _summary(graph, state, Status.UNKNOWN, termination, raw_status=raw_status, error=error,
                       elapsed=monotonic() - started)
    state["solution_status"] = summary["solution_status"]
    state["termination_reason"] = summary["termination_reason"]
    save()
    return summary, state["trials"]


def run_exact_optimization(graph, method: str, timeout_seconds: float, checkpoint=None) -> dict:
    if method not in EXACT_SOLVERS:
        raise ValueError(f"unknown exact method: {method}")
    started = monotonic()
    state = _initial_state(graph)
    progress_lock = Lock()
    def save():
        if checkpoint is not None:
            checkpoint({**state, "elapsed_seconds": monotonic() - started,
                        "proven_optimal": state["lower_bound"] == state["upper_bound"]})
    save()
    def progress(labeling, upper_bound):
        with progress_lock:
            before = (state["solver_best_value"], state["has_solver_incumbent"],
                      state["lower_bound"], state["upper_bound"])
            if labeling is not None:
                value = validate_solution(graph, labeling)
                if state["solver_best_value"] is None or value > state["solver_best_value"]:
                    state["solver_labeling"] = labeling
                state["solver_best_value"] = max(state["solver_best_value"] or 0, value)
                state["has_solver_incumbent"] = True
                if value > state["lower_bound"]:
                    state.update(labeling=labeling, best_value=value, lower_bound=value,
                                 lower_bound_source="SOLVER", solution_source="SOLVER")
            if upper_bound is not None and upper_bound < state["upper_bound"]:
                state["upper_bound"] = upper_bound
                state["upper_bound_source"] = "BACKEND"
            if state["lower_bound"] > state["upper_bound"]:
                raise ValueError("backend bound contradicts verified incumbent")
            after = (state["solver_best_value"], state["has_solver_incumbent"],
                     state["lower_bound"], state["upper_bound"])
            if after != before:
                save()
    result = EXACT_SOLVERS[method](graph, timeout_seconds, progress=progress)
    state["solver_reported_objective"] = result.reported_objective
    if result.status == Status.INFEASIBLE:
        result = result.__class__(Status.UNKNOWN, error="backend infeasible contradicts fallback",
                                  termination=Termination.ERROR, raw_status=result.raw_status)
    if result.termination != Termination.ERROR:
        upper = result.objective if result.status == Status.OPTIMAL else result.upper_bound
        progress(result.labeling, upper)
    elif result.labeling is not None:
        progress(result.labeling, None)
    summary = _summary(graph, state, result.status, result.termination, result.raw_status,
                       result.error, monotonic() - started)
    summary.update(n_primary_vars=None, n_aux_vars=None, n_clauses=None,
                   encode_seconds=None, solve_seconds=None, trial_count=None)
    state["solution_status"] = summary["solution_status"]
    state["termination_reason"] = summary["termination_reason"]
    state["raw_status"] = summary["raw_status"]
    save()
    return summary


def recover_optimization(graph, state, termination: Termination, elapsed: float) -> dict:
    """Report a killed worker without inventing a solver conclusion."""
    if state is None:
        state = _initial_state(graph)
    else:
        state = state.copy()
        if state["has_solver_incumbent"] and state["solution_source"] == "SOLVER":
            state["solution_source"] = "CHECKPOINT"
    return _summary(graph, state, Status.UNKNOWN, termination,
                    raw_status="worker_killed", elapsed=elapsed)
