import builtins
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from app.core.stimulation import (  # noqa: E402
    _create_recording_data,
    _create_spike_data,
    _detect_and_enqueue_spikes,
)
from app.domains.simulation import RecordingLocation  # noqa: E402


class _FakeStimulus:
    def __init__(self, time):
        self.time = time


def _make_cell(voltage_by_section: dict[str, np.ndarray], time: np.ndarray):
    cell = MagicMock()
    cell.sections = {name: MagicMock(name=f"section-{name}") for name in voltage_by_section}

    def _get_var(_var_name, sec, _seg):
        # find which section was passed
        for name, section_mock in cell.sections.items():
            if section_mock is sec:
                return voltage_by_section[name]
        raise KeyError("unknown section")

    cell.get_variable_recording.side_effect = _get_var
    cell.get_time.return_value = time
    return cell


class TestCreateRecordingData(unittest.TestCase):
    def test_create_recording_data_kind_is_trace(self):
        rec = _create_recording_data(
            label="AP_WAVEFORM_0.5",
            recording_name="soma[0]_0.5",
            time_data=np.array([0.0, 1.0]),
            values_data=np.array([-65.0, -64.0]),
            variable_name="v",
            unit="mV",
            amplitude=0.5,
            frequency=None,
        )
        self.assertEqual(rec["kind"], "trace")
        self.assertEqual(rec["label"], "AP_WAVEFORM_0.5")
        self.assertEqual(rec["recording_name"], "soma[0]_0.5")
        self.assertEqual(rec["time_data"], [0.0, 1.0])
        self.assertEqual(rec["values_data"], [-65.0, -64.0])


class TestCreateSpikeData(unittest.TestCase):
    def test_create_spike_data_shape(self):
        rec = _create_spike_data(
            label="AP_WAVEFORM_0.5",
            recording_name="soma[0]_0.5",
            spikes=[10.0, 20.5],
            variable_name="v",
            unit="ms",
            amplitude=0.5,
            frequency=None,
        )
        self.assertEqual(rec["kind"], "spikes")
        self.assertEqual(rec["spikes"], [10.0, 20.5])
        self.assertEqual(rec["variable_name"], "v")
        self.assertEqual(rec["unit"], "ms")
        self.assertEqual(rec["amplitude"], 0.5)
        self.assertIsNone(rec["frequency"])
        self.assertNotIn("x", rec)
        self.assertNotIn("y", rec)


class TestDetectAndEnqueueSpikes(unittest.TestCase):
    def setUp(self):
        # Provide a stub `efel` module so the lazy `import efel` inside the
        # helper resolves to our mock instead of the real (forked-process-only)
        # library.
        self._efel_stub = MagicMock()
        self._efel_patch = patch.dict(sys.modules, {"efel": self._efel_stub})
        self._efel_patch.start()

    def tearDown(self):
        self._efel_patch.stop()

    def _run(
        self,
        *,
        cell,
        locations,
        stimulus=_FakeStimulus(np.array([5.0, 100.0])),
        amplitude=0.5,
        frequency=None,
        label="AP_WAVEFORM_0.5",
        simulation_duration=200,
    ):
        queue = MagicMock()
        _detect_and_enqueue_spikes(
            cell=cell,
            recording_locations=locations,
            stimulus=stimulus,
            simulation_duration=simulation_duration,
            label=label,
            amplitude=amplitude,
            frequency=frequency,
            simulation_queue=queue,
        )
        return queue

    def test_emits_one_message_per_recording_with_peak_times(self):
        time = np.linspace(0.0, 100.0, 200)
        voltage = np.full(200, -65.0)
        cell = _make_cell({"soma[0]": voltage, "dend[1]": voltage}, time)
        locations = [
            RecordingLocation(section="soma[0]", offset=0.5),
            RecordingLocation(section="dend[1]", offset=0.5),
        ]

        self._efel_stub.get_feature_values.return_value = [
            {"peak_time": np.array([10.5, 20.0])}
        ]

        queue = self._run(cell=cell, locations=locations)

        self.assertEqual(queue.put.call_count, 2)
        first = queue.put.call_args_list[0].args[0]
        self.assertEqual(first["kind"], "spikes")
        self.assertEqual(first["spikes"], [10.5, 20.0])
        self.assertEqual(first["recording_name"], "soma[0]_0.5")
        self.assertEqual(first["unit"], "ms")
        self.assertEqual(first["variable_name"], "v")
        self.assertEqual(first["amplitude"], 0.5)
        self.assertIsNone(first["frequency"])

        second = queue.put.call_args_list[1].args[0]
        self.assertEqual(second["recording_name"], "dend[1]_0.5")

    def test_none_peak_time_emits_empty_spikes(self):
        time = np.linspace(0.0, 100.0, 200)
        voltage = np.full(200, -65.0)
        cell = _make_cell({"soma[0]": voltage}, time)
        locations = [RecordingLocation(section="soma[0]", offset=0.5)]

        self._efel_stub.get_feature_values.return_value = [{"peak_time": None}]

        queue = self._run(cell=cell, locations=locations)

        self.assertEqual(queue.put.call_count, 1)
        record = queue.put.call_args.args[0]
        self.assertEqual(record["kind"], "spikes")
        self.assertEqual(record["spikes"], [])

    def test_skips_short_voltage_trace(self):
        cell = _make_cell({"soma[0]": np.array([-65.0])}, np.array([0.0]))
        locations = [RecordingLocation(section="soma[0]", offset=0.5)]

        queue = self._run(cell=cell, locations=locations)

        self.assertEqual(queue.put.call_count, 0)
        self._efel_stub.get_feature_values.assert_not_called()

    def test_swallows_efel_runtime_exception(self):
        time = np.linspace(0.0, 100.0, 200)
        voltage = np.full(200, -65.0)
        cell = _make_cell({"soma[0]": voltage}, time)
        locations = [RecordingLocation(section="soma[0]", offset=0.5)]

        self._efel_stub.get_feature_values.side_effect = RuntimeError("kaboom")

        # Must not raise.
        queue = self._run(cell=cell, locations=locations)
        self.assertEqual(queue.put.call_count, 0)

    def test_swallows_efel_import_error(self):
        # Stop the per-test stub so the import fails inside the helper.
        self._efel_patch.stop()
        try:
            real_import = builtins.__import__

            def _fake_import(name, *args, **kwargs):
                if name == "efel":
                    raise ImportError("efel not installed")
                return real_import(name, *args, **kwargs)

            time = np.linspace(0.0, 100.0, 200)
            voltage = np.full(200, -65.0)
            cell = _make_cell({"soma[0]": voltage}, time)
            locations = [RecordingLocation(section="soma[0]", offset=0.5)]

            with patch.object(builtins, "__import__", side_effect=_fake_import):
                queue = self._run(cell=cell, locations=locations)

            self.assertEqual(queue.put.call_count, 0)
        finally:
            # Restart the stub so tearDown can stop it cleanly.
            self._efel_patch.start()

    def test_stim_window_uses_stimulus_time_bounds(self):
        time = np.linspace(0.0, 100.0, 200)
        voltage = np.full(200, -65.0)
        cell = _make_cell({"soma[0]": voltage}, time)
        locations = [RecordingLocation(section="soma[0]", offset=0.5)]

        self._efel_stub.get_feature_values.return_value = [{"peak_time": None}]

        self._run(
            cell=cell,
            locations=locations,
            stimulus=_FakeStimulus(np.array([7.5, 42.0])),
            simulation_duration=999,
        )

        traces_arg, features_arg = self._efel_stub.get_feature_values.call_args.args
        self.assertEqual(features_arg, ["peak_time"])
        self.assertEqual(len(traces_arg), 1)
        self.assertEqual(traces_arg[0]["stim_start"], [7.5])
        self.assertEqual(traces_arg[0]["stim_end"], [42.0])

    def test_stim_window_falls_back_to_simulation_duration(self):
        time = np.linspace(0.0, 100.0, 200)
        voltage = np.full(200, -65.0)
        cell = _make_cell({"soma[0]": voltage}, time)
        locations = [RecordingLocation(section="soma[0]", offset=0.5)]

        self._efel_stub.get_feature_values.return_value = [{"peak_time": None}]

        self._run(cell=cell, locations=locations, stimulus=None, simulation_duration=250)

        traces_arg, _features_arg = self._efel_stub.get_feature_values.call_args.args
        self.assertEqual(traces_arg[0]["stim_start"], [0.0])
        self.assertEqual(traces_arg[0]["stim_end"], [250.0])


if __name__ == "__main__":
    unittest.main()
