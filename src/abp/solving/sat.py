"""Fixed-threshold SAT checks and monotone ABP optimization search."""

from threading import Timer
from time import monotonic

from pysat.solvers import Solver

from .result import Result, Status, Termination, checked_result


def solve_sat(graph, threshold, encoder, timeout_seconds=None, solver_name="g3") -> Result:
    if timeout_seconds is not None and timeout_seconds <= 0:
        return Result(Status.UNKNOWN, termination=Termination.TIME_LIMIT)
    deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
    try:
        encoding = encoder(graph, threshold)
        remaining = None if deadline is None else deadline - monotonic()
        if remaining is not None and remaining <= 0:
            return Result(Status.UNKNOWN, termination=Termination.TIME_LIMIT)
        with Solver(name=solver_name, bootstrap_with=encoding.clauses) as solver:
            timer = None
            if remaining is not None:
                timer = Timer(remaining, solver.interrupt)
                timer.start()
            try:
                answer = solver.solve_limited(expect_interrupt=True)
            finally:
                if timer is not None:
                    timer.cancel()
                    timer.join()
                    solver.clear_interrupt()
            if answer is None:
                return Result(Status.UNKNOWN, termination=Termination.TIME_LIMIT)
            if not answer:
                return Result(Status.INFEASIBLE)
            return checked_result(graph, Status.FEASIBLE, encoding.decode(solver.get_model()), threshold)
    except Exception as exc:
        return Result(Status.UNKNOWN, error=f"{type(exc).__name__}: {exc}",
                      termination=Termination.ERROR)


def optimize_sat(graph, encoder, timeout_seconds=None, solver_name="g3") -> Result:
    """Increase thresholds until UNSAT proves the previous one optimal."""
    deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
    incumbent = None
    for threshold in range(1, graph.n):
        remaining = None if deadline is None else deadline - monotonic()
        if remaining is not None and remaining <= 0:
            return checked_result(graph, Status.UNKNOWN, incumbent,
                                  termination=Termination.TIME_LIMIT)
        decision = solve_sat(graph, threshold, encoder, remaining, solver_name)
        if decision.status == Status.FEASIBLE:
            incumbent = decision.labeling
        elif decision.status == Status.INFEASIBLE:
            return checked_result(graph, Status.OPTIMAL, incumbent)
        elif decision.status == Status.UNKNOWN:
            return checked_result(graph, Status.UNKNOWN, incumbent, error=decision.error,
                                  termination=decision.termination)
    return checked_result(graph, Status.OPTIMAL, incumbent)
