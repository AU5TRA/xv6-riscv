"""Host model of user/spmvbench.c: the same matrix, the same draws in the
same order, so the same reference string and RESULT lines.

    python3 tools/hostmodel/spmvbench.py <footprint> <margin> <iters> <seed> <mode> [flags]
"""
from __future__ import annotations

import bisect

if __package__ in (None, ""):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .common import PGSIZE, Rng

N = 131072
K = 4
MAX_ROW = 2 * K - 1
BAND = 32768
MOD = 65521
MAX_PAGES = 4096


def pages_for(nbytes):
    return (nbytes + PGSIZE - 1) // PGSIZE


def run(args, ref):
    if len(args) not in (5, 6):
        raise SystemExit("spmvbench model: want 5 or 6 arguments")
    P, margin, iters, seed = (int(a) for a in args[:4])
    if args[4] not in ("rand", "band"):
        raise SystemExit("spmvbench model: unknown mode %r" % args[4])
    band = args[4] == "band"
    if iters < 1 or not 1 <= P <= MAX_PAGES:
        raise SystemExit("spmvbench model: arguments out of range")
    x_pages = pages_for(N * 8)
    y_pages = x_pages
    rp_pages = pages_for((N + 1) * 4)
    fixed = x_pages + y_pages + rp_pages
    if fixed + 2 > P:
        raise SystemExit("spmvbench model: footprint too small")

    rng = Rng(seed)
    col = []
    row_ptr = [0]
    for i in range(N):
        ln = 1 + rng.below(MAX_ROW)
        if fixed + 2 * pages_for((len(col) + ln) * 4) > P:
            raise SystemExit("spmvbench model: footprint too small (row %d)" % i)
        lo, hi = 0, N - 1
        if band:
            lo, hi = max(0, i - BAND), min(N - 1, i + BAND)
        row = []
        for _ in range(ln):
            while True:
                c = lo + rng.below(hi - lo + 1)
                if c not in row:
                    break
            bisect.insort(row, c)
        col.extend(row)
        row_ptr.append(len(col))
    nnz = len(col)
    col_pages = pages_for(nnz * 4)
    need = fixed + 2 * col_pages
    val = [1 + rng.below(15) for _ in range(nnz)]
    x = [1 + rng.below(1000) for _ in range(N)]
    y = [0] * N

    x_base = 0
    y_base = x_pages * PGSIZE
    rp_base = (x_pages + y_pages) * PGSIZE
    col_base = fixed * PGSIZE
    val_base = (fixed + col_pages) * PGSIZE

    refs = checksum = 0
    for _ in range(iters):
        ref(rp_base // PGSIZE, False)
        refs += 1
        lo = row_ptr[0]
        for i in range(N):
            ref((rp_base + (i + 1) * 4) // PGSIZE, False)
            refs += 1
            hi = row_ptr[i + 1]
            s = 0
            for j in range(lo, hi):
                c = col[j]
                ref((col_base + j * 4) // PGSIZE, False)
                ref((val_base + j * 4) // PGSIZE, False)
                ref((x_base + c * 8) // PGSIZE, False)
                s += val[j] * x[c]
                refs += 3
            y[i] = s
            ref((y_base + i * 8) // PGSIZE, True)
            refs += 1
            checksum += s
            lo = hi
        for i in range(N):
            ref((y_base + i * 8) // PGSIZE, False)
            x[i] = 1 + y[i] % MOD
            ref((x_base + i * 8) // PGSIZE, True)
            refs += 2

    return {
        "footprint_pages": P,
        "resident_margin": margin,
        "iters": iters,
        "seed": seed,
        "rows": N,
        "band": BAND if band else 0,
        "nnz": nnz,
        "pages_needed": need,
        "checksum": checksum,
        "trace_refs": refs,
    }


if __name__ == "__main__":
    from .check_run import model_main
    model_main("spmvbench")
