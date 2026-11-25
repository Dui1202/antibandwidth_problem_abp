"""Run the complete ABP experiment and generate every available figure."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import run_with_figures
from visualization import supplement
from visualization.generate import generate


ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Benchmark options such as --time-limit, --memory-mb, and --max-clauses are forwarded to experiments/run.py.")
    parser.add_argument("--output", type=Path, help="Results directory (required when resuming)")
    parser.add_argument("--dataset", type=Path, default=ROOT / "data" / "dataset")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--supplement-time-limit", type=float, default=60,
                        help="Wall-clock seconds per supplemental measurement (default: 60)")
    parser.add_argument("--repetitions", type=int, default=3,
                        help="Supplemental optimization repetitions (default: 3)")
    args, benchmark_options = parser.parse_known_args(argv)
    if args.resume and args.output is None:
        parser.error("--resume requires --output")
    if args.supplement_time_limit <= 0 or args.repetitions <= 0:
        parser.error("supplement time limit and repetitions must be positive")

    output = (args.output or ROOT / "results" / datetime.now(timezone.utc).strftime("benchmark_%Y%m%dT%H%M%SZ")).resolve()
    dataset = args.dataset.resolve()
    runner_args = ["--output", str(output), "--dataset", str(dataset)]
    if args.resume:
        runner_args.append("--resume")
    runner_args.extend(benchmark_options)

    run_with_figures.main(runner_args)
    supplement.run(output, dataset, args.supplement_time_limit, args.repetitions)
    generate(output)
    print(f"Complete figures: {output / 'figures'}", flush=True)
    return output


if __name__ == "__main__":
    main()
