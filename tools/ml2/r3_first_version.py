#!/usr/bin/env python3
"""R3: the first-version failure on PageRank, redone with the current deterministic seeds.

First-version data = no 'most recently accessed' candidates (N_RECENT=0), no probation (protect_age 0), data built
into a separate ML2_CACHE.  Fit every one of the 300 linear feature sets on graph's training rows, replay
graph-pr2000x2-s2 at 10%, and for one model recount where its victims were loaded and when they were needed again.

    ML2_CACHE=/tmp/ml2_v1 N_RECENT=0 python3 r3_first_version.py [--jobs 6]   -> report/results2/r3_first_version.csv
"""
import argparse
import csv
from multiprocessing import Pool

import numpy as np

import models as M
import pagesim as ps
import sweep_linear as SL

STEM, FRAC = "graph-pr2000x2-s2", "0.1"
OUT = ps.ROOT / "report" / "results2" / "r3_first_version.csv"
S = SPECS = CAP = CLOCK = None  # per worker process


def init(specs, cap, clock):
    global S, SPECS, CAP, CLOCK
    S, SPECS, CAP, CLOCK = ps.load_stream(STEM), specs, cap, clock


def one(i):
    r = ps.run(S, CAP, "learned", M.to_scored(SPECS[i], protect_age=0), max_faults=3 * CLOCK)
    return i, r["faults"], r["aborted"]


def ages(s, cap, vict_vpn):
    """Replay the stream with the given victim list. Per eviction: was the victim loaded by the previous fault; references until
    it is needed again; and for Belady's choice (resident page used farthest ahead), references since it was last used."""
    vpn2page = {int(v): i for i, v in enumerate(s.vpns)}
    vict = [vpn2page[int(v)] for v in vict_vpn]
    page, nxt = s.page, s.next_use
    nu = {}                      # resident page -> index of its next reference
    last = {}
    prev = None
    k = 0
    at_prev, until, bel_idle = [], [], []
    for t in range(s.n):
        p = int(page[t])
        if p not in nu:
            if len(nu) >= cap:
                if k >= len(vict):
                    break
                v = vict[k]
                k += 1
                at_prev.append(v == prev)
                until.append(nu[v] - t)   # next_use is a distance in references
                b = max(nu, key=nu.get)
                bel_idle.append(t - last[b])
                del nu[v]
            prev = p
        nu[p] = t + int(nxt[t])
        last[p] = t
    return np.array(at_prev), np.array(until), np.array(bel_idle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    s = ps.load_stream(STEM)
    cap = s.capacities[FRAC]
    clock = ps.run(s, cap, "clock")["faults"]
    d = M.load_scope("train", "graph")
    fitter = M.LinearFitter(d)
    specs = [fitter.fit(fs) for fs in SL.feature_sets()]
    print(f"{len(specs)} linear models, clock {clock} faults, {cap} frames, {s.n:,} references", flush=True)
    with Pool(a.jobs, initializer=init, initargs=(specs, cap, clock)) as pool:
        res = sorted(pool.map(one, range(len(specs)), chunksize=4))
    ratio = np.array([f / clock for _, f, _ in res])
    n3 = int((ratio >= 3).sum())
    print(f"models at or above 3x Clock: {n3} of {len(res)}; best {ratio.min():.3f}, median {np.median(ratio):.2f}", flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["features", "faults", "faults_over_clock", "aborted_at_3x"])
        for (i, fl, ab) in res:
            w.writerow(["+".join(specs[i]["features"]), fl, f"{fl / clock:.4f}", int(ab)])
    # victim ages for the model with the lowest ratio, and for the 'every feature' model
    allf = len(specs) - 1
    med = int(np.argsort(ratio)[len(ratio) // 2])
    for name, i in (("best of 300", int(np.argmin(ratio))), ("median of 300", med), ("all features", allf)):
        v, _ = ps.victims(s, cap, M.to_scored(specs[i], protect_age=0))
        ap_, un, bi = ages(s, cap, v)
        print(f"{name} ({'+'.join(specs[i]['features'])}): {len(v):,} victims, {100 * ap_.mean():.1f}% loaded at the previous fault, "
              f"median refs until needed again {np.median(un):.0f}, Belady's victim last used median {np.median(bi):.0f} refs earlier", flush=True)


if __name__ == "__main__":
    main()
