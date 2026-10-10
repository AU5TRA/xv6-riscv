#!/usr/bin/env python3
"""Safety-guard prototype in the simulator: does alternating the learned policy and Clock keep the wins and remove the losses?

Guard (pagesim.c): windows of W accesses. One window under the learned policy, one under Clock; the better one (fewer faults, the learned policy
gets a margin) is used for the next K windows, then the test repeats. W is a fraction of the stream length. Simulated from a filled-memory start
(one sweep over the pages first, as the kernel's benchmarks have). Margin 0 in all variants (0.03 made no difference in a first grid). The learned policy is the global linear kernel-signal model, probation 2.

    python3 exp_guard.py [--jobs 2]   -> report/results2/guard.csv
"""
import argparse
import csv
from multiprocessing import Pool

import numpy as np

import kernel_vs_sim as kvs
import pagesim as ps
import warm_start as W

OUT = ps.ROOT / "report" / "results2" / "guard.csv"
# streams the settings were NOT tuned on (--heldout), and the three settings carried over from the grid
HELDOUT = ["btree-lookup-s5", "btree-insert-s5", "kv-B-s5", "kv-T24-s1", "kv-T4-s1", "sort-n20000-s3", "matmul-naive128-s1", "heap-mixed-s1", "heap-churn-s1",
           "join-uni-s1", "join-r4-s1", "chase-n256-s1", "patb-zipf099-s1", "patb-phase-s1", "app-spmv-s1", "app-hashjoin-s1", "pat-zipf099-s5", "graph-bfs2000-s1"]
CARRIED = [(200, 20, 0.0), (100, 20, 0.0), (100, 10, 0.0)]
STREAMS = ["kv-A-s5", "kv-T17-s1", "btree-mixed-s5", "sort-n40000-s3", "matmul-blocked128-s1", "heap-small-s1", "join-zipf-s1", "spmv-band-s1",
           "spmv-rand-s1", "graph-pr2000x2-s3", "kv-C-s5"]
FRACS = ("0.05", "0.1", "0.2")
VARIANTS = [(d, k, 0.0) for d in (200, 100, 50) for k in (10, 20, 40, 80)]      # W = n / d, K windows, margin
HEADER = ["stem", "fraction", "frames", "policy", "faults", "guard_clock_share"]


def model(**kw):
    spec = kvs.FM["global"]
    return ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"], std=spec["std"],
                          layers=[(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32)) for L in spec["layers"]],
                          quant_w=8, protect_age=spec.get("protect_age", 0), **kw)


def job(a):
    stem, frac, variants = a
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    t = W.warm(s)
    n = t.n
    out = []

    def go(name, pol, m=None):
        r = ps.run(t, cap, pol, m)
        ev = max(r["evictions"], 1)
        out.append([stem, frac, cap, name, r["faults"] - s.n_pages, round(r["guard_clock_evictions"] / ev, 3)])
    go("clock", "clock")
    go("learned", "learned", model())
    for d, k, m in variants:
        go(f"guard W=n/{d} K={k} margin={m}", "learned", model(guard_w=max(n // d, 1000), guard_k=k, guard_margin=m))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--heldout", action="store_true")
    a = ap.parse_args()
    out = OUT.with_name("guard_heldout.csv") if a.heldout else OUT
    streams, variants = (HELDOUT, CARRIED) if a.heldout else (STREAMS, VARIANTS)
    tasks = [(st, fr, variants) for st in streams for fr in FRACS]
    with Pool(a.jobs) as p, open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for rows in p.imap_unordered(job, tasks):
            w.writerows(rows)
            fh.flush()
            print(rows[0][0], rows[0][1], "done", flush=True)


if __name__ == "__main__":
    main()
