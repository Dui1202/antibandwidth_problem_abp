"""Independent labeling and objective validation."""


def validate_solution(graph, labeling, threshold=None) -> int:
    """Return the minimum edge distance; raise ValueError on invalid input."""
    n = graph.n
    if (set(labeling) != set(range(n))
            or any(type(label) is not int for label in labeling.values())
            or sorted(labeling.values()) != list(range(1, n + 1))):
        raise ValueError("labeling must be a bijection onto 1..n")
    objective = min(abs(labeling[u] - labeling[v]) for u, v in graph.edges)
    if threshold is not None and objective < threshold:
        raise ValueError("labeling violates edge-distance threshold")
    return objective
