# Local environment

This repository contains the project instructions, three SAT decision encodings, SAT threshold search, and small exact optimization baselines. Large experiments and the report are still to be implemented.

The package starts under `src/abp/`. Add encoders under `src/abp/encoding/`, solving routines under `src/abp/solving/`, and tests under `tests/`. The `data/`, `experiments/`, `results/`, `report/`, and `slides/` directories are reserved for the corresponding research artifacts. Empty directories use `.gitkeep` so Git can track the layout.

Use Python 3.11 or newer. On Linux or macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Run all tests before any large experiment:

```bash
.venv/bin/python -m pytest -q
```

The exact solver formulations and status meanings are documented in
`docs/solvers.md`.

Verify the SAT installation independently:

```bash
.venv/bin/python -c "from pysat.solvers import Solver; s = Solver(name='g3'); s.add_clause([1]); assert s.solve(); s.delete(); print('PySAT OK')"
```

Install optional tools only for the experiment you run:

```bash
.venv/bin/python -m pip install -r requirements-cp.txt
.venv/bin/python -m pip install -r requirements-gurobi.txt
.venv/bin/python -m pip install -r requirements-plot.txt
```

For the four exact baselines together, use `requirements-verified.txt` (direct
pins) or `requirements-lock-py314.txt` (all packages observed in the verified
Python 3.14.10 environment). The lock snapshot does not include the native CP
Optimizer executable, CPLEX Studio installation, or Gurobi license.

IBM CP Optimizer is launched through `docplex` using the native executable
next to the active Python interpreter, for example `.venv/bin/cpoptimizer`.
No manual `PATH` change is needed. Set `ABP_CP_OPTIMIZER` to an executable path
only when the engine lives elsewhere. A local solve log identified the engine
as **CP Optimizer 22.2.0.0**; this is separate from `docplex` **2.32.264**.

Gurobi **14.0.0** returned `HostID mismatch (licensed to ..., hostid is 0)`
inside the sandbox. The same tiny model solved optimally in the licensed host
environment. Run Gurobi experiments only in that licensed environment; the
adapter reports a licensing error as `ERROR` when the license is unavailable.
No license files, IDs, or credentials belong in the repository.

Gurobi needs a valid license configured outside this repository. Never commit license files or activation credentials. CP-SAT is the license-free exact alternative. The plot dependency is separate because it brings in a larger scientific stack.

Record the actual environment with `.venv/bin/python -m pip freeze` alongside experimental results. The requirement files pin direct dependencies; transitive dependencies and solver configuration must also be recorded for reproducible measurements. Source PDFs are not present in this checkout; the SCL paper is linked in `docs/encodings.md`.
