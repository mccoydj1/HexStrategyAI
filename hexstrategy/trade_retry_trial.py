"""Compare a second, targeted trade attempt against the released Hard policy."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import blake2b
from pathlib import Path
from time import perf_counter
import argparse
import json

from .ai import BASE, choose, play, targeted_offer
from .coach import worker_count
from .game import Game
from .opening_search import seeds
from .placement_trial import placement_choice
from .session import load_policy
from .tactical import summary
from .train import ARTIFACTS, save


def second_offer(observation):
    if (observation.phase != "action" or not observation.traded
            or not observation.history or observation.history[-1][1] != "decline"):
        return None
    recipients = []
    for seat, kind, args in reversed(observation.history):
        if kind == "end":
            break
        if kind == "offer" and seat == observation.seat:
            recipients.append(args[0])
    if len(recipients) != 1:
        return None
    return targeted_offer(observation, .8, exclude=recipients)


def trial(job):
    weights, seed, challenger = job
    retries = 0

    def decide(observation, policy):
        nonlocal retries
        if observation.seat != 0:
            return choose(observation, policy)
        move = placement_choice(observation, policy)
        if challenger and move == ("end",):
            offer = second_offer(observation)
            if offer:
                retries += 1
                return offer
        return move

    winner = play(Game(seed), (weights, BASE, BASE, BASE), decision=decide)
    return winner, retries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    start = perf_counter()
    weights = load_policy()
    seed, count = (500711409, 1000) if args.holdout else (198420181, 144)
    batch = seeds(seed, count)
    progress = ARTIFACTS / "trade-retry-control.json"
    package = Path(__file__).resolve().parent
    sources = ("ai.py", "board.py", "game.py", "opening_search.py", "placement_trial.py",
               "tactical.py", "trade_retry_trial.py")
    fingerprint = blake2b(b"".join((package / name).read_bytes() for name in sources),
                          digest_size=16).hexdigest()
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        checkpoint = json.loads(progress.read_text()) if args.holdout and progress.exists() else {}
        if (checkpoint.get("seed") == seed and tuple(checkpoint.get("weights", ())) == weights
                and checkpoint.get("source") == fingerprint
                and len(checkpoint.get("winners", ())) == count):
            incumbent = checkpoint["winners"]
        else:
            incumbent = [winner for winner, _ in pool.map(
                trial, ((weights, game_seed, False) for game_seed in batch), chunksize=2)]
            if args.holdout:
                save(progress.name, dict(seed=seed, weights=weights, source=fingerprint, winners=incumbent))
        results = list(pool.map(trial, ((weights, game_seed, True) for game_seed in batch), chunksize=2))
    challenger = [winner for winner, _ in results]
    gains = sum(a != 0 and b == 0 for a, b in zip(incumbent, challenger))
    losses = sum(a == 0 and b != 0 for a, b in zip(incumbent, challenger))
    name = "trade-retry-holdout.json" if args.holdout else "trade-retry-pilot.json"
    save(name, dict(seed=seed, incumbent=asdict(summary(weights, incumbent)),
         challenger=asdict(summary(weights, challenger)), gains=gains, losses=losses,
         incumbent_winners=incumbent, challenger_winners=challenger,
         retries=sum(retries for _, retries in results), seconds=perf_counter()-start))
    print(summary(weights, incumbent), summary(weights, challenger), flush=True)


if __name__ == "__main__":
    main()
