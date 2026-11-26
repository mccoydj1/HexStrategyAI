"""Process-pool scheduling for independent simulation batches."""
import os
from pathlib import Path

from .ai import estimate, simulate_batch

OUTCOMES = 1000
BATCH = 50


def worker_count():
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    quota = Path("/sys/fs/cgroup/cpu.max")
    if quota.exists():
        count, period = quota.read_text().split()
        if count != "max":
            cpus = min(cpus or 1, max(1, (int(count) + int(period)-1)//int(period)))
    limit = 60 if os.name == "nt" else 128
    return max(1, min(cpus or 1, limit))


def submit(executor, observation, actions, seed, weights, opponent_weights=None):
    workers = worker_count()
    games_per_worker = (OUTCOMES*len(actions) + workers-1)//workers
    block = min(BATCH, max(1, games_per_worker))
    return {
        action: [executor.submit(simulate_batch, observation, action, start,
                                 min(block, OUTCOMES-start), seed, weights, opponent_weights)
                 for start in range(0, OUTCOMES, block)]
        for action in actions
    }


def collect(observation, jobs):
    estimates = [estimate(observation, action, (future.result() for future in futures))
                 for action, futures in jobs.items()]
    return sorted(estimates, key=lambda result: -result.probability)
