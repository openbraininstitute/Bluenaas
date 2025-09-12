import unittest
import numpy as np
from app.utils.util import (
    generate_pre_spiketrain,
)


class TestSpikeTrainGeneration(unittest.TestCase):
    def test_single_frequency(self):
        # Test with a single frequency
        duration = 1000
        delay = 100
        frequencies = [10.0]  # 10 Hz

        result = generate_pre_spiketrain(duration, delay, frequencies)

        # Test that the result is a numpy array
        self.assertIsInstance(result, np.ndarray)

        # Test that all spike times are greater than or equal to the delay
        self.assertTrue(np.all(result >= delay))

        # Test that the number of spikes is close to the expected number
        expected_spikes = int(duration / 1000 * frequencies[0])
        self.assertAlmostEqual(len(result), expected_spikes, delta=1)

    def test_multiple_frequencies(self):
        # Test with multiple frequencies
        duration = 1000
        delay = 50
        frequencies = [20.0, 5.0]

        result = generate_pre_spiketrain(duration, delay, frequencies)

        # Test that the result is a numpy array
        self.assertIsInstance(result, np.ndarray)

        # Test that the array is sorted
        self.assertTrue(np.all(np.diff(result) >= 0))

        # Test that all spike times are greater than or equal to the delay
        self.assertTrue(np.all(result >= delay))

        # Check the total number of spikes is close to the combined expected number
        expected_spikes = int(duration / 1000 * (frequencies[0] + frequencies[1]))
        self.assertAlmostEqual(len(result), expected_spikes, delta=2)

    def test_spike_train_is_in_ascending_order_of_time(self):
        duration = 1000
        delay = 100
        frequencies = [10.0, 20.0, 5.0]  # Hz

        result = generate_pre_spiketrain(duration, delay, frequencies)

        # Check that the result is sorted in ascending order
        self.assertTrue(np.all(np.diff(result) >= 0), "Spike times are not in ascending order")

    def test_empty_frequencies(self):
        duration = 1000
        delay = 50
        frequencies = []

        result = generate_pre_spiketrain(duration, delay, frequencies)

        self.assertEqual(result.size, 0)

    def test_zero_duration(self):
        duration = 0
        delay = 10
        frequencies = [10.0]

        result = generate_pre_spiketrain(duration, delay, frequencies)
        self.assertTrue(np.array_equal(result, np.array([10])))


if __name__ == "__main__":
    unittest.main()
