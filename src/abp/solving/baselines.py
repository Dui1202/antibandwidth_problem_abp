"""Independent CP and assignment-MIP optimization baselines."""

import os
from pathlib import Path
import shutil
import sys

from .result import Result, Status, checked_result


def cp_optimizer_executable() -> Path:
    """Find the native engine without requiring an activated shell PATH."""
    override = os.environ.get("ABP_CP_OPTIMIZER")
    if override:
        if Path(override).is_file() and os.access(override, os.X_OK):
            return Path(override).resolve()
        raise FileNotFoundError("ABP_CP_OPTIMIZER does not name an executable file")
    candidates = [Path(sys.executable).parent / "cpoptimizer", shutil.which("cpoptimizer")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate).resolve()
    raise FileNotFoundError("CP Optimizer executable not found; set ABP_CP_OPTIMIZER")


def optimize_cp_optimizer(graph, timeout_seconds=None) -> Result:
    try:
        from docplex.cp.model import CpoModel
        from docplex.cp.modeler import all_diff, abs_of

        model = CpoModel()
        labels = [model.integer_var(min=1, max=graph.n, name=f"y{v}") for v in range(graph.n)]
        objective = model.integer_var(min=1, max=graph.n - 1, name="T")
        model.add(all_diff(labels))
        for u, v in graph.edges:
            model.add(abs_of(labels[u] - labels[v]) >= objective)
        model.maximize(objective)
        options = {"execfile": str(cp_optimizer_executable()), "LogVerbosity": "Quiet",
                   "Workers": 1, "RandomSeed": 42}
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                return Result(Status.TIMEOUT)
            options["TimeLimit"] = timeout_seconds
        solved = model.solve(**options)
        solve_status = solved.get_solve_status()
        status = {"Optimal": Status.OPTIMAL, "Feasible": Status.FEASIBLE,
                  "Infeasible": Status.INFEASIBLE}.get(
                      solve_status, Status.TIMEOUT if timeout_seconds is not None
                      else Status.FEASIBLE if solved.is_solution() else Status.ERROR)
        labeling = ({v: int(solved.get_value(labels[v])) for v in range(graph.n)}
                    if solved.is_solution() else None)
        return checked_result(graph, status, labeling,
                              reported_objective=solved.get_objective_value() if labeling else None)
    except Exception as exc:
        return Result(Status.ERROR, error=f"{type(exc).__name__}: {exc}")


def optimize_cp_sat(graph, timeout_seconds=None) -> Result:
    try:
        from ortools.sat.python import cp_model

        model = cp_model.CpModel()
        labels = [model.new_int_var(1, graph.n, f"y{v}") for v in range(graph.n)]
        model.add_all_different(labels)
        objective = model.new_int_var(1, graph.n - 1, "T")
        for u, v in graph.edges:
            delta = model.new_int_var(-(graph.n - 1), graph.n - 1, f"delta_{u}_{v}")
            distance = model.new_int_var(0, graph.n - 1, f"distance_{u}_{v}")
            model.add(delta == labels[u] - labels[v])
            model.add_abs_equality(distance, delta)
            model.add(distance >= objective)
        model.maximize(objective)
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 42
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                return Result(Status.TIMEOUT)
            solver.parameters.max_time_in_seconds = timeout_seconds
        code = solver.solve(model)
        status = {cp_model.OPTIMAL: Status.OPTIMAL, cp_model.FEASIBLE: Status.FEASIBLE,
                  cp_model.INFEASIBLE: Status.INFEASIBLE,
                  cp_model.UNKNOWN: Status.TIMEOUT if timeout_seconds is not None
                  else Status.ERROR}.get(code, Status.ERROR)
        labeling = ({v: solver.value(labels[v]) for v in range(graph.n)}
                    if code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None)
        return checked_result(graph, status, labeling,
                              reported_objective=solver.objective_value if labeling else None)
    except Exception as exc:
        return Result(Status.ERROR, error=f"{type(exc).__name__}: {exc}")


def optimize_cplex(graph, timeout_seconds=None) -> Result:
    try:
        from docplex.mp.model import Model

        if timeout_seconds is not None and timeout_seconds <= 0:
            return Result(Status.TIMEOUT)
        model = Model(name="abp")
        try:
            n = graph.n
            assignment = {(v, l): model.binary_var(name=f"a_{v}_{l}")
                          for v in range(n) for l in range(1, n + 1)}
            labels = [model.integer_var(lb=1, ub=n, name=f"y_{v}") for v in range(n)]
            objective = model.integer_var(lb=1, ub=n - 1, name="T")
            for v in range(n):
                model.add_constraint(model.sum(assignment[v, l] for l in range(1, n + 1)) == 1)
                model.add_constraint(labels[v] == model.sum(l * assignment[v, l] for l in range(1, n + 1)))
            for l in range(1, n + 1):
                model.add_constraint(model.sum(assignment[v, l] for v in range(n)) == 1)
            big_m = 2 * (n - 1)
            for u, v in graph.edges:
                direction = model.binary_var(name=f"z_{u}_{v}")
                model.add_constraint(labels[u] - labels[v] + big_m * (1 - direction) >= objective)
                model.add_constraint(labels[v] - labels[u] + big_m * direction >= objective)
            model.maximize(objective)
            model.parameters.threads = 1
            model.parameters.randomseed = 42
            model.parameters.mip.tolerances.mipgap = 0
            model.parameters.mip.tolerances.absmipgap = 0
            if timeout_seconds is not None:
                model.parameters.timelimit = timeout_seconds
            solved = model.solve(log_output=False)
            code = model.solve_details.status_code
            status = (Status.OPTIMAL if code == 101 else Status.INFEASIBLE if code == 103
                      else Status.TIMEOUT if code in (107, 108, 131, 132)
                      else Status.FEASIBLE if solved is not None else Status.ERROR)
            labeling = ({v: int(round(solved.get_value(labels[v]))) for v in range(n)}
                        if solved is not None else None)
            return checked_result(graph, status, labeling,
                                  error=None if status != Status.ERROR else model.solve_details.status,
                                  reported_objective=solved.get_value(objective) if solved else None)
        finally:
            model.end()
    except Exception as exc:
        return Result(Status.ERROR, error=f"{type(exc).__name__}: {exc}")


def optimize_gurobi(graph, timeout_seconds=None) -> Result:
    try:
        import gurobipy as gp

        if timeout_seconds is not None and timeout_seconds <= 0:
            return Result(Status.TIMEOUT)
        env = gp.Env(empty=True)
        try:
            env.setParam("OutputFlag", 0)
            env.start()
            with gp.Model(env=env) as model:
                n = graph.n
                assignment = model.addVars(range(n), range(1, n + 1), vtype=gp.GRB.BINARY, name="a")
                labels = model.addVars(range(n), lb=1, ub=n, vtype=gp.GRB.INTEGER, name="y")
                objective = model.addVar(lb=1, ub=n - 1, vtype=gp.GRB.INTEGER, name="T")
                for v in range(n):
                    model.addConstr(gp.quicksum(assignment[v, l] for l in range(1, n + 1)) == 1)
                    model.addConstr(labels[v] == gp.quicksum(l * assignment[v, l] for l in range(1, n + 1)))
                for l in range(1, n + 1):
                    model.addConstr(gp.quicksum(assignment[v, l] for v in range(n)) == 1)
                big_m = 2 * (n - 1)
                for u, v in graph.edges:
                    direction = model.addVar(vtype=gp.GRB.BINARY, name=f"z_{u}_{v}")
                    model.addConstr(labels[u] - labels[v] + big_m * (1 - direction) >= objective)
                    model.addConstr(labels[v] - labels[u] + big_m * direction >= objective)
                model.setObjective(objective, gp.GRB.MAXIMIZE)
                model.Params.Threads = 1
                model.Params.Seed = 42
                model.Params.MIPGap = 0
                model.Params.MIPGapAbs = 0
                if timeout_seconds is not None:
                    model.Params.TimeLimit = timeout_seconds
                model.optimize()
                status = (Status.OPTIMAL if model.Status == gp.GRB.OPTIMAL
                          else Status.INFEASIBLE if model.Status == gp.GRB.INFEASIBLE
                          else Status.TIMEOUT if model.Status == gp.GRB.TIME_LIMIT
                          else Status.FEASIBLE if model.SolCount else Status.ERROR)
                labeling = ({v: int(round(labels[v].X)) for v in range(n)} if model.SolCount else None)
                return checked_result(graph, status, labeling,
                                      error=None if status != Status.ERROR else f"Gurobi status {model.Status}",
                                      reported_objective=objective.X if labeling else None)
        finally:
            env.dispose()
    except Exception as exc:
        return Result(Status.ERROR, error=f"{type(exc).__name__}: {exc}")
