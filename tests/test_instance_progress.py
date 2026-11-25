import csv
import json

from visualization.instance_progress import InstanceProgress, completed_instances, format_instance_line


def write_rows(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_instance_is_complete_only_after_last_fixed_workload(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"config": {"sat_methods": ["pairwise", "order", "scl"],
                                                             "exact_methods": ["cp_sat"], "legacy_fixed": True}}))
    write_rows(tmp_path / "manifest.csv", [{"instance": "g", "n_vertices": "4"}])
    write_rows(tmp_path / "thresholds.csv", [{"instance": "g", "threshold": "2"}])
    write_rows(tmp_path / "optimization.csv", [
        {"instance": "g", "method": method} for method in ("cp_sat", "pairwise", "order", "scl")])
    write_rows(tmp_path / "fixed.csv", [
        {"instance": "g", "method": method, "assignment_amo": amo, "threshold": str(k)}
        for method in ("pairwise", "order", "scl") for amo in ("sequential", "pairwise")
        for k in (2, 3) if (method, amo, k) != ("scl", "pairwise", 3)])
    assert completed_instances(tmp_path) == set()
    monitor = InstanceProgress(tmp_path)
    with (tmp_path / "fixed.csv").open("a", newline="") as stream:
        csv.DictWriter(stream, fieldnames=["instance", "method", "assignment_amo", "threshold"]).writerow(
            {"instance": "g", "method": "scl", "assignment_amo": "pairwise", "threshold": "3"})
    assert completed_instances(tmp_path) == {"g"}
    index, total, vertices, name, elapsed = monitor.poll()[0]
    assert (index, total, vertices, name) == (1, 1, 4, "g")
    assert elapsed >= 0


def test_instance_line_uses_compact_seconds_format():
    assert format_instance_line(3, 24, 30, "pores_1", 0.000487) == (
        "[3/24] N=30 pores_1 -> done (0.000487s)")
