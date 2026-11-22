"""Order-variable SAT decision encoding for ABP.

Primary variable y[v,l] means f(v) >= l, for 2 <= l <= n.
"""

from itertools import combinations
from time import perf_counter

from .common import Builder, EncodingResult, check_threshold, exactly_one_sequential


class OrderEncodingResult(EncodingResult):
    def variable(self, vertex: int, label: int) -> int:
        """DIMACS ID of y[vertex,label] where label is a lower bound."""
        n = self.n_vertices
        if not 0 <= vertex < n or not 2 <= label <= n:
            raise ValueError("order variable requires vertex in 0..n-1 and label in 2..n")
        return vertex * (n - 1) + label - 1

    def decode(self, model: list[int]) -> dict[int, int]:
        signs = {}
        for literal in model:
            if 0 < abs(literal) <= self.n_primary_vars:
                if abs(literal) in signs and signs[abs(literal)] != (literal > 0):
                    raise ValueError("contradictory order literals")
                signs[abs(literal)] = literal > 0
        if len(signs) != self.n_primary_vars:
            raise ValueError("incomplete order-variable model")
        labeling = {}
        for vertex in range(self.n_vertices):
            values = [signs[self.variable(vertex, label)]
                      for label in range(2, self.n_vertices + 1)]
            if values != sorted(values, reverse=True):
                raise ValueError("order literals are not monotone")
            labeling[vertex] = 1 + sum(values)
        if len(set(labeling.values())) != self.n_vertices:
            raise ValueError("model repeats a label")
        return labeling


def encode_order(graph, threshold: int, *, assignment_amo="pairwise", max_clauses=None) -> OrderEncodingResult:
    """Encode AB(G) >= threshold with order variables."""
    check_threshold(graph, threshold)
    if assignment_amo not in {"pairwise", "sequential"}:
        raise ValueError("assignment_amo must be pairwise or sequential")
    started = perf_counter()
    n = graph.n
    builder = Builder(n * (n - 1), max_clauses)

    def y(vertex: int, label: int) -> int:
        return vertex * (n - 1) + label - 1

    def not_equal(vertex: int, label: int) -> list[int]:
        # Equality is y[v,label] AND NOT y[v,label+1]. The two
        # out-of-range sentinel terms are constant true/false.
        terms = []
        if label > 1:
            terms.append(-y(vertex, label))
        if label < n:
            terms.append(y(vertex, label + 1))
        return terms

    for vertex in range(n):
        for label in range(2, n):
            builder.add(-y(vertex, label + 1), y(vertex, label))

    # Every monotone order row denotes exactly one label. Injection
    # across n vertices and n labels therefore gives a bijection.
    for label in range(1, n + 1):
        if assignment_amo == "pairwise":
            for u, v in combinations(range(n), 2):
                builder.add(*not_equal(u, label), *not_equal(v, label))
        else:
            equal_vars = []
            for vertex in range(n):
                equality = builder.fresh()
                equal_vars.append(equality)
                if label > 1:
                    builder.add(-equality, y(vertex, label))
                if label < n:
                    builder.add(-equality, -y(vertex, label + 1))
                builder.add(equality, *not_equal(vertex, label))
            exactly_one_sequential(builder, equal_vars)

    for u, v in graph.edges:
        for label in range(1, n + 1):
            # If f(u)=label, then f(v) <= label-t OR f(v) >= label+t.
            clause = not_equal(u, label)
            if label - threshold >= 1:
                clause.append(-y(v, label - threshold + 1))
            if label + threshold <= n:
                clause.append(y(v, label + threshold))
            builder.add(*clause)

    return builder.result(graph, threshold, started, OrderEncodingResult)
