import unittest

import numpy as np

from app.domains.morphology import ExclusionRule, LocationData
from app.utils.util import (
    get_segments_satisfying_all_exclusion_rules,
    perpendicular_vector,
)


class TestExclusionRules(unittest.TestCase):
    distances = [
        28.525972794621996,
        48.820898141288524,
        69.11582348795505,
        89.41074883462159,
        109.70567418128812,
    ]

    def _create_mock_location_data(self, nseg: int = 5) -> LocationData:
        """Create a mock LocationData object for testing"""
        return LocationData(
            index=0,
            nseg=nseg,
            xstart=[0.0] * nseg,
            xend=[1.0] * nseg,
            xcenter=[0.5] * nseg,
            xdirection=[1.0] * nseg,
            ystart=[0.0] * nseg,
            yend=[1.0] * nseg,
            ycenter=[0.5] * nseg,
            ydirection=[1.0] * nseg,
            zstart=[0.0] * nseg,
            zend=[1.0] * nseg,
            zcenter=[0.5] * nseg,
            zdirection=[1.0] * nseg,
            segx=[0.0] * nseg,
            diam=[1.0] * nseg,
            length=[1.0] * nseg,
            distance=[0.0] * nseg,
            distance_from_soma=0.0,
            sec_length=1.0,
            neuron_segments_offset=[0.0] * nseg,
            neuron_section_id=0,
            segment_distance_from_soma=[0.0] * nseg,
        )

    def test_returns_none_if_no_exclusion_rules(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=None,
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_returns_satisfying_indices_when_exclusion_has_both(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_gte=29.122, distance_soma_lte=90.89)],
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, [0, 4])

    def test_returns_satisfying_indices_when_exclusion_has_gte_only(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_gte=29.122)],
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, [0])

    def test_returns_satisfying_indices_when_exclusion_has_lte_only(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=90.67)],
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, [4])

    def test_returns_all_indices_when_all_ele_staisfy_exclusion_rule(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_gte=200.67)],
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_returns_all_indices_when_all_ele_staisfy_exclusion_rule_with_lte(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=5)],
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_returns_no_indices_when_no_ele_staisfy_exclusion_rule_with_lte(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=200)],
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, None)

    def test_intersection_rules_return_indices_of_all_satisfying_rules(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=200)],
            segment_distances=self.distances,
            section_info=self._create_mock_location_data(),
        )
        self.assertEqual(result, None)

    def test_work_for_one_distance(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=50)],
            segment_distances=[
                37.19594572627648,
                46.140226793353406,
                55.08450786043035,
            ],
            section_info=self._create_mock_location_data(3),
        )
        self.assertEqual(result, [2])


class TestPerpendicularVector(unittest.TestCase):
    def test_perpendicular_to_x_axis_deterministic(self):
        # Test with fixed random seed for deterministic results
        np.random.seed(42)
        v = np.array([1, 0, 0])
        result = perpendicular_vector(v)
        # Should be perpendicular
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_perpendicular_to_y_axis_deterministic(self):
        # Test with fixed random seed for deterministic results
        np.random.seed(42)
        v = np.array([0, 1, 0])
        result = perpendicular_vector(v)
        # Should be perpendicular
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_perpendicular_to_z_axis_deterministic(self):
        # Test with fixed random seed for deterministic results
        np.random.seed(42)
        v = np.array([0, 0, 1])
        result = perpendicular_vector(v)
        # Should be perpendicular
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_perpendicular_to_xy_vector_deterministic(self):
        # Test with fixed random seed for deterministic results
        np.random.seed(42)
        v = np.array([3, 4, 0])
        result = perpendicular_vector(v)
        # Should be perpendicular
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_perpendicular_to_original_problem_vector_deterministic(self):
        # Test with fixed random seed for deterministic results
        np.random.seed(42)
        v = np.array([0, 21.46288667, 0])
        result = perpendicular_vector(v)
        # Should be perpendicular
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_perpendicular_to_xyz_vector_deterministic(self):
        # Test with fixed random seed for deterministic results
        np.random.seed(42)
        v = np.array([1, 2, 3])
        result = perpendicular_vector(v)
        # Should be perpendicular
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_result_is_perpendicular_xy_case(self):
        v = np.array([5, 12, 0])
        result = perpendicular_vector(v)
        # Dot product should be zero
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_result_is_perpendicular_z_case(self):
        v = np.array([0, 0, 7])
        result = perpendicular_vector(v)
        # Dot product should be zero
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_result_is_perpendicular_general_case(self):
        v = np.array([1.5, -2.7, 3.9])
        result = perpendicular_vector(v)
        # Dot product should be zero
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_zero_vector_raises_error(self):
        v = np.array([0, 0, 0])
        with self.assertRaises(ValueError) as context:
            perpendicular_vector(v)
        self.assertIn("Cannot find perpendicular vector for zero vector", str(context.exception))

    def test_near_zero_vector_raises_error(self):
        v = np.array([1e-15, 1e-15, 1e-15])
        with self.assertRaises(ValueError):
            perpendicular_vector(v)

    def test_small_but_valid_vector(self):
        v = np.array([1e-5, 0, 0])
        result = perpendicular_vector(v)
        # Should be perpendicular
        dot_product = np.dot(v, result)
        self.assertAlmostEqual(dot_product, 0, places=10)

    def test_randomization_produces_different_results(self):
        v = np.array([1, 2, 3])
        results = []
        # Generate multiple results to check they're different
        for _ in range(10):
            result = perpendicular_vector(v)
            # Each should be perpendicular
            dot_product = np.dot(v, result)
            self.assertAlmostEqual(dot_product, 0, places=10)
            results.append(result.copy())

        # Check that not all results are identical (randomization works)
        all_same = all(np.allclose(results[0], r) for r in results[1:])
        self.assertFalse(
            all_same, "All results should not be identical - randomization should work"
        )

    def test_result_lies_in_perpendicular_plane(self):
        # Test that the result lies in the 2D plane perpendicular to the input vector
        v = np.array([1, 1, 1])
        v_normalized = v / np.linalg.norm(v)

        for _ in range(5):
            result = perpendicular_vector(v)
            # Should be perpendicular to v
            dot_product = np.dot(v_normalized, result)
            self.assertAlmostEqual(dot_product, 0, places=10)
            # Should be non-zero
            self.assertGreater(np.linalg.norm(result), 1e-10)

    def test_deterministic_behavior_with_seed(self):
        v = np.array([2, 3, 5])

        # Same seed should give same result
        np.random.seed(123)
        result1 = perpendicular_vector(v)

        np.random.seed(123)
        result2 = perpendicular_vector(v)

        np.testing.assert_array_almost_equal(result1, result2)

        # Different seed should give different result
        np.random.seed(456)
        result3 = perpendicular_vector(v)

        self.assertFalse(np.allclose(result1, result3))


if __name__ == "__main__":
    unittest.main()
