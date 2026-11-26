"""Versioned, deterministic replay saves."""
import json
from math import isfinite
from tempfile import NamedTemporaryFile
from pathlib import Path

from .ai import BASE, interval
from .game import Game

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


def load_policy():
    path = ARTIFACTS / "policy.json"
    if not path.exists():
        return BASE
    payload = json.loads(path.read_text())
    weights = tuple(payload["weights"])
    if (payload["format"] != 1 or len(weights) not in (len(BASE), 10, 13, 14, 15)
            or any(type(w) not in (float, int) or not isfinite(w) for w in weights)):
        raise ValueError("Unsupported policy artifact")
    evidence = payload["holdout"]
    if tuple(evidence["weights"]) != weights or evidence["games"] < 1000:
        raise ValueError("Unsupported policy artifact")
    return weights


def _validated_search(weights, before, after, gained, lost):
    return (tuple(after["weights"]) == tuple(before["weights"]) == weights
            and after["games"] == before["games"] == 1000
            and gained + lost > 0 and interval(gained, gained+lost)[0] > .5)


def load_search(weights):
    path = ARTIFACTS / "tactical-holdout.json"
    if not path.exists():
        return False
    evidence = json.loads(path.read_text())
    return _validated_search(weights, evidence["baseline"], evidence["searched"],
                             evidence["improved"], evidence["worsened"])


def load_placement_search(weights):
    path = ARTIFACTS / "placement-holdout.json"
    if not path.exists():
        return False
    evidence = json.loads(path.read_text())
    return _validated_search(weights, evidence["incumbent"], evidence["challenger"],
                             evidence["gains"], evidence["losses"])


class Session:
    def __init__(self, seed, difficulty="Hard"):
        self.seed = seed
        self.difficulty = difficulty
        self.game = Game(seed)
        self.moves = []

    def step(self, action):
        if action[0] == "offer":
            self.game.trade_offer(*action[1:])
        else:
            self.game.step(action)
        self.moves.append(action)

    def save(self, path):
        path = Path(path)
        file = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
        temporary = Path(file.name)
        try:
            with file:
                json.dump(dict(version=2, seed=self.seed, moves=self.moves,
                               difficulty=self.difficulty), file)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text())
        if payload["version"] != 2:
            raise ValueError("Unsupported save version")
        session = cls(payload["seed"], payload["difficulty"])

        def tuplify(value):
            return tuple(map(tuplify, value)) if isinstance(value, list) else value

        for step in payload["moves"]:
            session.step(tuplify(step))
        return session
