"""Status and independently checked results shared by exact solvers."""

from dataclasses import dataclass
from enum import StrEnum

from abp.validation import validate_solution


class Status(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Result:
    status: Status
    objective: int | None = None
    labeling: dict[int, int] | None = None
    error: str | None = None


def checked_result(graph, status: Status, labeling=None, threshold=None, error=None,
                   reported_objective=None) -> Result:
    """Never report an unchecked incumbent as feasible or optimal."""
    if labeling is None:
        if status in (Status.OPTIMAL, Status.FEASIBLE):
            return Result(Status.ERROR, error="solver reported a solution without a labeling")
        return Result(status, error=error)
    try:
        objective = validate_solution(graph, labeling, threshold)
    except (ValueError, TypeError) as exc:
        return Result(Status.ERROR, error=f"invalid solver labeling: {exc}")
    if status == Status.INFEASIBLE:
        return Result(Status.ERROR, error="solver reported both infeasibility and a labeling")
    if reported_objective is not None and status == Status.OPTIMAL and abs(reported_objective - objective) > 1e-6:
        return Result(Status.ERROR, error="solver objective disagrees with independently evaluated labeling")
    return Result(status, objective, labeling, error)
