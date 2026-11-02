"""Command-line entry point for Milestone 1."""

import argparse
from pathlib import Path

from src.data import DATASETS, DatasetValidationError, PreprocessConfig, prepare_dataset


def main(argv: list[str] | None = None) -> int:
    """Prepare a registered dataset and print validated before/after counts."""
    parser = argparse.ArgumentParser(description="Misinformation blocking research tools")
    commands = parser.add_subparsers(dest="command", required=True)
    dataset = commands.add_parser("dataset", help="Validate and preprocess a SNAP dataset")
    dataset.add_argument("--name", required=True, choices=DATASETS)
    dataset.add_argument("--raw-dir", type=Path, help="Raw dataset root (default: data/raw)")
    dataset.add_argument("--output-dir", type=Path, help="Artifact directory (default: data/processed/NAME)")
    loops = dataset.add_mutually_exclusive_group()
    loops.add_argument("--remove-self-loops", dest="remove_self_loops", action="store_true")
    loops.add_argument("--keep-self-loops", dest="remove_self_loops", action="store_false")
    dataset.set_defaults(remove_self_loops=None)
    args = parser.parse_args(argv)
    config = None if args.remove_self_loops is None else PreprocessConfig(args.remove_self_loops)
    try:
        result = prepare_dataset(
            args.name, raw_directory=args.raw_dir, output_directory=args.output_dir, config=config,
        )
    except (DatasetValidationError, OSError) as exc:
        parser.exit(1, f"Dataset pipeline failed: {exc}\n")
    raw = result.metadata["raw_statistics"]
    processed = result.metadata["processed_statistics"]
    print(f"Dataset: {args.name} ({'directed' if result.graph.is_directed() else 'undirected'})")
    print(f"Raw:       {raw['node_count']} nodes, {raw['edge_count']} edges, "
          f"{raw['self_loop_count']} self-loops, {raw['duplicate_edges']} duplicate edges")
    print(f"Processed: {processed['node_count']} nodes, {processed['edge_count']} edges, "
          f"{processed['self_loop_count']} self-loops, {processed['isolated_node_count']} isolated nodes")
    print(f"Source SHA-256: {result.metadata['source']['sha256']}")
    print(f"Saved to: {result.output_directory}")
    print("Verified: exact topology round-trip; raw source unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
