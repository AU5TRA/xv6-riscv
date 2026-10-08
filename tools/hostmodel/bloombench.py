"""Host model of user/bloombench.c: the same salts, keys and bit positions,
so the same reference string and RESULT lines.

    python3 tools/hostmodel/bloombench.py <footprint> <margin> <n_keys> <seed> <mode> [flags]
"""
from __future__ import annotations

if __package__ in (None, ""):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .common import MASK64, PGSIZE, Rng, mix64

QUERY_RATIO = 4
ABSENT_SPACE = 1 << 40
MAX_PAGES = 4096
BITS_PER_PAGE = PGSIZE * 8
MODES = {"k3": 3, "k7": 7}


def run(args, ref):
    if len(args) not in (5, 6):
        raise SystemExit("bloombench model: want 5 or 6 arguments")
    P, margin, n, seed = (int(a) for a in args[:4])
    if args[4] not in MODES:
        raise SystemExit("bloombench model: unknown mode %r" % args[4])
    k = MODES[args[4]]
    if not 1 <= P <= MAX_PAGES or n < 1:
        raise SystemExit("bloombench model: arguments out of range")
    m = P * BITS_PER_PAGE
    queries = QUERY_RATIO * n

    rng = Rng(seed)
    salts = [rng.next() for _ in range(k)]
    base = rng.next()
    bits = bytearray(m // 8)

    def positions(key):
        return [mix64(key ^ s) % m for s in salts]

    refs = bits_set = 0
    for i in range(n):
        key = mix64((base + i) & MASK64)
        for b in positions(key):
            mask = 1 << (b % 8)
            if not bits[b // 8] & mask:
                bits_set += 1
            bits[b // 8] |= mask
            ref(b // BITS_PER_PAGE, True)
            refs += 1

    present = positives = false_positives = probes = checksum = 0
    for q in range(queries):
        is_present = rng.below(2) == 0
        i = rng.below(n) if is_present else n + rng.below(ABSENT_SPACE)
        key = mix64((base + i) & MASK64)
        yes = True
        for s in salts:
            b = mix64(key ^ s) % m
            ref(b // BITS_PER_PAGE, False)
            refs += 1
            probes += 1
            if not bits[b // 8] & (1 << (b % 8)):
                yes = False
                break
        present += is_present
        if yes:
            positives += 1
            checksum += q
            if not is_present:
                false_positives += 1

    return {
        "footprint_pages": P,
        "resident_margin": margin,
        "n_keys": n,
        "seed": seed,
        "hashes": k,
        "filter_bits": m,
        "queries": queries,
        "present_queries": present,
        "bits_set": bits_set,
        "query_probes": probes,
        "positives": positives,
        "false_positives": false_positives,
        "checksum": checksum,
        "trace_refs": refs,
    }


if __name__ == "__main__":
    from .check_run import model_main
    model_main("bloombench")
