#!/usr/bin/env python3
"""Learned policies against the classical ones in the xv6 kernel, with 95% intervals.

For each memory size and each pair (policy A, policy B): faults of A relative to B on every stream both ran, grouped by workload.
The summary is the geometric mean over workloads of each workload's geometric mean over its streams (so a workload with 17 kv streams
counts once, like one with 2). The interval resamples workloads, then streams inside each chosen workload (10000 resamples).

    python3 kernel_ci_classic.py   -> report/results2/kernel_ci_classic.csv, and a short table on screen
"""
import csv
import math
from collections import defaultdict

import numpy as np

import pagesim as ps

R = ps.ROOT / "report" / "results2"
PAIRS = [("arck", "clock"), ("lhd", "clock"), ("s3fifo", "clock"), ("ml:global", "clock"),
         ("ml:global", "arck"), ("ml:global", "lhd"),
         ("ml:cnn-all", "arck"), ("ml:mlp-all", "arck"), ("ml:attention-all", "arck"), ("ml:trees-all", "arck"),
         ("ml:cnn-all", "ml:global"), ("ml:mlp-all", "ml:global")]


def group(stem):
    return "kv-T" if stem.startswith("kv-T") else stem.split("-")[0]


def main():
    rows = [r for r in csv.DictReader(open(R / "kernel_eval_all.csv")) if r["status"] == "ok"]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"] or 0)
    d = defaultdict(dict)                      # (fraction, policy) -> stem -> faults
    for r in rows:
        d[(r["fraction"], r["policy"] + (":" + r["model"] if r["model"] else ""))][r["stem"]] = f(r)
    rng = np.random.default_rng(7)
    out = []
    for fr in ("0.05", "0.1", "0.2"):
        for a, b in PAIRS:
            va, vb = d.get((fr, a), {}), d.get((fr, b), {})
            by = defaultdict(list)
            for s in va:
                if s in vb:
                    by[group(s)].append(math.log(max(va[s], 1) / max(vb[s], 1)))
            if len(by) < 3:
                continue
            groups = [np.array(v) for v in by.values()]
            point = float(np.mean([g.mean() for g in groups]))
            bs = []
            for _ in range(10000):
                pick = rng.integers(0, len(groups), len(groups))
                bs.append(np.mean([groups[i][rng.integers(0, len(groups[i]), len(groups[i]))].mean() for i in pick]))
            bs = np.sort(bs)
            out.append([fr, a, b, len(by), sum(len(g) for g in groups), round(math.exp(point), 3),
                        round(math.exp(bs[250]), 3), round(math.exp(bs[9749]), 3)])
    with open(R / "kernel_ci_classic.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fraction", "policy", "against", "workloads", "streams", "faults_ratio", "ci95_low", "ci95_high"])
        w.writerows(out)
    for r in out:
        sig = "<" if r[7] < 1 else (">" if r[6] > 1 else " ")
        print(f"{r[0]:>5} {r[1]:18s} vs {r[2]:10s} wl={r[3]:2d} streams={r[4]:3d}  {r[5]:.3f} [{r[6]:.3f}, {r[7]:.3f}] {sig}")


if __name__ == "__main__":
    main()
