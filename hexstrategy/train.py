"""Reproducible policy search and a disjoint randomized holdout."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from json import dumps
from pathlib import Path
from random import Random
from time import perf_counter
import argparse

from .ai import BASE, interval, play
from .game import Game

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


@dataclass
class Result:
    weights: tuple
    games: int
    wins: int
    unresolved: int
    interval95: tuple


def trial(job):
    weights, seed = job
    winner = play(Game(seed), (weights, BASE, BASE, BASE), record_history=False)
    return winner


def measure(pool, weights, seeds):
    outcomes = list(pool.map(trial, ((weights, seed) for seed in seeds), chunksize=8))
    wins = outcomes.count(0)
    return Result(weights, len(outcomes), wins, outcomes.count(None), interval(wins, len(outcomes)))


def save(name, payload):
    target = ARTIFACTS / name
    temporary = target.with_suffix(".tmp")
    temporary.write_text(dumps(payload, indent=2) + "\n")
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--training-games", type=int, default=128)
    parser.add_argument("--candidates", type=int, default=16)
    args = parser.parse_args()
    started = perf_counter()
    random = Random(12021)
    training = tuple(random.getrandbits(64) for _ in range(args.training_games))
    prospects = [BASE]
    strategic = (1.1, 1.05, .7, 1.45, 1.38, 3., 3., 4., 6., 3.)
    prospects.append(strategic)
    prospects += [tuple(round(w*random.uniform(.45, 1.7), 3) for w in strategic)
                  for _ in range(args.candidates-2)]
    holdout = Random(81388)
    test = tuple(holdout.getrandbits(64) for _ in range(1000))
    results = []
    ARTIFACTS.mkdir(exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for weights in prospects:
            result = measure(pool, weights, training)
            results.append(result)
            save("training.json", {"training_seed": 12021,
                                   "results": [asdict(item) for item in results]})
            print(result, flush=True)
        best = max(results, key=lambda item: item.wins)
        measured = measure(pool, best.weights, test)
    save("policy.json", {"format": 1, "weights": best.weights, "holdout_seed": 81388,
                         "holdout": asdict(measured), "seconds": perf_counter()-started})
    print(measured, flush=True)


if __name__ == "__main__":
    main()
