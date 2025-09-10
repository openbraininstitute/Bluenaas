import unittest

import numpy as np

from app.domains.morphology import ExclusionRule
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

    def test_returns_none_if_no_exclusion_rules(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=None, segment_distances=self.distances
        )
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_returns_satisfying_indices_when_exclusion_has_both(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_gte=29.122, distance_soma_lte=90.89)],
            segment_distances=self.distances,
        )
        self.assertEqual(result, [0, 4])

    def test_returns_satisfying_indices_when_exclusion_has_gte_only(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_gte=29.122)],
            segment_distances=self.distances,
        )
        self.assertEqual(result, [0])

    def test_returns_satisfying_indices_when_exclusion_has_lte_only(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=90.67)],
            segment_distances=self.distances,
        )
        self.assertEqual(result, [4])

    def test_returns_all_indices_when_all_ele_staisfy_exclusion_rule(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_gte=200.67)],
            segment_distances=self.distances,
        )
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_returns_all_indices_when_all_ele_staisfy_exclusion_rule_with_lte(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=5)],
            segment_distances=self.distances,
        )
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_returns_no_indices_when_no_ele_staisfy_exclusion_rule_with_lte(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=200)],
            segment_distances=self.distances,
        )
        self.assertEqual(result, None)

    def test_intersection_rules_return_indices_of_all_satisfying_rules(self):
        result = get_segments_satisfying_all_exclusion_rules(
            rules=[ExclusionRule(distance_soma_lte=200)],
            segment_distances=self.distances,
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
        )
        self.assertEqual(result, [2])


class TestPerpendicularVector(unittest.TestCase):
    def test_perpendicular_to_x_axis(self):
        v = np.array([1, 0, 0])
        result = perpendicular_vector(v)
        expected = np.array([0, 1, 0])
        np.testing.assert_array_equal(result, expected)

    def test_perpendicular_to_y_axis(self):
        v = np.array([0, 1, 0])
        result = perpendicular_vector(v)
        expected = np.array([-1, 0, 0])
        np.testing.assert_array_equal(result, expected)

    def test_perpendicular_to_z_axis(self):
        v = np.array([0, 0, 1])
        result = perpendicular_vector(v)
        expected = np.array([-1, 0, 0])
        np.testing.assert_array_equal(result, expected)

    def test_perpendicular_to_xy_vector(self):
        v = np.array([3, 4, 0])
        result = perpendicular_vector(v)
        expected = np.array([-4, 3, 0])
        np.testing.assert_array_equal(result, expected)

    def test_perpendicular_to_original_problem_vector(self):
        v = np.array([0, 21.46288667, 0])
        result = perpendicular_vector(v)
        expected = np.array([-21.46288667, 0, 0])
        np.testing.assert_array_almost_equal(result, expected)

    def test_perpendicular_to_xyz_vector(self):
        v = np.array([1, 2, 3])
        result = perpendicular_vector(v)
        expected = np.array([-2, 1, 0])
        np.testing.assert_array_equal(result, expected)

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
        expected = np.array([0, 1e-5, 0])
        np.testing.assert_array_equal(result, expected)


if __name__ == "__main__":
    unittest.main()
