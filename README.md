# README.md — Antibandwidth Problem (ABP) SAT Research Project

This file is the working context for AI coding agents and human contributors. Read it before making changes to this repository. Prefer correctness, reproducibility, and evidence over feature count or speculative optimizations.

## 1. Project identity and objective

- **Course:** Các vấn đề hiện đại trong Khoa học máy tính (Modern Issues in Computer Science), VNU-UET, semester 1, academic year 2026–2027.
- **Assignment:** Group Assignment 2, topic 5 — **Antibandwidth Problem (ABP)**.
- **Team:** 2–3 students.
- **Deadline:** **2026-11-30**, as stated in the course introduction slides. Confirm any subsequent instructor announcement separately.
- **Core deliverable:** An independently implemented and validated exact SAT-based ABP solver, comparing **pairwise encoding** against **staircase encoding**, plus an exact non-SAT baseline and reproducible experimental evaluation.
- **Additional deliverables:** Scientific-paper-style report, presentation, public/source-available repository, experimental data, and plots.
- **Preferred implementation language:** Python 3, with PySAT for SAT solvers; use `gurobipy` (Gurobi MIP) and/or OR-Tools CP-SAT for a non-SAT exact comparison.

**Do not confuse ABP (maximization of minimum edge-label distance) with BMP / 2DBMP (bandwidth minimization).** A supplied document named `Mau xay dung bao cao BTL so 1 và BTL so 2.pdf` is a scientific-paper/report exemplar, **not** the ABP algorithm to implement.

## 2. Authoritative sources and source boundaries

Prioritize these documents if they are available in this repository or have been explicitly supplied in the working conversation:

1. `Assignment 2 - requirements.pdf` — mandatory course deliverables. Specifically requests **pairwise and staircase encoding** for ABP; comparison with an exact ILP/CP method; large-instance experiments; Elsevier `cas-sc` report; GitHub/Data Availability; and plots with `cnsplots`.
2. `5 - Antibandwidth Problem - ABP.pdf` — H. X. Truong, T. V. Kieu, K. V. To, _Sequential Counter Encoding for Staircase At-Most-One Constraints_, ICAART 2025, DOI **10.5220/0013124600003890**. Particularly: Sections 2 (SCAMO), 3 (SCL encoding), 4 (ABP formulation), 5 (evaluation).
3. `Module3_AMO ALO Encoding.pdf` — pairwise/binomial and sequential/other cardinality encodings.
4. `SAT Book 300726v1-1.pdf` — SAT-encoding design, propagation, validation, and benchmarking background.
5. `Module 0 - Introduction.pdf` — presentation, teamwork, and assignment-deadline context.
6. `Mau xay dung bao cao BTL so 1 và BTL so 2.pdf` — report structure/style reference; it discusses a different graph problem.

Source PDFs are reference documents, not necessarily committed to this repository. Do not assume a path exists. If a source is absent, say so and do not claim to have verified a formula or an algorithm from it. Explicitly distinguish (a) course requirements, (b) published-paper methods, and (c) our implementation choices.

Paper reference implementations for **study only**, not copying/submitting as our own work:

- https://github.com/TruongXuanHieu-H/StaircaseEncoderSCL
- https://github.com/TruongXuanHieu-H/AntiBandwidthSCL

Cite borrowed algorithms, ideas, benchmark sources, or code dependencies. All submitted code and analysis must represent the team's own work. The course explicitly warns that copying source code or reports may lead to failure.

## 3. Precise mathematical problem and conventions

Input: A simple, undirected, unweighted graph `G = (V, E)` with `n = |V|` and a nonempty edge set. A valid labeling is a bijection:

`f: V -> {1, 2, ..., n}`.

For a labeling `f`, define:

`ab(G, f) = min_{(u,v) in E} |f(u) - f(v)|`.

The ABP optimum is:

`AB(G) = max_{bijections f} ab(G, f)`.

**Decision version:** Given integer threshold `t`, determine whether a bijection exists satisfying

`|f(u) - f(v)| >= t` for every edge `(u,v) in E`.

Conventions:

- In Python, vertex indices are `0..n-1`; graph labels are integers `1..n`.
- Canonicalize undirected edges as `(min(u,v), max(u,v))`; remove duplicates.
- Reject self-loops and malformed endpoints unless explicitly implementing a documented alternative.
- Include isolated vertices in `n` and in the bijection constraints.
- To avoid an undefined minimum on an empty edge set, reject `E = {}` for optimization unless a separately documented convention is introduced and tested.
- The useful threshold domain for `n >= 2` and `E != {}` is `1..n-1`.
- **Monotonicity:** Feasible at threshold `t` implies feasible at all lower thresholds. This permits binary search or successive feasibility tests.
- **Off-by-one warning:** The ICAART paper uses a parameter `k` in the question `AB(G) >= k+1`. Our public API uses `t` directly, so `t = k+1`. Never mix the two silently.

## 4. SAT variable mapping and fundamental constraints

Use one Boolean assignment variable for each vertex/label pair:

`x[v,l] = True  <=>  vertex v receives label l`, for `v in 0..n-1` and `l in 1..n`.

Create a deterministic, documented, collision-free mapping from `(v, l)` to positive DIMACS variable IDs. Allocate auxiliary variables without collisions using a shared ID pool or equivalent allocator.

Mandatory assignment constraints:

1. **Exactly one label per vertex:** `sum_l x[v,l] == 1` for each vertex `v`.
2. **Exactly one vertex per label:** `sum_v x[v,l] == 1` for each label `l`.

Express `ExactlyOne = AtLeastOne + AtMostOne`. For baseline pairwise AMO on variables `a_1, ..., a_r`, add `(!a_i OR !a_j)` for all `i < j`, plus one ALO clause when ExactlyOne is required.

The model decoder must return a complete mapping `vertex -> label`, not merely a SAT assignment. Independently verify the bijection and every edge distance after solving.

## 5. Required encoding A — pairwise

For every undirected edge `(u,v)`, every label pair `p,q in {1..n}` that violates the selected threshold, add:

`(!x[u,p] OR !x[v,q])  whenever |p-q| < t`.

Use explicit pairwise/binomial AMO for the assignment constraints in the reference pairwise baseline, unless an experiment clearly documents a different AMO choice. Count primary variables, auxiliary variables, clauses, and construction time separately.

Avoid silently using a solver's native integer constraints or cardinality helper as a substitute for the required pairwise **SAT encoding**.

## 6. Required encoding B — staircase / SCAMO / SCL

For an edge `(u,v)`, the threshold condition can also be represented by overlapping windows of labels:

`sum_{l=s}^{s+t-1} (x[u,l] + x[v,l]) <= 1` for `s = 1..n-t+1`,

combined with the assignment constraints. This is an equivalent **constraint formulation** of the edge-distance condition when both endpoints have exactly one label.

**Critical distinction:** Naively encoding each overlapping AMO window separately is NOT the optimized **SCL (Sequential Counter Encoding for Ladder constraints)** described in the paper.

Implementation target:

- Study and implement the paper's SCAMO block decomposition and **shared sequential-counter register bits** (Section 3), including cross-block connection clauses.
- For the paper's efficient ABP-specific version (Section 4.2), understand how edge SCAMO constraints are decomposed into vertex-side SCAMO structures and reconnected via zero-count/AMZ conditions, avoiding duplicated structures.
- Keep semantics of auxiliary register bits and their CNF implications explicit and testable. Do not introduce extra window constraints by flattening/interleaving two vertex sequences incorrectly.
- Pay particular attention to short final blocks, `t = 1`, `t = n-1`, and transitions across block boundaries.
- Maintain the same graph, threshold semantics, and assignment constraints as the pairwise solver.
- If a simpler window-by-window staircase encoder is implemented first, name it `staircase_naive` and mark it as a baseline, **not** as a completed SCL implementation.
- Do not claim SCL's published size/runtime advantages before our own measurements confirm them. Fewer clauses do not guarantee lower solve time.

Recommended development order:

1. Implement a small, independently checkable SCAMO encoder and exhaustive tests.
2. Implement reusable SC blocks and test them against the independent reference.
3. Integrate the correct ABP edge constraints.
4. Validate against the pairwise decision model for all small graphs/thresholds feasible to enumerate.
5. Only then consider symmetry breaking, incremental SAT, or additional AMO encodings.

## 7. Optimization search and solver statuses

A SAT check for fixed `t` answers feasibility, not optimality by itself. To certify `AB(G) = t*`:

- Obtain a valid model at threshold `t*`.
- Establish `UNSAT` at `t* + 1`, or use a mathematically proven upper bound equal to `t*`.
- More generally, maintain certified lower and upper bounds until they coincide.

Implement a deterministic threshold-search policy; binary search is acceptable because feasibility is monotone. Distinguish:

- `SAT`: feasible assignment/model verified.
- `UNSAT`: infeasible at that threshold.
- `UNKNOWN` / `TIMEOUT` / `ERROR`: do **not** treat these as `UNSAT`.
- `OPTIMAL`: optimum certified, not just a high-quality incumbent.

Keep wall-clock limits and memory budgets explicit. A timeout may leave a feasible incumbent/lower bound but not a proof of optimality.
The benchmark records mathematical `solution_status` separately from
`termination_reason`. It checkpoints verified incumbents and proven bounds so
forced termination retains recoverable evidence. Every optimization method
receives the same validated vertex-order fallback, which is reported separately
from a solver-discovered incumbent and never masks a backend error. For
maximization, report `LB <= AB(G) <= UB` and gaps `UB-LB` and `(UB-LB)/UB`.

## 8. Exact non-SAT baseline: Gurobi MIP and/or CP-SAT

The course requires comparison with an exact alternative (ILP/MIP/CP). Prefer an independently formulated **Gurobi MIP** baseline if a valid Gurobi license is available; OR-Tools CP-SAT is an acceptable practical alternative.

Suggested exact MIP design (one implementation option, not copied from the paper):

- Binary assignment variables `a[v,l]`, with row/column sums each equal to 1.
- Integer vertex labels `y[v] = sum_l l * a[v,l]`.
- Integer objective variable `T`, with `1 <= T <= n-1`, to maximize.
- For each edge `(u,v)`, a binary orientation variable `z[u,v]`, and big-M disjunction enforcing either `y[u]-y[v] >= T` or `y[v]-y[u] >= T` (e.g., `M = 2*(n-1)` is a sufficient bound for this model). Verify the inequalities and bounds with small exhaustive tests.

A direct fixed-threshold feasibility MIP is also valid if the experiment compares the same decision question. Do not compare a SAT **single-threshold** run against a MIP **complete optimization** run as if they are equivalent workloads.

Gurobi may be installed locally on Linux. License files, activation keys, WLS secrets, credentials, and system-specific absolute paths must **never** be committed. Gurobi is optional for contributors without a license; optional tests should skip clearly when unavailable.

## 9. Data loading, oracle, and test requirements

Provide an independent `validate_solution(graph, labeling, threshold=None)` that checks:

- Every vertex has exactly one label in `1..n`.
- No label is repeated or omitted.
- For each edge, the absolute difference is at least `threshold`, if provided.
- The returned objective equals the minimum edge-label difference.

Required test categories:

1. **Brute-force oracle** on small graphs: enumerate permutations and compute true ABP optimum.
2. **Encoding equivalence:** for the same graph/threshold, pairwise and staircase/SCL return identical SAT/UNSAT status; compare with brute force.
3. **SCAMO truth-table tests:** enumerate small Boolean sequences and verify every sliding-window AMO constraint versus its CNF encoding (existentially over auxiliary variables).
4. **Boundary tests:** `t=1`, `t=n-1`, small `n`, incomplete blocks, isolated vertices, graph with one edge, paths, cycles, cliques, stars.
5. **Decoder tests:** detect duplicate labels, missing assignments, and edge-distance violations.
6. **Input parser tests:** malformed files, duplicate edges, invalid vertex IDs, directed-versus-undirected handling.
7. **Regression tests:** keep a fixture for each fixed bug.

When handling Matrix Market or Harwell–Boeing files, document the conversion from sparse matrices to simple undirected graph edges (e.g., off-diagonal nonzeros, symmetric closure, removal of loops and duplicates); preserve dataset source and preprocessing metadata. Do not claim a particular graph size without verifying the parsed instance.

## 10. Experimental methodology

Two separate experiments must be reported:

**A. Fixed-threshold encoding/feasibility comparison**

- Same `G`, same `t`, same SAT solver version/configuration, same hardware and budgets.
- Compare pairwise vs optimized staircase/SCL, and optionally naive staircase as an ablation.
- Record primary/auxiliary variables, clause count, CNF size if feasible, encoding time, solver time, and total time.

**B. End-to-end ABP optimization comparison**

- Same graph instances and per-instance wall-time limits.
- Compare pairwise SAT search, staircase/SCL SAT search, and Gurobi MIP or CP-SAT.
- Report best feasible value, certified optimal value if proven, status, total elapsed time, memory where measured, and search policy.

Use small synthetic graphs for correctness tests and larger benchmark graphs (the supplied paper uses Harwell–Boeing matrices). Do not treat published runs on different hardware as a controlled head-to-head comparison with our own results.

A machine-readable experimental record should include at least:

`instance, n_vertices, n_edges, threshold, method, solver, solver_version, seed, solution_status, termination_reason, raw_status, solver_reported_objective, solver_best_value, fallback_value, best_value, has_solver_incumbent, solution_source, lower_bound, upper_bound, lower_bound_source, upper_bound_source, absolute_gap, relative_gap, proven_optimal, n_primary_vars, n_aux_vars, n_clauses, encode_seconds, solve_seconds, total_seconds, timeout_seconds, peak_memory_mb, hardware, commit_sha`

- Use a fixed master seed and record generated graphs so experiments are reproducible.
- Use explicit resource limits; keep failure and timeout rows instead of silently dropping them.
- Compare medians or distributions if running multiple repeats; never invent numbers.
- Generate tables and figures from saved experimental data, not manually transcribed results.
- Follow the assignment's instruction to use **cnsplots** for visualization where feasible; document any environment/tool limitations.
- Interpret results carefully: clause count, auxiliary variable count, encoding time, propagation strength, and solving time are different metrics.

## 11. Proposed repository layout (adapt to existing files)

```text
.
├── AGENTS.md
├── README.md
├── pyproject.toml            # or requirements.txt
├── src/abp/
│   ├── graph.py              # parsing, normalization, graph model
│   ├── validation.py         # independent solution checker
│   ├── encoding/
│   │   ├── common.py         # variable IDs, CNF helpers
│   │   ├── pairwise.py
│   │   ├── staircase_naive.py # optional reference implementation
│   │   └── staircase_scl.py  # actual optimized SCL
│   ├── solving/
│   │   ├── sat.py
│   │   ├── search.py
│   │   └── gurobi_mip.py      # optional exact baseline
│   └── cli.py
├── tests/
│   ├── test_oracle.py
│   ├── test_pairwise.py
│   ├── test_scamo.py
│   ├── test_scl.py
│   ├── test_equivalence.py
│   └── test_mip.py
├── data/
│   ├── synthetic/
│   └── benchmark/             # license/source permitting
├── experiments/
│   ├── run.py
│   ├── analyze.py
│   └── plot.py
├── results/                   # reproducible CSV/JSON and metadata
├── report/                    # LaTeX Elsevier cas-sc
└── slides/
```

The tree is **proposed**, not proof that those paths already exist. Inspect the current repo before creating or renaming anything. Keep modules small and avoid unnecessary frameworks, web services, GUIs, or cloud dependencies.

Recommended API contracts (proposals; agree on final signatures before implementing):

```python
encode_pairwise(graph, threshold) -> EncodingResult
encode_staircase_scl(graph, threshold) -> EncodingResult
solve_sat(encoding, solver_name, timeout_seconds=None) -> DecisionResult
optimize_sat(graph, encoder, timeout_seconds=None) -> OptimizationResult
optimize_mip(graph, timeout_seconds=None) -> OptimizationResult
validate_solution(graph, labeling, threshold=None) -> bool
```

`EncodingResult` should carry CNF, variable mapping, original/auxiliary counts, and timing metadata. `DecisionResult` and `OptimizationResult` should distinguish feasibility, proven optimality, and unknown/timeout.

## 12. Coding standards and agent workflow

1. **Inspect before editing.** Read `README.md`, package metadata, current modules, and tests. Do not overwrite existing work or assume a file is absent.
2. **Make small, verifiable changes.** Implement one meaningful behavior at a time and add tests in the same change.
3. **Do not silently modify mathematical semantics.** If changing threshold convention, label ranges, AMO construction, or symmetry breaking, update docs and tests explicitly.
4. **Preserve reproducibility.** Pin or record dependency versions and seeds; separate setup instructions from measured experimental results.
5. **Keep source and evidence honest.** Do not fabricate experiments, optimality proofs, literature claims, or successful tests. Distinguish proposed work from implemented/verified work.
6. **Avoid introducing accidental constraints.** Every added clause must follow from the ABP formulation or be a proven symmetry-breaking/strengthening clause that preserves feasibility under the intended conditions.
7. **Never conflate SCL with naive sliding-window AMO.** Keep implementation names and report terminology faithful to the algorithm implemented.
8. **Security and repository hygiene.** Never commit Gurobi license materials, API keys, tokens, machine identifiers, absolute personal paths, `.venv/`, or confidential datasets.
9. **Do not add large dependencies without justification.** Python + PySAT + one exact alternative + test/plotting tools should suffice.
10. **Run relevant tests and report actual outcomes.** If a dependency, license, source PDF, benchmark, or solver is unavailable, report the blocker precisely instead of claiming success.

When responding to implementation tasks, explain (briefly) what changed, which tests ran, and what remains unverified. Use Vietnamese for human-facing explanations when appropriate; English is acceptable for source code names and scientific report text.

## 13. Report and presentation targets

Report format: **scientific paper**, using the Elsevier `cas-sc` LaTeX template (per assignment). Suggested contents:

1. Abstract and keywords
2. Introduction, problem motivation, contributions
3. Background and related work (ABP, SAT/CNF, AMO/SCAMO/SCL)
4. Methods (pairwise, staircase/SCL, exact baseline, optimization search)
5. Experimental design (instances, hardware/software, reproducibility)
6. Results and discussion (correctness, counts, runtime, timeout/optimality)
7. Conclusion, limitations, future work
8. References and **Data Availability** linking to the actual repository/experiment files

Create slides only from validated findings and clearly identified examples. Do not present unmeasured speedups, fabricated charts, or paper results as our own experiments.

## 14. Definition of done

The assignment is complete only when:

- [ ] Mathematical ABP definition, threshold convention, and graph input contract are documented.
- [ ] Pairwise CNF encoder works and passes independent brute-force tests.
- [ ] Optimized staircase/SCL encoder is implemented and **clearly distinguished** from naive staircase.
- [ ] Both SAT approaches agree on all validated small test cases and return independently verified labelings.
- [ ] Optimization procedure correctly distinguishes `OPTIMAL`, `SAT`, `UNSAT`, and `TIMEOUT/UNKNOWN`.
- [ ] At least one exact ILP/MIP/CP baseline (preferably Gurobi MIP if licensed) is implemented and validated.
- [ ] Reproducible experimental scripts, input manifests, raw records, and figures are available.
- [ ] The scientific report includes substantive analysis, honest limitations, citations, and Data Availability.
- [ ] Presentation slides and submission materials are prepared.
- [ ] No source/report plagiarism, no invented experimental claims, and no sensitive licenses/secrets in Git.

**Priority if time is constrained:** a correct pairwise reference, a demonstrably correct SCL implementation, independent validation, and a small but reproducible exact comparison are more valuable than unverified optimizations or polished presentation visuals.
