"""Persist actual coaching outcomes and environment data."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from json import dumps
from cProfile import Profile
from pstats import Stats
from os import cpu_count
from pathlib import Path
from platform import platform, python_implementation, python_version
from time import perf_counter, process_time
import argparse

from .ai import BASE, choose, play, ranked, simulate_batch, suggested_offer
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


def benchmark_positions():
    game = Game(907)
    cases = [("opening", game.observe(game.actor))]
    while game.winner is None:
        obs = game.observe(game.actor)
        if game.turn >= 36 and game.phase == "action" and len(obs.actions) >= 3:
            cases.append(("midgame", obs))
            break
        action = choose(obs, BASE)
        if action[0] == "offer":
            game.trade_offer(*action[1:])
        else:
            game.apply(action)
    if len(cases) != 2:
        raise RuntimeError("Benchmark seed did not produce a suitable midgame position.")
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--cpu-probe", action="store_true")
    parser.add_argument("--output", default="coaching.json")
    arguments = parser.parse_args()
    if Path(arguments.output).name != arguments.output:
        parser.error("--output must be a filename within artifacts")
    if arguments.profile:
        profile()
        return
    weights = load_policy()
    cases = benchmark_positions()
    if arguments.cpu_probe:
        results = []
        for name, obs in cases:
            action = ranked(obs, weights)[0][1]
            started = process_time()
            outcomes = simulate_batch(obs, action, 0, 120, 4411, weights)
            results.append(dict(case=name, turn=obs.turn, cpu_seconds=process_time()-started,
                                outcomes=outcomes))
        print(dumps(results), flush=True)
        return
    results = []
    cpu = Path("/proc/cpuinfo")
    model = next((line.split(":", 1)[1].strip() for line in cpu.read_text().splitlines()
                  if line.startswith("model name")), None) if cpu.exists() else None
    quota = Path("/sys/fs/cgroup/cpu.max")
    environment = {"os": platform(), "python": python_version(),
                   "interpreter": python_implementation(), "reported_cpus": cpu_count(),
                   "cpu_model": model, "quota": quota.read_text().strip() if quota.exists() else None}
    environment["coaching_workers"] = worker_count()
    with ProcessPoolExecutor(max_workers=worker_count()) as pool:
        for name, obs in cases:
            start = perf_counter()
            actions = [action for _, action in ranked(obs, weights)[:3]]
            offer = suggested_offer(obs, weights)
            if offer:
                actions.append(offer)
            measurements = collect(obs, submit(pool, obs, actions, 4411, weights))
            results.append(dict(case=name, game_seed=907, sampling_seed=4411,
                                seat=obs.seat, turn=obs.turn, legal_actions=len(obs.actions),
                                seconds=perf_counter()-start, estimates=list(map(asdict, measurements))))
            save(arguments.output, dict(environment=environment, policy=weights, positions=results))
            print(name, results[-1]["seconds"], flush=True)


if __name__ == "__main__":
    main()
