"""Experiment with information-set search in close endgames."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import blake2b
from random import Random
from time import perf_counter
import argparse

from .ai import BASE, choose, determinize, interval, play, public_minimum, ranked, suggested_offer
from .coach import worker_count
from .game import Game
from .opening_search import seeds
from .session import load_policy
from .train import Result, save


def tactical_choice(obs, weights):
    if obs.phase != "action" or len(obs.actions) < 2:
        return choose(obs, weights)
    own = sum(piece[1] for piece in obs.buildings if piece and piece[0] == obs.seat)
    own += 2*((obs.longest == obs.seat)+(obs.army == obs.seat))
    own += sum(card == "point" for card, _ in obs.cards)
    if own < 8:
        return choose(obs, weights)
    (first_rating, first), (next_rating, alternative), *_ = ranked(obs, weights)
    if first[0] in ("settlement", "city") or first_rating-next_rating > 7:
        return first if first != ("end",) else (suggested_offer(obs, weights) or first)
    if first == ("end",):
        first = suggested_offer(obs, weights) or first
    features = (obs.turn, obs.seat, obs.hand, obs.buildings, obs.roads, obs.bank, obs.cards, obs.robber)
    fingerprint = blake2b(repr(features).encode(), digest_size=8).digest()
    rng = Random(int.from_bytes(fingerprint, "big"))
    worlds = [rng.getrandbits(64) for _ in range(4)]
    policies = tuple(weights if i == obs.seat else BASE for i in range(4))
    minimum = public_minimum(obs)

    def wins(action):
        count = 0
        for seed in worlds:
            simulated = determinize(obs, seed, minimum)
            if action[0] == "offer":
                simulated.trade_offer(*action[1:])
            else:
                simulated.step(action)
            winner = play(simulated, policies, obs.turn+36, record_history=False)
            count += winner == obs.seat
        return count

    first_wins, alternative_wins = wins(first), wins(alternative)
    return alternative if alternative_wins >= first_wins+2 else first


def test_player(obs, weights):
    return tactical_choice(obs, weights) if obs.seat == 0 else choose(obs, weights)


def trial(job):
    weights, seed, search = job
    decision = test_player if search else choose
    return play(Game(seed), (weights, BASE, BASE, BASE),
                record_history=search, decision=decision)


def outcomes(pool, weights, batch, search):
    return list(pool.map(trial, ((weights, seed, search) for seed in batch), chunksize=4))


def summary(weights, winners):
    wins = winners.count(0)
    return Result(weights, len(winners), wins, winners.count(None), interval(wins, len(winners)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args()
    start = perf_counter()
    weights = load_policy()
    seed, count = (866482032, 1000) if args.holdout else (25511293, 192)
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        batch = seeds(seed, count)
        baseline = outcomes(pool, weights, batch, False)
        searched = outcomes(pool, weights, batch, True)
    improved = sum(b != 0 and s == 0 for b, s in zip(baseline, searched))
    worsened = sum(b == 0 and s != 0 for b, s in zip(baseline, searched))
    name = "tactical-holdout.json" if args.holdout else "tactical-pilot.json"
    save(name, dict(seed=seed, baseline=asdict(summary(weights, baseline)),
         searched=asdict(summary(weights, searched)), improved=improved, worsened=worsened,
         baseline_winners=baseline, search_winners=searched, seconds=perf_counter()-start))
    print(summary(weights, baseline), summary(weights, searched), flush=True)


if __name__ == "__main__":
    main()
