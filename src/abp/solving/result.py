"""Mathematical conclusions, stop reasons, and independently checked ABP bounds."""

from dataclasses import dataclass
from enum import StrEnum
from math import floor, isfinite

from abp.validation import validate_solution


class Status(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


class Termination(StrEnum):
    COMPLETED = "COMPLETED"
    TIME_LIMIT = "TIME_LIMIT"
    MEMORY_LIMIT = "MEMORY_LIMIT"
    CLAUSE_LIMIT = "CLAUSE_LIMIT"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Result:
    status: Status
    objective: int | None = None
    labeling: dict[int, int] | None = None
    error: str | None = None
    termination: Termination = Termination.COMPLETED
    raw_status: str | None = None
    upper_bound: int | None = None
    reported_objective: float | None = None


def integer_upper_bound(value, n: int, tolerance: float = 1e-6) -> int | None:
    """Round a floating maximization bound outward, retaining the domain bound."""
    if value is None or not isfinite(value) or value < 1 - tolerance:
        return None
    return min(n - 1, floor(value + tolerance))


def bound_metrics(lower: int, upper: int, n: int) -> dict:
    if not (1 <= lower <= upper <= n - 1):
        raise ValueError(f"inconsistent ABP bounds: {lower} <= optimum <= {upper}, n={n}")
    gap = upper - lower
    return {"absolute_gap": gap, "relative_gap": gap / upper,
            "proven_optimal": gap == 0}


def checked_result(graph, status: Status, labeling=None, threshold=None, error=None,
                   reported_objective=None, termination=Termination.COMPLETED,
                   raw_status=None, upper_bound=None) -> Result:
    """Never report an unchecked solver labeling as feasible or optimal."""
    if labeling is None:
        if status in (Status.OPTIMAL, Status.FEASIBLE):
            return Result(Status.UNKNOWN, error="solver reported a solution without a labeling",
                          termination=Termination.ERROR, raw_status=raw_status)
        return Result(status, error=error, termination=termination,
                      raw_status=raw_status, upper_bound=upper_bound)
    try:
        objective = validate_solution(graph, labeling, threshold)
    except (ValueError, TypeError) as exc:
        return Result(Status.UNKNOWN, error=f"invalid solver labeling: {exc}",
                      termination=Termination.ERROR, raw_status=raw_status)
    if status == Status.INFEASIBLE:
        return Result(Status.UNKNOWN, error="solver reported both infeasibility and a labeling",
                      termination=Termination.ERROR, raw_status=raw_status)
    if reported_objective is not None:
        if (not isfinite(reported_objective) or reported_objective > objective + 1e-6
                or status == Status.OPTIMAL and abs(reported_objective - objective) > 1e-6):
            return Result(Status.UNKNOWN, error="solver objective disagrees with independently evaluated labeling",
                          termination=Termination.ERROR, raw_status=raw_status,
                          reported_objective=reported_objective)
    return Result(status, objective, labeling, error, termination, raw_status,
                  upper_bound, reported_objective)
