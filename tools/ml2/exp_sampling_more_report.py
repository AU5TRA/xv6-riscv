#!/usr/bin/env python3
"""Cost-and-quality table for the ways of sampling (sampling_more.csv).  Faults vs the full linear score and vs Clock (workload-weighted
geometric means), and the pages scanned and scored per eviction; the estimated instructions per eviction use the kernel's exact counts:
a page scanned costs the Aging cost per page (cost_grid, 118 instructions), a page scored costs the rest of the 264 per sampled page
(a fit to the exact counts for 4 to 64 random pages), plus 26 per eviction. Pool and clock-filter bookkeeping is not counted: an estimate."""
import csv
import math
import sys
from collections import defaultdict

import pagesim as ps

R = ps.ROOT / "report" / "results2"


def gmean(xs):
    xs = list(xs)
    return math.exp(sum(math.log(max(x, 1e-12)) for x in xs) / len(xs))


def wl(stem):
    return "kv-T" if stem.startswith("kv-T") else stem.split("-")[0]


def grid():
    d = {}
    for r in csv.DictReader(open(R / "cost_grid.csv")):
        d[(r["policy"], r["model"], int(r["frames"]))] = float(r["select_instructions_per_eviction"])
    return d


def main(fraction="0.1"):
    rows = [r for r in csv.DictReader(open(R / "sampling_more.csv")) if r["fraction"] == fraction and r["aborted"] == "0"]
    cell = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = (r["variant"], int(r["k"]), int(r["pool"]))
        cell[r["stem"]][key].append((int(r["faults"]), int(r["evictions"]), int(r["scanned"]), int(r["scored"])))
    g = grid()
    # Calibration from the kernel's exact counts at 68 pages, new code: k sampled random pages cost 26 + 264 x k (k = 4..64, fit through
    # 1,097, 2,129, 4,237, 8,465 and 16,911); the plain scan of a page (Aging) costs 118 of those 264, so scoring a page costs 146.
    scan_pp = (g[("aging", "", 512)] - g[("aging", "", 64)]) / (516 - 68)             # instructions per page scanned (read the used bit, update counters)
    score_pp = 264 - scan_pp                                                           # instructions per page scored
    fixed = 26
    keys = sorted({k for c in cell.values() for k in c}, key=lambda k: (k[0] != "full", k[0], k[1], k[2]))
    print(f"fraction {fraction}: scan {scan_pp:.0f} + score {score_pp:.0f} instructions per page, fixed {fixed} per eviction (new kernel code)")
    print(f"{'scheme':24s} {'vs all pages':>13s} {'vs Clock':>9s} {'scanned/ev':>11s} {'scored/ev':>10s} {'est. instr/ev':>14s}")
    out = []
    for k in keys:
        if k[0] == "clock" and k[1] == 0:
            continue
        by_full, by_clock, sc, so = defaultdict(list), defaultdict(list), [], []
        for stem, c in cell.items():
            if k not in c or ("full", 0, 0) not in c or ("clock", 0, 0) not in c:
                continue
            f = gmean(x[0] for x in c[k])
            by_full[wl(stem)].append(f / c[("full", 0, 0)][0][0])
            by_clock[wl(stem)].append(f / c[("clock", 0, 0)][0][0])
            ev = max(c[k][0][1], 1)
            sc.append(gmean(x[2] / max(x[1], 1) for x in c[k])); so.append(gmean(x[3] / max(x[1], 1) for x in c[k]))
        if not by_full:
            continue
        vf = gmean(gmean(v) for v in by_full.values()); vc = gmean(gmean(v) for v in by_clock.values())
        a, b = gmean(sc), gmean(so)
        est = fixed + a * scan_pp + b * score_pp
        name = {"full": "all pages", "random": f"random {k[1]}", "pool": f"pool {k[1]} new + {k[2]} kept", "clock": f"clock-filter {k[1]}"}[k[0]]
        print(f"{name:24s} {vf:13.3f} {vc:9.3f} {a:11.1f} {b:10.1f} {est:14,.0f}")
        out.append([fraction, name, round(vf, 4), round(vc, 4), round(a, 2), round(b, 2), round(est)])
    with open(R / f"sampling_more_summary_{fraction}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fraction", "scheme", "faults_vs_all_pages", "faults_vs_clock", "scanned_per_eviction", "scored_per_eviction", "estimated_instructions_per_eviction"])
        w.writerows(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "0.1")
