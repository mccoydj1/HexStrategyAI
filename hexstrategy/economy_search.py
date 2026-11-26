"""Screen economic priorities, then compare the finalist on fresh paired boards."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from time import perf_counter

from .coach import worker_count
from .opening_search import seeds
from .session import load_policy
from .tactical import outcomes, summary
from .train import measure, save


def candidates(weights):
    yield "incumbent", weights
    variants = (
        ("city income", {3: 1.35, 4: 1.4, 6: 1.7, 11: 1.5}),
        ("balanced openings", {0: 1.15, 1: 1.15, 10: 1.5, 13: 1.35}),
        ("earlier expansion", {0: 1.35, 1: 1.25, 5: 1.55, 8: .62, 14: 1.7}),
        ("development and army", {2: 1.4, 3: 1.2, 4: 1.2, 7: 1.7}),
        ("route contest", {0: 1.2, 1: 1.25, 8: .72, 9: 1.4, 12: 1.65}),
        ("conserve resources", {8: 1.3, 9: .8, 7: .75, 6: 1.4}),
    )
    for name, factors in variants:
        yield name, tuple(round(w*factors.get(i, 1), 6) for i, w in enumerate(weights))


def main():
    start = perf_counter()
    incumbent = load_policy()
    training_seed, holdout_seed = 729441503, 547016238
    training = seeds(training_seed, 224)
    results = []
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        for name, weights in candidates(incumbent):
            result = measure(pool, weights, training)
            results.append((name, result))
            save("economy-selection.json", dict(seed=training_seed,
                 results=[dict(name=label, **asdict(value)) for label, value in results]))
        name, finalist = max(results, key=lambda pair: pair[1].wins)
        holdout = seeds(holdout_seed, 1000)
        control = outcomes(pool, incumbent, holdout, True)
        challenger = control if name == "incumbent" else outcomes(pool, finalist.weights, holdout, True)
    gained = sum(a != 0 and b == 0 for a, b in zip(control, challenger))
    lost = sum(a == 0 and b != 0 for a, b in zip(control, challenger))
    save("economy-holdout.json", dict(seed=holdout_seed, finalist=name,
         incumbent=asdict(summary(incumbent, control)),
         challenger=asdict(summary(finalist.weights, challenger)),
         gains=gained, losses=lost, incumbent_winners=control,
         challenger_winners=challenger, seconds=perf_counter()-start))
    print(name, summary(incumbent, control), summary(finalist.weights, challenger), flush=True)


if __name__ == "__main__":
    main()
