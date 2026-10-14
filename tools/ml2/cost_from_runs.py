#!/usr/bin/env python3
"""A rough check of the cost grid on the real programs, from runs already done (no new runs).

Every kernel run records the time the kernel spent choosing victims (select_ticks; QEMU's timer, 10 ticks per microsecond of emulated time)
and how many pages it had to choose from (candidates_scanned, summed over evictions). These runs were NOT in instruction-counting mode, so a
tick is emulated time, which depends on the PC's load and on the kind of instructions: the numbers are rough. Only runs done on the thesis PC
are used (Kaggle machines run at another speed). To cancel the machine's speed, each policy is also shown relative to Aging (which scans
every page and does little else) on the same streams; the cost grid (patbench uniform, exact instruction counts, 68 pages) gives
linear / Aging = 2.81, ARC / Aging = 1.47, LHD / Aging = 1.75, LeCaR / Aging = 1.00, Clock / Aging = 0.05.

    python3 cost_from_runs.py   -> report/results2/cost_from_runs.csv (per policy and workload, 10% memory) and cost_fit.csv (per policy)
"""
import csv
import glob
import statistics as st
from collections import defaultdict

import numpy as np

import pagesim as ps

R = ps.ROOT / "report" / "results2"
PC_FILES = ["kernel_eval.csv"] + sorted(p.split("/")[-1] for p in glob.glob(str(R / "kernel_eval_w16*.csv"))) + \
    ["kernel_eval_classic.csv", "kernel_eval_more.csv", "kernel_eval_models.csv", "kernel_eval_lecar.csv"]
POLS = ["clock", "aging", "lfu", "s3fifo", "arck", "lhd", "lecar", "ml:global", "ml:global@32", "ml:global@16"]


def group(stem):
    return "kv-T" if stem.startswith("kv-T") else stem.split("-")[0]


def main():
    runs = {}
    for f in PC_FILES:
        if not (R / f).exists():
            continue
        for r in csv.DictReader(open(R / f)):
            if r["status"] != "ok" or not r["select_ticks"] or not r["candidates_scanned"]:
                continue
            ev, cand, t = int(r["evictions"] or 0), int(r["candidates_scanned"]), int(r["select_ticks"])
            if ev <= 0 or cand <= 0:
                continue
            pol = r["policy"] + (":" + r["model"] if r["model"] else "")
            runs[(r["stem"], r["fraction"], pol)] = (t / ev, cand / ev)        # ticks per eviction, pages to choose from
    out = []
    for fr in ("0.05", "0.1", "0.2"):
        by = defaultdict(list)
        for (stem, f, pol), v in runs.items():
            if f == fr:
                by[(group(stem), pol)].append((stem, v))
        for (wl, pol), lst in sorted(by.items()):
            if pol not in POLS:
                continue
            per_page = st.median(t / c for _, (t, c) in lst)
            rel = [runs[(s, fr, pol)][0] / runs[(s, fr, "aging")][0] for s, _ in lst if (s, fr, "aging") in runs]
            out.append([fr, wl, pol, len(lst), round(st.median(c for _, (_, c) in lst)), round(st.median(t for _, (t, _) in lst), 1),
                        round(per_page, 3), round(st.median(rel), 3) if rel else ""])
    with open(R / "cost_from_runs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fraction", "workload", "policy", "streams", "pages_to_choose_from", "ticks_per_eviction", "ticks_per_page", "relative_to_aging"])
        w.writerows(out)
    # per policy: ticks per eviction = fixed + per_page * pages, least squares over every PC run (all memory sizes)
    fit = []
    for pol in POLS:
        pts = [(c, t) for (s, f, p), (t, c) in runs.items() if p == pol]
        if len(pts) < 10:
            continue
        x = np.array([c for c, _ in pts]); y = np.array([t for _, t in pts])
        b, a = np.polyfit(x, y, 1)
        resid = y - (a + b * x)
        fit.append([pol, len(pts), round(a, 1), round(b, 3), round(float(np.median(np.abs(resid) / y)), 3)])
    with open(R / "cost_fit.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["policy", "runs", "fixed_ticks_per_eviction", "ticks_per_page", "median_relative_misfit"])
        w.writerows(fit)
    for r in fit:
        print(f"{r[0]:14s} runs={r[1]:4d} fixed={r[2]:7.1f} ticks + {r[3]:.3f} ticks/page   (median misfit {100 * r[4]:.0f}%)")
    print("\n10% memory, relative to Aging on the same streams (exact patbench-uniform value in brackets):")
    exact = {"clock": 0.05, "arck": 1.47, "lhd": 1.75, "lecar": 1.00, "ml:global": 2.81, "lfu": 0.99, "s3fifo": 0.17}
    rows = defaultdict(dict)
    for fr, wl, pol, n, c, t, pp, rel in out:
        if fr == "0.1":
            rows[wl][pol] = rel
    show = ["clock", "arck", "lhd", "lecar", "ml:global"]
    print("workload ".ljust(9) + "".join(p.replace("ml:", "").rjust(10) for p in show))
    print("exact    " + "".join(f"{exact[p]:10.2f}" for p in show))
    for wl in sorted(rows):
        print(wl.ljust(9) + "".join((f"{rows[wl][p]:10.2f}" if rows[wl].get(p) != "" and p in rows[wl] else " " * 10) for p in show))


if __name__ == "__main__":
    main()
