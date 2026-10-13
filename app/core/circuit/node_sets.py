import json
from pathlib import Path

import libsonata


class _NodeSets:
    """Circuit and simulation node sets merged, the latter take precedence.

    Merged before parsing, as simulation node sets can reference the circuit ones.
    """

    def __init__(
        self,
        simulation_config: libsonata.SimulationConfig,
        circuit_config: libsonata.CircuitConfig,
    ):
        self._definitions: dict = {}
        for node_sets_file in (circuit_config.node_sets_path, simulation_config.node_sets_file):
            if node_sets_file:
                with open(node_sets_file) as f:
                    self._definitions.update(json.load(f))

        self._node_sets = libsonata.NodeSets(json.dumps(self._definitions))

    def __contains__(self, name: str) -> bool:
        return name in self._definitions

    def materialize(self, name: str, population: libsonata.NodePopulation) -> list[int]:
        """Compound node sets are resolved member by member, so a member defined by an
        attribute the population doesn't have doesn't drop the cells of the other ones.
        """
        definition = self._definitions[name]
        if isinstance(definition, list):
            node_ids = set()
            for member in definition:
                node_ids.update(self.materialize(member, population))
            return sorted(node_ids)

        try:
            return self._node_sets.materialize(name, population).flatten().tolist()
        except libsonata.SonataError as e:
            if "No such attribute" not in str(e):
                raise
            return []


def resolve_simulation_cells(simulation_config_path: Path | str) -> list[tuple[str, int]]:
    """Resolve the node set of a simulation into (population, node_id) pairs.

    A node set can be defined by explicit node ids, by node properties
    (e.g. {"synapse_class": "EXC"}) or as a list of other node sets, either in the circuit
    or in the simulation node sets file, so it has to be resolved against the circuit nodes.
    Without a node set all the nodes are simulated.

    Virtual populations are skipped as they can't be instantiated.
    """
    simulation_config = libsonata.SimulationConfig.from_file(str(simulation_config_path))
    circuit_config = libsonata.CircuitConfig.from_file(simulation_config.network)

    node_set_name = simulation_config.node_set
    node_sets = _NodeSets(simulation_config, circuit_config)

    if node_set_name is not None and node_set_name not in node_sets:
        raise KeyError(f"Node set '{node_set_name}' not found in node sets file")

    cells: list[tuple[str, int]] = []
    for population_name in sorted(circuit_config.node_populations):
        if circuit_config.node_population_properties(population_name).type == "virtual":
            continue

        population = circuit_config.node_population(population_name)
        if node_set_name is None:
            node_ids = population.select_all().flatten().tolist()
        else:
            node_ids = node_sets.materialize(node_set_name, population)

        cells.extend((population_name, node_id) for node_id in node_ids)

    if not cells:
        raise ValueError(f"Node set '{node_set_name or 'All nodes'}' doesn't contain any cells")

    return cells
