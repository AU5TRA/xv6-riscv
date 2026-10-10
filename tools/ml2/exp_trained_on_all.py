#!/usr/bin/env python3
"""Fair comparison of the five extra model kinds: trained on one workload (as run in the kernel) against trained on all workloads
(the "global" scope, like the global linear model).

Simulated with the same whole-number code the kernel uses (kernel/mlnet.h), from a populated memory start (one write sweep over the
stream's pages in front, as the kernel's benchmarks have; each page is touched once in the sweep, so it adds exactly n_pages faults, which
are subtracted). Streams: the ten used for the five models at 5% and 20% in the kernel, at 5, 10 and 20% memory.

    python3 exp_trained_on_all.py [--jobs 3]   -> report/results2/trained_on_all.csv
"""
import argparse
import csv
import time
from multiprocessing import Pool

import numpy as np

import extra_core as Z
import kernel_vs_sim as kvs
import netint
import pagesim as ps
import warm_start as W

OUT = ps.ROOT / "report" / "results2" / "trained_on_all.csv"
STREAMS = "btree-mixed-s5,kv-A-s5,kv-T17-s1,sort-n40000-s3,matmul-blocked128-s1,heap-small-s1,join-zipf-s1,spmv-band-s1,chase-tree-s1,bloom-k7-s1".split(",")
FRACS = ("0.05", "0.1", "0.2")
# kind -> (trained on one workload, trained on all)
KINDS = {"CNN on aging bits": ("kv.agecnn.K.-", "global.agecnn.K.-"), "deeper MLP": ("kv.deep.K.-", "global.deep.K.-"),
         "boosted trees": ("kv.gbdt.K.trees100-leaves16", "global.gbdt.K.trees100-leaves16"),
         "set-attention": ("graph.setctx.K.-", "global.setctx.K.-"), "ranking trees": ("graph.rank.K.trees100-leaves16", "global.rank.K.trees100-leaves16")}
HEADER = ["stem", "fraction", "frames", "policy", "faults", "seconds"]


def linear_global():
    spec = kvs.FM["global"]
    return ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"], std=spec["std"],
                          layers=[(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32)) for L in spec["layers"]],
                          quant_w=8, protect_age=spec.get("protect_age", 0))


def job(a):
    stem, frac = a
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    out = []

    def go(name, pol, model):
        t = time.time()
        n = s.n_pages
        t2 = W.warm(s)
        f = ps.run(t2, cap, pol, model)["faults"] - n
        out.append([stem, frac, cap, name, f, round(time.time() - t, 1)])
    go("clock", "clock", None)
    go("linear, global", "learned", linear_global())
    for kind, (one, allw) in KINDS.items():
        go(kind + " | one workload", "learned", netint.scored(Z.load_spec(one), 2))
        go(kind + " | all workloads", "learned", netint.scored(Z.load_spec(allw), 2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    streams = a.only.split(",") if a.only else STREAMS
    done = set()
    if OUT.exists():            # resumable: a (stream, memory size) cell is done when all 12 policies are in the file
        cnt = {}
        for r in csv.DictReader(open(OUT)):
            cnt[(r["stem"], r["fraction"])] = cnt.get((r["stem"], r["fraction"]), 0) + 1
        done = {k for k, v in cnt.items() if v >= 12}
    tasks = [(st, fr) for st in streams for fr in FRACS if (st, fr) not in done]
    tasks.sort(key=lambda t: -ps.load_stream(t[0]).n)
    new = not OUT.exists()
    with Pool(a.jobs) as p, open(OUT, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(HEADER)
        for rows in p.imap_unordered(job, tasks):
            w.writerows(rows)
            fh.flush()
            print(rows[0][0], rows[0][1], "done", flush=True)


if __name__ == "__main__":
    main()
