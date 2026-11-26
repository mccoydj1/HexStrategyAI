"""Learn context-dependent action preferences from paired game continuations."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from random import Random
from time import perf_counter

from .ai import BASE, building_metrics, choose, play, ranked, simulate_batch, suggested_offer
from .coach import worker_count
from .game import Game
from .opening_search import seeds
from .session import load_policy
from .tactical import summary, tactical_choice
from .train import save

KINDS = ("end", "road", "settlement", "city", "buy", "bank", "knight", "roads",
         "monopoly", "plenty", "offer")
TRAINING_SEED = 84193007
SAMPLES = 16


def alternatives(obs, weights):
    if obs.phase != "action" or len(obs.actions) < 2 or obs.seat != 0:
        return None
    _, scores, _ = building_metrics(obs.board, obs.buildings)
    scores = tuple(n+2*((obs.longest == p)+(obs.army == p)) for p, n in enumerate(scores))
    own_score = scores[obs.seat] + sum(card == "point" for card, _ in obs.cards)
    if own_score >= 8:
        return None
    (rating, best), (other_rating, other), *_ = ranked(obs, weights)
    if rating - other_rating > 9 or best[0] == other[0]:
        return None
    if best == ("end",):
        best = suggested_offer(obs, weights) or best
    if best[0] not in KINDS or other[0] not in KINDS:
        return None

    def features(action, value):
        kind = action[0]
        context = (1.0, (own_score-4)/4, (sum(obs.hand)-5)/5,
                   (max(scores)-5)/5)
        return (max(-2., min(4., value/10)),) + tuple(
            feature if label == kind else 0. for label in KINDS for feature in context)

    forward, reverse = features(best, rating), features(other, other_rating)
    return best, other, tuple(b-a for a, b in zip(forward, reverse))


def collect(job):
    weights, seed = job
    game, rng = Game(seed), Random(seed ^ 0xA917)
    chosen = None
    seen = 0
    while game.winner is None and game.turn < 400:
        obs = game.observe(game.actor)
        pair = alternatives(obs, weights)
        if pair:
            seen += 1
            if rng.randrange(seen) == 0:
                chosen = obs, pair
        action = choose(obs, weights if obs.seat == 0 else BASE)
        if action[0] == "offer":
            game.trade_offer(*action[1:])
        else:
            game.apply(action)
    if chosen is None:
        return None
    observation, (best, alternative, features) = chosen
    chance_seed = rng.getrandbits(64)
    before = simulate_batch(observation, best, 0, SAMPLES, chance_seed, weights, BASE)
    after = simulate_batch(observation, alternative, 0, SAMPLES, chance_seed, weights, BASE)
    return dict(game_seed=seed, simulation_seed=chance_seed, turn=observation.turn,
                primary=best, alternative=alternative, features=features,
                primary_outcomes=before, alternative_outcomes=after, delta=(after[1]-before[1])/SAMPLES)


def fit(rows):
    coefficients = [0.] * len(rows[0]["features"])
    for _ in range(180):
        gradient = [0.] * len(coefficients)
        for row in rows:
            features = row["features"]
            residual = sum(a*b for a, b in zip(coefficients, features)) - row["delta"]
            for i, feature in enumerate(features):
                gradient[i] += residual*feature
        for i, derivative in enumerate(gradient):
            coefficients[i] -= .30*(derivative/len(rows) + .045*coefficients[i])
    return tuple(coefficients)


def trial(job):
    seed, weights, coefficients = job

    def decision(obs, policy):
        if obs.seat != 0:
            return choose(obs, policy)
        if coefficients:
            pair = alternatives(obs, policy)
            if pair:
                primary, alternative, features = pair
                effect = sum(a*b for a, b in zip(coefficients, features))
                return alternative if effect > .025 else primary
        return tactical_choice(obs, policy)

    return play(Game(seed), (weights, BASE, BASE, BASE), decision=decision)


def match(pool, weights, coefficients, batch):
    winners = list(pool.map(trial, ((seed, weights, coefficients) for seed in batch), chunksize=4))
    return winners


def main():
    start = perf_counter()
    weights = load_policy()
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        jobs = ((weights, seed) for seed in seeds(TRAINING_SEED, 148))
        rows = [row for row in pool.map(collect, jobs, chunksize=2) if row is not None]
        coefficients = fit(rows)
        save("causal-training.json", dict(seed=TRAINING_SEED, evaluated_positions=rows,
             samples_per_action=SAMPLES, features=KINDS, coefficients=coefficients))
        pilot_seed = 131073009
        pilot = seeds(pilot_seed, 192)
        control = match(pool, weights, None, pilot)
        learned = match(pool, weights, coefficients, pilot)
    save("causal-pilot.json", dict(seed=pilot_seed, control=asdict(summary(weights, control)),
         learned=asdict(summary(weights, learned)), seconds=perf_counter()-start))
    print(summary(weights, control), summary(weights, learned), flush=True)


if __name__ == "__main__":
    main()
