# Small exact optimization adapters

`solve_sat(graph, t, encoder)` answers one decision question: `AB(G) >= t`.
It returns `FEASIBLE` with an independently checked labeling, `INFEASIBLE`,
`TIMEOUT`, or `ERROR`. `optimize_sat` checks increasing thresholds and returns
`OPTIMAL` only after the next threshold is UNSAT or the upper bound `n-1` is
attained. A timeout may retain an independently checked incumbent.

The CP-SAT and CP Optimizer adapters assign one integer label in `1..n` to
each vertex, enforce all-different labels, and maximize integer `T` subject
to `|y[u]-y[v]| >= T` on every edge. The CPLEX and Gurobi MIP adapters use
binary assignment variables, integer labels, and one binary edge orientation
for each distance disjunction. Their big-M value is `2*(n-1)`, sufficient for
labels and `T` in the documented ranges. These are our implementation choices.

Every returned labeling is checked independently for the permutation and
edge-distance objective. `OPTIMAL` means the backend proved the optimum;
`FEASIBLE` means an incumbent exists without proof; `INFEASIBLE` applies to a
fixed-threshold decision check; `TIMEOUT` means the budget ended and may carry
an incumbent; `ERROR` means a runtime, license, model, or validation failure.
The small integration suite checks one-edge, path, and clique graphs against
permutation enumeration. It is a prerequisite for larger benchmarks, not a
performance benchmark itself.
