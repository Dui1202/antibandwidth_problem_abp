import csv
import gzip
import json
from argparse import Namespace
from pathlib import Path
import subprocess
import sys

import pytest

from abp.solving.result import Termination
from experiments import run as runner


@pytest.mark.parametrize("field,changed", [
    ("hardware", "different CPU"),
    ("versions", {"cp_sat": "different version"}),
    ("usable", {"gurobi": False}),
])
def test_resume_environment_reports_mismatched_field(field, changed):
    recorded = {"hardware": "CPU A", "versions": {"cp_sat": "9.15"},
                "usable": {"gurobi": True}}
    current = {**recorded, field: changed}
    with pytest.raises(ValueError, match=field):
        runner.check_environment(recorded, current)


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
                    "solver_version", "seed", "solution_status", "termination_reason", "best_value", "proven_optimal",
                    "n_primary_vars", "n_aux_vars", "n_clauses", "encode_seconds",
                    "solve_seconds", "total_seconds", "timeout_seconds", "peak_memory_mb",
                    "hardware", "commit_sha"}
        assert required <= set(reader.fieldnames)
        rows = list(reader)
    assert {(row["method"], row["solution_status"], row["best_value"]) for row in rows} == {
        ("cp_sat", "OPTIMAL", "2"), ("pairwise", "OPTIMAL", "2")}
    with (output / "fixed.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert required <= set(reader.fieldnames)
        fixed = list(reader)
    assert {(row["assignment_amo"], row["threshold"], row["solution_status"]) for row in fixed} == {
        ("sequential", "2", "FEASIBLE"), ("sequential", "3", "INFEASIBLE"),
        ("pairwise", "2", "FEASIBLE"), ("pairwise", "3", "INFEASIBLE")}
    metadata = json.loads((output / "metadata.json").read_text())
    assert metadata["source_tree_sha256"]
    assert metadata["schema_version"] == 3
    assert metadata["environment"]["versions"]["cp_sat"]
    with (output / "trials.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert required <= set(reader.fieldnames)
        assert list(reader)
    assert all(row["n_clauses"] and row["encode_seconds"] for row in fixed)
    solutions = [json.loads(line) for line in (output / "solutions.jsonl").read_text().splitlines()]
    assert {row["assignment_amo"] for row in solutions if row["workload"] == "fixed"} == {
        "pairwise", "sequential"}
    (output / "optimization.csv").unlink()
    subprocess.run(command + ["--resume"], check=True, capture_output=True, text=True)
    with (output / "optimization.csv").open(newline="") as stream:
        assert len(list(csv.DictReader(stream))) == len(rows)
    assert len((output / "solutions.jsonl").read_text().splitlines()) == len(solutions)
    analyze = script.with_name("analyze.py")
    subprocess.run([sys.executable, str(analyze), str(output)],
                   check=True, capture_output=True, text=True)
    with (output / "summary.csv").open(newline="") as stream:
        summary = {row["method"]: row for row in csv.DictReader(stream)}
    assert summary["pairwise"]["proven_optimal"] == "1"
    assert summary["pairwise"]["solver_feasible"] == "1"
    assert (output / "figures" / "optimization_absolute_gap.svg").is_file()
    metadata_path = output / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["schema_version"] = 2
    metadata_path.write_text(json.dumps(metadata))
    incompatible = subprocess.run(command + ["--resume"], capture_output=True, text=True)
    assert incompatible.returncode != 0
    assert "schema" in incompatible.stderr


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
    assert rows["pairwise"]["termination_reason"] == "MEMORY_LIMIT"
    assert int(rows["pairwise"]["best_value"]) >= 1
    assert int(rows["pairwise"]["lower_bound"]) <= int(rows["pairwise"]["upper_bound"])


def test_interrupted_pilot_is_archived_then_retried_before_fixed_trials(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    with gzip.open(dataset / "path.mtx.gz", "wt") as stream:
        stream.write("%%MatrixMarket matrix coordinate pattern symmetric\n4 4 3\n1 2\n2 3\n3 4\n")
    output = tmp_path / "results"
    args = Namespace(dataset=dataset, output=output, time_limit=3, memory_mb=8192,
                     max_clauses=10000, sat_methods="pairwise", exact_methods="cp_sat",
                     no_legacy_fixed=True, resume=False)
    with monkeypatch.context() as patcher:
        patcher.setattr(runner, "run_worker", lambda payload, memory, graph:
                        runner.recover_worker(payload, graph, Termination.INTERRUPTED, 1.0, 1.0))
        with pytest.raises(KeyboardInterrupt):
            runner.benchmark(args)
    with (output / "optimization.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows == []
    attempts = list((output / "attempts").glob("*.json"))
    assert len(attempts) == 1
    archived = json.loads(attempts[0].read_text())
    assert archived["summary"]["termination_reason"] == "INTERRUPTED"
    assert archived["summary"]["best_value"] == 1
    args.resume = True
    runner.benchmark(args)
    with (output / "optimization.csv").open(newline="") as stream:
        resumed = list(csv.DictReader(stream))
    assert len(resumed) == 2
    assert sum(row["method"] == "cp_sat" for row in resumed) == 1
    with (output / "thresholds.csv").open(newline="") as stream:
        assert [row["threshold"] for row in csv.DictReader(stream)] == ["2"]
    with (output / "fixed.csv").open(newline="") as stream:
        assert {row["threshold"] for row in csv.DictReader(stream)} == {"2", "3"}


def test_resume_rejects_changed_solver_environment(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    with gzip.open(dataset / "path.mtx.gz", "wt") as stream:
        stream.write("%%MatrixMarket matrix coordinate pattern symmetric\n4 4 3\n1 2\n2 3\n3 4\n")
    output = tmp_path / "results"
    args = Namespace(dataset=dataset, output=output, time_limit=3, memory_mb=8192,
                     max_clauses=10000, sat_methods="pairwise", exact_methods="cp_sat",
                     no_legacy_fixed=True, resume=False)
    runner.benchmark(args)
    original = runner.environment_fingerprint
    def changed(sat_methods, exact_methods):
        result = original(sat_methods, exact_methods)
        result["versions"]["cp_sat"] = "different version"
        return result
    monkeypatch.setattr(runner, "environment_fingerprint", changed)
    args.resume = True
    with pytest.raises(ValueError, match="versions.cp_sat"):
        runner.benchmark(args)
