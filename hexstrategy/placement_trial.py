"""Test paired information-set rollouts for the second opening settlement."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import blake2b
from random import Random
from time import perf_counter
import argparse
import json

from .ai import BASE, determinize, play, public_minimum, ranked
from .coach import worker_count
from .game import Game
from .opening_search import seeds
from .session import load_policy
from .tactical import outcomes, summary, test_player
from .train import ARTIFACTS, save


def placement_choice(observation, weights):
    if not (observation.seat == 0 and observation.phase == "opening" and observation.setup >= 4):
        return test_player(observation, weights)
    actions = [action for _, action in ranked(observation, weights)[:3]]
    features = (observation.board.tiles, observation.board.ports, observation.buildings,
                observation.roads, observation.setup, observation.seating)
    seed = int.from_bytes(blake2b(repr(features).encode(), digest_size=8).digest(), "big")
    rng = Random(seed)
    worlds = [rng.getrandbits(64) for _ in range(4)]
    minimum = public_minimum(observation)
    policies = (weights, BASE, BASE, BASE)
    wins = []
    for action in actions:
        count = 0
        for world in worlds:
            game = determinize(observation, world, minimum)
            game.step(action)
            count += play(game, policies, record_history=False) == observation.seat
        wins.append(count)
    best = max(range(len(actions)), key=wins.__getitem__)
    return actions[best] if wins[best] >= wins[0]+2 else actions[0]


def trial(job):
    weights, seed = job
    return play(Game(seed), (weights, BASE, BASE, BASE), decision=placement_choice)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    start = perf_counter()
    weights = load_policy()
    seed, count = (774308121, 1000) if args.holdout else (65171322, 128)
    batch = seeds(seed, count)
    progress = ARTIFACTS / "placement-holdout-control.json"
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        checkpoint = json.loads(progress.read_text()) if args.holdout and progress.exists() else {}
        if (checkpoint.get("seed") == seed and tuple(checkpoint.get("weights", ())) == weights
                and len(checkpoint.get("winners", ())) == count):
            incumbent = checkpoint["winners"]
        else:
            incumbent = outcomes(pool, weights, batch, True)
            if args.holdout:
                save(progress.name, dict(seed=seed, weights=weights, winners=incumbent))
        challenger = list(pool.map(trial, ((weights, game_seed) for game_seed in batch), chunksize=2))
    name = "placement-holdout.json" if args.holdout else "placement-pilot.json"
    gained = sum(a != 0 and b == 0 for a, b in zip(incumbent, challenger))
    lost = sum(a == 0 and b != 0 for a, b in zip(incumbent, challenger))
    save(name, dict(seed=seed, incumbent=asdict(summary(weights, incumbent)),
         challenger=asdict(summary(weights, challenger)), gains=gained, losses=lost,
         incumbent_winners=incumbent, challenger_winners=challenger,
         seconds=perf_counter()-start))
    print(summary(weights, incumbent), summary(weights, challenger), flush=True)


if __name__ == "__main__":
    main()
