"""Bounded, resumable ABP benchmark for Matrix Market instances."""

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abp.dataset import load_matrix_market
from abp.experiment import (SAT_ENCODERS, EXACT_SOLVERS, fallback_labeling,
                            run_exact_optimization, run_sat_decision,
                            run_sat_optimization)
from abp.validation import validate_solution


FIELDS = ["instance", "n_vertices", "n_edges", "workload", "method", "assignment_amo",
          "threshold", "solver", "solver_version", "seed", "status", "best_value",
          "proven_optimal", "n_primary_vars", "n_aux_vars", "n_clauses",
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


def read_rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def append_row(path, row, fields=FIELDS):
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        if stream.tell() == 0:
            writer.writeheader()
        writer.writerow(row)


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


def run_worker(payload, memory_mb):
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
        return {"summary": {"status": forced, "best_value": None, "proven_optimal": False,
                            "error": "worker exceeded memory limit" if forced == "RESOURCE_LIMIT"
                            else "worker exceeded wall-time limit",
                            "total_seconds": monotonic() - started}, "trials": [],
                "peak_memory_mb": peak_kb / 1024}
    try:
        result = json.loads(stdout)
        if process.returncode != 0:
            raise ValueError(stderr[-500:] or f"worker exited {process.returncode}")
        result["peak_memory_mb"] = max(peak_kb / 1024, result.get("peak_memory_mb", 0))
        if result["peak_memory_mb"] > memory_mb:
            return {"summary": {"status": "RESOURCE_LIMIT", "best_value": None,
                                "proven_optimal": False, "error": "worker exceeded memory limit",
                                "total_seconds": monotonic() - started}, "trials": [],
                    "peak_memory_mb": result["peak_memory_mb"]}
        return result
    except (ValueError, json.JSONDecodeError) as exc:
        return {"summary": {"status": "ERROR", "best_value": None, "proven_optimal": False,
                            "error": f"worker failed: {exc}", "total_seconds": monotonic() - started},
                "trials": [], "peak_memory_mb": peak_kb / 1024}


def worker():
    import resource
    payload = json.load(sys.stdin)
    graph = load_matrix_market(ROOT / payload["file"]).graph
    method = payload["method"]
    if payload["workload"] == "fixed":
        summary = run_sat_decision(graph, payload["threshold"], method,
                                   payload["timeout_seconds"], payload["max_clauses"],
                                   payload["assignment_amo"])
        trials = []
    elif method in SAT_ENCODERS:
        summary, trials = run_sat_optimization(graph, method, payload["timeout_seconds"],
                                               payload["max_clauses"], payload["assignment_amo"])
    else:
        summary = run_exact_optimization(graph, method, payload["timeout_seconds"])
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


def record_solution(path, known, instance, workload, method, assignment_amo, result, threshold=None):
    key = (instance.name, workload, method, assignment_amo or "", threshold)
    if result.get("labeling") is not None and key not in known:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"instance": instance.name, "workload": workload,
                                     "method": method, "assignment_amo": assignment_amo or "",
                                     "threshold": threshold,
                                     "objective": result["best_value"],
                                     "labeling": result["labeling"]}) + "\n")
        known.add(key)


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
        old_metadata = json.loads((output / "metadata.json").read_text())
        if old_metadata["config"] != config or old_metadata["source_tree_sha256"] != source_tree_hash():
            raise ValueError("resume configuration differs from original run")
    else:
        output.mkdir(parents=True)
        (output / "metadata.json").write_text(json.dumps({"config": config,
             "hardware": hardware_description(), "commit_sha": commit_sha(),
             "source_tree_sha256": source_tree_hash(),
             "python": sys.version, "started_utc": datetime.now(timezone.utc).isoformat(),
             "data_source": "supplied data/dataset; original collection provenance not recorded",
             "versions": {m: dependency_version(m) for m in sat_methods + exact_methods}}, indent=2))
        seen = {}
        for _, instance in instances:
            row = instance.manifest_row()
            row["duplicate_of"] = seen.get(instance.graph_hash, "")
            seen.setdefault(instance.graph_hash, instance.name)
            append_row(output / "manifest.csv", row, list(row))
    metadata = json.loads((output / "metadata.json").read_text())
    hardware, sha = metadata["hardware"], metadata["commit_sha"]
    optimization_path = output / "optimization.csv"
    fixed_path = output / "fixed.csv"
    trials_path = output / "trials.csv"
    solutions_path = output / "solutions.jsonl"
    thresholds_path = output / "thresholds.csv"
    done_opt = {(r["instance"], r["method"]) for r in read_rows(optimization_path)}
    done_fixed = {(r["instance"], r["method"], r["assignment_amo"], r["threshold"])
                  for r in read_rows(fixed_path)}
    done_trials = {(r["instance"], r["method"], r["assignment_amo"], r["threshold"])
                   for r in read_rows(trials_path)}
    known_solutions = set()
    if solutions_path.exists():
        for line in solutions_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            known_solutions.add((item["instance"], item["workload"], item["method"],
                                 item.get("assignment_amo", ""), item["threshold"]))
    chosen = {r["instance"]: int(r["threshold"]) for r in read_rows(thresholds_path)}

    def execute(path, instance, workload, method, timeout, assignment_amo=None, threshold=None):
        payload = {"file": str(path.resolve()), "workload": workload,
                   "method": method, "wall_seconds": timeout,
                   "timeout_seconds": max(0.01, timeout - min(2, timeout * 0.2)),
                   "max_clauses": args.max_clauses,
                   "assignment_amo": assignment_amo, "threshold": threshold}
        response = run_worker(payload, args.memory_mb)
        result = response["summary"]
        result["error"] = redact_error(method, result.get("error"))
        if (workload == "optimization" and method in SAT_ENCODERS
                and result.get("best_value") is None):
            result["labeling"] = fallback_labeling(instance.graph)
            result["best_value"] = validate_solution(instance.graph, result["labeling"])
        peak = response["peak_memory_mb"]
        row = method_row(instance, workload, method, assignment_amo, timeout, result,
                         peak, hardware, sha, 42 if method in EXACT_SOLVERS else "", threshold)
        for trial in response["trials"]:
            trial_row = method_row(instance, "search_trial", method, assignment_amo, timeout,
                                   trial, peak, hardware, sha, "", trial["threshold"])
            trial_key = (instance.name, method, assignment_amo or "", str(trial["threshold"]))
            if trial_key not in done_trials:
                append_row(trials_path, trial_row)
                done_trials.add(trial_key)
            record_solution(solutions_path, known_solutions, instance, "search_trial", method,
                            assignment_amo, trial, trial["threshold"])
        record_solution(solutions_path, known_solutions, instance, workload, method,
                        assignment_amo, result, threshold)
        append_row(optimization_path if workload == "optimization" else fixed_path, row)
        print(f"{instance.name:12} {workload:12} {method:15} {assignment_amo or '':10} "
              f"{str(threshold or ''):5} {result['status']:15} {result.get('best_value')}", flush=True)
        return result

    for path, instance in instances:
        if (instance.name, "cp_sat") not in done_opt:
            cp_result = execute(path, instance, "optimization", "cp_sat", args.time_limit)
        else:
            cp_row = next(r for r in read_rows(optimization_path)
                          if r["instance"] == instance.name and r["method"] == "cp_sat")
            cp_result = {"best_value": int(cp_row["best_value"]) if cp_row["best_value"] else None}
        if instance.name not in chosen:
            threshold = cp_result.get("best_value") or validate_solution(instance.graph, fallback_labeling(instance.graph))
            append_row(thresholds_path, {"instance": instance.name, "threshold": threshold,
                         "source": "cp_sat_incumbent" if cp_result.get("best_value") else "vertex_order"},
                       ["instance", "threshold", "source"])
            chosen[instance.name] = threshold
        for method in sat_methods + [m for m in exact_methods if m != "cp_sat"]:
            if (instance.name, method) not in done_opt:
                execute(path, instance, "optimization", method, args.time_limit,
                        "sequential" if method in SAT_ENCODERS else None)
        thresholds = [chosen[instance.name]]
        if thresholds[0] < instance.graph.n - 1:
            thresholds.append(thresholds[0] + 1)
        for method in sat_methods:
            for amo in (["sequential", "pairwise"] if not args.no_legacy_fixed else ["sequential"]):
                for threshold in thresholds:
                    key = (instance.name, method, amo, str(threshold))
                    if key not in done_fixed:
                        execute(path, instance, "fixed", method, args.time_limit / len(thresholds),
                                amo, threshold)
    print(f"Results: {output}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "dataset")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--time-limit", type=float, default=60)
    parser.add_argument("--memory-mb", type=int, default=2048)
    parser.add_argument("--max-clauses", type=int, default=5_000_000)
    parser.add_argument("--sat-methods", default="pairwise,order,scl")
    parser.add_argument("--exact-methods", default="cp_sat,cp_optimizer,cplex,gurobi")
    parser.add_argument("--no-legacy-fixed", action="store_true")
    parser.add_argument("--resume", action="store_true")
    benchmark(parser.parse_args())


if __name__ == "__main__":
    main()
