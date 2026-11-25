"""Resumable focused threshold and repetition study outside the benchmark fingerprint."""

import argparse
import csv
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Timer
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abp.dataset import load_matrix_market
from abp.encoding.common import ClauseLimitError
from abp.experiment import SAT_ENCODERS, EXACT_SOLVERS, run_sat_optimization, run_exact_optimization
from abp.validation import validate_solution
from experiments.run import _rss_kb, atomic_text, dependency_version, source_tree_hash
from pysat.solvers import Solver

from .generate import SAT, METHODS, Benchmark, integer, read_csv
from .instance_progress import format_instance_line


def select_instances(instances):
    return list(dict.fromkeys(instances[int((len(instances) - 1) * q)] for q in (0.25, 0.5, 0.75)))


def nearby_thresholds(center, vertices):
    valid = range(1, vertices)
    return sorted(sorted(valid, key=lambda k: (abs(k - center), k))[:5])


def selected_thresholds(benchmark, instance, vertices):
    certified = [integer(row, "best_value") for row in benchmark.optimization
                 if row.get("instance") == instance and row.get("proven_optimal") == "True"
                 and row.get("solution_status") == "OPTIMAL"]
    if certified:
        if None in certified or len(set(certified)) != 1:
            raise ValueError(f"conflicting certified optima for {instance}")
        return nearby_thresholds(certified[0], vertices), "certified_optimum", certified[0]
    pilot = benchmark.thresholds.get(instance)
    return (nearby_thresholds(pilot, vertices), "pilot_unverified", pilot) if pilot else ([], "missing_pilot", None)


def decision_with_stats(graph, method, threshold, limit, max_clauses):
    started = monotonic()
    result = {"solution_status": "UNKNOWN", "termination_reason": "UNKNOWN",
              "raw_status": None, "n_clauses": None, "n_primary_vars": None,
              "n_aux_vars": None, "encode_seconds": None, "solve_seconds": None,
              "total_seconds": None, "conflicts": None, "decisions": None,
              "propagations": None, "restarts": None, "error": None}
    try:
        encoding = SAT_ENCODERS[method](graph, threshold, assignment_amo="sequential",
                                        max_clauses=max_clauses)
        result.update(n_clauses=encoding.n_clauses, n_primary_vars=encoding.n_primary_vars,
                      n_aux_vars=encoding.n_aux_vars, encode_seconds=encoding.encode_seconds)
        remaining = limit - (monotonic() - started)
        if remaining <= 0:
            result["termination_reason"] = "TIME_LIMIT"
        else:
            solve_started = monotonic()
            with Solver(name="g3", bootstrap_with=encoding.clauses) as solver:
                remaining = limit - (monotonic() - started)
                answer = None
                if remaining > 0:
                    timer = Timer(remaining, solver.interrupt)
                    timer.start()
                    try:
                        answer = solver.solve_limited(expect_interrupt=True)
                    finally:
                        timer.cancel()
                        timer.join()
                        solver.clear_interrupt()
                result.update({key: solver.accum_stats().get(key) for key in
                               ("conflicts", "decisions", "propagations", "restarts")})
                if answer is True:
                    validate_solution(graph, encoding.decode(solver.get_model()), threshold)
                    result.update(solution_status="FEASIBLE", termination_reason="COMPLETED", raw_status="SAT")
                elif answer is False:
                    result.update(solution_status="INFEASIBLE", termination_reason="COMPLETED", raw_status="UNSAT")
                else:
                    result.update(termination_reason="TIME_LIMIT", raw_status="INTERRUPTED")
            result["solve_seconds"] = monotonic() - solve_started
    except ClauseLimitError as exc:
        result.update(termination_reason="CLAUSE_LIMIT", error=str(exc))
    except MemoryError as exc:
        result.update(termination_reason="MEMORY_LIMIT", error=str(exc))
    except Exception as exc:
        result.update(termination_reason="ERROR", error=f"{type(exc).__name__}: {exc}")
    result["total_seconds"] = monotonic() - started
    return result


def worker():
    payload = json.load(sys.stdin)
    graph = load_matrix_market(payload["file"]).graph
    if payload["kind"] == "sweep":
        result = decision_with_stats(graph, payload["method"], payload["threshold"],
                                     payload["time_limit"], payload["max_clauses"])
    elif payload["method"] in SAT_ENCODERS:
        result, _ = run_sat_optimization(graph, payload["method"], payload["time_limit"],
                                         payload["max_clauses"], "sequential")
    else:
        result = run_exact_optimization(graph, payload["method"], payload["time_limit"])
    result.pop("labeling", None)
    result.pop("solver_labeling", None)
    result.pop("trials", None)
    print(json.dumps(result))


def invoke(payload, memory_mb):
    started = monotonic()
    process = subprocess.Popen([sys.executable, "-m", "visualization.supplement", "worker"],
                               cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    sent = False
    forced = None
    try:
        while True:
            try:
                stdout, stderr = process.communicate(input=json.dumps(payload) if not sent else None,
                                                     timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                sent = True
                if _rss_kb(process.pid) > memory_mb * 1024:
                    forced = "MEMORY_LIMIT"
                elif monotonic() - started > payload["time_limit"]:
                    forced = "TIME_LIMIT"
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
    elapsed = monotonic() - started
    if forced:
        return {"solution_status": "UNKNOWN", "termination_reason": forced,
                "total_seconds": elapsed, "error": "worker exceeded resource limit"}
    try:
        if process.returncode:
            raise ValueError(stderr[-300:] or f"worker exited {process.returncode}")
        result = json.loads(stdout)
        result["total_seconds"] = elapsed
        if elapsed > payload["time_limit"]:
            result.update(termination_reason="TIME_LIMIT", solution_status="UNKNOWN")
        return result
    except (ValueError, json.JSONDecodeError) as exc:
        return {"solution_status": "UNKNOWN", "termination_reason": "ERROR",
                "total_seconds": elapsed, "error": str(exc)}


def project(directory):
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((directory / "records").glob("*.json"))]
    for kind in ("sweep", "repeat"):
        selected = [row for row in rows if row["kind"] == kind]
        fields = ["kind", "instance", "method", "threshold", "repetition", "center_source", "center_threshold",
                  "solver", "solver_version", "assignment_amo", "time_limit", "memory_mb", "seed_policy",
                  "solution_status", "termination_reason", "raw_status", "proven_optimal", "n_clauses",
                  "n_primary_vars", "n_aux_vars", "encode_seconds", "solve_seconds", "total_seconds",
                  "conflicts", "decisions", "propagations", "restarts", "error"]
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
        atomic_text(directory / f"{kind}.csv", stream.getvalue())


def run(results, dataset, time_limit=60, repetitions=3):
    benchmark = Benchmark(results)
    chosen = select_instances(benchmark.instances)
    manifest = {row["instance"]: row for row in read_csv(benchmark.directory / "manifest.csv")}
    required = benchmark.metadata.get("config", {}).get("sat_methods", list(SAT)) + benchmark.metadata.get("config", {}).get("exact_methods", ["cp_sat"])
    for instance in chosen:
        if any((instance, method) not in benchmark.opt for method in required):
            raise ValueError(f"selected instance lacks completed main benchmark rows: {instance}")
        if benchmark.thresholds.get(instance) is None:
            raise ValueError(f"selected instance lacks a pilot threshold: {instance}")
    centers = {instance: list(selected_thresholds(benchmark, instance, integer(manifest[instance], "n_vertices")))
               for instance in chosen}
    config = {"run_id": benchmark.metadata.get("run_id"), "selected": chosen,
              "centers": centers,
              "time_limit": time_limit, "repetitions": repetitions,
              "memory_mb": benchmark.metadata.get("config", {}).get("memory_mb", 8192),
              "max_clauses": benchmark.metadata.get("config", {}).get("max_clauses", 30_000_000),
              "source_tree_sha256": source_tree_hash(),
              "supplement_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "solver_versions": {method: dependency_version(method) for method in METHODS}}
    if config["source_tree_sha256"] != benchmark.metadata.get("source_tree_sha256"):
        raise ValueError("benchmark source hash changed; supplemental results cannot be paired safely")
    if any(config["solver_versions"].get(method) != recorded
           for method, recorded in benchmark.metadata.get("versions", {}).items()):
        raise ValueError("solver versions differ from the benchmark; start a matching environment")
    directory = benchmark.directory / "supplemental"
    directory.mkdir(exist_ok=True)
    metadata_path = directory / "metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != config:
            raise ValueError("supplemental configuration differs; use a separate result directory")
    else:
        atomic_text(metadata_path, json.dumps(config, indent=2))
    for instance_index, instance in enumerate(chosen, 1):
        instance_started = monotonic()
        did_work = False
        file = Path(dataset) / f"{instance}.mtx.gz"
        if not file.is_file() or sha256(file.read_bytes()).hexdigest() != manifest[instance]["source_sha256"]:
            raise ValueError(f"dataset file does not match manifest: {instance}")
        thresholds, center_source, center = centers[instance]
        tasks = [("sweep", method, threshold, None) for threshold in thresholds for method in SAT]
        tasks += [("repeat", method, None, repetition) for repetition in range(1, repetitions + 1)
                  for method in METHODS]
        for kind, method, threshold, repetition in tasks:
            key = [kind, instance, method, threshold, repetition]
            path = directory / "records" / (sha256(json.dumps(key).encode()).hexdigest() + ".json")
            if path.exists():
                continue
            did_work = True
            payload = {"kind": kind, "file": str(file.resolve()), "method": method,
                       "threshold": threshold, "time_limit": time_limit,
                       "max_clauses": config["max_clauses"]}
            result = invoke(payload, config["memory_mb"])
            row = {"kind": kind, "instance": instance, "method": method, "threshold": threshold,
                   "repetition": repetition, "center_source": center_source, "center_threshold": center,
                   "solver": "g3" if method in SAT else method,
                   "solver_version": benchmark.metadata["versions"].get(method),
                   "assignment_amo": "sequential" if method in SAT else "",
                   "time_limit": time_limit, "memory_mb": config["memory_mb"],
                   "seed_policy": "fixed 42" if method not in SAT else "g3 default; no exposed seed",
                   **result}
            atomic_text(path, json.dumps(row, sort_keys=True))
            project(directory)
            print(f"{instance} {kind} {method} k={threshold} rep={repetition}:"
                  f" {row['termination_reason']}", flush=True)
        if did_work:
            print(format_instance_line(instance_index, len(chosen),
                                       integer(manifest[instance], "n_vertices"), instance,
                                       monotonic() - instance_started), flush=True)
    project(directory)
    return directory


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "dataset")
    parser.add_argument("--time-limit", type=float, default=60)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.time_limit <= 0 or args.repetitions < 1:
        parser.error("time limit and repetitions must be positive")
    print(run(args.results, args.dataset, args.time_limit, args.repetitions))


if __name__ == "__main__":
    main()
