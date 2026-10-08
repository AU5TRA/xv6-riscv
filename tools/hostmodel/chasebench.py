"""Host model of user/chasebench.c: the same structure, the same PRNG draws
in the same order, so the same reference string and RESULT lines.

    python3 tools/hostmodel/chasebench.py <footprint> <margin> <ops> <seed> <mode> [flags]
"""
from __future__ import annotations

if __package__ in (None, ""):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .common import PGSIZE, Perm, Rng

LISTS = 64
WRITE_PCT = 10
MAX_PAGES = 4096
NONE = -1

# name -> (tree, node_bytes)
MODES = {
    "list": (False, 64),
    "tree": (True, 64),
    "list256": (False, 256),
    "tree256": (True, 256),
}


def run(args, ref):
    if len(args) not in (5, 6):
        raise SystemExit("chasebench model: want 5 or 6 arguments")
    P, margin, ops, seed = (int(a) for a in args[:4])
    mode = args[4]
    if mode not in MODES:
        raise SystemExit("chasebench model: unknown mode %r" % mode)
    tree, node_bytes = MODES[mode]
    if not 1 <= P <= MAX_PAGES or ops < 1:
        raise SystemExit("chasebench model: arguments out of range")
    per_page = PGSIZE // node_bytes
    n = P * per_page
    list_len = n // LISTS

    rng = Rng(seed)
    place = Perm(n, rng.next())
    slot_of = [place.fwd(i) for i in range(n)]
    link = [None] * n          # by slot; None = never written
    payload = [0] * n
    if tree:
        link[slot_of[0]] = NONE
        for i in range(1, n):
            link[slot_of[i]] = slot_of[rng.below(i)]
    else:
        for i in range(LISTS * list_len):
            link[slot_of[i]] = NONE if (i + 1) % list_len == 0 else slot_of[i + 1]

    steps = writes = longest = checksum = 0
    below = rng.below
    for _ in range(ops):
        if tree:
            slot = slot_of[below(n)]
            budget = -1
        else:
            k = below(LISTS)
            budget = 1 + below(list_len)
            slot = slot_of[k * list_len]
        taken = 0
        while True:
            is_write = below(100) < WRITE_PCT
            nxt = link[slot]
            v = payload[slot]
            checksum += v
            if is_write:
                payload[slot] = v + 1
                writes += 1
            ref(slot // per_page, is_write)
            steps += 1
            taken += 1
            if taken == budget or nxt == NONE:
                break
            slot = nxt
        longest = max(longest, taken)

    return {
        "footprint_pages": P,
        "resident_margin": margin,
        "ops": ops,
        "seed": seed,
        "tree": int(tree),
        "node_bytes": node_bytes,
        "nodes": n,
        "lists": 0 if tree else LISTS,
        "list_len": 0 if tree else list_len,
        "write_pct": WRITE_PCT,
        "steps": steps,
        "longest_op": longest,
        "writes": writes,
        "checksum": checksum,
        "trace_refs": steps,
    }


if __name__ == "__main__":
    from .check_run import model_main
    model_main("chasebench")
