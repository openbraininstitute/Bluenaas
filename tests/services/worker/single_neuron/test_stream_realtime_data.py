import os
import unittest
from queue import Queue
from unittest.mock import MagicMock, patch

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.exceptions import SimulationError  # noqa: E402
from app.domains.job import JobStatus  # noqa: E402
from app.services.worker.single_neuron.simulation import (  # noqa: E402
    queue_record_to_stream_record,
    queue_spike_to_stream_record,
    stream_realtime_data,
)
from app.utils.const import QUEUE_STOP_EVENT  # noqa: E402


def _trace_record(*, frequency=None, amplitude=0.5):
    return {
        "kind": "trace",
        "label": "AP_WAVEFORM_0.5",
        "recording_name": "soma[0]_0.5",
        "time_data": [0.0, 1.0, 2.0],
        "values_data": [-65.0, -64.0, -63.0],
        "variable_name": "v",
        "unit": "mV",
        "amplitude": amplitude,
        "frequency": frequency,
    }


def _spike_record(*, frequency=None, amplitude=0.5):
    return {
        "kind": "spikes",
        "label": "AP_WAVEFORM_0.5",
        "recording_name": "soma[0]_0.5",
        "spikes": [10.5, 20.0, 31.2],
        "variable_name": "v",
        "unit": "ms",
        "amplitude": amplitude,
        "frequency": frequency,
    }


class TestQueueRecordToStreamRecord(unittest.TestCase):
    def test_trace_payload_shape_unchanged(self):
        chunk = queue_record_to_stream_record(_trace_record(amplitude=0.5), is_current_varying=True)

        self.assertEqual(
            set(chunk.keys()),
            {
                "x",
                "y",
                "type",
                "name",
                "recording",
                "amplitude",
                "frequency",
                "varying_key",
                "variable_name",
                "unit",
            },
        )
        self.assertEqual(chunk["x"], [0.0, 1.0, 2.0])
        self.assertEqual(chunk["y"], [-65.0, -64.0, -63.0])
        self.assertEqual(chunk["type"], "scatter")
        self.assertEqual(chunk["name"], "AP_WAVEFORM_0.5")
        self.assertEqual(chunk["recording"], "soma[0]_0.5")
        self.assertEqual(chunk["amplitude"], 0.5)
        self.assertIsNone(chunk["frequency"])
        self.assertEqual(chunk["varying_key"], 0.5)
        self.assertEqual(chunk["variable_name"], "v")
        self.assertEqual(chunk["unit"], "mV")

    def test_trace_payload_uses_frequency_when_not_current_varying(self):
        chunk = queue_record_to_stream_record(
            _trace_record(amplitude=0.5, frequency=42.0),
            is_current_varying=False,
        )
        self.assertEqual(chunk["varying_key"], 42.0)


class TestQueueSpikeToStreamRecord(unittest.TestCase):
    def test_spike_payload_uses_spikes_axis(self):
        chunk = queue_spike_to_stream_record(_spike_record(amplitude=0.5), is_current_varying=True)

        self.assertEqual(
            set(chunk.keys()),
            {
                "spikes",
                "type",
                "name",
                "recording",
                "amplitude",
                "frequency",
                "varying_key",
                "variable_name",
                "unit",
            },
        )
        self.assertNotIn("x", chunk)
        self.assertNotIn("y", chunk)
        self.assertEqual(chunk["spikes"], [10.5, 20.0, 31.2])
        self.assertEqual(chunk["type"], "scatter")
        self.assertEqual(chunk["name"], "AP_WAVEFORM_0.5")
        self.assertEqual(chunk["recording"], "soma[0]_0.5")
        self.assertEqual(chunk["amplitude"], 0.5)
        self.assertEqual(chunk["varying_key"], 0.5)
        self.assertEqual(chunk["variable_name"], "v")
        self.assertEqual(chunk["unit"], "ms")

    def test_spike_payload_varying_key_falls_back_to_frequency(self):
        chunk = queue_spike_to_stream_record(
            _spike_record(amplitude=0.5, frequency=42.0),
            is_current_varying=False,
        )
        self.assertEqual(chunk["varying_key"], 42.0)


class TestStreamRealtimeData(unittest.TestCase):
    def setUp(self):
        self._patcher = patch(
            "app.services.worker.single_neuron.simulation.JobStream"
        )
        self._mock_job_stream_cls = self._patcher.start()
        self._mock_stream = MagicMock()
        self._mock_job_stream_cls.return_value = self._mock_stream
        self._patcher_key = patch(
            "app.services.worker.single_neuron.simulation.get_job_stream_key",
            return_value="test-stream-key",
        )
        self._patcher_key.start()

        self._fake_process = MagicMock()
        self._fake_process.is_alive.return_value = True

    def tearDown(self):
        self._patcher.stop()
        self._patcher_key.stop()

    def test_routes_trace_records_with_data_type_trace(self):
        q: Queue = Queue()
        q.put(_trace_record())
        q.put(QUEUE_STOP_EVENT)

        stream_realtime_data(q, self._fake_process, is_current_varying=True)

        self.assertEqual(self._mock_stream.send_data.call_count, 1)
        call = self._mock_stream.send_data.call_args
        self.assertEqual(call.kwargs["data_type"], "trace")
        chunk = call.args[0]
        self.assertIn("x", chunk)
        self.assertIn("y", chunk)
        self.assertNotIn("spikes", chunk)

    def test_routes_spike_records_with_data_type_spikes(self):
        q: Queue = Queue()
        q.put(_spike_record())
        q.put(QUEUE_STOP_EVENT)

        stream_realtime_data(q, self._fake_process, is_current_varying=True)

        self.assertEqual(self._mock_stream.send_data.call_count, 1)
        call = self._mock_stream.send_data.call_args
        self.assertEqual(call.kwargs["data_type"], "spikes")
        chunk = call.args[0]
        self.assertEqual(chunk["spikes"], [10.5, 20.0, 31.2])
        self.assertNotIn("x", chunk)
        self.assertNotIn("y", chunk)

    def test_default_kind_is_trace_for_legacy_records(self):
        legacy = _trace_record()
        legacy.pop("kind")

        q: Queue = Queue()
        q.put(legacy)
        q.put(QUEUE_STOP_EVENT)

        stream_realtime_data(q, self._fake_process, is_current_varying=True)

        call = self._mock_stream.send_data.call_args
        self.assertEqual(call.kwargs["data_type"], "trace")
        self.assertIn("x", call.args[0])

    def test_routes_mix_of_trace_and_spike_records(self):
        q: Queue = Queue()
        q.put(_trace_record())
        q.put(_spike_record())
        q.put(QUEUE_STOP_EVENT)

        stream_realtime_data(q, self._fake_process, is_current_varying=True)

        self.assertEqual(self._mock_stream.send_data.call_count, 2)
        first, second = self._mock_stream.send_data.call_args_list
        self.assertEqual(first.kwargs["data_type"], "trace")
        self.assertEqual(second.kwargs["data_type"], "spikes")

    def test_simulation_error_sends_status_and_breaks(self):
        q: Queue = Queue()
        q.put(SimulationError("boom"))

        stream_realtime_data(q, self._fake_process, is_current_varying=True)

        self._mock_stream.send_status.assert_called_once()
        sent_status = self._mock_stream.send_status.call_args.kwargs["job_status"]
        self.assertEqual(sent_status, JobStatus.error)
        self._mock_stream.send_data.assert_not_called()

    def test_queue_stop_event_sends_done_status(self):
        q: Queue = Queue()
        q.put(QUEUE_STOP_EVENT)

        stream_realtime_data(q, self._fake_process, is_current_varying=True)

        self._mock_stream.send_status.assert_called_once_with(job_status=JobStatus.done)
        self._mock_stream.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
