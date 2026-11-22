"""Shared sequential-counter blocks for grouped staircase AMO constraints.

Each position is a label and contains both endpoint assignment literals.
Keeping positions grouped avoids the extra windows introduced by flattening.
"""

from time import perf_counter

from .common import Builder, assignment_constraints, check_threshold, variable


def _or_prefixes(builder: Builder, literals: list[int]) -> list[int]:
    """Exact prefix-OR registers; a register is true iff its prefix has a true literal."""
    registers = [literals[0]]
    for literal in literals[1:]:
        previous = registers[-1]
        current = builder.fresh()
        builder.add(-literal, current)
        builder.add(-previous, current)
        builder.add(-current, literal, previous)
        registers.append(current)
    return registers


def add_grouped_scamo(builder: Builder, groups: list[tuple[int, ...]], width: int) -> None:
    """AMO for every consecutive `width` groups using reusable SC blocks.

    Blocks have `width` groups (last may be short). Each has an AMO
    sequential counter and shared prefix/suffix OR registers. Adjacent
    blocks are joined by one AMZ clause for every crossing window.
    """
    if not 1 <= width <= len(groups) or any(not group for group in groups):
        raise ValueError("invalid SCAMO groups or width")
    blocks = [groups[i:i + width] for i in range(0, len(groups), width)]
    previous_suffix = None
    previous_size = 0
    for block_index, block in enumerate(blocks):
        literals = [literal for group in block for literal in group]
        prefix = _or_prefixes(builder, literals)
        for literal, previous in zip(literals[1:], prefix[:-1]):
            builder.add(-literal, -previous)
        suffix = _or_prefixes(builder, list(reversed(literals)))
        if previous_suffix is not None:
            for right_count in range(1, min(width, len(block) + 1)):
                left_count = width - right_count
                if left_count > previous_size:
                    continue
                left_literal_count = sum(len(group) for group in blocks[block_index - 1][-left_count:])
                right_literal_count = sum(len(group) for group in block[:right_count])
                builder.add(-previous_suffix[left_literal_count - 1], -prefix[right_literal_count - 1])
        previous_suffix = suffix
        previous_size = len(block)


def encode_staircase_scl(graph, threshold: int, *, assignment_amo="pairwise", max_clauses=None):
    """ABP-specific SCL: share each vertex's block registers across edges."""
    check_threshold(graph, threshold)
    started = perf_counter()
    n = graph.n
    builder = Builder(n * n, max_clauses)
    assignment_constraints(builder, n, assignment_amo)
    incident_vertices = {vertex for edge in graph.edges for vertex in edge}
    registers = {}
    for vertex in sorted(incident_vertices):
        blocks = []
        for start in range(1, n + 1, threshold):
            literals = [variable(n, vertex, label)
                        for label in range(start, min(n, start + threshold - 1) + 1)]
            # Vertex exactly-one already supplies every block AMO. These
            # exact OR registers are the reusable AMZ sub-expressions.
            blocks.append((_or_prefixes(builder, literals),
                           _or_prefixes(builder, list(reversed(literals)))))
        registers[vertex] = blocks

    def window_terms(vertex: int, start: int) -> tuple[int, ...]:
        end = start + threshold - 1
        left_block, right_block = (start - 1) // threshold, (end - 1) // threshold
        left_start = left_block * threshold + 1
        if left_block == right_block:
            return (registers[vertex][left_block][0][threshold - 1],)
        left_count = left_start + threshold - start
        right_count = end - right_block * threshold
        return (registers[vertex][left_block][1][left_count - 1],
                registers[vertex][right_block][0][right_count - 1])

    for u, v in graph.edges:
        for start in range(1, n - threshold + 2):
            # AMZ(left window) OR AMZ(right window). When a window
            # straddles blocks, distribute the two disjunctions to CNF.
            for left in window_terms(u, start):
                for right in window_terms(v, start):
                    builder.add(-left, -right)
    return builder.result(graph, threshold, started)
