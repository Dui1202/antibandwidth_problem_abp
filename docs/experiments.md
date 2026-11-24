# Dataset experiment

`experiments/run.py` reads all `data/dataset/*.mtx.gz` files and runs three SAT
encoders (`pairwise`, `order`, `scl`) and four exact optimization backends
(`cp_sat`, `cp_optimizer`, `cplex`, `gurobi`). The main SAT comparison uses
sequential assignment AMO in all three methods. Fixed-threshold trials also
measure each original pairwise-assignment version where resources allow.
Instances run in ascending vertex count, with name as the tie breaker.

## Input conversion

Only square Matrix Market coordinate matrices with `pattern`, `real`, or
`integer` fields and `general` or `symmetric` symmetry are accepted. Every
off-diagonal **nonzero** stored position creates an undirected edge. Diagonal
positions and explicit numeric zeros are ignored; reciprocal positions collapse
to one edge. All matrix rows remain graph vertices, including isolated rows.
`manifest.csv` records source and normalized-graph SHA-256 hashes, dimensions,
and conversion counts. `bcsstk06` and `bcsstk07` have different source hashes
but the same normalized graph hash. The original collection provenance is not
recorded in this repository.

## Reproduce the bounded run

From the repository root, with the optional exact backends installed and
Gurobi running in its licensed host environment:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python experiments/run.py --output results/benchmark_run
.venv/bin/python experiments/analyze.py results/benchmark_run
```

The benchmark runner requires Linux `/proc` for process-tree memory tracking.

The defaults are 600 seconds (10 minutes) per method and instance for each
workload, 8 GiB (8192 MiB) resident memory per worker, 30 million SAT clauses,
CP/native solver single thread settings, and seed 42 where supported. A
two-second solver reporting margin fits inside each 600-second wall budget.
The parent process enforces wall
time and memory, including native CP Optimizer child processes. A stopped run
can use the identical command with `--resume`; it checks dataset and source
hashes before continuing. The run must use the same source code when resumed.

The CP-SAT optimization result supplies a verified pilot threshold for each
instance. If CP-SAT returns no incumbent, the deterministic vertex-order
labeling supplies it. Fixed-threshold tests use this threshold and its successor
when the successor is in `1..n-1`, sharing each method's 600-second budget between
the two tests. SAT optimization first probes one threshold above its verified
lower bound, then uses binary search. It reports `OPTIMAL` only after a matching
upper bound is established. A timeout, resource skip, or backend error cannot
establish an optimum.

`optimization.csv` contains one row per instance and method. `fixed.csv` holds
fixed-threshold SAT trials, `trials.csv` holds the SAT optimization search path,
and `solutions.jsonl` holds independently checked labelings. `thresholds.csv`
locks pilot choices, while `metadata.json` records the base commit, source-tree
hash, dependency versions, hardware, and run limits. The commit SHA is the base
commit; the source-tree hash identifies uncommitted benchmark code.

Each experiment CSV has these required columns: `instance`, `n_vertices`,
`n_edges`, `threshold`, `method`, `solver`, `solver_version`, `seed`, `status`,
`best_value`, `proven_optimal`, `n_primary_vars`, `n_aux_vars`, `n_clauses`,
`encode_seconds`, `solve_seconds`, `total_seconds`, `timeout_seconds`,
`peak_memory_mb`, `hardware`, and `commit_sha`. Workload, assignment AMO,
trial count, and error columns provide additional context. Fields that do not
apply to a method are blank, not fabricated.

Native exact-backend model construction and solver time are not separated in this
version, so their `solve_seconds` field is blank and `total_seconds` is the
measured method call duration. `peak_memory_mb` is the maximum observed worker
RSS, including native descendants; it is sampled, not a perfect high-water mark.

`experiments/analyze.py` derives `summary.csv`, `summary.md`, and vector plots
from the raw CSV files using `cnsplots`. Completed-run medians exclude timed-out
and resource-limited rows. Do not treat the two structurally duplicate `bcsstk`
files as independent graph evidence.
