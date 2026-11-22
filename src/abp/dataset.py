"""Load sparse Matrix Market instances as simple unweighted ABP graphs."""

from dataclasses import dataclass
import gzip
from hashlib import sha256
from pathlib import Path

from .graph import Graph


@dataclass(frozen=True)
class MatrixInstance:
    name: str
    graph: Graph
    source_sha256: str
    graph_hash: str
    field: str
    symmetry: str
    declared_nnz: int
    ignored_diagonal: int
    ignored_zero: int
    duplicate_edges: int

    def manifest_row(self) -> dict:
        return {
            "instance": self.name,
            "n_vertices": self.graph.n,
            "n_edges": len(self.graph.edges),
            "field": self.field,
            "symmetry": self.symmetry,
            "declared_nnz": self.declared_nnz,
            "ignored_diagonal": self.ignored_diagonal,
            "ignored_zero": self.ignored_zero,
            "duplicate_edges": self.duplicate_edges,
            "source_sha256": self.source_sha256,
            "graph_sha256": self.graph_hash,
        }


def load_matrix_market(path: str | Path) -> MatrixInstance:
    path = Path(path)
    try:
        with gzip.open(path, "rt", encoding="ascii") as stream:
            header = stream.readline().strip().split()
            if (len(header) != 5 or header[:3] != ["%%MatrixMarket", "matrix", "coordinate"]
                    or header[3] not in {"pattern", "real", "integer"}
                    or header[4] not in {"general", "symmetric"}):
                raise ValueError("unsupported Matrix Market header")
            field, symmetry = header[3:]
            rows = (line.strip() for line in stream if line.strip() and not line.startswith("%"))
            n_rows, n_cols, declared_nnz = map(int, next(rows).split())
            if n_rows != n_cols or n_rows < 2 or declared_nnz < 0:
                raise ValueError("matrix must be square with at least two rows")
            edges = set()
            diagonal = zeros = duplicate_edges = read_nnz = 0
            for line in rows:
                read_nnz += 1
                parts = line.split()
                if len(parts) != (2 if field == "pattern" else 3):
                    raise ValueError("invalid Matrix Market entry")
                a, b = map(int, parts[:2])
                if not 1 <= a <= n_rows or not 1 <= b <= n_rows:
                    raise ValueError("Matrix Market coordinate outside matrix")
                if a == b:
                    diagonal += 1
                    continue
                if field != "pattern" and float(parts[2]) == 0:
                    zeros += 1
                    continue
                edge = (min(a, b) - 1, max(a, b) - 1)
                duplicate_edges += edge in edges
                edges.add(edge)
            if read_nnz != declared_nnz:
                raise ValueError("Matrix Market entry count differs from header")
            graph = Graph(n_rows, edges)
    except (OSError, EOFError, StopIteration, UnicodeError) as exc:
        raise ValueError(f"cannot read Matrix Market file: {exc}") from exc
    digest = sha256()
    digest.update(f"{graph.n}\n".encode())
    for u, v in graph.edges:
        digest.update(f"{u},{v}\n".encode())
    name = path.name.removesuffix(".mtx.gz")
    return MatrixInstance(name, graph, sha256(path.read_bytes()).hexdigest(), digest.hexdigest(),
                          field, symmetry, declared_nnz, diagonal, zeros, duplicate_edges)
