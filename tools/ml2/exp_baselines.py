#!/usr/bin/env python3
"""Literature baselines on every test / held-out cell: exact MRU (needs per-access
recency, so an oracle-information reference), ARC, S3-FIFO (as published, and in a
form that only reads accessed bits at queue heads), an MGLRU analogue for anonymous
memory, and LHD (scan form). Policies are in pagesim.c; tests in test_baselines.py.

    python3 exp_baselines.py run [--jobs 6]   -> report/results2/baselines_ext.csv
    python3 exp_baselines.py report            -> faults and page writes vs Clock
"""
import argparse
import csv
import math
import time
from collections import defaultdict
from multiprocessing import Pool

import pagesim as ps

R = ps.ROOT / "report" / "results2"
FRACS = ("0.05", "0.1", "0.2")
POLS = ["mru", "arc", "s3fifo", "s3scan", "mglru", "lhd"]
SHOW = ["fifo", "lru", "belady", "mru", "arc", "s3fifo", "s3scan", "mglru", "lhd"]
OUT = R / "baselines_ext.csv"
HEADER = ["policy", "stem", "split", "workload", "fraction", "frames", "faults", "writebacks", "aborted"]


def clock_faults():
    return {(r["stem"], r["fraction"]): int(r["faults"])
            for r in csv.DictReader(open(R / "classical.csv")) if r["policy"] == "clock"}


def job(args):
    stem, frac = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    limit = 3 * clock_faults()[(stem, frac)]
    rows = []
    for pol in POLS:
        r = ps.run(s, cap, pol, max_faults=limit)
        rows.append([pol, stem, s.split, s.workload, frac, cap, r["faults"], r["writebacks"], int(r["aborted"])])
    return rows


def run(jobs):
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = sorted(((st, fr) for st in ps.stems(("test", "heldout")) for fr in FRACS), key=lambda t: -refs[t[0]])
    t0 = time.time()
    with Pool(jobs) as pool, open(OUT, "w", newline="") as f:
        w = csv.writer(f); w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows); f.flush()
            if i % 20 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} cells, {time.time() - t0:.0f}s", flush=True)
    print("wrote", OUT)


def gm(v):
    return math.exp(sum(math.log(max(x, 1e-9)) for x in v) / len(v))


def report():
    base = {}
    for r in csv.DictReader(open(R / "classical.csv")):
        base[(r["policy"], r["stem"], r["fraction"])] = (int(r["faults"]), int(r["writebacks"]))
    cells = defaultdict(dict)
    meta = {}
    for r in csv.DictReader(open(OUT)):
        k = (r["stem"], r["fraction"])
        cells[k][r["policy"]] = (int(r["faults"]), int(r["writebacks"]), int(r["aborted"]))
        meta[k] = (r["split"], r["workload"])
    for (stem, fr), d in cells.items():
        for p in ("fifo", "lru", "belady"):
            f, w = base[(p, stem, fr)]; d[p] = (f, w, 0)
    agg = defaultdict(lambda: defaultdict(lambda: [[], [], 0]))
    for k, d in cells.items():
        split, wl = meta[k]
        cf, cw = base[("clock", k[0], k[1])]
        for p, (f, w, ab) in d.items():
            a = agg[(wl, split)][p]
            a[0].append(f / cf); a[1].append(max(w, 1) / max(cw, 1)); a[2] += ab
    wls = sorted({k[0] for k in agg})
    for title, idx in (("FAULTS / Clock", 0), ("PAGE WRITES / Clock", 1)):
        print(f"\n{title} (geo-mean over streams x 5/10/20%; * = some cells censored at 3x Clock)")
        print(f"{'':<17}" + "".join(f"{p:>9}" for p in SHOW))
        for wl in wls:
            for sp in ("test", "heldout"):
                if (wl, sp) in agg:
                    print(f"{wl + ' ' + sp:<17}" + "".join(
                        f"{gm(agg[(wl, sp)][p][idx]):>8.3f}" + ("*" if agg[(wl, sp)][p][2] else " ") for p in SHOW))
    allv = {p: [x for k in agg for x in agg[k][p][0]] for p in SHOW}
    print("\nALL CELLS faults/Clock geo-mean: " + "  ".join(f"{p} {gm(allv[p]):.3f}" for p in SHOW))
    wins = {p: sum(1 for d in cells.values() if d[p][0] < base[("clock", *[k for k in cells if cells[k] is d][0])][0]) for p in SHOW}
    print("cells where the policy beats Clock (of %d): " % len(cells) + "  ".join(f"{p} {wins[p]}" for p in SHOW))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["run", "report"])
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    run(a.jobs) if a.what == "run" else report()
