# Small exact optimization adapters

`solve_sat(graph, t, encoder)` answers one decision question: `AB(G) >= t`.
It returns `FEASIBLE` with an independently checked labeling, `INFEASIBLE`,
or `UNKNOWN` with a separate stop reason. `optimize_sat` checks increasing thresholds and returns
`OPTIMAL` only after the next threshold is UNSAT or the upper bound `n-1` is
attained. A timeout may retain an independently checked incumbent.

The CP-SAT and CP Optimizer adapters assign one integer label in `1..n` to
each vertex, enforce all-different labels, and maximize integer `T` subject
to `|y[u]-y[v]| >= T` on every edge. The CPLEX and Gurobi MIP adapters use
binary assignment variables, integer labels, and one binary edge orientation
for each distance disjunction. Their big-M value is `2*(n-1)`, sufficient for
labels and `T` in the documented ranges. These are our implementation choices.

Every returned labeling is checked independently for the permutation and
edge-distance objective. `solution_status` describes the mathematical conclusion:
`OPTIMAL`, `FEASIBLE`, `INFEASIBLE` for fixed-threshold decisions, or `UNKNOWN`.
`termination_reason` independently records `COMPLETED`, `TIME_LIMIT`,
`MEMORY_LIMIT`, `CLAUSE_LIMIT`, `INTERRUPTED`, `ERROR`, or `UNKNOWN`.
Backend status text is retained separately. A backend failure stays an error even
when the benchmark has a verified fallback labeling.
For a feasible CP/MIP incumbent, the solver's objective variable `T` can be
lower than the independently measured minimum edge distance. The former is
recorded as `solver_reported_objective`; the latter is the verified solution
value. A reported `T` above the measured distance is invalid, and an `OPTIMAL`
result requires agreement within numerical tolerance.

Optimization results use the validated incumbent as a lower bound and `n-1` as
a theoretical upper bound. SAT UNSAT decisions and backend objective bounds may
tighten the upper bound. Floating maximization bounds are rounded outward to
an integer. `absolute_gap = upper_bound - lower_bound` and
`relative_gap = absolute_gap / upper_bound`; the latter is stored as a ratio.
An optimum is certified only when the bounds meet. Solver objective values,
fallback values, selected verified values, and their sources remain separate.
The small integration suite checks one-edge, path, and clique graphs against
permutation enumeration. It is a prerequisite for larger benchmarks, not a
performance benchmark itself.
