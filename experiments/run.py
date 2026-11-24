"""Bounded, resumable ABP benchmark for Matrix Market instances."""

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abp.dataset import load_matrix_market
from abp.graph import Graph
from abp.checkpoint import read_checkpoint, write_checkpoint
from abp.experiment import (SAT_ENCODERS, EXACT_SOLVERS,
                            recover_optimization, run_exact_optimization, run_sat_decision,
                            run_sat_optimization)
from abp.solving.result import Status, Termination
from abp.validation import validate_solution


SCHEMA_VERSION = 3
FIELDS = ["instance", "n_vertices", "n_edges", "workload", "method", "assignment_amo",
          "threshold", "solver", "solver_version", "seed", "solution_status",
          "termination_reason", "raw_status", "solver_reported_objective",
          "solver_best_value", "fallback_value",
          "best_value", "has_solver_incumbent", "solution_source", "lower_bound",
          "upper_bound", "lower_bound_source", "upper_bound_source", "absolute_gap",
          "relative_gap", "proven_optimal", "n_primary_vars", "n_aux_vars", "n_clauses",
          "encode_seconds", "solve_seconds", "total_seconds", "timeout_seconds",
          "peak_memory_mb", "hardware", "commit_sha", "trial_count", "error"]
VERSIONS = {"pairwise": "python-sat", "order": "python-sat", "scl": "python-sat",
            "cp_sat": "ortools", "cp_optimizer": "docplex", "cplex": "docplex",
            "gurobi": "gurobipy"}


def dependency_version(method):
    try:
        return version(VERSIONS[method])
    except PackageNotFoundError:
        return "unavailable"


def hardware_description():
    cpu = platform.processor() or platform.machine()
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as stream:
            cpu = next(line.split(":", 1)[1].strip() for line in stream
                       if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    return f"{cpu}; {platform.system()} {platform.release()}"


def environment_fingerprint(sat_methods, exact_methods):
    """Comparable run environment without license secrets or machine identifiers."""
    methods = list(dict.fromkeys(sat_methods + exact_methods))
    native = {}
    if "cp_optimizer" in exact_methods:
        try:
            from abp.solving.baselines import cp_optimizer_executable
            digest = sha256()
            with cp_optimizer_executable().open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            native["cp_optimizer_binary_sha256"] = digest.hexdigest()
        except (OSError, FileNotFoundError):
            native["cp_optimizer_binary_sha256"] = "unavailable"
    if "cplex" in exact_methods:
        try:
            import cplex
            native["cplex_runtime"] = cplex.Cplex().get_version()
        except Exception:
            native["cplex_runtime"] = "unavailable"
    if "gurobi" in exact_methods:
        try:
            import gurobipy as gp
            native["gurobi_runtime"] = ".".join(map(str, gp.gurobi.version()))
        except Exception:
            native["gurobi_runtime"] = "unavailable"
    usable = {}
    probe_graph = Graph(2, [(0, 1)])
    for method in ("cp_optimizer", "cplex", "gurobi"):
        if method in exact_methods:
            result = EXACT_SOLVERS[method](probe_graph, timeout_seconds=5)
            usable[method] = result.status == Status.OPTIMAL
    try:
        memory_kb = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemTotal:"))
    except (OSError, StopIteration, ValueError):
        memory_kb = None
    return {"python": sys.version, "hardware": hardware_description(),
            "logical_cpus": os.cpu_count(), "physical_memory_kb": memory_kb,
            "versions": {method: dependency_version(method) for method in methods},
            "native": native, "usable": usable}


def check_environment(recorded, current):
    """Name the first changed environment field before mixing result rows."""
    def compare(prefix, old, new):
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                compare(f"{prefix}.{key}" if prefix else key, old.get(key), new.get(key))
        elif old != new:
            raise ValueError(f"resume environment differs at {prefix}: {old!r} != {new!r}")
    compare("", recorded, current)


def commit_sha():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def source_tree_hash():
    digest = sha256()
    for root in (ROOT / "src" / "abp", ROOT / "experiments"):
        for path in sorted(root.rglob("*.py")):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def redact_error(method, error):
    if error and "license" in error.lower():
        return f"{method} license unavailable in this environment"
    if error and "hostid" in error.lower():
        return f"{method} license unavailable in this environment"
    return error


def atomic_text(path, content):
    """Replace an output only after its new contents have reached disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".output-",
                                         delete=False, encoding="utf-8") as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def record_key(instance, workload, method, amo=None, threshold=None):
    return (instance, workload, method, amo or "", threshold)


def load_records(output):
    records = {}
    for path in sorted((output / "records").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        key = tuple(item["key"])
        if path.stem != sha256(json.dumps(key).encode()).hexdigest() or key in records:
            raise ValueError(f"invalid workload record: {path.name}")
        records[key] = item
    return records


def save_record(output, item):
    name = sha256(json.dumps(item["key"]).encode()).hexdigest() + ".json"
    atomic_text(output / "records" / name, json.dumps(item, sort_keys=True))


def project_records(output, records):
    """Rebuild derived files from durable complete-workload records."""
    for filename, rows, fields in (
        ("optimization.csv", [x["row"] for x in records.values() if x["key"][1] == "optimization"], FIELDS),
        ("fixed.csv", [x["row"] for x in records.values() if x["key"][1] == "fixed"], FIELDS),
        ("trials.csv", [t for x in records.values() for t in x["trials"]], FIELDS),
        ("thresholds.csv", [x["threshold_row"] for x in records.values() if x.get("threshold_row")],
         ["instance", "threshold", "source"]),
    ):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        atomic_text(output / filename, stream.getvalue())
    solutions = [s for x in records.values() for s in x["solutions"]]
    atomic_text(output / "solutions.jsonl", "".join(json.dumps(s) + "\n" for s in solutions))


def _rss_kb(pid):
    """Current resident memory of a worker and its native solver children."""
    seen = set()
    def visit(child):
        if child in seen:
            return 0
        seen.add(child)
        total = 0
        try:
            status = Path(f"/proc/{child}/status").read_text()
            match = re.search(r"^VmRSS:\s+(\d+) kB", status, re.MULTILINE)
            total += int(match.group(1)) if match else 0
            children = Path(f"/proc/{child}/task/{child}/children").read_text().split()
            total += sum(visit(int(p)) for p in children)
        except (OSError, ValueError):
            pass
        return total
    return visit(pid)


def run_worker(payload, memory_mb, graph):
    started = monotonic()
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker"],
                               cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    sent = False
    peak_kb = 0
    forced = None
    try:
        while True:
            try:
                stdout, stderr = process.communicate(input=json.dumps(payload) if not sent else None,
                                                     timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                sent = True
                peak_kb = max(peak_kb, _rss_kb(process.pid))
                if peak_kb > memory_mb * 1024:
                    forced = "RESOURCE_LIMIT"
                elif monotonic() - started > payload["wall_seconds"]:
                    forced = "TIMEOUT"
                if forced:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    stdout, stderr = process.communicate()
                    break
    except KeyboardInterrupt:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        return recover_worker(payload, graph, Termination.INTERRUPTED,
                              monotonic() - started, peak_kb / 1024)
    except BaseException:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        raise
    peak_kb = max(peak_kb, _rss_kb(process.pid))
    if forced:
        reason = Termination.MEMORY_LIMIT if forced == "RESOURCE_LIMIT" else Termination.TIME_LIMIT
        return recover_worker(payload, graph, reason, monotonic() - started, peak_kb / 1024)
    try:
        result = json.loads(stdout)
        if process.returncode != 0:
            raise ValueError(stderr[-500:] or f"worker exited {process.returncode}")
        result["peak_memory_mb"] = max(peak_kb / 1024, result.get("peak_memory_mb", 0))
        if result["peak_memory_mb"] > memory_mb:
            return recover_worker(payload, graph, Termination.MEMORY_LIMIT,
                                  monotonic() - started, result["peak_memory_mb"])
        if monotonic() - started > payload["wall_seconds"]:
            return recover_worker(payload, graph, Termination.TIME_LIMIT,
                                  monotonic() - started, result["peak_memory_mb"])
        return result
    except (ValueError, json.JSONDecodeError) as exc:
        reason = Termination.INTERRUPTED if process.returncode and process.returncode < 0 else Termination.ERROR
        return recover_worker(payload, graph, reason, monotonic() - started,
                              peak_kb / 1024, f"worker failed: {exc}")


def recover_worker(payload, graph, reason, elapsed, peak, error=None):
    if payload["workload"] == "fixed":
        summary = {"solution_status": "UNKNOWN", "termination_reason": reason.value,
                   "raw_status": "worker_killed", "best_value": None, "labeling": None,
                   "total_seconds": elapsed, "error": error}
        trials = []
    else:
        checkpoint_path = Path(payload["checkpoint_path"])
        state = read_checkpoint(checkpoint_path, payload["identity"], graph)
        if checkpoint_path.exists() and state is None:
            error = f"invalid checkpoint; {error}" if error else "invalid checkpoint"
        summary = recover_optimization(graph, state, reason, elapsed)
        summary["error"] = error
        trials = summary["trials"]
    return {"summary": summary, "trials": trials, "peak_memory_mb": peak}


def worker():
    import resource
    payload = json.load(sys.stdin)
    graph = load_matrix_market(ROOT / payload["file"]).graph
    method = payload["method"]
    def checkpoint(state):
        write_checkpoint(Path(payload["checkpoint_path"]), payload["identity"], state)
    if payload["workload"] == "fixed":
        summary = run_sat_decision(graph, payload["threshold"], method,
                                   payload["timeout_seconds"], payload["max_clauses"],
                                   payload["assignment_amo"])
        trials = []
    elif method in SAT_ENCODERS:
        summary, trials = run_sat_optimization(graph, method, payload["timeout_seconds"],
                                               payload["max_clauses"], payload["assignment_amo"], checkpoint)
    else:
        summary = run_exact_optimization(graph, method, payload["timeout_seconds"], checkpoint)
        trials = []
    print(json.dumps({"summary": summary, "trials": trials,
                      "peak_memory_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}))


def method_row(instance, workload, method, assignment_amo, timeout, result, peak_memory,
               hardware, sha, seed, threshold=None):
    summary = result.copy()
    summary.pop("labeling", None)
    solver = "g3" if method in SAT_ENCODERS else method
    return {**summary, "instance": instance.name, "n_vertices": instance.graph.n,
            "n_edges": len(instance.graph.edges), "workload": workload, "method": method,
            "assignment_amo": assignment_amo or "", "threshold": threshold,
            "solver": solver, "solver_version": dependency_version(method),
            "seed": seed, "timeout_seconds": timeout, "peak_memory_mb": peak_memory,
            "hardware": hardware, "commit_sha": sha}


def benchmark(args):
    if not Path("/proc/self/status").exists():
        raise RuntimeError("the benchmark memory watchdog requires Linux /proc")
    if args.time_limit <= 0 or args.memory_mb <= 0 or args.max_clauses <= 0:
        raise ValueError("all resource limits must be positive")
    sat_methods = args.sat_methods.split(",")
    exact_methods = args.exact_methods.split(",")
    if set(sat_methods) - SAT_ENCODERS.keys() or set(exact_methods) - EXACT_SOLVERS.keys():
        raise ValueError("unknown method in --sat-methods or --exact-methods")
    if "cp_sat" not in exact_methods:
        raise ValueError("CP-SAT is required for pilot thresholds")
    files = sorted(args.dataset.glob("*.mtx.gz"))
    if not files:
        raise ValueError("no .mtx.gz instances found")
    instances = sorted(((path, load_matrix_market(path)) for path in files),
                       key=lambda item: (item[1].graph.n, item[1].name))
    output = args.output or ROOT / "results" / datetime.now(timezone.utc).strftime("benchmark_%Y%m%dT%H%M%SZ")
    output = output.resolve()
    config = {"dataset": [[instance.name, instance.source_sha256] for _, instance in instances],
              "time_limit": args.time_limit, "memory_mb": args.memory_mb,
              "max_clauses": args.max_clauses, "seed": 42,
              "sat_methods": sat_methods, "exact_methods": exact_methods,
              "legacy_fixed": not args.no_legacy_fixed}
    if output.exists():
        if not args.resume:
            raise ValueError("output exists; use --resume or choose a new directory")
        metadata = json.loads((output / "metadata.json").read_text())
        if (metadata.get("schema_version") != SCHEMA_VERSION or metadata["config"] != config
                or metadata["source_tree_sha256"] != source_tree_hash()):
            raise ValueError("resume schema, configuration, or source differs from original run")
        check_environment(metadata["environment"],
                          environment_fingerprint(sat_methods, exact_methods))
    else:
        output.mkdir(parents=True)
        environment = environment_fingerprint(sat_methods, exact_methods)
        metadata = {"schema_version": SCHEMA_VERSION, "run_id": uuid4().hex,
                    "config": config, "environment": environment,
                    "hardware": environment["hardware"],
                    "commit_sha": commit_sha(), "source_tree_sha256": source_tree_hash(),
                    "python": environment["python"], "started_utc": datetime.now(timezone.utc).isoformat(),
                    "data_source": "supplied data/dataset; original collection provenance not recorded",
                    "versions": environment["versions"]}
        atomic_text(output / "metadata.json", json.dumps(metadata, indent=2))
    seen = {}
    manifest_rows = []
    for _, instance in instances:
        row = instance.manifest_row()
        row["duplicate_of"] = seen.get(instance.graph_hash, "")
        seen.setdefault(instance.graph_hash, instance.name)
        manifest_rows.append(row)
    manifest_stream = io.StringIO()
    manifest_writer = csv.DictWriter(manifest_stream, fieldnames=list(manifest_rows[0]))
    manifest_writer.writeheader()
    manifest_writer.writerows(manifest_rows)
    atomic_text(output / "manifest.csv", manifest_stream.getvalue())
    records = load_records(output)
    project_records(output, records)
    hardware, sha = metadata["hardware"], metadata["commit_sha"]

    def execute(path, instance, workload, method, timeout, assignment_amo=None, threshold=None):
        key = record_key(instance.name, workload, method, assignment_amo, threshold)
        if key in records:
            return records[key]["summary"]
        attempt = uuid4().hex
        identity = {"run_id": metadata["run_id"], "attempt": attempt,
                    "instance": instance.name, "graph_hash": instance.graph_hash,
                    "source_sha256": instance.source_sha256, "workload": workload,
                    "method": method, "solver": "g3" if method in SAT_ENCODERS else method,
                    "assignment_amo": assignment_amo or "",
                    "threshold": threshold, "config": config}
        checkpoint_path = output / "checkpoints" / f"{attempt}.json"
        payload = {"file": str(path.resolve()), "workload": workload,
                   "method": method, "wall_seconds": timeout,
                   "timeout_seconds": max(0.01, timeout - min(2, timeout * 0.2)),
                   "max_clauses": args.max_clauses, "assignment_amo": assignment_amo,
                   "threshold": threshold, "identity": identity,
                   "checkpoint_path": str(checkpoint_path)}
        response = run_worker(payload, args.memory_mb, instance.graph)
        result = response["summary"]
        for item in [result, *response["trials"]]:
            if item.get("labeling") is not None:
                item["labeling"] = {int(vertex): label for vertex, label in item["labeling"].items()}
            if item.get("solver_labeling") is not None:
                item["solver_labeling"] = {int(vertex): label
                                           for vertex, label in item["solver_labeling"].items()}
        result["error"] = redact_error(method, result.get("error"))
        if result.get("labeling") is not None:
            result["best_value"] = validate_solution(instance.graph, result["labeling"],
                                                      threshold if workload == "fixed" else None)
        peak = response["peak_memory_mb"]
        row = method_row(instance, workload, method, assignment_amo, timeout, result,
                         peak, hardware, sha, 42 if method in EXACT_SOLVERS else "", threshold)
        trial_rows = []
        solutions = []
        def add_solution(item, kind, item_amo, item_threshold):
            if item.get("labeling") is None:
                return
            objective = validate_solution(instance.graph, item["labeling"],
                                          item_threshold if kind in ("fixed", "search_trial") else None)
            solutions.append({"instance": instance.name, "workload": kind, "method": method,
                              "assignment_amo": item_amo or "", "threshold": item_threshold,
                              "objective": objective,
                              "solver_reported_objective": item.get("solver_reported_objective"),
                              "solution_source": item.get("solution_source", "SOLVER"),
                              "labeling": item["labeling"]})
        for trial in response["trials"]:
            trial_rows.append(method_row(instance, "search_trial", method, assignment_amo,
                                         timeout, trial, peak, hardware, sha, "", trial["threshold"]))
            add_solution(trial, "search_trial", assignment_amo, trial["threshold"])
        add_solution(result, workload, assignment_amo, threshold)
        if (workload == "optimization" and result.get("solver_labeling") is not None
                and (result["solution_source"] == "FALLBACK"
                     or result["solver_labeling"] != result["labeling"])):
            solver_value = validate_solution(instance.graph, result["solver_labeling"])
            if solver_value != result["solver_best_value"]:
                raise ValueError("solver incumbent value disagrees with its labeling")
            solutions.append({"instance": instance.name, "workload": "solver_incumbent",
                              "method": method, "assignment_amo": assignment_amo or "",
                              "threshold": None, "objective": solver_value,
                              "solver_reported_objective": result.get("solver_reported_objective"),
                              "solution_source": "SOLVER", "labeling": result["solver_labeling"]})
        threshold_row = None
        if workload == "optimization" and method == "cp_sat":
            threshold_row = {"instance": instance.name, "threshold": result["best_value"],
                             "source": "cp_sat_incumbent" if result.get("has_solver_incumbent")
                             else "vertex_order"}
        item = {"key": key, "summary": result, "row": row, "trials": trial_rows,
                "solutions": solutions, "threshold_row": threshold_row}
        if workload == "optimization" and method == "cp_sat" and result["termination_reason"] == "INTERRUPTED":
            item["attempt_identity"] = identity
            atomic_text(output / "attempts" / f"{attempt}.json", json.dumps(item, sort_keys=True))
            checkpoint_path.unlink(missing_ok=True)
            raise KeyboardInterrupt
        save_record(output, item)
        records[key] = item
        project_records(output, records)
        checkpoint_path.unlink(missing_ok=True)
        if result["termination_reason"] == "INTERRUPTED":
            raise KeyboardInterrupt
        print(f"{instance.name:12} {workload:12} {method:15} {assignment_amo or '':10} "
              f"{str(threshold or ''):5} {result['solution_status']:12} "
              f"{result['termination_reason']:12} {result.get('best_value')}", flush=True)
        return result

    for path, instance in instances:
        execute(path, instance, "optimization", "cp_sat", args.time_limit)
        cp_record = records[record_key(instance.name, "optimization", "cp_sat")]
        threshold = int(cp_record["threshold_row"]["threshold"])
        for method in sat_methods + [m for m in exact_methods if m != "cp_sat"]:
            execute(path, instance, "optimization", method, args.time_limit,
                    "sequential" if method in SAT_ENCODERS else None)
        thresholds = [threshold]
        if threshold < instance.graph.n - 1:
            thresholds.append(threshold + 1)
        for method in sat_methods:
            for amo in (["sequential", "pairwise"] if not args.no_legacy_fixed else ["sequential"]):
                for tested in thresholds:
                    execute(path, instance, "fixed", method, args.time_limit / len(thresholds),
                            amo, tested)
    print(f"Results: {output}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "dataset")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--time-limit", type=float, default=600)
    parser.add_argument("--memory-mb", type=int, default=8192)
    parser.add_argument("--max-clauses", type=int, default=30_000_000)
    parser.add_argument("--sat-methods", default="pairwise,order,scl")
    parser.add_argument("--exact-methods", default="cp_sat,cp_optimizer,cplex,gurobi")
    parser.add_argument("--no-legacy-fixed", action="store_true")
    parser.add_argument("--resume", action="store_true")
    previous_term = signal.getsignal(signal.SIGTERM)
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        benchmark(parser.parse_args())
    finally:
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    main()
