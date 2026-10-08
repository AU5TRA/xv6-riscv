#!/usr/bin/env python3
"""Summarise handwritten_vs_ml.csv: faults and page writes relative to Clock,
geometric mean over streams x {5,10,20}% per workload and split, plus
per-cell win counts.

    python3 exp_handwritten_report.py  -> prints tables; writes
                                          report/results2/summary_handwritten.csv
"""
import csv
import math
from collections import defaultdict

import pagesim as ps

R = ps.ROOT / "report" / "results2"
ORDER = ["fifo", "aging", "lru", "belady", "idle", "mru", "softdirty", "clean",
         "clean+p4", "ml_global", "ml_workload"]
WL = ["btree", "graph", "kv", "matmul", "sort"]


def gm(v):
    return math.exp(sum(math.log(max(x, 1e-9)) for x in v) / len(v))


def main():
    cl = {}
    for r in csv.DictReader(open(R / "classical.csv")):
        cl[(r["policy"], r["stem"], r["fraction"])] = (int(r["faults"]), int(r["writebacks"]))
    cells = defaultdict(dict)   # (stem, frac) -> policy -> (faults, writes, aborted)
    meta = {}
    for r in csv.DictReader(open(R / "handwritten_vs_ml.csv")):
        k = (r["stem"], r["fraction"])
        cells[k][r["policy"]] = (int(r["faults"]), int(r["writebacks"]), int(r["aborted"]))
        meta[k] = (r["split"], r["workload"])
    for (stem, frac), d in cells.items():
        for p in ("fifo", "aging", "lru", "belady"):
            f, w = cl[(p, stem, frac)]
            d[p] = (f, w, 0)

    agg = defaultdict(lambda: defaultdict(lambda: ([], [], 0)))
    for k, d in cells.items():
        split, wl = meta[k]
        cf, cw = cl[("clock", k[0], k[1])]
        for p, (f, w, ab) in d.items():
            fr, wr, n = agg[(wl, split)][p]
            fr.append(f / cf)
            wr.append(max(w, 1) / max(cw, 1))
            agg[(wl, split)][p] = (fr, wr, n + ab)

    out = []
    for metric, idx in (("FAULTS / Clock", 0), ("PAGE WRITES / Clock", 1)):
        print(f"\n{metric} (geo-mean over streams x 5/10/20%; * = some cells censored at 3x Clock)")
        print(f"{'workload split':<18}" + "".join(f"{p:>12}" for p in ORDER))
        for wl in WL:
            for split in ("test", "heldout"):
                if (wl, split) not in agg:
                    continue
                row = []
                for p in ORDER:
                    fr, wr, n = agg[(wl, split)][p]
                    v = gm((fr, wr)[idx])
                    row.append(f"{v:.3f}" + ("*" if n else " "))
                    if idx == 0:
                        out.append([wl, split, p, f"{gm(fr):.4f}", f"{gm(wr):.4f}", n])
                print(f"{wl + ' ' + split:<18}" + "".join(f"{x:>12}" for x in row))

    print("\nPER-CELL WINS (99 cells; lower faults wins)")
    for a, b in [("clean", "clock"), ("ml_workload", "clock"), ("ml_workload", "clean"),
                 ("ml_workload", "clean+p4"), ("ml_workload", "softdirty"),
                 ("ml_global", "clean"), ("idle", "clock")]:
        base = (lambda d: d["clock"]) if b == "clock" else (lambda d, b=b: d[b])
        if b == "clock":
            wins = sum(d[a][0] < cl[("clock", k[0], k[1])][0] for k, d in cells.items())
        else:
            wins = sum(d[a][0] < d[b][0] for k, d in cells.items())
        print(f"  {a:<12} < {b:<10}: {wins:>3} / {len(cells)}")
    with open(R / "summary_handwritten.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workload", "split", "policy", "geo_faults_vs_clock",
                    "geo_writes_vs_clock", "censored"])
        w.writerows(out)
    print("\nwrote", R / "summary_handwritten.csv")


if __name__ == "__main__":
    main()
