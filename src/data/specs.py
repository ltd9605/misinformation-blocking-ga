"""Explicit dataset sources and preprocessing policies."""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DatasetSpec:
    """Describe one raw edge list without inferring its graph type."""

    name: str
    relative_path: Path
    directed: bool
    expected_nodes: int
    expected_edges: int
    remove_self_loops: bool = False


@dataclass(frozen=True)
class PreprocessConfig:
    """Configure the only topology transformation in Milestone 1."""

    remove_self_loops: bool = False


DATASETS = {
    "email-Eu-core": DatasetSpec(
        "email-Eu-core", Path("email-Eu-core/email-Eu-core.txt.gz"),
        True, 1005, 25571, True,
    ),
    "ego-Facebook": DatasetSpec(
        "ego-Facebook", Path("ego-Facebook/facebook_combined.txt.gz"),
        False, 4039, 88234,
    ),
    "Wiki-Vote": DatasetSpec(
        "Wiki-Vote", Path("wiki-Vote/wiki-Vote.txt.gz"),
        True, 7115, 103689,
    ),
}


def get_dataset_spec(name: str) -> DatasetSpec:
    """Return the registered source and policy for a dataset."""
    try:
        return DATASETS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown dataset {name!r}; choose from {', '.join(DATASETS)}") from exc
