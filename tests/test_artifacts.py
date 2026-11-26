import json
import unittest

from hexstrategy.ai import interval
from hexstrategy.session import ARTIFACTS, load_placement_search, load_policy, load_search


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

    def test_placement_search_loads_and_matches_paired_outcomes(self):
        self.assertTrue(load_placement_search(load_policy()))
        evidence = json.loads((ARTIFACTS / "placement-holdout.json").read_text())
        incumbent, challenger = evidence["incumbent_winners"], evidence["challenger_winners"]
        self.assertEqual(len(incumbent), 1000)
        self.assertEqual(len(challenger), 1000)
        self.assertEqual(incumbent.count(0), evidence["incumbent"]["wins"])
        self.assertEqual(challenger.count(0), evidence["challenger"]["wins"])
        self.assertEqual(evidence["gains"], sum(a != 0 and b == 0 for a, b in zip(incumbent, challenger)))
        self.assertEqual(evidence["losses"], sum(a == 0 and b != 0 for a, b in zip(incumbent, challenger)))

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

    def test_optimized_rollouts_reproduce_the_original_seeded_estimates(self):
        baseline = json.loads((ARTIFACTS / "coaching.json").read_text())
        for artifact in ("coaching-optimized.json", "coaching-setup-cache.json",
                         "coaching-production-cache.json", "coaching-board-cache.json",
                         "coaching-route-cache.json", "coaching-cython.json"):
            with self.subTest(artifact=artifact):
                optimized = json.loads((ARTIFACTS / artifact).read_text())
                self.assertEqual(baseline["policy"], optimized["policy"])
                for original, revised in zip(baseline["positions"], optimized["positions"], strict=True):
                    self.assertEqual({k: v for k, v in original.items() if k != "seconds"},
                                     {k: v for k, v in revised.items() if k != "seconds"})
