"""Simple undirected graph with vertex IDs 0..n-1."""

from dataclasses import dataclass


@dataclass(frozen=True, init=False)
class Graph:
    n: int
    edges: tuple[tuple[int, int], ...]

    def __init__(self, n: int, edges):
        if isinstance(n, bool) or not isinstance(n, int) or n < 2:
            raise ValueError("n must be an integer of at least 2")
        normalized = set()
        for edge in edges:
            try:
                u, v = edge
            except (TypeError, ValueError) as exc:
                raise ValueError("each edge must have two endpoints") from exc
            if any(isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < n for x in (u, v)) or u == v:
                raise ValueError("edge endpoints must be distinct vertex IDs in 0..n-1")
            normalized.add((min(u, v), max(u, v)))
        if not normalized:
            raise ValueError("graph must have at least one edge")
        object.__setattr__(self, "n", n)
        object.__setattr__(self, "edges", tuple(sorted(normalized)))
