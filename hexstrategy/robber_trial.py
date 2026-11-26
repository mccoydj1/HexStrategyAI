"""Evaluate a robber policy that accounts for public production and rival threats."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import blake2b
from pathlib import Path
from time import perf_counter
import argparse
import json

from .ai import BASE, building_metrics, choose, play, production
from .board import RESOURCES
from .coach import worker_count
from .game import Game
from .opening_search import seeds
from .placement_trial import placement_choice
from .session import load_policy
from .tactical import summary
from .train import ARTIFACTS, save


def threat_choice(obs):
    board, seat = obs.board, obs.seat
    owned, base_points, _ = building_metrics(board, obs.buildings)
    pips = production(board)
    income = [tuple(sum(pips[v][i]*obs.buildings[v][1] for v in locations) for i in range(5))
              for locations in owned]
    points = [n+2*((obs.longest == rival)+(obs.army == rival)) for rival, n in enumerate(base_points)]
    threat = [1 + .16*n + .11*obs.development_totals[rival] + .035*obs.card_totals[rival]
              + .28*max(0, n-6) for rival, n in enumerate(points)]
    denial = {}

    def rank(action):
        _, tile, victim = action
        if tile not in denial:
            hexagon = board.tiles[tile]
            rating = 0.0
            if hexagon.resource is not None:
                resource = RESOURCES.index(hexagon.resource)
                odds = 6-abs(7-hexagon.number)
                for vertex in board.corners[tile]:
                    building = obs.buildings[vertex]
                    if building:
                        owner, amount = building
                        contributed = odds*amount
                        dependence = contributed/max(3, income[owner][resource])
                        adjustment = 0.65+0.70*dependence
                        rating += contributed*adjustment*(-3.6 if owner == seat else threat[owner])
            denial[tile] = rating
        if victim is not None and obs.card_totals[victim]:
            return denial[tile]+3+0.85*threat[victim]
        return denial[tile]

    return max(obs.actions, key=rank)


def trial(job):
    weights, seed, challenger = job

    def decide(obs, policy):
        if obs.seat != 0:
            return choose(obs, policy)
        if challenger and obs.phase == "robber":
            return threat_choice(obs)
        return placement_choice(obs, policy)

    return play(Game(seed), (weights, BASE, BASE, BASE), decision=decide)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    start = perf_counter()
    weights = load_policy()
    seed, count = (198932380, 1000) if args.holdout else (44013051, 144)
    batch = seeds(seed, count)
    progress = ARTIFACTS / "robber-holdout-control.json"
    package = Path(__file__).resolve().parent
    sources = ("ai.py", "board.py", "game.py", "placement_trial.py", "tactical.py", "robber_trial.py")
    fingerprint = blake2b(b"".join((package / name).read_bytes() for name in sources),
                          digest_size=16).hexdigest()
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        checkpoint = json.loads(progress.read_text()) if args.holdout and progress.exists() else {}
        if (checkpoint.get("seed") == seed and tuple(checkpoint.get("weights", ())) == weights
                and checkpoint.get("source") == fingerprint
                and len(checkpoint.get("winners", ())) == count):
            incumbent = checkpoint["winners"]
        else:
            incumbent = list(pool.map(trial, ((weights, game_seed, False) for game_seed in batch),
                                      chunksize=2))
            if args.holdout:
                save(progress.name, dict(seed=seed, weights=weights, source=fingerprint, winners=incumbent))
        challenger = list(pool.map(trial, ((weights, game_seed, True) for game_seed in batch), chunksize=2))
    gained = sum(a != 0 and b == 0 for a, b in zip(incumbent, challenger))
    lost = sum(a == 0 and b != 0 for a, b in zip(incumbent, challenger))
    name = "robber-holdout.json" if args.holdout else "robber-pilot.json"
    save(name, dict(seed=seed, incumbent=asdict(summary(weights, incumbent)),
         challenger=asdict(summary(weights, challenger)), gains=gained, losses=lost,
         incumbent_winners=incumbent, challenger_winners=challenger, seconds=perf_counter()-start))
    print(summary(weights, incumbent), summary(weights, challenger), flush=True)


if __name__ == "__main__":
    main()
