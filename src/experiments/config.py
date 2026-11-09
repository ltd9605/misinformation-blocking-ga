"""Strict JSON experiment configurations with no implicit research settings."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any

from src.data.specs import DATASETS, PROJECT_ROOT
from src.diffusion import TieBreakingRule


ALGORITHMS = ("no_intervention", "random", "degree", "pagerank", "full_greedy",
              "candidate_restricted_greedy", "genetic_algorithm")
OPTIMIZERS = frozenset(ALGORITHMS[4:])
GA_KEYS = {"population_size", "max_generations", "crossover_rate", "mutation_rate",
           "tournament_size", "elitism_count", "cache_fitness"}
LIMIT_KEYS = {"max_optimization_evaluations", "max_optimization_cic_simulations",
              "max_full_greedy_evaluations", "max_full_greedy_cic_simulations"}


class ExperimentConfigError(ValueError):
    """An incomplete, ambiguous or invalid experiment specification."""


def _integer(name: str, value: Any, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ExperimentConfigError(f"{name} must be an integer >= {minimum}")


def _real(name: str, value: Any, lower: float, upper: float) -> None:
    if type(value) not in (int, float) or not isfinite(value) or not lower <= value <= upper:
        raise ExperimentConfigError(f"{name} must be finite and in [{lower}, {upper}]")


def _keys(name: str, value: Any, allowed: set[str], required: set[str] | None = None) -> None:
    if not isinstance(value, dict):
        raise ExperimentConfigError(f"{name} must be an object")
    if set(value) - allowed or (required or set()) - set(value):
        raise ExperimentConfigError(f"Invalid/missing keys in {name}: allowed={sorted(allowed)}, required={sorted(required or [])}")


def _nodes(name: str, value: Any) -> None:
    if not isinstance(value, list) or any(type(node) is not int for node in value):
        raise ExperimentConfigError(f"{name} must be a list of integer node IDs")
    if len(value) != len(set(value)):
        raise ExperimentConfigError(f"{name} contains duplicate node IDs")


@dataclass(frozen=True)
class ExperimentConfig:
    """Validated normalized values; to_dict returns an isolated copy."""

    _values: dict[str, Any]
    source_path: Path | None = None

    @classmethod
    def from_dict(cls, values: dict[str, Any], *, base_directory: Path = PROJECT_ROOT,
                  source_path: Path | None = None) -> "ExperimentConfig":
        allowed = {"schema_version", "purpose", "dataset", "processed_directory", "rumor_seeds",
                   "rumor_seed_policy", "k", "p", "tie_breaking", "S_opt", "S_eval", "algorithm",
                   "algorithms", "ga_parameters", "pagerank_parameters", "candidate_restriction",
                   "limits", "random_seed", "independent_run_index", "seed_block_size",
                   "output_directory", "save_raw_observations"}
        required = {"dataset", "k", "p", "tie_breaking", "S_opt", "S_eval", "random_seed",
                    "independent_run_index", "output_directory"}
        _keys("experiment", values, allowed, required)
        c = deepcopy(values)
        if type(c.get("schema_version", 1)) is not int or c.get("schema_version", 1) != 1:
            raise ExperimentConfigError("Only schema_version=1 is supported")
        c["schema_version"] = 1
        if not isinstance(c["dataset"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", c["dataset"]):
            raise ExperimentConfigError("dataset must be a safe nonempty identifier")
        if c["dataset"] not in DATASETS and "processed_directory" not in c:
            raise ExperimentConfigError("Custom datasets require processed_directory")
        if ("algorithm" in c) == ("algorithms" in c):
            raise ExperimentConfigError("Supply exactly one of algorithm or algorithms")
        algorithms = [c.pop("algorithm")] if "algorithm" in c else c["algorithms"]
        if (not isinstance(algorithms, list) or not algorithms
                or any(not isinstance(name, str) or name not in ALGORITHMS for name in algorithms)
                or len(set(algorithms)) != len(algorithms)):
            raise ExperimentConfigError(f"algorithms must be a nonempty unique list from {ALGORITHMS}")
        c["algorithms"] = ["no_intervention"] + [name for name in algorithms if name != "no_intervention"]
        if ("rumor_seeds" in c) == ("rumor_seed_policy" in c):
            raise ExperimentConfigError("Supply exactly one of rumor_seeds or rumor_seed_policy")
        if "rumor_seeds" in c:
            _nodes("rumor_seeds", c["rumor_seeds"])
            c["rumor_seeds"].sort()
        else:
            policy = c["rumor_seed_policy"]
            _keys("rumor_seed_policy", policy, {"method", "count", "scope"}, {"method", "count", "scope"})
            if policy["method"] != "random" or policy["scope"] not in ("fixed", "per_run"):
                raise ExperimentConfigError("Rumor policy requires random and scope=fixed/per_run")
            _integer("rumor count", policy["count"])
        for key, minimum in (("k", 0), ("S_opt", 1), ("S_eval", 1), ("random_seed", 0), ("independent_run_index", 0)):
            _integer(key, c[key], minimum)
        _real("p", c["p"], 0, 1)
        try:
            c["tie_breaking"] = TieBreakingRule(c["tie_breaking"]).value
        except (ValueError, TypeError) as exc:
            raise ExperimentConfigError("Unknown tie_breaking rule") from exc
        c.setdefault("seed_block_size", 1_000_000)
        _integer("seed_block_size", c["seed_block_size"], 2)
        if c["seed_block_size"] % 2 or max(c["S_opt"], c["S_eval"]) > c["seed_block_size"] // 2:
            raise ExperimentConfigError("Seed block must be even and fit both S_opt/S_eval in separate halves")
        c.setdefault("purpose", "unspecified")
        if not isinstance(c["purpose"], str) or not c["purpose"]:
            raise ExperimentConfigError("purpose must be a nonempty string")
        c.setdefault("save_raw_observations", False)
        if type(c["save_raw_observations"]) is not bool:
            raise ExperimentConfigError("save_raw_observations must be boolean")
        ga = c.setdefault("ga_parameters", {})
        _keys("ga_parameters", ga, GA_KEYS, GA_KEYS if "genetic_algorithm" in algorithms or ga else set())
        if ga:
            for key, minimum in (("population_size", 1), ("max_generations", 0), ("tournament_size", 1), ("elitism_count", 0)):
                _integer(key, ga[key], minimum)
            if ga["tournament_size"] > ga["population_size"] or ga["elitism_count"] > ga["population_size"]:
                raise ExperimentConfigError("Tournament/elite count cannot exceed population size")
            for key in ("crossover_rate", "mutation_rate"):
                _real(key, ga[key], 0, 1)
            if type(ga["cache_fitness"]) is not bool:
                raise ExperimentConfigError("cache_fitness must be boolean")
        pr = c.setdefault("pagerank_parameters", {})
        pr_keys = {"alpha", "tol", "max_iter"}
        _keys("pagerank_parameters", pr, pr_keys, pr_keys if "pagerank" in algorithms or pr else set())
        if pr:
            _real("alpha", pr["alpha"], 0, 1)
            _real("tol", pr["tol"], 0, float("inf"))
            _integer("max_iter", pr["max_iter"], 1)
            if pr["alpha"] == 1 or pr["tol"] == 0:
                raise ExperimentConfigError("Require alpha<1 and tol>0")
        restriction = c.setdefault("candidate_restriction", {})
        if not isinstance(restriction, dict):
            raise ExperimentConfigError("candidate_restriction must be an object")
        if restriction or "candidate_restricted_greedy" in algorithms:
            if not isinstance(restriction, dict) or restriction.get("method") not in ("degree", "explicit"):
                raise ExperimentConfigError("Candidate restriction requires method=degree/explicit")
            if restriction["method"] == "degree":
                _keys("candidate_restriction", restriction, {"method", "size"}, {"method", "size"})
                _integer("candidate size", restriction["size"])
                if restriction["size"] < c["k"]:
                    raise ExperimentConfigError("Candidate pool smaller than k")
            else:
                _keys("candidate_restriction", restriction, {"method", "nodes"}, {"method", "nodes"})
                _nodes("candidate nodes", restriction["nodes"])
                restriction["nodes"].sort()
                if len(restriction["nodes"]) < c["k"]:
                    raise ExperimentConfigError("Candidate pool smaller than k")
        limits = c.setdefault("limits", {})
        needed = {"max_optimization_evaluations", "max_optimization_cic_simulations"} if OPTIMIZERS & set(algorithms) else set()
        if "full_greedy" in algorithms:
            needed |= {"max_full_greedy_evaluations", "max_full_greedy_cic_simulations"}
        _keys("limits", limits, LIMIT_KEYS, needed)
        for key, value in limits.items():
            _integer(key, value)
        for key in LIMIT_KEYS:
            limits.setdefault(key, 0)
        base = Path(base_directory)
        for key in ("output_directory", "processed_directory"):
            if key not in c:
                c[key] = str(PROJECT_ROOT / "data/processed" / c["dataset"])
            value = c[key]
            if not isinstance(value, str) or not value:
                raise ExperimentConfigError(f"{key} must be a nonempty path string")
            path = Path(value)
            c[key] = (path if path.is_absolute() else base / path).resolve().as_posix()
        return cls(c, source_path)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._values)

    @property
    def fingerprint(self) -> str:
        """Output location does not alter the scientific identity or seed schedule."""
        values = self.to_dict()
        values.pop("output_directory")
        values.pop("save_raw_observations")
        return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def run_directory(self) -> Path:
        c = self._values
        return Path(c["output_directory"]) / c["dataset"] / f"run_{c['independent_run_index']:04d}_{self.fingerprint[:12]}"


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    """Read UTF-8 JSON; relative paths are relative to the configuration file."""
    path = Path(path).resolve()
    if path.suffix.lower() != ".json":
        raise ExperimentConfigError("Use a .json configuration; YAML is not required or installed")
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExperimentConfigError(f"Cannot read configuration {path}: {exc}") from exc
    return ExperimentConfig.from_dict(values, base_directory=path.parent, source_path=path)
