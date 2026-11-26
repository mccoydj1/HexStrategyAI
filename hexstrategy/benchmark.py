"""Persist actual coaching outcomes and environment data."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from cProfile import Profile
from pstats import Stats
from os import cpu_count
from pathlib import Path
from platform import platform, python_version
from time import perf_counter
import argparse

from .ai import BASE, choose, play, ranked, suggested_offer
from .coach import collect, submit, worker_count
from .game import Game
from .session import load_policy
from .train import save


def profile():
    weights = load_policy()
    profiler = Profile()
    start = perf_counter()
    with profiler:
        for seed in range(30):
            play(Game(seed), (weights, BASE, BASE, BASE), record_history=False)
    stats = Stats(profiler)
    entries = sorted(stats.stats.items(), key=lambda item: -item[1][3])[:20]
    save("profile.json", {"games": 30, "seed_range": [0, 29], "weights": weights,
                          "wall_seconds": perf_counter()-start,
                          "hotspots": [{"file": Path(location[0]).name, "line": location[1],
                                        "function": location[2], "calls": values[1],
                                        "self_seconds": values[2], "cumulative_seconds": values[3]}
                                       for location, values in entries]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", action="store_true")
    if parser.parse_args().profile:
        profile()
        return
    game = Game(907)
    weights = load_policy()
    cases = [("opening", game.observe(game.actor))]
    while game.turn < 36 or game.phase != "action":
        obs = game.observe(game.actor)
        action = choose(obs, BASE)
        if action[0] == "offer":
            game.trade_offer(*action[1:])
        else:
            game.apply(action)
    cases.append(("midgame", game.observe(game.actor)))
    results = []
    cpu = Path("/proc/cpuinfo")
    model = next((line.split(":", 1)[1].strip() for line in cpu.read_text().splitlines()
                  if line.startswith("model name")), None) if cpu.exists() else None
    quota = Path("/sys/fs/cgroup/cpu.max")
    environment = {"os": platform(), "python": python_version(), "reported_cpus": cpu_count(),
                   "cpu_model": model, "quota": quota.read_text().strip() if quota.exists() else None}
    environment["coaching_workers"] = worker_count()
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        for name, obs in cases:
            start = perf_counter()
            actions = [action for _, action in ranked(obs, weights)[:3]]
            if obs.actions[0] not in actions:
                actions.append(obs.actions[0])
            offer = suggested_offer(obs, weights)
            if offer:
                actions.append(offer)
            measurements = collect(obs, submit(pool, obs, actions, 4411, weights))
            results.append(dict(case=name, game_seed=907, sampling_seed=4411,
                                seat=obs.seat, turn=obs.turn, legal_actions=len(obs.actions),
                                seconds=perf_counter()-start, estimates=list(map(asdict, measurements))))
            save("coaching.json", dict(environment=environment, policy=weights, positions=results))
            print(name, results[-1]["seconds"], flush=True)


if __name__ == "__main__":
    main()
