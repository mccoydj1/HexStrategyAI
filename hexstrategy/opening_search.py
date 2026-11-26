"""Validate opening lookahead against the strongest route-aware policy."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from random import Random
from time import perf_counter
import json

from .train import ARTIFACTS, measure, save

INCUMBENT = (1.258, 1.055, 1.394, 1.332, 1.707, 2.443, 2.934, 4.725, 3.733,
             2.038, 0.509, 1.105, 1.384)


def seeds(seed, count):
    rng = Random(seed)
    return [rng.getrandbits(64) for _ in range(count)]


def main():
    started = perf_counter()
    candidates = [INCUMBENT, INCUMBENT+(.7, .15), INCUMBENT+(1., .25), INCUMBENT+(.25, .2)]
    with ProcessPoolExecutor(max_workers=2) as pool:
        training = [measure(pool, w, seeds(8512, 128)) for w in candidates]
        save("opening-search.json", dict(training_seed=8512, results=list(map(asdict, training))))
        champion = max(training, key=lambda r: r.wins).weights
        test = seeds(1290433, 1000)
        winner = measure(pool, champion, test)
        save("opening-holdout.json", dict(seed=1290433, candidate=asdict(winner)))
        comparison = winner if champion == INCUMBENT else measure(pool, INCUMBENT, test)
    save("opening-holdout.json", dict(seed=1290433, candidate=asdict(winner),
         incumbent=asdict(comparison), seconds=perf_counter()-started))
    if winner.wins > comparison.wins:
        selected = winner
    else:
        selected = comparison
    previous = json.loads((ARTIFACTS / "policy.json").read_text())
    if selected.wins >= previous["holdout"]["wins"]:
        save("policy.json", dict(format=1, weights=selected.weights, holdout_seed=1290433,
                                holdout=asdict(selected), seconds=perf_counter()-started))
    print(winner, comparison, flush=True)


if __name__ == "__main__":
    main()
