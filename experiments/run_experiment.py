"""CLI for a single configured comparison and independent run index."""

import argparse
from pathlib import Path

import networkx as nx

from src.data import DatasetValidationError
from src.experiments import ExperimentConfig, load_experiment_config, run_experiment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-index", type=int)
    args = parser.parse_args(argv)
    try:
        config = load_experiment_config(args.config)
        values = config.to_dict()
        if args.output_dir is not None:
            values["output_directory"] = args.output_dir.resolve().as_posix()
        if args.run_index is not None:
            values["independent_run_index"] = args.run_index
        config = ExperimentConfig.from_dict(values, source_path=config.source_path)
        result = run_experiment(config)
    except (ValueError, OSError, DatasetValidationError, nx.NetworkXException) as exc:
        parser.exit(1, f"Experiment failed: {exc}\n")
    print(f"Saved experiment: {result.output_directory}")
    print(f"Methods: {len(result.rows)}; CIC simulations: {result.summary['total_cic_simulations']}")
    print(f"Total runtime: {result.metadata['timings']['total_experiment_runtime_seconds']:.6f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
