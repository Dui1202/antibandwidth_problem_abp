import csv
import json

from visualization.generate import Benchmark, fixed_comparison, generate, reference_values, runtime_parts, status_category


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_fixed_comparison_uses_pilot_and_common_amo(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"schema_version": 3, "config": {}}))
    write_csv(tmp_path / "manifest.csv", [{"instance": "g", "n_vertices": "4"}])
    write_csv(tmp_path / "thresholds.csv", [{"instance": "g", "threshold": "2"}])
    base = {"instance": "g", "threshold": "2", "assignment_amo": "sequential",
            "n_primary_vars": "16", "n_aux_vars": "12", "n_clauses": "100"}
    write_csv(tmp_path / "fixed.csv", [
        {**base, "method": "pairwise"},
        {**base, "method": "order", "n_primary_vars": "12", "n_aux_vars": "20", "n_clauses": "60"},
        {**base, "method": "scl", "n_clauses": "50"},
        {**base, "method": "pairwise", "assignment_amo": "pairwise", "n_clauses": "200"},
        {**base, "method": "scl", "threshold": "3", "n_clauses": "1"},
    ])
    benchmark = Benchmark(tmp_path)
    compared = fixed_comparison(benchmark)
    assert compared[("g", "order")]["reduction_pct"] == 40
    assert compared[("g", "scl")]["reduction_pct"] == 50
    assert compared[("g", "order")]["primary"] == 12


def test_runtime_parts_do_not_count_unfinished_call_as_measured_overhead():
    complete = {"encode_seconds": "2", "solve_seconds": "5", "total_seconds": "8",
                "termination_reason": "COMPLETED"}
    interrupted = {**complete, "termination_reason": "TIME_LIMIT"}
    assert runtime_parts(complete) == (2, 5, 1, False)
    assert runtime_parts(interrupted) == (2, 5, 1, True)


def test_reference_and_status_keep_fallback_and_certification_distinct():
    rows = [
        {"instance": "g", "method": "pairwise", "best_value": "2", "solution_source": "FALLBACK",
         "proven_optimal": "False", "solution_status": "FEASIBLE", "termination_reason": "TIME_LIMIT"},
        {"instance": "g", "method": "order", "best_value": "3", "solution_source": "SOLVER",
         "proven_optimal": "True", "solution_status": "OPTIMAL", "termination_reason": "COMPLETED"},
    ]
    references = reference_values(rows)
    assert references["g"] == {"value": 3, "source": "order", "certified": True}
    assert status_category(rows[0]) == "Feasible but uncertified"
    assert status_category(None) == "Missing or invalid experiment"


def test_all_comparison_figures_render_from_partial_results(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"schema_version": 3,
                                                         "config": {"time_limit": 10, "memory_mb": 100}}))
    write_csv(tmp_path / "manifest.csv", [{"instance": "g", "n_vertices": "4"},
                                           {"instance": "h", "n_vertices": "5"}])
    write_csv(tmp_path / "thresholds.csv", [{"instance": "g", "threshold": "2"}])
    write_csv(tmp_path / "fixed.csv", [
        {"instance": "g", "method": method, "threshold": "2", "assignment_amo": "sequential",
         "n_clauses": str(100 - i * 20), "n_primary_vars": str(16 - i * 2),
         "n_aux_vars": str(i * 4), "termination_reason": "COMPLETED"}
        for i, method in enumerate(("pairwise", "order", "scl"))])
    write_csv(tmp_path / "optimization.csv", [
        {"instance": "g", "method": "pairwise", "best_value": "2", "solution_source": "SOLVER",
         "proven_optimal": "True", "solution_status": "OPTIMAL", "termination_reason": "COMPLETED",
         "encode_seconds": "1", "solve_seconds": "2", "total_seconds": "4", "peak_memory_mb": "20"},
        {"instance": "h", "method": "pairwise", "best_value": "1", "solution_source": "FALLBACK",
         "proven_optimal": "False", "solution_status": "FEASIBLE", "termination_reason": "TIME_LIMIT",
         "encode_seconds": "1", "solve_seconds": "2", "total_seconds": "10", "peak_memory_mb": "25"},
    ])
    output = generate(tmp_path)
    names = ("clause_count_comparison", "variable_count_comparison", "runtime_breakdown",
             "peak_memory_comparison", "optimization_runtime_heatmap", "optimality_cactus_plot",
             "relative_solution_gap_heatmap", "solution_status_comparison")
    assert all((output / f"{name}.{suffix}").is_file() for name in names for suffix in ("svg", "pdf"))
    with (tmp_path / "solution_status_counts.csv").open() as stream:
        assert all(sum(int(value) for key, value in row.items() if key != "method") == 2
                   for row in csv.DictReader(stream))


def test_figures_render_before_any_workload_finishes(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"schema_version": 3, "config": {}}))
    write_csv(tmp_path / "manifest.csv", [{"instance": "g", "n_vertices": "4"}])
    assert (generate(tmp_path) / "optimality_cactus_plot.svg").is_file()
