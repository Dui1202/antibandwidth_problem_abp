"""Shared CNF builder and deterministic assignment-variable mapping."""

from dataclasses import dataclass
from itertools import combinations
from time import perf_counter


@dataclass(frozen=True)
class EncodingResult:
    clauses: tuple[tuple[int, ...], ...]
    n_vertices: int
    threshold: int
    n_primary_vars: int
    n_aux_vars: int
    encode_seconds: float

    @property
    def n_clauses(self):
        return len(self.clauses)

    def variable(self, vertex: int, label: int) -> int:
        if not 0 <= vertex < self.n_vertices or not 1 <= label <= self.n_vertices:
            raise ValueError("invalid vertex or label")
        return vertex * self.n_vertices + label

    def decode(self, model: list[int]) -> dict[int, int]:
        """Decode primary literals and reject missing or duplicate assignments."""
        positives = set(literal for literal in model if 0 < literal <= self.n_primary_vars)
        labeling = {}
        for vertex in range(self.n_vertices):
            labels = [label for label in range(1, self.n_vertices + 1)
                      if self.variable(vertex, label) in positives]
            if len(labels) != 1:
                raise ValueError("model does not assign exactly one label per vertex")
            labeling[vertex] = labels[0]
        if len(set(labeling.values())) != self.n_vertices:
            raise ValueError("model repeats a label")
        return labeling


class Builder:
    def __init__(self, n_primary: int):
        self.n_primary = n_primary
        self.next_id = n_primary + 1
        self.clauses: list[tuple[int, ...]] = []

    def fresh(self) -> int:
        result = self.next_id
        self.next_id += 1
        return result

    def add(self, *literals: int) -> None:
        self.clauses.append(tuple(literals))

    def result(self, graph, threshold: int, started: float,
               result_type=EncodingResult) -> EncodingResult:
        return result_type(tuple(self.clauses), graph.n, threshold,
                              self.n_primary, self.next_id - self.n_primary - 1,
                              perf_counter() - started)


def variable(n: int, vertex: int, label: int) -> int:
    return vertex * n + label


def check_threshold(graph, threshold: int) -> None:
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold < graph.n:
        raise ValueError("threshold must be in 1..n-1")


def assignment_constraints(builder: Builder, n: int) -> None:
    """Exactly one per vertex and label, with explicit pairwise AMO."""
    for v in range(n):
        exactly_one_pairwise(builder, [variable(n, v, l) for l in range(1, n + 1)])
    for l in range(1, n + 1):
        exactly_one_pairwise(builder, [variable(n, v, l) for v in range(n)])


def exactly_one_pairwise(builder: Builder, literals: list[int]) -> None:
    builder.add(*literals)
    for a, b in combinations(literals, 2):
        builder.add(-a, -b)
