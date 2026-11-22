# SAT decision encodings

All three encoders answer whether `AB(G) >= t` for `1 <= t < n`.
The pairwise and staircase encoders use primary variable `x[v,l]`, which has
DIMACS ID `v*n + l` and means vertex `v` receives label `l`.
They add explicit pairwise exactly-one constraints for every vertex
and label, including isolated vertices. Auxiliary IDs start at `n*n + 1`.
For the benchmark, `assignment_amo="sequential"` is available on all three
encoders. It uses shared sequential-counter AMO construction for assignment
constraints. The default remains `"pairwise"` for the original reference
formulation; fixed-threshold results record both choices separately.

`encode_pairwise` adds `(!x[u,p] OR !x[v,q])` for each edge and every
`|p-q| < t`.

`encode_order` uses only primary Boolean variables `y[v,l]`, meaning
`f(v) >= l` for `2 <= l <= n`, with ID `v*(n-1) + l-1`. Monotonicity clauses
make each vertex row a threshold sequence. The label-equality predicate is
`y[v,l] AND NOT y[v,l+1]`, with true/false sentinels at the domain ends.
Pairwise inequality clauses for each label make all vertices distinct. For
each edge and possible label `p` of one endpoint, an implication requires
the other endpoint's label to be at most `p-t` or at least `p+t`.
This is our direct order-variable formulation, using the conventional
[order-encoding variable semantics](https://cspsat.gitlab.io/sugar/docs/order-encoding/).
It has `n*(n-1)` primary variables and no auxiliary variables.
With sequential assignment AMO, extra equality-indicator and counter variables
are auxiliary; order variables remain the primary variables.

`encode_staircase_scl` partitions each vertex's labels into blocks of `t` and
builds exact sequential prefix/suffix OR registers once per incident vertex.
Assignment exactly-one constraints already enforce AMO within and across the
vertex blocks. For each edge and each `t`-label window, AMZ connection clauses
forbid both endpoint registers from being true. A crossing window has one
suffix and one prefix term per endpoint, so distribution gives up to four
binary clauses. The incomplete final block uses only its actual labels.
`add_grouped_scamo` separately provides the grouped SCAMO block construction
and is checked by exhaustive Boolean truth tables; it keeps the two endpoint
literals at each label position together so it cannot create extra windows.

These implementations follow the block/register/AMZ construction in
[Truong et al., ICAART 2025](https://www.scitepress.org/Papers/2025/131246/131246.pdf),
Sections 2–4. The ABP encoder reuses vertex-side registers across edges, but
its exact CNF construction and assignment AMO choice are our implementation
decisions; do not attribute the paper's size or runtime claims to it without
measurement.

Use each result's `decode(model)` to obtain `vertex -> label`, then
`validate_solution(graph, labeling, t)` to independently check the solution.
An UNSAT result at one threshold is only a decision result, not an optimum
certificate on its own.
