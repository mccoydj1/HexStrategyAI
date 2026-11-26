"""Test offer targeting and preserve performance on a fresh holdout."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from time import perf_counter

from .opening_search import INCUMBENT, seeds
from .train import measure, save


def main():
    start = perf_counter()
    with ProcessPoolExecutor(max_workers=2) as pool:
        training = [measure(pool, weights, seeds(130832, 196))
                    for weights in (INCUMBENT, INCUMBENT+(.5,), INCUMBENT+(1.,), INCUMBENT+(2.,))]
        save("trade-search.json", dict(training_seed=130832, results=list(map(asdict, training))))
        best = max(training, key=lambda result: result.wins)
        seeds_for_validation = seeds(2323455, 1000)
        validated = measure(pool, best.weights, seeds_for_validation)
        incumbent = validated if best.weights == INCUMBENT else measure(pool, INCUMBENT, seeds_for_validation)
    save("trade-holdout.json", dict(seed=2323455, selected=asdict(validated),
         incumbent=asdict(incumbent), seconds=perf_counter()-start))
    if validated.wins > incumbent.wins:
        save("policy.json", dict(format=1, weights=validated.weights, holdout_seed=2323455,
                                holdout=asdict(validated), seconds=perf_counter()-start))
    print(validated, incumbent, flush=True)


if __name__ == "__main__":
    main()
