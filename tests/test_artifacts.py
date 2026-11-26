import json
import unittest

from hexstrategy.ai import interval
from hexstrategy.session import ARTIFACTS, load_policy, load_search


class ReleasedEvidence(unittest.TestCase):
    def test_hard_policy_loads_and_matches_paired_outcomes(self):
        weights = load_policy()
        self.assertTrue(load_search(weights))
        evidence = json.loads((ARTIFACTS / "tactical-holdout.json").read_text())
        for result, outcomes in (("baseline", "baseline_winners"), ("searched", "search_winners")):
            self.assertEqual(len(evidence[outcomes]), 1000)
            self.assertEqual(evidence[outcomes].count(0), evidence[result]["wins"])
            self.assertEqual(evidence[outcomes].count(None), evidence[result]["unresolved"])
        pairs = list(zip(evidence["baseline_winners"], evidence["search_winners"]))
        self.assertEqual(evidence["improved"], sum(a != 0 and b == 0 for a, b in pairs))
        self.assertEqual(evidence["worsened"], sum(a == 0 and b != 0 for a, b in pairs))

    def test_persisted_coaching_has_full_batches_and_ranked_estimates(self):
        evidence = json.loads((ARTIFACTS / "coaching.json").read_text())
        self.assertEqual(tuple(evidence["policy"]), load_policy())
        for position in evidence["positions"]:
            results = position["estimates"]
            self.assertGreaterEqual(len(results), 2)
            self.assertEqual(results, sorted(results, key=lambda result: -result["probability"]))
            for result in results:
                self.assertGreaterEqual(result["games"], 1000)
                self.assertEqual(result["probability"], result["wins"]/result["games"])
                self.assertEqual(tuple(result["interval"]), interval(result["wins"], result["games"]))
