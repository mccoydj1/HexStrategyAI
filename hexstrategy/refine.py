from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from random import Random
from time import perf_counter
from .train import measure, save

def main():
    start = perf_counter()
    incumbent = (1.274, 1.278, 1.183, 1.112, 1.665, 3.535, 4.609, 6.241, 3.848, 1.99)
    rng = Random(91420)
    training = [rng.getrandbits(64) for _ in range(176)]
    revised = incumbent + (0.6, 1.1, 2.0)
    prospects = [incumbent, revised]
    prospects += [tuple(round(w*rng.uniform(.63, 1.45), 3) for w in revised)
                  for _ in range(11)]
    results = []
    with ProcessPoolExecutor(max_workers=2) as pool:
        for candidate in prospects:
            result = measure(pool, candidate, training)
            results.append(result)
            save("refinement.json", {"training_seed": 91420, "results": [asdict(r) for r in results]})
            print(result, flush=True)
        holdout_seed = 9414394
        rng = Random(holdout_seed)
        test = [rng.getrandbits(64) for _ in range(1000)]
        champion = max(results, key=lambda r: r.wins)
        final = measure(pool, champion.weights, test)
        incumbent_result = final if tuple(champion.weights) == incumbent else measure(pool, incumbent, test)
        save("refinement-holdout.json", {"holdout_seed": holdout_seed, "incumbent": asdict(incumbent_result),
                 "challenger": asdict(final), "seconds": perf_counter()-start})
        print(final, incumbent_result, flush=True)

if __name__ == "__main__":
    main()
