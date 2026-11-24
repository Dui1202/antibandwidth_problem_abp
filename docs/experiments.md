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
can use the identical command with `--resume`; it checks dataset, source code,
Python, solver versions and availability, native solver identity, and recorded
hardware characteristics before continuing. An environment mismatch requires a
new output directory. The fingerprint contains no license credentials or unique
machine identifier; the operator must still verify the physical host.

The CP-SAT optimization result supplies a verified pilot threshold for each
instance. If CP-SAT returns no incumbent, the deterministic vertex-order
labeling supplies it. Fixed-threshold tests use this threshold and its successor
when the successor is in `1..n-1`, sharing each method's 600-second budget between
the two tests. SAT optimization first probes one threshold above its verified
lower bound, then uses binary search. It reports `OPTIMAL` only after a matching
upper bound is established. A timeout, resource skip, or backend error does not
by itself establish an optimum.

`optimization.csv` contains one row per instance and method. `fixed.csv` holds
fixed-threshold SAT trials, `trials.csv` holds the SAT optimization search path,
and `solutions.jsonl` holds independently checked labelings. `thresholds.csv`
locks pilot choices, while `metadata.json` records schema version 3, a run ID,
the base commit, source-tree hash, dependency versions, hardware, and run limits.
The commit SHA is the base commit; the source-tree hash identifies uncommitted
benchmark code. Each finished workload has an atomic JSON record under
`records/`; CSV and solution files are rebuilt from those records on resume.
Old-schema runs cannot be resumed with this version. Start a new output directory.
An interrupted CP-SAT pilot is archived under `attempts/` and has no final
threshold. On `--resume`, the pilot is retried before fixed-threshold trials.
A time- or memory-limited pilot remains a final attempt and uses its verified
incumbent or the fallback threshold. Other interrupted workloads remain recorded
and are skipped on resume.

Optimization workers atomically replace an isolated checkpoint after the
fallback is initialized, after SAT decisions and bound changes, on exact solver
progress events, and before returning. On a forced stop the parent checks the
checkpoint identity, validates the labeling again, and recovers completed
trials and bounds. An absent or corrupt checkpoint leaves only the independently
validated fallback. Checkpoints retain evidence, not internal solver search
state; the last event may be lost if termination occurs before its write.
`solution_source` is `SOLVER`, `FALLBACK`, or `CHECKPOINT` for optimization rows;
fixed decisions leave it blank. The workload record also retains a separate
validated `solver_labeling` when a solver found one, even if the selected best
labeling is the fallback.

CP-SAT uses solution and bound callbacks; CP Optimizer uses `Solution` and
`ObjBound` events; CPLEX uses progress and solution listeners; Gurobi uses MIP
callbacks when its license is available. Progress delivery is backend dependent.
CP-SAT does not expose a definitive stop cause for every feasible return, so
such cases use `UNKNOWN` rather than assuming a time limit. The parent's
wall-time and memory reasons take precedence when it kills a worker.

Each experiment CSV has these required columns: `instance`, `n_vertices`,
`n_edges`, `threshold`, `method`, `solver`, `solver_version`, `seed`,
`solution_status`, `termination_reason`, `raw_status`,
`solver_reported_objective`, `solver_best_value`,
`fallback_value`, `best_value`, `has_solver_incumbent`, `solution_source`,
`lower_bound`, `upper_bound`, their sources, `absolute_gap`, `relative_gap`,
`proven_optimal`, `n_primary_vars`, `n_aux_vars`, `n_clauses`,
`encode_seconds`, `solve_seconds`, `total_seconds`, `timeout_seconds`,
`peak_memory_mb`, `hardware`, and `commit_sha`. Workload, assignment AMO,
trial count, and error columns provide additional context. Fields that do not
apply to a method are blank, not fabricated.

Native exact-backend model construction and solver time are not separated in this
version, so their `solve_seconds` field is blank and `total_seconds` is the
measured method call duration. `peak_memory_mb` is the maximum observed worker
RSS, including native descendants; it is sampled, not a perfect high-water mark.

`experiments/analyze.py` derives `summary.csv`, `summary.md`, and vector plots
from the raw CSV files using `cnsplots`. It separates observed (censored) and
completed runtimes, counts fallback-only runs apart from solver incumbents,
and plots verified values, upper bounds, and gaps. Do not treat the two structurally duplicate `bcsstk`
files as independent graph evidence.
