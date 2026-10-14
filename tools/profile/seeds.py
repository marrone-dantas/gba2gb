"""Deterministic seed generator shared by the lockstep test and the range tracer."""
import random
import zlib

FIXED = [(0, 0, 0, 0), (0xFFFFFFFF,) * 4, (0x80000000, 0x7FFFFFFF, 1, 0xFFFFFFFF), (1, 2, 3, 4)]


def seeds(name: str, n: int = 1000):
    """Return n (r0, r1, r2, r3) tuples: 4 fixed edge cases, then random ones
    derived deterministically from the kernel name."""
    rnd = random.Random(zlib.crc32(name.encode()))
    out = FIXED[:n]
    while len(out) < n:
        out.append(tuple(rnd.getrandbits(32) for _ in range(4)))
    return out
