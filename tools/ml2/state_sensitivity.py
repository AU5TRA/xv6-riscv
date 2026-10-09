#!/usr/bin/env python3
"""How much does a policy's result depend on what is in memory when the workload starts?

The simulator starts from empty memory; the kernel's benchmarks populate their data first, so memory is full and aged when
the traced workload starts. For each policy the same stream is replayed from five starting states: empty, and after one
populate sweep over the stream's pages in ascending, descending and two random orders (faults of the sweep itself are
not counted). A policy whose result moves a lot between starting states cannot be trusted from one simulation.

    python3 state_sensitivity.py   -> report/results2/state_sensitivity.csv
"""
import csv
from multiprocessing import Pool

import numpy as np

import extra_core as Z
import kernel_vs_sim as kvs
import netint
import pagesim as ps
import warm_start as W

OUT = ps.ROOT / "report" / "results2" / "state_sensitivity.csv"
STREAMS = ["kv-A-s5", "kv-T17-s1", "kv-T24-s1", "btree-insert-s5", "sort-n20000-s3", "matmul-blocked128-s1",
           "graph-both1000x3-s3", "graph-both2000x1-s5", "graph-pr2000x2-s3", "lzw-r20-s5", "pat-zipf099-s5",
           "pat-phase-s5", "app-bloom-s1", "app-spmv-s1"]
NETS = ["cnn-kv", "attention-graph", "mlp-kv", "ranktrees-graph", "trees-kv"]


def model(name):
    if name == "clock":
        return "clock", None
    if name in NETS:
        return "learned", netint.scored(Z.load_spec(kvs.NETS[name]), 2)
    spec = kvs.FM[name]
    return "learned", ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"], std=spec["std"],
                                     layers=[(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32)) for L in spec["layers"]],
                                     quant_w=8, protect_age=spec.get("protect_age", 0))


def job(a):
    stem, name = a
    s = ps.load_stream(stem)
    cap = s.capacities["0.1"]
    n = s.n_pages
    rng = np.random.default_rng(1)
    orders = {"empty": None, "ascending": np.arange(n), "descending": np.arange(n)[::-1],
              "random1": rng.permutation(n), "random2": rng.permutation(n)}
    pol, m = model(name)
    out = []
    for state, o in orders.items():
        pol, m = model(name)
        f = ps.run(s, cap, pol, m)["faults"] if o is None else W.faults_with_order(s, cap, pol, m, o)
        out.append([stem, name, state, f])
    return out


def main():
    own = {"kv": "kv", "btree": "btree", "sort": "sort", "matmul": "matmul", "graph": "graph", "lzw": "lzw"}
    tasks = []
    for st in STREAMS:
        wl = st.split("-")[0]
        names = ["clock", "global"] + ([own[wl]] if wl in own else []) + NETS
        tasks += [(st, nm) for nm in names]
    tasks.sort(key=lambda t: -ps.load_stream(t[0]).n)
    with Pool(4) as p, open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stem", "policy", "start", "faults"])
        for rows in p.imap_unordered(job, tasks):
            w.writerows(rows)
            f.flush()
    print("done")


if __name__ == "__main__":
    main()
