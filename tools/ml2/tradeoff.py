#!/usr/bin/env python3
"""Data for the cost / benefit figure: for every policy, the instructions the kernel spends choosing one victim (68 candidates, exact counts
from cost_grid.csv) and the faults relative to Clock at 10% memory (xv6 kernel; geometric mean over the streams of each workload, then over the
workloads the policy has data for). Policies that were not run on every workload (sampled linear, the heavier models) come with the number of
workloads and the global linear score on the same workloads, so the two can be compared on the same footing.

    python3 tradeoff.py   -> report/results2/tradeoff.csv
"""
import csv
import math
from collections import defaultdict

import pagesim as ps

R = ps.ROOT / "report" / "results2"
POLICIES = [("fifo", "", "FIFO"), ("clock", "", "Clock"), ("aging", "", "Aging"), ("lfu", "", "LFU"), ("s3fifo", "", "S3-FIFO (adapted)"),
            ("arck", "", "ARC (adapted)"), ("lhd", "", "LHD (adapted)"), ("ml", "global", "linear score, global, all candidates"),
            ("ml", "global@32", "linear score, global, 32 sampled candidates"), ("ml", "global@16", "linear score, global, 16 sampled candidates"),
            ("ml", "trees-all", "boosted trees"), ("ml", "ranktrees-all", "ranking trees"), ("ml", "attention-all", "set-attention"),
            ("ml", "cnn-all", "CNN"), ("ml", "mlp-all", "deeper MLP")]


def grp(s):
    return "kv-T" if s.startswith("kv-T") else s.split("-")[0]


def main():
    cost = {(r["policy"], r["model"]): float(r["select_instructions_per_eviction"]) for r in csv.DictReader(open(R / "cost_grid.csv")) if r["frames"] == "64"}
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"] or 0)
    d = defaultdict(dict)
    for r in csv.DictReader(open(R / "kernel_eval_all.csv")):
        if r["status"] == "ok" and r["fraction"] == "0.1":
            d[(r["policy"], r["model"])][r["stem"]] = f(r)
    clock = d[("clock", "")]

    def per_workload(key):
        by = defaultdict(list)
        for s, v in d[key].items():
            if s in clock:
                by[grp(s)].append(math.log(max(v, 1) / clock[s]))
        return {w: sum(x) / len(x) for w, x in by.items()}

    glob = per_workload(("ml", "global"))
    out = []
    for pol, model, name in POLICIES:
        pw = per_workload((pol, model))
        if not pw:
            continue
        mean = lambda m, ws: math.exp(sum(m[w] for w in ws) / len(ws))
        ws = sorted(pw)
        out.append([name, f"{cost.get((pol, model), float('nan')):.0f}", f"{mean(pw, ws):.3f}", len(ws), f"{mean(glob, ws):.3f}" if all(w in glob for w in ws) else ""])
    with open(R / "tradeoff.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["policy", "instructions_per_decision_68_candidates", "faults_over_clock_10pct", "workloads_covered",
                    "linear_global_faults_over_clock_on_same_workloads"])
        w.writerows(out)
    for r in out:
        print(f"{r[0]:48s} {r[1]:>10s} {r[2]:>7s}  workloads {r[3]:2d}  linear on same {r[4]}")


if __name__ == "__main__":
    main()
