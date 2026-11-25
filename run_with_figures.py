"""Run or resume the benchmark, then produce all analysis figures."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from visualization.instance_progress import InstanceProgress, format_instance_line
from visualization.retry import archive_interrupted


ROOT = Path(__file__).resolve().parent


def run_stage(command, monitor=None):
    process = subprocess.Popen(command, cwd=ROOT)
    try:
        while True:
            try:
                code = process.wait(timeout=0.2 if monitor else None)
                break
            except subprocess.TimeoutExpired:
                for details in monitor.poll():
                    print(format_instance_line(*details), flush=True)
    except BaseException:
        if process.poll() is None:
            process.terminate()
            process.wait()
        raise
    if monitor:
        for details in monitor.poll():
            print(format_instance_line(*details), flush=True)
    if code:
        raise subprocess.CalledProcessError(code, command)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--time-limit", type=float)
    parser.add_argument("-h", "--help", action="store_true")
    known, remaining = parser.parse_known_args(argv)
    if known.help:
        subprocess.run([sys.executable, str(ROOT / "experiments" / "run.py"), "--help"], check=True)
        return
    output = known.output or ROOT / "results" / datetime.now(timezone.utc).strftime("benchmark_%Y%m%dT%H%M%SZ")
    output = output.resolve()
    if known.time_limit is not None and known.time_limit <= 0:
        parser.error("--time-limit must be positive")
    if "--resume" in remaining:
        count = archive_interrupted(output)
        if count:
            print(f"Retrying {count} interrupted workload(s)", flush=True)
    if known.time_limit is not None:
        time_limit = known.time_limit
    elif "--resume" in remaining:
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        time_limit = metadata["config"]["time_limit"]
    else:
        time_limit = 300
    run_stage([sys.executable, str(ROOT / "experiments" / "run.py"),
               "--output", str(output), *remaining, "--time-limit", f"{time_limit:g}"],
              monitor=InstanceProgress(output))
    run_stage([sys.executable, str(ROOT / "experiments" / "analyze.py"), str(output)])
    run_stage([sys.executable, "-m", "visualization.generate", str(output)])
    print(f"Figures: {output / 'figures'}", flush=True)


if __name__ == "__main__":
    main()
