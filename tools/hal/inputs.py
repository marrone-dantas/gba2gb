"""Deterministic 300-frame input sequence (GB-representable keys only: no L/R)."""
import random

KEYS = ["a", "b", "select", "start", "right", "left", "up", "down"]


def sequence(n=300, seed=2):
    rnd = random.Random(seed)
    out, cur, hold = [], set(), 0
    for _ in range(n):
        if hold == 0:
            cur = set(rnd.sample(["right", "left", "up", "down"], rnd.choice([0, 1, 1, 2])))
            if rnd.random() < 0.3:
                cur.add(rnd.choice(["a", "b", "select", "start"]))
            if {"right", "left"} <= cur:
                cur.discard("left")
            if {"up", "down"} <= cur:
                cur.discard("up")
            hold = rnd.randint(3, 25)
        hold -= 1
        out.append(set(cur))
    return out
