import unittest

from bluenaas.domains.morphology import ExclusionRule
from bluenaas.utils.util import (
    get_segments_satisfying_all_exclusion_rules,
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


if __name__ == "__main__":
    unittest.main()
