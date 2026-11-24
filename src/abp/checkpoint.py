"""Atomic, workload-bound evidence snapshots for benchmark workers."""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from .validation import validate_solution

CHECKPOINT_VERSION = 1


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def write_checkpoint(path: Path, identity: dict, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": CHECKPOINT_VERSION, "identity": identity, "state": state}
    document = {**body, "sha256": sha256(_canonical(body).encode()).hexdigest()}
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".checkpoint-",
                                         delete=False, encoding="utf-8") as stream:
            name = stream.name
            stream.write(_canonical(document))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def read_checkpoint(path: Path, identity: dict, graph) -> dict | None:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        body = {key: document[key] for key in ("version", "identity", "state")}
        if (body["version"] != CHECKPOINT_VERSION or body["identity"] != identity
                or document["sha256"] != sha256(_canonical(body).encode()).hexdigest()):
            return None
        state = body["state"]
        labeling = state.get("labeling")
        if labeling is None:
            return None
        labeling = {int(k): v for k, v in labeling.items()}
        value = validate_solution(graph, labeling)
        if value != state.get("best_value", state.get("lower_bound")) or value != state.get("lower_bound"):
            return None
        state["labeling"] = labeling
        lower, upper = state.get("lower_bound"), state.get("upper_bound")
        if (type(lower) is not int or type(upper) is not int
                or not 1 <= lower <= upper <= graph.n - 1):
            return None
        if state.get("proven_optimal", lower == upper) != (lower == upper):
            return None
        if "fallback_value" in state:
            fallback = {vertex: vertex + 1 for vertex in range(graph.n)}
            if state["fallback_value"] != validate_solution(graph, fallback):
                return None
        if state.get("solver_best_value") is not None and state["solver_best_value"] > value:
            return None
        if state.get("has_solver_incumbent", False) != (state.get("solver_best_value") is not None):
            return None
        if (state.get("solver_best_value") is None) != (state.get("solver_labeling") is None):
            return None
        if state.get("solver_labeling") is not None:
            solver_labeling = {int(k): v for k, v in state["solver_labeling"].items()}
            if validate_solution(graph, solver_labeling) != state["solver_best_value"]:
                return None
            state["solver_labeling"] = solver_labeling
        if not isinstance(state.get("trials", []), list):
            return None
        for trial in state.get("trials", []):
            if trial.get("labeling") is not None:
                trial["labeling"] = {int(k): v for k, v in trial["labeling"].items()}
                if validate_solution(graph, trial["labeling"], trial["threshold"]) != trial["best_value"]:
                    return None
        return state
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
