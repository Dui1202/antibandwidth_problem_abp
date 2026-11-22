from itertools import combinations, permutations

import pytest
from pysat.solvers import Solver

from abp.graph import Graph
from abp.validation import validate_solution
from abp.encoding.pairwise import encode_pairwise
from abp.encoding.order import encode_order
from abp.encoding.staircase_scl import encode_staircase_scl, add_grouped_scamo
from abp.encoding.common import Builder


def satisfiable(encoding):
    with Solver(name="g3", bootstrap_with=encoding.clauses) as solver:
        return solver.solve()


@pytest.mark.parametrize("n", range(2, 5))
def test_all_small_graphs_against_permutation_oracle(n):
    possible_edges = list(combinations(range(n), 2))
    for mask in range(1, 1 << len(possible_edges)):
        edges = [edge for i, edge in enumerate(possible_edges) if mask & (1 << i)]
        graph = Graph(n, edges)
        for threshold in range(1, n):
            expected = any(
                all(abs(p[u] - p[v]) >= threshold for u, v in edges)
                for p in permutations(range(1, n + 1))
            )
            for encode in (encode_pairwise, encode_order, encode_staircase_scl):
                assert satisfiable(encode(graph, threshold)) == expected, (encode.__name__, graph, threshold)


@pytest.mark.parametrize("width,groups", [(1, 3), (2, 3), (3, 4), (4, 5)])
def test_grouped_scamo_truth_table(width, groups):
    # Two variables per label position, matching an ABP edge.
    for values in range(1 << (2 * groups)):
        builder = Builder(2 * groups)
        add_grouped_scamo(builder, [tuple(range(2*i+1, 2*i+3)) for i in range(groups)], width)
        expected = all(
            sum(bool(values & (1 << j)) for j in range(2*start, 2*(start+width))) <= 1
            for start in range(groups-width+1)
        )
        assumptions = [i+1 if values & (1 << i) else -(i+1) for i in range(2*groups)]
        with Solver(name="g3", bootstrap_with=builder.clauses) as solver:
            assert solver.solve(assumptions=assumptions) == expected


def test_graph_rejects_invalid_edges_and_normalizes_duplicates():
    assert Graph(3, [(1, 0), (0, 1)]).edges == ((0, 1),)
    for edges in ([], [(0, 0)], [(0, 3)], [(-1, 1)]):
        with pytest.raises(ValueError):
            Graph(3, edges)


@pytest.mark.parametrize("encode", [encode_pairwise, encode_order, encode_staircase_scl])
def test_decoded_model_is_independently_validated(encode):
    graph = Graph(4, [(0, 1), (1, 2)])
    encoding = encode(graph, 2)
    with Solver(name="g3", bootstrap_with=encoding.clauses) as solver:
        assert solver.solve()
        labeling = encoding.decode(solver.get_model())
    assert validate_solution(graph, labeling, 2) >= 2
    with pytest.raises(ValueError):
        encoding.decode([])


def test_validation_rejects_missing_repeated_and_short_edges():
    graph = Graph(3, [(0, 1)])
    for labeling in ({0: 1, 1: 2}, {0: 1, 1: 1, 2: 3}, {0: 1, 1: 2, 2: 3}):
        with pytest.raises(ValueError):
            validate_solution(graph, labeling, 2)


def test_staircase_vertex_registers_are_shared_across_edges():
    path = Graph(5, [(0, 1), (1, 2), (2, 3), (3, 4)])
    cycle = Graph(5, [*path.edges, (0, 4)])
    a = encode_staircase_scl(path, 3)
    b = encode_staircase_scl(cycle, 3)
    assert a.n_aux_vars == b.n_aux_vars
    assert a.n_aux_vars > 0
    assert encode_pairwise(path, 3).n_aux_vars == 0


@pytest.mark.parametrize("edges", [
    [(i, i + 1) for i in range(5)],
    [(0, i) for i in range(1, 6)],
    list(combinations(range(6), 2)),
    [(i, (i + 1) % 6) for i in range(6)],
])
def test_six_vertex_boundary_cases(edges):
    graph = Graph(6, edges)
    for threshold in range(1, 6):
        expected = any(
            all(abs(p[u] - p[v]) >= threshold for u, v in graph.edges)
            for p in permutations(range(1, 7))
        )
        assert satisfiable(encode_pairwise(graph, threshold)) == expected
        assert satisfiable(encode_order(graph, threshold)) == expected
        assert satisfiable(encode_staircase_scl(graph, threshold)) == expected


def test_order_variable_mapping_and_model_contract():
    graph = Graph(3, [(0, 1)])
    encoding = encode_order(graph, 2)
    assert encoding.n_primary_vars == 6
    assert encoding.n_aux_vars == 0
    assert encoding.variable(0, 2) == 1
    assert encoding.variable(2, 3) == 6
    for model in ([1], [1, -1, -2, -3, -4, -5, -6]):
        with pytest.raises(ValueError):
            encoding.decode(model)


def test_order_encoding_accepts_exactly_valid_fixed_labelings():
    graph = Graph(4, [(0, 1), (1, 2)])  # Vertex 3 is isolated.
    for threshold in range(1, 4):
        encoding = encode_order(graph, threshold)
        with Solver(name="g3", bootstrap_with=encoding.clauses) as solver:
            for permutation in permutations(range(1, 5)):
                assumptions = [
                    encoding.variable(vertex, bound)
                    if permutation[vertex] >= bound else -encoding.variable(vertex, bound)
                    for vertex in range(4) for bound in range(2, 5)
                ]
                expected = all(abs(permutation[u] - permutation[v]) >= threshold
                               for u, v in graph.edges)
                assert solver.solve(assumptions=assumptions) == expected


@pytest.mark.parametrize("encode", [encode_pairwise, encode_order, encode_staircase_scl])
def test_compact_assignment_option_preserves_decision_semantics(encode):
    for n in range(2, 5):
        possible_edges = list(combinations(range(n), 2))
        for mask in range(1, 1 << len(possible_edges)):
            graph = Graph(n, [edge for i, edge in enumerate(possible_edges) if mask & (1 << i)])
            for threshold in range(1, n):
                compact = encode(graph, threshold, assignment_amo="sequential")
                assert satisfiable(compact) == satisfiable(encode(graph, threshold))
                assert compact.n_aux_vars > 0


def test_clause_cap_stops_construction():
    from abp.encoding.common import ClauseLimitError

    with pytest.raises(ClauseLimitError):
        encode_pairwise(Graph(5, [(0, 1)]), 2, max_clauses=10)
