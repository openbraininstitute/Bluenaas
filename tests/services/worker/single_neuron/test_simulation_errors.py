import json
import multiprocessing as mp
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.exceptions import SimulationError, SingleNeuronInitError
from app.services.worker.single_neuron.simulation import (
    init_current_varying_simulation,
    stream_realtime_data,
)
from app.utils.const import QUEUE_STOP_EVENT


HOC_ERROR = "Less than three axon sections are present!"
NEURON_BLOCK = (
    f"NEURON: {HOC_ERROR}\n"
    " in /app/storage/single-neuron/model/ab/cd/hoc/cell.hoc near line 42\n"
    " cADpyr[0].replace_axon()"
)


class _QueueStub:
    """Records what the child puts on the queue, and replays it to the parent."""

    def __init__(self, records=()):
        self.puts = []
        self._records = list(records)

    def put(self, record):
        self.puts.append(record)

    def get(self, timeout=None):
        return self._records.pop(0)


class TestChildReportsWhyTheModelFailed(unittest.TestCase):
    def _run(self, model_error):
        simulation_queue = _QueueStub()
        config = MagicMock()
        config.type = "single-neuron-simulation"
        config.synaptome = None

        with patch("app.core.model.model_factory", side_effect=model_error):
            with self.assertRaises(SimulationError) as ctx:
                init_current_varying_simulation(
                    MagicMock(),
                    config,
                    access_token="token",
                    realtime=True,
                    simulation_queue=simulation_queue,
                    stop_event=MagicMock(),
                    project_context=MagicMock(),
                )

        return ctx.exception, simulation_queue

    def test_the_reason_survives_instead_of_a_constant_string(self):
        error, simulation_queue = self._run(SingleNeuronInitError(HOC_ERROR))

        self.assertEqual(str(error), HOC_ERROR)
        self.assertNotEqual(str(error), SimulationError.default_message)

    def test_the_reason_is_queued_so_the_parent_does_not_just_see_a_dead_child(self):
        _error, simulation_queue = self._run(SingleNeuronInitError(HOC_ERROR))

        queued, stop = simulation_queue.puts
        self.assertIsInstance(queued, SimulationError)
        self.assertEqual(str(queued), HOC_ERROR)
        self.assertEqual(stop, QUEUE_STOP_EVENT)

    def test_neurons_printed_block_is_queued_with_the_reason(self):
        _error, simulation_queue = self._run(SingleNeuronInitError(HOC_ERROR, details=NEURON_BLOCK))

        queued = simulation_queue.puts[0]
        self.assertEqual(str(queued), HOC_ERROR)
        self.assertEqual(queued.details, NEURON_BLOCK)

    def test_the_block_survives_the_queue_to_the_parent_process(self):
        # The parent reads a pickled copy, and details is not one of the exception's args.
        simulation_queue = mp.get_context("spawn").Queue()
        simulation_queue.put(SimulationError(HOC_ERROR, details=NEURON_BLOCK))

        received = simulation_queue.get(timeout=5)

        self.assertEqual(str(received), HOC_ERROR)
        self.assertEqual(received.details, NEURON_BLOCK)

    def test_an_error_that_is_already_a_simulation_error_is_passed_through(self):
        original = SimulationError("stimulus outside the recording window")
        error, simulation_queue = self._run(original)

        self.assertIs(error, original)
        self.assertIs(simulation_queue.puts[0], original)


class TestParentStreamsTheReason(unittest.TestCase):
    def _stream(self, error):
        simulation_queue = _QueueStub([error])
        process = MagicMock()

        with patch("app.services.worker.single_neuron.simulation.get_job_stream_key"):
            with patch("app.services.worker.single_neuron.simulation.JobStream") as JobStreamMock:
                with self.assertRaises(SimulationError):
                    stream_realtime_data(
                        simulation_queue=simulation_queue,
                        _process=process,
                        is_current_varying=True,
                    )

        _kwargs = JobStreamMock.return_value.send_status.call_args.kwargs
        return json.loads(_kwargs["extra"])

    def test_the_client_is_told_why(self):
        payload = self._stream(SimulationError(HOC_ERROR))

        self.assertEqual(payload["details"], HOC_ERROR)

    def test_the_client_gets_neurons_block_after_the_reason(self):
        payload = self._stream(SimulationError(HOC_ERROR, details=NEURON_BLOCK))

        self.assertTrue(payload["details"].startswith(f"{HOC_ERROR}\n"), payload["details"])
        self.assertIn("cell.hoc near line 42", payload["details"])
        self.assertIn("cADpyr[0].replace_axon()", payload["details"])
        self.assertNotIn("/app/storage", payload["details"])

    def test_container_paths_do_not_reach_the_client(self):
        error = SimulationError("NEURON: Couldn't find: /app/storage/single-neuron/ab/cell.hoc")

        payload = self._stream(error)

        self.assertNotIn("/app/storage", payload["details"])
        self.assertIn("cell.hoc", payload["details"])


if __name__ == "__main__":
    unittest.main()
