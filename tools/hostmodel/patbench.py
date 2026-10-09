"""Host model of user/patbench.c: the same PRNG draws in the same order,
so the same reference string and the same RESULT lines.

    python3 tools/hostmodel/patbench.py <footprint> <margin> <accesses> <seed> <mode> [flags]

prints the predicted RESULT lines and the trace's reference count, byte
count and MD5 (at arena VPN 0 unless --arena-vpn is given). The checker,
tools/hostmodel/check_run.py, runs it against a collected log and trace.
"""
from __future__ import annotations

if __package__ in (None, ""):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .common import Perm, Rng, load_cdf, zipf_sample

WRITE_PCT = 10
HOT_DIV = 16
MAX_PAGES = 4096
ZIPF_N = 1024

# name -> (kind, hot_pct, phase_div, theta_x100, zipf table)
MODES = {
    "loop": ("loop", 0, 0, 0, None),
    "scanhot": ("scanhot", 50, 0, 0, None),
    "scanhotlo": ("scanhot", 20, 0, 0, None),
    "zipf060": ("zipf", 0, 0, 60, "060"),
    "zipf080": ("zipf", 0, 0, 80, "080"),
    "zipf099": ("zipf", 0, 0, 99, "099"),
    "zipf120": ("zipf", 0, 0, 120, "120"),
    "uniform": ("uniform", 0, 0, 0, None),
    "phase": ("phase", 80, 8, 0, None),
    "phaseshort": ("phase", 80, 32, 0, None),
    "switch": ("switch", 0, 8, 99, "099"),
}


def run(args, ref):
    """args: the program's arguments after its name, as strings. Calls
    ref(page, write) once per reference, page relative to the arena.
    Returns the RESULT values the model can predict."""
    if len(args) not in (5, 6):
        raise SystemExit("patbench model: want 5 or 6 arguments")
    P = int(args[0])
    margin = int(args[1])
    accesses = int(args[2])
    seed = int(args[3])
    mode = args[4]
    if mode not in MODES:
        raise SystemExit("patbench model: unknown mode %r" % mode)
    kind, hot_pct, phase_div, theta, table = MODES[mode]
    if not HOT_DIV <= P <= MAX_PAGES or accesses < 1:
        raise SystemExit("patbench model: arguments out of range")
    cdf = load_cdf(table) if table else None
    if cdf is not None and P != ZIPF_N:
        raise SystemExit("patbench model: zipf modes need P = %d" % ZIPF_N)

    rng = Rng(seed)
    perm_a = Perm(P, rng.next())
    perm_b = Perm(P, rng.next())
    perm_hot = perm_a
    hot = P // HOT_DIV
    phase_len = 0
    if phase_div:
        phase_len = max(1, accesses // phase_div)

    # The arena's words, one per page, as the benchmark leaves them.
    word = [0] * P
    loop_pos = scan_pos = checksum = reads = writes = 0
    for i in range(accesses):
        if kind == "loop":
            page = perm_a.fwd(loop_pos)
            loop_pos = 0 if loop_pos + 1 == P else loop_pos + 1
        elif kind == "scanhot":
            if rng.below(100) < hot_pct:
                page = perm_a.fwd(rng.below(hot))
            else:
                while True:
                    page = scan_pos
                    scan_pos = 0 if scan_pos + 1 == P else scan_pos + 1
                    if perm_a.inv(page) >= hot:
                        break
        elif kind == "zipf":
            page = perm_a.fwd(zipf_sample(rng, cdf))
        elif kind == "uniform":
            page = rng.below(P)
        elif kind == "phase":
            if i % phase_len == 0:
                perm_hot = Perm(P, rng.next())
            if rng.below(100) < hot_pct:
                page = perm_hot.fwd(rng.below(hot))
            else:
                page = rng.below(P)
        else:  # switch
            if (i // phase_len) % 2 == 0:
                page = perm_a.fwd(loop_pos)
                loop_pos = 0 if loop_pos + 1 == P else loop_pos + 1
            else:
                page = perm_b.fwd(zipf_sample(rng, cdf))
        is_write = rng.below(100) < WRITE_PCT
        v = word[page]
        checksum += v
        if is_write:
            word[page] = v + 1
            writes += 1
        else:
            reads += 1
        ref(page, is_write)

    loops = kind in ("loop", "switch")
    hots = kind in ("scanhot", "phase")
    return {
        "footprint_pages": P,
        "resident_margin": margin,
        "accesses": accesses,
        "seed": seed,
        "loop_pages": P if loops else 0,
        "hot_pages": hot if hots else 0,
        "hot_pct": hot_pct,
        "phase_len": phase_len,
        "zipf_theta_x100": theta,
        "write_pct": WRITE_PCT,
        "reads": reads,
        "writes": writes,
        "checksum": checksum,
        "trace_refs": accesses,
    }


if __name__ == "__main__":
    from .check_run import model_main
    model_main("patbench")
