"""Versioned seed plan, independent of algorithm order and runtime/cache hits."""

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class ExperimentSeedPlan:
    version: str
    master_seed: int
    independent_run_index: int
    seed_block_size: int
    block_start: int
    optimization_base_random_seed: int
    final_base_random_seed: int
    rumor_seed_fixed: int
    rumor_seed_per_run: int
    random_selection_seed: int
    ga_random_seed: int


def make_experiment_seed_plan(master_seed: int, run_index: int, block_size: int) -> ExperimentSeedPlan:
    """Cantor-pair master/run into disjoint blocks of a fixed declared width.

    First half is reserved for optimization, second for final evaluation.
    Different runs/master seeds have disjoint blocks at the same block_size.
    Selection phases use domain-separated SHA-256 seeds, not these CIC blocks.
    """
    if any(type(x) is not int or x < 0 for x in (master_seed, run_index)):
        raise ValueError("Master seed and run index must be nonnegative integers")
    if type(block_size) is not int or block_size < 2 or block_size % 2:
        raise ValueError("Seed block size must be positive and even")
    paired = (master_seed + run_index) * (master_seed + run_index + 1) // 2 + run_index
    base = paired * block_size
    def derive(domain: str, index: int = run_index) -> int:
        digest = hashlib.sha256(f"experiment-runner-v1:{master_seed}:{index}:{domain}".encode()).digest()
        return int.from_bytes(digest[:8], "big")
    return ExperimentSeedPlan("cantor-block-v1/sha256-phases-v1", master_seed, run_index, block_size,
                              base, base, base + block_size // 2,
                              derive("rumor", 0), derive("rumor"), derive("random-selection"), derive("ga"))
