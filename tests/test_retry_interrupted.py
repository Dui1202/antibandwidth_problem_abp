import json
import csv

from experiments.run import save_record
from visualization.retry import archive_interrupted


def test_resume_archives_only_interrupted_workloads(tmp_path):
    interrupted = {"key": ["g", "optimization", "order", "sequential", None],
                   "summary": {"termination_reason": "INTERRUPTED"},
                   "row": {"instance": "g", "method": "order", "termination_reason": "INTERRUPTED"},
                   "trials": [], "solutions": []}
    completed = {"key": ["g", "optimization", "pairwise", "sequential", None],
                 "summary": {"termination_reason": "COMPLETED"},
                 "row": {"instance": "g", "method": "pairwise", "termination_reason": "COMPLETED"},
                 "trials": [], "solutions": []}
    (tmp_path / "metadata.json").write_text(json.dumps({"schema_version": 3, "source_tree_sha256": "same"}))
    save_record(tmp_path, interrupted)
    save_record(tmp_path, completed)

    assert archive_interrupted(tmp_path, expected_source_hash="same") == 1
    remaining = list((tmp_path / "records").glob("*.json"))
    assert len(remaining) == 1
    assert json.loads(remaining[0].read_text())["summary"]["termination_reason"] == "COMPLETED"
    archived = list((tmp_path / "attempts" / "interrupted_before_retry").glob("*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text())["summary"]["termination_reason"] == "INTERRUPTED"
    with (tmp_path / "optimization.csv").open(newline="") as stream:
        assert [row["method"] for row in csv.DictReader(stream)] == ["pairwise"]
    assert archive_interrupted(tmp_path, expected_source_hash="same") == 0
