"""Detect when all benchmark workloads for an instance have been recorded."""

import csv
import json
from pathlib import Path
from time import monotonic


def _rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def completed_instances(output):
    output = Path(output)
    metadata_path = output / "metadata.json"
    if not metadata_path.exists():
        return set()
    config = json.loads(metadata_path.read_text(encoding="utf-8"))["config"]
    optimization = {(row["instance"], row["method"])
                    for row in _rows(output / "optimization.csv")
                    if row.get("termination_reason") != "INTERRUPTED"}
    fixed = {(row["instance"], row["method"], row["assignment_amo"], row["threshold"])
             for row in _rows(output / "fixed.csv")
             if row.get("termination_reason") != "INTERRUPTED"}
    pilots = {row["instance"]: int(row["threshold"])
              for row in _rows(output / "thresholds.csv")}
    complete = set()
    for instance in _rows(output / "manifest.csv"):
        name = instance["instance"]
        pilot = pilots.get(name)
        if pilot is None:
            continue
        methods = config["exact_methods"] + config["sat_methods"]
        if any((name, method) not in optimization for method in methods):
            continue
        thresholds = [pilot] + ([pilot + 1] if pilot < int(instance["n_vertices"]) - 1 else [])
        amos = ("sequential", "pairwise") if config["legacy_fixed"] else ("sequential",)
        if all((name, method, amo, str(threshold)) in fixed
               for method in config["sat_methods"] for amo in amos for threshold in thresholds):
            complete.add(name)
    return complete


def format_instance_line(index, total, vertices, name, seconds):
    return f"[{index}/{total}] N={vertices} {name} -> done ({seconds:.6f}s)"


class InstanceProgress:
    def __init__(self, output):
        self.output = Path(output)
        self.seen = completed_instances(output)
        self.started = monotonic()

    def poll(self):
        newly = completed_instances(self.output) - self.seen
        if not newly:
            return []
        manifest = _rows(self.output / "manifest.csv")
        order = {row["instance"]: (i + 1, int(row["n_vertices"]))
                 for i, row in enumerate(manifest)}
        now = monotonic()
        elapsed = now - self.started
        self.started = now
        self.seen.update(newly)
        return [(order[name][0], len(manifest), order[name][1], name, elapsed)
                for name in sorted(newly, key=lambda name: order[name][0])]
