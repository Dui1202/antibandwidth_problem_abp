"""Independent CP and assignment-MIP optimization baselines."""

import os
from pathlib import Path
import shutil
import sys

from .result import Result, Status, Termination, checked_result, integer_upper_bound


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


def _emit(progress, graph, labeling=None, bound=None):
    if progress is None:
        return
    checked = None
    if labeling is not None:
        checked = checked_result(graph, Status.FEASIBLE, labeling)
        if checked.termination == Termination.ERROR:
            raise ValueError(checked.error)
    progress(checked.labeling if checked else None, integer_upper_bound(bound, graph.n))


def optimize_cp_optimizer(graph, timeout_seconds=None, progress=None) -> Result:
    try:
        from docplex.cp.model import CpoModel
        from docplex.cp.modeler import all_diff, abs_of
        from docplex.cp.solver.cpo_callback import CpoCallback

        if timeout_seconds is not None and timeout_seconds <= 0:
            return Result(Status.UNKNOWN, termination=Termination.TIME_LIMIT, raw_status="not_started")
        model = CpoModel()
        labels = [model.integer_var(min=1, max=graph.n, name=f"y{v}") for v in range(graph.n)]
        objective = model.integer_var(min=1, max=graph.n - 1, name="T")
        model.add(all_diff(labels))
        for u, v in graph.edges:
            model.add(abs_of(labels[u] - labels[v]) >= objective)
        model.maximize(objective)
        if progress is not None:
            class Snapshot(CpoCallback):
                def invoke(self, solver, event, sres):
                    if event in {"Solution", "ObjBound"}:
                        labeling = ({v: int(sres.get_value(labels[v])) for v in range(graph.n)}
                                    if event == "Solution" and sres.is_solution() else None)
                        bounds = sres.get_objective_bounds()
                        _emit(progress, graph, labeling, bounds[0] if bounds else None)
            model.add_solver_callback(Snapshot())
        options = {"execfile": str(cp_optimizer_executable()), "LogVerbosity": "Quiet",
                   "Workers": 1, "RandomSeed": 42}
        if timeout_seconds is not None:
            options["TimeLimit"] = timeout_seconds
        solved = model.solve(**options)
        raw = f"{solved.get_solve_status()}/{solved.get_search_status()}/{solved.get_stop_cause()}"
        status = {"Optimal": Status.OPTIMAL, "Feasible": Status.FEASIBLE,
                  "Infeasible": Status.INFEASIBLE}.get(solved.get_solve_status(), Status.UNKNOWN)
        cause = solved.get_stop_cause()
        termination = (Termination.TIME_LIMIT if cause == "SearchStoppedByLimit"
                       else Termination.INTERRUPTED if cause == "SearchStoppedByAbort"
                       else Termination.ERROR if solved.get_solve_status() == "JobFailed"
                       else Termination.COMPLETED if status in (Status.OPTIMAL, Status.INFEASIBLE)
                       else Termination.UNKNOWN)
        labeling = ({v: int(solved.get_value(labels[v])) for v in range(graph.n)}
                    if solved.is_solution() else None)
        bounds = solved.get_objective_bounds()
        return checked_result(graph, status, labeling, termination=termination, raw_status=raw,
                              upper_bound=integer_upper_bound(bounds[0], graph.n) if bounds else None,
                              reported_objective=solved.get_objective_value() if labeling else None)
    except Exception as exc:
        return Result(Status.UNKNOWN, error=f"{type(exc).__name__}: {exc}", termination=Termination.ERROR)


def optimize_cp_sat(graph, timeout_seconds=None, progress=None) -> Result:
    try:
        from ortools.sat.python import cp_model

        if timeout_seconds is not None and timeout_seconds <= 0:
            return Result(Status.UNKNOWN, termination=Termination.TIME_LIMIT, raw_status="not_started")
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
            solver.parameters.max_time_in_seconds = timeout_seconds
        callback = None
        if progress is not None:
            class Snapshot(cp_model.CpSolverSolutionCallback):
                def on_solution_callback(self):
                    _emit(progress, graph, {v: self.value(labels[v]) for v in range(graph.n)},
                          self.best_objective_bound)
            callback = Snapshot()
            solver.best_bound_callback = lambda bound: _emit(progress, graph, bound=bound)
        code = solver.solve(model, callback)
        status = {cp_model.OPTIMAL: Status.OPTIMAL, cp_model.FEASIBLE: Status.FEASIBLE,
                  cp_model.INFEASIBLE: Status.INFEASIBLE}.get(code, Status.UNKNOWN)
        termination = (Termination.COMPLETED if status in (Status.OPTIMAL, Status.INFEASIBLE)
                       else Termination.UNKNOWN)
        labeling = ({v: solver.value(labels[v]) for v in range(graph.n)}
                    if status in (Status.OPTIMAL, Status.FEASIBLE) else None)
        return checked_result(graph, status, labeling, termination=termination,
                              raw_status=solver.status_name(code),
                              upper_bound=integer_upper_bound(solver.best_objective_bound, graph.n),
                              reported_objective=solver.objective_value if labeling else None)
    except Exception as exc:
        return Result(Status.UNKNOWN, error=f"{type(exc).__name__}: {exc}", termination=Termination.ERROR)


def optimize_cplex(graph, timeout_seconds=None, progress=None) -> Result:
    try:
        from docplex.mp.model import Model
        from docplex.mp.progress import ProgressClock, ProgressListener, SolutionListener

        if timeout_seconds is not None and timeout_seconds <= 0:
            return Result(Status.UNKNOWN, termination=Termination.TIME_LIMIT, raw_status="not_started")
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
            if progress is not None:
                class Bounds(ProgressListener):
                    def __init__(self):
                        super().__init__(ProgressClock.BestBound)
                    def notify_progress(self, data):
                        _emit(progress, graph, bound=data.best_bound)
                class Solutions(SolutionListener):
                    def notify_solution(self, solution):
                        labeling = {v: int(round(solution.get_value(labels[v]))) for v in range(n)}
                        data = self.current_progress_data
                        _emit(progress, graph, labeling, data.best_bound if data else None)
                model.add_progress_listener(Bounds())
                model.add_progress_listener(Solutions())
            model.parameters.threads = 1
            model.parameters.randomseed = 42
            model.parameters.mip.tolerances.mipgap = 0
            model.parameters.mip.tolerances.absmipgap = 0
            if timeout_seconds is not None:
                model.parameters.timelimit = timeout_seconds
            solved = model.solve(log_output=False)
            details = model.solve_details
            code = details.status_code
            status = (Status.OPTIMAL if code == 101 else Status.INFEASIBLE if code == 103
                      else Status.FEASIBLE if solved is not None else Status.UNKNOWN)
            termination = (Termination.TIME_LIMIT if code in (107, 108, 131, 132)
                           else Termination.MEMORY_LIMIT if code in (111, 112)
                           else Termination.INTERRUPTED if code in (113, 114)
                           else Termination.COMPLETED if status in (Status.OPTIMAL, Status.INFEASIBLE)
                           else Termination.UNKNOWN)
            labeling = ({v: int(round(solved.get_value(labels[v]))) for v in range(n)}
                        if solved is not None else None)
            return checked_result(graph, status, labeling, termination=termination,
                                  raw_status=f"{code}: {details.status}",
                                  upper_bound=integer_upper_bound(details.best_bound, n),
                                  reported_objective=solved.get_value(objective) if solved else None)
        finally:
            model.end()
    except Exception as exc:
        return Result(Status.UNKNOWN, error=f"{type(exc).__name__}: {exc}", termination=Termination.ERROR)


def optimize_gurobi(graph, timeout_seconds=None, progress=None) -> Result:
    try:
        import gurobipy as gp

        if timeout_seconds is not None and timeout_seconds <= 0:
            return Result(Status.UNKNOWN, termination=Termination.TIME_LIMIT, raw_status="not_started")
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
                def callback(current, where):
                    if progress is None:
                        return
                    if where == gp.GRB.Callback.MIPSOL:
                        values = current.cbGetSolution(labels)
                        labeling = {v: int(round(values[v])) for v in range(n)}
                        _emit(progress, graph, labeling, current.cbGet(gp.GRB.Callback.MIPSOL_OBJBND))
                    elif where == gp.GRB.Callback.MIP:
                        _emit(progress, graph, bound=current.cbGet(gp.GRB.Callback.MIP_OBJBND))
                model.optimize(callback if progress is not None else None)
                code = model.Status
                status = (Status.OPTIMAL if code == gp.GRB.OPTIMAL
                          else Status.INFEASIBLE if code == gp.GRB.INFEASIBLE
                          else Status.FEASIBLE if model.SolCount else Status.UNKNOWN)
                termination = (Termination.TIME_LIMIT if code == gp.GRB.TIME_LIMIT
                               else Termination.MEMORY_LIMIT if code == gp.GRB.MEM_LIMIT
                               else Termination.INTERRUPTED if code == gp.GRB.INTERRUPTED
                               else Termination.COMPLETED if status in (Status.OPTIMAL, Status.INFEASIBLE)
                               else Termination.UNKNOWN)
                labeling = ({v: int(round(labels[v].X)) for v in range(n)} if model.SolCount else None)
                return checked_result(graph, status, labeling, termination=termination,
                                      raw_status=str(code), upper_bound=integer_upper_bound(model.ObjBound, n),
                                      reported_objective=objective.X if labeling else None)
        finally:
            env.dispose()
    except Exception as exc:
        return Result(Status.UNKNOWN, error=f"{type(exc).__name__}: {exc}", termination=Termination.ERROR)
