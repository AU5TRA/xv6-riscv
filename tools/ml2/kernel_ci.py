#!/usr/bin/env python3
"""95% intervals for the in-kernel results.

An xv6 run repeats exactly (same faults every time), so there is no run-to-run noise to show. What varies is the stream:
the variants and seeds of a workload. For each workload and policy: faults relative to Clock on every stream of that workload,
the geometric mean, and a 95% interval from resampling the streams (paired with Clock, 10000 resamples). A workload needs at
least 3 streams for an interval.

    python3 kernel_ci.py   -> report/results2/kernel_ci.csv
"""
import csv
import math
from collections import defaultdict

import numpy as np

import pagesim as ps

R = ps.ROOT / "report" / "results2"
OWN = {"btree": "btree", "graph": "graph", "kv": "kv", "kv-T": "kv", "lzw": "lzw", "matmul": "matmul", "sort": "sort"}


def main():
    rows = [r for r in csv.DictReader(open(R / "kernel_eval_all.csv")) if r["fraction"] == "0.1"]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    grp = lambda s: "kv-T" if s.startswith("kv-T") else s.split("-")[0]
    d = defaultdict(dict)
    for r in rows:
        d[(grp(r["stem"]), r["policy"] + (":" + r["model"] if r["model"] else ""))][r["stem"]] = f(r)
    rng = np.random.default_rng(1)
    out = []
    for (g, pol), v in sorted(d.items()):
        if pol in ("clock",):
            continue
        clk = d.get((g, "clock"), {})
        stems = sorted(s for s in v if s in clk)
        if len(stems) < 3:
            continue
        lr = np.array([math.log(max(v[s], 1) / clk[s]) for s in stems])
        bs = np.sort([np.exp(lr[rng.integers(0, len(lr), len(lr))].mean()) for _ in range(10000)])
        out.append([g, pol, len(stems), round(float(np.exp(lr.mean())), 3), round(float(bs[250]), 3), round(float(bs[9749]), 3)])
    # paired: each extra model against the linear model of the same workload (its own, else the global one), per stream
    paired = []
    for (g, pol), v in sorted(d.items()):
        if pol.split(":")[-1] not in ("cnn-kv", "mlp-kv", "trees-kv", "attention-graph", "ranktrees-graph"):
            continue
        base = d.get((g, "ml:" + OWN[g])) if g in OWN and (g, "ml:" + OWN[g]) in d else d.get((g, "ml:global"))
        bname = "own linear" if g in OWN and (g, "ml:" + OWN[g]) in d else "global linear"
        if not base:
            continue
        stems = sorted(s for s in v if s in base)
        if len(stems) < 3:
            continue
        lr = np.array([math.log(max(v[s], 1) / max(base[s], 1)) for s in stems])
        bs = np.sort([np.exp(lr[rng.integers(0, len(lr), len(lr))].mean()) for _ in range(10000)])
        paired.append([g, pol, bname, len(stems), round(float(np.exp(lr.mean())), 3), round(float(bs[250]), 3), round(float(bs[9749]), 3)])
    with open(R / "kernel_ci_paired.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["workload", "model", "against", "streams", "faults_ratio", "ci95_low", "ci95_high"])
        w.writerows(paired)
    with open(R / "kernel_ci.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["workload", "policy", "streams", "faults_over_clock", "ci95_low", "ci95_high"])
        w.writerows(out)
    print("written", len(out), "rows")


if __name__ == "__main__":
    main()
