"""Host model of user/joinbench.c: the same relations, the same table, the
same probe sequences, so the same reference string and RESULT lines.

    python3 tools/hostmodel/joinbench.py <footprint> <margin> <r_tuples> <seed> <mode> [flags]
"""
from __future__ import annotations

if __package__ in (None, ""):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .common import PGSIZE, Perm, Rng, load_bucketed, mix64, zipf_sample_bucketed

EMPTY = 0
KEY_SPACE = 4
MAX_PAGES = 4096
TUPLE = 16
SLOT = 8
OUT = 8

# name -> (s_ratio, zipf)
MODES = {"uni": (2, False), "zipf": (2, True), "r4": (4, False)}


def pages_for(nbytes):
    return (nbytes + PGSIZE - 1) // PGSIZE


def run(args, ref):
    if len(args) not in (5, 6):
        raise SystemExit("joinbench model: want 5 or 6 arguments")
    P, margin, nr, seed = (int(a) for a in args[:4])
    mode = args[4]
    if mode not in MODES:
        raise SystemExit("joinbench model: unknown mode %r" % mode)
    s_ratio, zipf = MODES[mode]
    if nr < 1:
        raise SystemExit("joinbench model: r_tuples must be at least 1")
    if zipf:
        cdf, start, zn = load_bucketed("64k099")
        if nr != zn:
            raise SystemExit("joinbench model: zipf needs r_tuples = %d" % zn)
    ns = nr * s_ratio
    per_page = PGSIZE // SLOT
    nslots = (2 * nr + per_page - 1) // per_page * per_page
    r_pages = pages_for(nr * TUPLE)
    t_pages = pages_for(nslots * SLOT)
    s_pages = pages_for(ns * TUPLE)
    o_pages = pages_for(ns * OUT)
    need = r_pages + t_pages + s_pages + o_pages
    if not need <= P <= MAX_PAGES:
        raise SystemExit("joinbench model: footprint must be %d-%d" % (need, MAX_PAGES))
    r_base = 0
    t_base = r_pages * PGSIZE
    s_base = (r_pages + t_pages) * PGSIZE
    o_base = (r_pages + t_pages + s_pages) * PGSIZE

    rng = Rng(seed)
    keys = Perm(KEY_SPACE * nr, rng.next())
    r_key = [1 + keys.fwd(i) for i in range(nr)]
    s_key = []
    for _ in range(ns):
        row = zipf_sample_bucketed(rng, cdf, start) if zipf else rng.below(nr)
        s_key.append(1 + keys.fwd(row))

    t_key = [EMPTY] * nslots
    t_pay = [0] * nslots
    refs = build_probes = probe_probes = longest = 0

    for i in range(nr):
        ref((r_base + i * TUPLE) // PGSIZE, False)
        refs += 1
        key = r_key[i]
        h = mix64(key) % nslots
        ln = 0
        while True:
            ln += 1
            if t_key[h] == EMPTY:
                t_key[h] = key
                t_pay[h] = i
                ref((t_base + h * SLOT) // PGSIZE, True)
                refs += 1
                break
            ref((t_base + h * SLOT) // PGSIZE, False)
            refs += 1
            h = 0 if h + 1 == nslots else h + 1
        build_probes += ln
        longest = max(longest, ln)

    matches = checksum = 0
    for j in range(ns):
        ref((s_base + j * TUPLE) // PGSIZE, False)
        refs += 1
        key = s_key[j]
        h = mix64(key) % nslots
        ln = 0
        while True:
            ln += 1
            k = t_key[h]
            ref((t_base + h * SLOT) // PGSIZE, False)
            refs += 1
            if k == key:
                ref((o_base + matches * OUT) // PGSIZE, True)
                refs += 1
                checksum += t_pay[h] ^ j
                matches += 1
                break
            if k == EMPTY:
                break
            h = 0 if h + 1 == nslots else h + 1
        probe_probes += ln
        longest = max(longest, ln)

    return {
        "footprint_pages": P,
        "resident_margin": margin,
        "r_tuples": nr,
        "seed": seed,
        "s_tuples": ns,
        "zipf_theta_x100": 99 if zipf else 0,
        "table_slots": nslots,
        "pages_needed": need,
        "build_probes": build_probes,
        "probe_probes": probe_probes,
        "longest_probe": longest,
        "matches": matches,
        "checksum": checksum,
        "trace_refs": refs,
    }


if __name__ == "__main__":
    from .check_run import model_main
    model_main("joinbench")
