import gzip
from pathlib import Path

import pytest

from abp.dataset import load_matrix_market


def write_matrix(tmp_path, text):
    path = tmp_path / "example.mtx.gz"
    with gzip.open(path, "wt") as stream:
        stream.write(text)
    return path


def test_matrix_loader_ignores_diagonal_and_explicit_zero(tmp_path):
    path = write_matrix(tmp_path, """%%MatrixMarket matrix coordinate real general
% a comment
4 4 6
1 1 2
1 2 1
2 1 3
2 3 0
3 4 -2
4 4 0
""")
    instance = load_matrix_market(path)
    assert instance.graph.n == 4
    assert instance.graph.edges == ((0, 1), (2, 3))
    assert instance.ignored_diagonal == 2
    assert instance.ignored_zero == 1
    assert instance.duplicate_edges == 1
    assert instance.declared_nnz == 6


@pytest.mark.parametrize("text", [
    "%%MatrixMarket matrix coordinate pattern symmetric\n3 4 1\n1 2\n",
    "%%MatrixMarket matrix coordinate pattern symmetric\n3 3 2\n1 2\n",
    "%%MatrixMarket matrix coordinate pattern symmetric\n3 3 1\n0 2\n",
    "%%MatrixMarket matrix coordinate complex general\n3 3 1\n1 2 1 0\n",
])
def test_matrix_loader_rejects_malformed_input(tmp_path, text):
    with pytest.raises(ValueError):
        load_matrix_market(write_matrix(tmp_path, text))


def test_all_supplied_instances_are_loadable():
    paths = sorted(Path("data/dataset").glob("*.mtx.gz"))
    assert len(paths) == 24
    instances = [load_matrix_market(path) for path in paths]
    assert min(instance.graph.n for instance in instances) == 30
    assert max(instance.graph.n for instance in instances) == 1104
    by_name = {instance.name: instance for instance in instances}
    assert by_name["impcol_b"].graph.edges != ()
    assert by_name["bcsstk06"].graph_hash == by_name["bcsstk07"].graph_hash
