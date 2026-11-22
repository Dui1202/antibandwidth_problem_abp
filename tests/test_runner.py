import csv
import gzip
import json
from pathlib import Path
import subprocess
import sys


def test_runner_records_all_rows_and_resumes_without_duplicates(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    with gzip.open(dataset / "path.mtx.gz", "wt") as stream:
        stream.write("%%MatrixMarket matrix coordinate pattern symmetric\n4 4 3\n1 2\n2 3\n3 4\n")
    output = tmp_path / "results"
    script = Path(__file__).resolve().parents[1] / "experiments" / "run.py"
    command = [sys.executable, str(script), "--dataset", str(dataset), "--output", str(output),
               "--time-limit", "3", "--max-clauses", "10000", "--sat-methods", "pairwise",
               "--exact-methods", "cp_sat"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    with (output / "optimization.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"instance", "n_vertices", "n_edges", "threshold", "method", "solver",
                    "solver_version", "seed", "status", "best_value", "proven_optimal",
                    "n_primary_vars", "n_aux_vars", "n_clauses", "encode_seconds",
                    "solve_seconds", "total_seconds", "timeout_seconds", "peak_memory_mb",
                    "hardware", "commit_sha"}
        assert required <= set(reader.fieldnames)
        rows = list(reader)
    assert {(row["method"], row["status"], row["best_value"]) for row in rows} == {
        ("cp_sat", "OPTIMAL", "2"), ("pairwise", "OPTIMAL", "2")}
    with (output / "fixed.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert required <= set(reader.fieldnames)
        fixed = list(reader)
    assert {(row["assignment_amo"], row["threshold"], row["status"]) for row in fixed} == {
        ("sequential", "2", "FEASIBLE"), ("sequential", "3", "INFEASIBLE"),
        ("pairwise", "2", "FEASIBLE"), ("pairwise", "3", "INFEASIBLE")}
    assert json.loads((output / "metadata.json").read_text())["source_tree_sha256"]
    with (output / "trials.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert required <= set(reader.fieldnames)
        assert list(reader)
    assert all(row["n_clauses"] and row["encode_seconds"] for row in fixed)
    solutions = [json.loads(line) for line in (output / "solutions.jsonl").read_text().splitlines()]
    assert {row["assignment_amo"] for row in solutions if row["workload"] == "fixed"} == {
        "pairwise", "sequential"}
    subprocess.run(command + ["--resume"], check=True, capture_output=True, text=True)
    with (output / "optimization.csv").open(newline="") as stream:
        assert len(list(csv.DictReader(stream))) == len(rows)
    assert len((output / "solutions.jsonl").read_text().splitlines()) == len(solutions)


def test_memory_kill_retains_verified_sat_fallback(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    with gzip.open(dataset / "path.mtx.gz", "wt") as stream:
        stream.write("%%MatrixMarket matrix coordinate pattern symmetric\n4 4 3\n1 2\n2 3\n3 4\n")
    output = tmp_path / "results"
    script = Path(__file__).resolve().parents[1] / "experiments" / "run.py"
    subprocess.run([sys.executable, str(script), "--dataset", str(dataset), "--output", str(output),
                    "--time-limit", "3", "--memory-mb", "1", "--sat-methods", "pairwise",
                    "--exact-methods", "cp_sat", "--no-legacy-fixed"],
                   check=True, capture_output=True, text=True)
    with (output / "optimization.csv").open(newline="") as stream:
        rows = {row["method"]: row for row in csv.DictReader(stream)}
    assert rows["pairwise"]["status"] == "RESOURCE_LIMIT"
    assert rows["pairwise"]["best_value"] == "1"
    assert rows["pairwise"]["proven_optimal"] == "False"
