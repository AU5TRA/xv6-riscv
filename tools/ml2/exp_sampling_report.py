#!/usr/bin/env python3
"""Summarise sampling_sweep.csv.

For every model, mode and K: faults (and page writes) of the sampled run
divided by the full-scoring run on the same stream and capacity (paired, so
cell-to-cell differences cancel), geometric mean over cells and seeds, per
workload; the same ratio against Clock; and the pages scanned / scored per
eviction relative to full scoring.

    python3 exp_sampling_report.py -> prints tables, writes
                                      report/results2/summary_sampling.csv
"""
import csv
import math
from collections import defaultdict

import pagesim as ps

R = ps.ROOT / "report" / "results2"
WL = ["btree", "graph", "kv", "matmul", "sort"]


def gm(v):
    return math.exp(sum(math.log(max(x, 1e-9)) for x in v) / len(v))


def main():
    clock = {(r["stem"], r["fraction"]): int(r["faults"])
             for r in csv.DictReader(open(R / "classical.csv")) if r["policy"] == "clock"}
    rows = list(csv.DictReader(open(R / "sampling_sweep.csv")))
    full = {}
    for r in rows:
        if r["mode"] == "all":
            full[(r["model"], r["stem"], r["fraction"])] = r
    acc = defaultdict(lambda: defaultdict(lambda: {"vs_full": [], "w_full": [], "vs_clock": [],
                                                   "scan": [], "scored": [], "cens": 0}))
    for r in rows:
        f = full[(r["model"], r["stem"], r["fraction"])]
        a = acc[(r["model"], r["mode"], int(r["k"]))][r["workload"]]
        a["vs_full"].append(int(r["faults"]) / int(f["faults"]))
        a["w_full"].append(max(int(r["writebacks"]), 1) / max(int(f["writebacks"]), 1))
        a["vs_clock"].append(int(r["faults"]) / clock[(r["stem"], r["fraction"])])
        ev = max(int(r["evictions"]), 1)
        a["scan"].append(int(r["scanned"]) / ev)
        a["scored"].append(int(r["scored"]) / ev)
        a["cens"] += int(r["aborted"])

    out = []
    for model in ("ml_workload", "ml_global"):
        print(f"\n=== {model}: faults relative to FULL scoring on the same cell "
              f"(1.000 = no loss), geo-mean over cells x seeds")
        print(f"{'mode k':<10}" + "".join(f"{w:>9}" for w in WL) +
              f"{'ALL':>9}{'scored/ev':>11}{'scan/ev':>9}{'vs Clock':>10}{'writes':>8}")
        keys = sorted((k for k in acc if k[0] == model), key=lambda k: (k[1] != "all", k[1], k[2]))
        fullscore = None
        for key in keys:
            _, mode, k = key
            per = acc[key]
            allv = [x for w in WL for x in per[w]["vs_full"]]
            sc = sum(sum(per[w]["scored"]) for w in WL) / sum(len(per[w]["scored"]) for w in WL)
            sn = sum(sum(per[w]["scan"]) for w in WL) / sum(len(per[w]["scan"]) for w in WL)
            if mode == "all":
                fullscore = (sc, sn)
            vc = gm([x for w in WL for x in per[w]["vs_clock"]])
            wr = gm([x for w in WL for x in per[w]["w_full"]])
            cens = sum(per[w]["cens"] for w in WL)
            label = "all" if mode == "all" else f"{mode} {k}"
            print(f"{label:<10}" + "".join(f"{gm(per[w]['vs_full']):>9.3f}" for w in WL) +
                  f"{gm(allv):>9.3f}{sc:>11.1f}{sn:>9.1f}{vc:>10.3f}{wr:>8.3f}" +
                  (f"  ({cens} censored)" if cens else ""))
            out.append([model, mode, k] + [f"{gm(per[w]['vs_full']):.4f}" for w in WL] +
                       [f"{gm(allv):.4f}", f"{sc:.2f}", f"{sn:.2f}", f"{vc:.4f}", f"{wr:.4f}", cens])
    with open(R / "summary_sampling.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "mode", "k"] + [f"vs_full_{x}" for x in WL] +
                   ["vs_full_all", "scored_per_eviction", "scanned_per_eviction",
                    "vs_clock_all", "writes_vs_full", "censored"])
        w.writerows(out)
    print("\nwrote", R / "summary_sampling.csv")


if __name__ == "__main__":
    main()
