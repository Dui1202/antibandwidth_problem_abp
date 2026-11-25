"""Prepare interrupted benchmark workloads for a fresh attempt on resume."""

from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from experiments.run import load_records, project_records, source_tree_hash


def archive_interrupted(output, expected_source_hash=None):
    output = Path(output)
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    expected = expected_source_hash or source_tree_hash()
    if metadata.get("schema_version") != 3 or metadata.get("source_tree_sha256") != expected:
        raise ValueError("benchmark schema or source changed; cannot retry interrupted records")

    interrupted = [item for item in load_records(output).values()
                   if item["summary"].get("termination_reason") == "INTERRUPTED"]
    if not interrupted:
        return 0
    archive = output / "attempts" / "interrupted_before_retry"
    archive.mkdir(parents=True, exist_ok=True)
    for item in interrupted:
        name = sha256(json.dumps(item["key"]).encode()).hexdigest() + ".json"
        original = output / "records" / name
        original.replace(archive / f"{original.stem}-{uuid4().hex}.json")
    project_records(output, load_records(output))
    return len(interrupted)
