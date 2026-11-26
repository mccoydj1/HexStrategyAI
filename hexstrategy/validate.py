"""Select a policy for the shuffled harbor frames and run a locked holdout."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from time import perf_counter

from .ai import interval
from .coach import worker_count
from .opening_search import INCUMBENT, seeds
from .train import Result, measure, save, trial


def main():
    started = perf_counter()
    selection_seed, holdout_seed = 822183205, 52771208
    candidates = (INCUMBENT, INCUMBENT+(.5,), INCUMBENT+(.7, .15))
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        selection = [measure(pool, policy, seeds(selection_seed, 176)) for policy in candidates]
        save("board-selection.json", {"seed": selection_seed, "results": list(map(asdict, selection))})
        selected = max(selection, key=lambda result: result.wins)
        jobs = ((selected.weights, seed) for seed in seeds(holdout_seed, 1000))
        outcomes = list(pool.map(trial, jobs, chunksize=8))
    wins = outcomes.count(0)
    result = Result(selected.weights, len(outcomes), wins, outcomes.count(None),
                    interval(wins, len(outcomes)))
    elapsed = perf_counter()-started
    save("board-holdout.json", dict(seed=holdout_seed, seconds=elapsed,
         result=asdict(result), winners=outcomes))
    save("policy.json", dict(format=1, weights=result.weights, holdout_seed=holdout_seed,
         holdout=asdict(result), seconds=elapsed))
    print(result, flush=True)


if __name__ == "__main__":
    main()
