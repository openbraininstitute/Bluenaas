import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import h5py
import libsonata
import numpy as np

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.constants import CIRCUIT_SIMULATION_CONFIG_NAME
from app.core.circuit.node_sets import resolve_simulation_cells
from app.core.circuit.simulation import Simulation

BIOPHYSICAL_POPULATION = {
    "type": "biophysical",
    "morphologies_dir": ".",
    "biophysical_neuron_models_dir": ".",
}

CIRCUIT_NODE_SETS = {
    "PopA": {"population": "popA"},
    "PopB": {"population": "popB"},
    "All": ["PopA", "PopB"],
    "Excitatory": {"synapse_class": "EXC"},
    "L1_DAC": {"mtype": "L1_DAC"},
    "Explicit": {"population": "popA", "node_id": [3, 1]},
    "Empty": {"mtype": "L6_UNKNOWN"},
    "L1_DAC_or_Excitatory": ["L1_DAC", "Excitatory"],
}

SIMULATION_NODE_SETS = {
    "Default: All Biophysical Neurons": ["Excitatory"],
    "Explicit": {"population": "popA", "node_id": [0]},
}


def _write_population(group: h5py.Group, attributes: dict[str, list[str]]) -> None:
    size = len(next(iter(attributes.values())))
    group["node_type_id"] = np.full(size, -1)
    attrs_group = group.create_group("0")
    for name, values in attributes.items():
        attrs_group.create_dataset(
            name, data=np.array(values, dtype=object), dtype=h5py.string_dtype()
        )


class TestResolveSimulationCells(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.circuit_dir = self.tmpdir / "circuit"
        self.simulation_dir = self.tmpdir / "simulation"
        self.circuit_dir.mkdir()
        self.simulation_dir.mkdir()

        with h5py.File(self.circuit_dir / "nodes.h5", "w") as f:
            _write_population(
                f.create_group("nodes/popA"),
                {
                    "mtype": ["L5_TPC", "L5_TPC", "L1_DAC", "L5_TPC"],
                    "synapse_class": ["EXC", "EXC", "INH", "EXC"],
                },
            )
            # No synapse_class attribute.
            _write_population(f.create_group("nodes/popB"), {"mtype": ["L2_IPC", "L1_DAC"]})

        with h5py.File(self.circuit_dir / "virtual_nodes.h5", "w") as f:
            _write_population(f.create_group("nodes/virt"), {"synapse_class": ["EXC", "EXC"]})

        (self.circuit_dir / "node_sets.json").write_text(json.dumps(CIRCUIT_NODE_SETS))
        (self.simulation_dir / "node_sets.json").write_text(json.dumps(SIMULATION_NODE_SETS))

        self._write_circuit_config(with_node_sets=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write_circuit_config(self, *, with_node_sets: bool) -> None:
        config = {
            "version": 2,
            "networks": {
                "nodes": [
                    {
                        "nodes_file": "nodes.h5",
                        "populations": {
                            "popA": BIOPHYSICAL_POPULATION,
                            "popB": BIOPHYSICAL_POPULATION,
                        },
                    },
                    {
                        "nodes_file": "virtual_nodes.h5",
                        "populations": {"virt": {"type": "virtual"}},
                    },
                ],
                "edges": [],
            },
        }
        if with_node_sets:
            config["node_sets_file"] = "node_sets.json"

        (self.circuit_dir / "circuit_config.json").write_text(json.dumps(config))

    def _write_simulation_config(self, node_set: str | None) -> Path:
        config = {
            "version": 1,
            "network": str(self.circuit_dir / "circuit_config.json"),
            "node_sets_file": "node_sets.json",
            "run": {"tstop": 1500.0, "dt": 0.025, "random_seed": 1},
        }
        if node_set is not None:
            config["node_set"] = node_set

        config_path = self.simulation_dir / CIRCUIT_SIMULATION_CONFIG_NAME
        config_path.write_text(json.dumps(config))
        return config_path

    def test_property_node_set(self):
        """popB lacks the attribute and virtual nodes are skipped"""
        config_path = self._write_simulation_config("Excitatory")

        self.assertEqual(
            resolve_simulation_cells(config_path),
            [("popA", 0), ("popA", 1), ("popA", 3)],
        )

    def test_property_node_set_across_populations(self):
        config_path = self._write_simulation_config("L1_DAC")

        self.assertEqual(resolve_simulation_cells(config_path), [("popA", 2), ("popB", 1)])

    def test_compound_node_set(self):
        config_path = self._write_simulation_config("All")

        self.assertEqual(
            resolve_simulation_cells(config_path),
            [("popA", 0), ("popA", 1), ("popA", 2), ("popA", 3), ("popB", 0), ("popB", 1)],
        )

    def test_compound_node_set_with_attribute_missing_in_population(self):
        """popB lacks synapse_class, its L1_DAC cell is still included"""
        config_path = self._write_simulation_config("L1_DAC_or_Excitatory")

        self.assertEqual(
            resolve_simulation_cells(config_path),
            [("popA", 0), ("popA", 1), ("popA", 2), ("popA", 3), ("popB", 1)],
        )

    def test_simulation_only_node_set(self):
        config_path = self._write_simulation_config("Default: All Biophysical Neurons")

        self.assertEqual(
            resolve_simulation_cells(config_path),
            [("popA", 0), ("popA", 1), ("popA", 3)],
        )

    def test_simulation_node_set_overrides_circuit_one(self):
        config_path = self._write_simulation_config("Explicit")

        self.assertEqual(resolve_simulation_cells(config_path), [("popA", 0)])

    def test_explicit_node_ids(self):
        (self.simulation_dir / "node_sets.json").write_text("{}")
        config_path = self._write_simulation_config("Explicit")

        self.assertEqual(resolve_simulation_cells(config_path), [("popA", 1), ("popA", 3)])

    def test_without_node_set(self):
        """All non-virtual nodes, even without an "All" node set"""
        self._write_circuit_config(with_node_sets=False)
        (self.simulation_dir / "node_sets.json").write_text("{}")
        config_path = self._write_simulation_config(None)

        self.assertEqual(
            resolve_simulation_cells(config_path),
            [("popA", 0), ("popA", 1), ("popA", 2), ("popA", 3), ("popB", 0), ("popB", 1)],
        )

    def test_circuit_without_node_sets(self):
        self._write_circuit_config(with_node_sets=False)
        (self.simulation_dir / "node_sets.json").write_text(
            json.dumps({"Sim": {"population": "popB"}})
        )
        config_path = self._write_simulation_config("Sim")

        self.assertEqual(resolve_simulation_cells(config_path), [("popB", 0), ("popB", 1)])

    def test_missing_node_set(self):
        config_path = self._write_simulation_config("Missing")

        with self.assertRaisesRegex(KeyError, "Node set 'Missing' not found"):
            resolve_simulation_cells(config_path)

    def test_invalid_node_set(self):
        (self.simulation_dir / "node_sets.json").write_text(json.dumps({"Invalid": {"mtype": 1}}))
        config_path = self._write_simulation_config("Invalid")

        with self.assertRaisesRegex(libsonata.SonataError, "Unexpected datatype"):
            resolve_simulation_cells(config_path)

    def test_empty_node_set(self):
        config_path = self._write_simulation_config("Empty")

        with self.assertRaisesRegex(ValueError, "doesn't contain any cells"):
            resolve_simulation_cells(config_path)

    def test_get_simulation_params(self):
        self._write_simulation_config("Excitatory")
        simulation = Simulation.__new__(Simulation)
        simulation.path = self.simulation_dir

        params = simulation.get_simulation_params()

        self.assertEqual(params.num_cells, 3)
        self.assertEqual(params.tstop, 1500.0)


if __name__ == "__main__":
    unittest.main()
