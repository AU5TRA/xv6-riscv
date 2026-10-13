#!/usr/bin/env python3
"""Does a policy's saving in faults pay for the time it spends choosing victims?

Per workload and policy (kernel runs at 10% memory):
  faults / Clock                    measured in xv6
  instructions to choose a victim   the measured per-candidate cost (cost_grid.csv, repeatable clock) x the number of
                                    candidates (the run's memory size); sampled models are capped at their sample size
  break-even fault cost             the cost of ONE fault (reading the page back, writing the evicted one) above which the
                                    policy comes out ahead of Clock: (extra instructions per eviction) / (faults saved per
                                    eviction); in microseconds at 1 instruction per nanosecond
  time vs Clock                     (faults x fault cost + evictions x choosing cost) relative to Clock, for a fast SSD
                                    (100 us per fault) and a hard disk (8 ms per fault)

    python3 cost_benefit.py   -> report/results2/cost_benefit.csv
"""
import csv
import glob
import math
from collections import defaultdict

import numpy as np

import pagesim as ps

R = ps.ROOT / "report" / "results2"
SSD_US, HDD_US = 100.0, 8000.0     # assumed fault costs (the defaults of week 15); overridden by --ssd-us / --hdd-us
NS_PER_INSTR = 1.0                 # assumed 1 ns per instruction; overridden by --ns-per-instr (measured, S2)
OUT_NAME = "cost_benefit.csv"
for _i, _a in enumerate(__import__("sys").argv):
    if _a == "--ssd-us":
        SSD_US = float(__import__("sys").argv[_i + 1])
    elif _a == "--hdd-us":
        HDD_US = float(__import__("sys").argv[_i + 1])
    elif _a == "--ns-per-instr":
        NS_PER_INSTR = float(__import__("sys").argv[_i + 1])
    elif _a == "--out":
        OUT_NAME = __import__("sys").argv[_i + 1]
POL = [("fifo", ""), ("aging", ""), ("lfu", ""), ("ml", "global"), ("ml", "own"), ("ml", "cnn-kv"), ("ml", "mlp-kv"),
       ("ml", "trees-kv"), ("ml", "attention-graph"), ("ml", "ranktrees-graph")]


def cost_model():
    """(policy, model) -> function n -> instructions to choose, from a least-squares line through the measured sizes"""
    rows = list(csv.DictReader(open(R / "cost_grid.csv")))
    pts = defaultdict(list)
    for r in rows:
        pts[(r["policy"], r["model"])].append((int(r["frames"]), float(r["select_instructions_per_eviction"])))
    out = {}
    for k, v in pts.items():
        n = np.array([x[0] for x in v], float)
        y = np.array([x[1] for x in v])
        m = k[1].split("@")
        cap = int(m[1]) if len(m) > 1 else None
        if cap:      # sampled: the cost stops growing at the sample size
            full = [(a, b) for (a, b) in v if a <= cap]
            lo = max(full, key=lambda t: t[0]) if full else None
            flat = np.mean([b for a, b in v if a > cap]) if any(a > cap for a, _ in v) else y.max()
            out[k] = (lambda nn, cap=cap, flat=flat, lo=lo: flat if nn >= cap else (lo[1] * nn / lo[0] if lo else flat))
        else:
            A = np.vstack([n, np.ones_like(n)]).T
            b, a = np.linalg.lstsq(A, y, rcond=None)[0]
            out[k] = (lambda nn, a=a, b=b: max(a + b * nn, 0))
    return out


def main():
    cm = cost_model()
    rows = []
    for f in [str(R / "kernel_eval_all.csv")]:       # the merged file: every distinct kernel run, all streams
        rows += [r for r in csv.DictReader(open(f)) if r["status"] == "ok" and r["fraction"] == "0.1"]
    seen = {}
    for r in rows:
        seen[(r["stem"], r["policy"], r["model"])] = r        # later files override older ones
    fl = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    grp = lambda s: "kv-T" if s.startswith("kv-T") else s.split("-")[0]
    own = lambda g: "kv" if g == "kv-T" else g
    by = defaultdict(dict)
    for (stem, p, m), r in seen.items():
        g = grp(stem)
        if g in ("redis", "sqlite", "patb"):
            continue
        key = (p, own(g) if m == own(g) or m == own(g) + "" else m)
        by[(g, stem)][(p, "own" if m == own(g) else m)] = r
    out = []
    agg = defaultdict(list)
    for (g, stem), d in by.items():
        c = d.get(("clock", ""))
        if not c:
            continue
        frames = int(c["frames"])
        cf, ce = fl(c), max(int(c["evictions"]), 1)
        cc = cm[("clock", "")](frames)
        for (p, m), r in d.items():
            if (p, m) == ("clock", ""):
                continue
            key = (p, "global" if m == "global" else m)
            ck = (p, "global" if m == "own" else m)    # the own-workload linear models cost about what the global one does
            if ck not in cm and "@" in m and m.split("@")[0] in ("lzw", "kv", "btree", "graph", "sort", "matmul", "global"):
                ck = (p, "global@" + m.split("@")[1])   # sampled own-workload linear model: same cost as the sampled global one
            if ck not in cm:
                continue
            ev = max(int(r["evictions"]), 1)
            cost = cm[ck](frames)
            fr = fl(r) / cf
            saved = (cf - fl(r)) / ce                    # faults saved per Clock eviction
            extra = cost - cc
            be = extra * NS_PER_INSTR / saved / 1000 if saved > 0 else float("inf")      # microseconds (NS_PER_INSTR ns per instruction)
            t = {}
            for name, us in (("ssd", SSD_US), ("hdd", HDD_US)):
                t[name] = (fl(r) * us * 1000 + ev * cost * NS_PER_INSTR) / (cf * us * 1000 + ce * cc * NS_PER_INSTR)
            agg[(g, p, m)].append((fr, be, t["ssd"], t["hdd"], frames, cost))
    for (g, p, m), v in sorted(agg.items()):
        gm = lambda i: math.exp(np.mean([math.log(max(x[i], 1e-9)) for x in v]))
        bes = [x[1] for x in v if x[1] != float("inf")]
        out.append([g, p + (":" + m if m else ""), len(v), round(np.mean([x[4] for x in v])), round(gm(0), 3),
                    round(np.mean([x[5] for x in v])), round(float(np.median(bes)), 1) if bes else "never",
                    round(gm(2), 3), round(gm(3), 3)])
    with open(R / OUT_NAME, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workload", "policy", "streams", "frames", "faults_over_clock", "choose_instructions", "break_even_us",
                    "time_vs_clock_ssd", "time_vs_clock_hdd"])
        w.writerows(out)
    print("written", R / OUT_NAME)


if __name__ == "__main__":
    main()
