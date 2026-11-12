"""Worker bridge and scope guards, using temporary processed fixtures only."""

from copy import deepcopy
import json
from unittest.mock import patch

from experiments.design_protocol_v1 import load_protocol
from experiments.pilot_milestone_7 import execute_pilot, selection_worker
from src.data.specs import PROJECT_ROOT
from src.data.storage import save_processed_graph
from tests.experiment_helpers import processed_fixture
from tests.helpers import metadata_for, TemporaryFilesTest


class SensitivityPilotTests(TemporaryFilesTest):
    def setUp(self):
        super().setUp()
        self.protocol = load_protocol(PROJECT_ROOT/"experiments/configs/experiment_protocol_v1.json")

    def test_selection_worker_preserves_core_output_seeds_and_processed_bytes(self):
        graph = processed_fixture(self.root)
        directory = self.root/"data/processed/unit-test-fixture"
        save_processed_graph(graph, metadata_for(graph), directory)
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        protocol = {**self.protocol, "k": 1, "p": .5, "S_opt": 3}
        params = {**self.protocol["reference_ga"], "population_size": 4, "max_generations": 1, "tournament_size": 2}
        destination = self.root/"kết quả selection.json"
        job = {"run_id": "fixture", "protocol": protocol,
               "scenario": {"dataset": "unit-test-fixture", "rumor_seeds": [10]},
               "profile": {"profile_id": "reference", "parameters": params},
               "seeds": {"operators_input_seed": 123, "optimization_base_seed": 1000, "final_base_seed": 501000},
               "selection_path": str(destination)}
        path = self.write(json.dumps(job), "job.json")
        with patch("experiments.pilot_milestone_7.PROJECT_ROOT", self.root):
            self.assertEqual(selection_worker(path), 0)
        saved = json.loads(destination.read_text())
        core = saved["core_GA_result"]
        self.assertEqual(core["parameters"]["random_seed"], 123)
        self.assertEqual(core["seeds"]["fitness_base_random_seed"], 1000)
        self.assertEqual(core["generations_run"], 1)
        self.assertEqual(len(core["history"]), 2)
        self.assertEqual(len(core["best_protector_nodes"]), 1)
        self.assertNotIn(10, core["best_protector_nodes"])
        self.assertEqual(core["cic_simulation_count"], core["evaluation_count"]*3)
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_non_admitted_pilot_is_rejected_before_any_output_or_GA_call(self):
        destination = self.root/"must-not-exist"
        design = {"preflights": {"pilot": {"within_declared_budget": False}}, "pilot_schedule": []}
        with patch("experiments.pilot_milestone_7.select_genetic_algorithm") as ga:
            with self.assertRaisesRegex(ValueError, "preflight rejected"):
                execute_pilot(self.protocol, design, destination)
        ga.assert_not_called()
        self.assertFalse(destination.exists())
