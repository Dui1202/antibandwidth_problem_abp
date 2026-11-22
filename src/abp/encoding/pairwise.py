"""Direct forbidden-label-pair SAT encoding for ABP."""

from time import perf_counter

from .common import Builder, assignment_constraints, check_threshold, variable


def encode_pairwise(graph, threshold: int):
    check_threshold(graph, threshold)
    started = perf_counter()
    n = graph.n
    builder = Builder(n * n)
    assignment_constraints(builder, n)
    for u, v in graph.edges:
        for p in range(1, n + 1):
            for q in range(max(1, p - threshold + 1), min(n, p + threshold - 1) + 1):
                builder.add(-variable(n, u, p), -variable(n, v, q))
    return builder.result(graph, threshold, started)
