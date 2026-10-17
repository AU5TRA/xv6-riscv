#!/usr/bin/env python3
"""Numbers the paper's revision (main2.tex) needs that no earlier script produced.

  belady      Belady and Clock in the simulator at the kernel's own memory sizes (frames of the kernel's Clock runs; short streams cut to
              the kernel's access count) -> how much of the gap between Clock and Belady each kernel policy closes
  tests       bootstrap p-values (the same two-level resampling, one seed per comparison) for the six primary comparisons, Holm-adjusted
  cdf         per-stream faults / Clock at 10% for the figure (policy, ARC, LHD)
  summary     FIFO / Aging / LFU vs Clock to 3 decimals; resident sizes in pages and MB; total kernel compute time

    python3 paper_extra.py belady|tests|cdf|summary   -> report/results2/paper_extra_*.csv and printed lines
"""
import csv
import math
import sys
import zlib
from collections import defaultdict
from multiprocessing import Pool

import numpy as np

import kernel_vs_sim as kvs
import pagesim as ps

R = ps.ROOT / "report" / "results2"
FR = ("0.05", "0.1", "0.2")
f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"] or 0)


def group(stem):
    return "kv-T" if stem.startswith("kv-T") else stem.split("-")[0]


def runs():
    d = defaultdict(dict)                       # (fraction, policy) -> stem -> faults
    meta = {}
    for r in csv.DictReader(open(R / "kernel_eval_all.csv")):
        if r["status"] != "ok":
            continue
        pol = r["policy"] + (":" + r["model"] if r["model"] else "")
        d[(r["fraction"], pol)][r["stem"]] = f(r)
        if pol == "clock":
            meta[(r["stem"], r["fraction"])] = (int(r["frames"]), int(r["accesses"] or 0), float(r["wall_s"] or 0))
    return d, meta


def wmean(ratios):                              # stem -> ratio; geometric mean per workload, then over workloads
    by = defaultdict(list)
    for s, x in ratios.items():
        by[group(s)].append(math.log(x))
    return math.exp(np.mean([np.mean(v) for v in by.values()])), len(by), len(ratios)


def bel_job(a):
    stem, frac, frames, acc = a
    s = ps.load_stream(stem)
    if acc:
        s = kvs.prefix(s, acc)
    return stem, frac, ps.run(s, frames, "belady")["faults"], ps.run(s, frames, "clock")["faults"]


def belady():
    d, meta = runs()
    tasks = [(s, fr, fm, acc) for (s, fr), (fm, acc, _) in meta.items()]
    with Pool(6) as pool:
        res = pool.map(bel_job, tasks)
    with open(R / "paper_extra_belady.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stem", "fraction", "belady_faults_sim", "clock_faults_sim"])
        w.writerows(res)
    sim = {(s, fr): (b, c) for s, fr, b, c in res}
    out = []
    for fr in FR:
        rb, nw, ns = wmean({s: b / c for (s, f2), (b, c) in sim.items() if f2 == fr})
        line = [fr, round(rb, 3)]
        for pol in ("ml:global@32", "ml:global", "arck", "lhd"):
            rp = wmean({s: v / d[(fr, "clock")][s] for s, v in d[(fr, pol)].items() if s in d[(fr, "clock")]})[0]
            line += [round(rp, 3), round((1 - rp) / (1 - rb), 3)]
        out.append(line)
        print(f"{fr}: Belady {rb:.3f} of Clock ({nw} workloads, {ns} streams); gap closed: policy {line[3]:.0%}, full scan {line[5]:.0%}, ARC {line[7]:.0%}, LHD {line[9]:.0%}")
    with open(R / "paper_extra_headroom.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fraction", "belady_vs_clock_sim", "policy32", "policy32_gap_closed", "full", "full_gap_closed", "arc", "arc_gap_closed",
                    "lhd", "lhd_gap_closed"])
        w.writerows(out)


def tests():
    d, _ = runs()
    prim = [(fr, "ml:global@32", b) for b in ("clock", "arck") for fr in FR]
    rows = []
    for fr, a, b in prim:
        va, vb = d[(fr, a)], d[(fr, b)]
        by = defaultdict(list)
        for s in va:
            if s in vb:
                by[group(s)].append(math.log(max(va[s], 1) / max(vb[s], 1)))
        groups = [np.array(v) for v in by.values()]
        point = float(np.mean([g.mean() for g in groups]))
        rng = np.random.default_rng(zlib.crc32(f"faults|{fr}|{a}|{b}".encode()) & 0xFFFFFFFF)   # the interval script's seed
        bs = np.empty(10000)
        for i in range(10000):
            pick = rng.integers(0, len(groups), len(groups))
            bs[i] = np.mean([groups[j][rng.integers(0, len(groups[j]), len(groups[j]))].mean() for j in pick])
        p = min(1.0, 2 * min((bs >= 0).mean(), (bs <= 0).mean()))
        rows.append([fr, a, b, round(math.exp(point), 3), round(float(math.exp(np.quantile(bs, 0.025))), 3),
                     round(float(math.exp(np.quantile(bs, 0.975))), 3), max(p, 1 / 10000)])
    order = sorted(range(len(rows)), key=lambda i: rows[i][6])
    m = len(rows)
    adj = [0.0] * m
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * rows[i][6]))
        adj[i] = run
    with open(R / "paper_extra_tests.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fraction", "policy", "against", "ratio", "ci95_low", "ci95_high", "p_bootstrap", "p_holm"])
        for r, h in zip(rows, adj):
            w.writerow(r + [round(h, 4)])
            print(f"{r[0]:5s} {r[1]} vs {r[2]:6s} {r[3]:.3f} [{r[4]:.3f}, {r[5]:.3f}]  p={r[6]:.4f}  Holm p={h:.4f}  {'significant' if h < 0.05 else ''}")


def cdf():
    d, _ = runs()
    with open(R / "paper_extra_cdf.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["policy", "fraction", "stem", "ratio"])
        for fr in FR:
            for pol in ("ml:global@32", "arck", "lhd", "ml:global"):
                for s, v in sorted(d[(fr, pol)].items()):
                    if s in d[(fr, "clock")]:
                        w.writerow([pol, fr, s, round(v / d[(fr, "clock")][s], 4)])
    print("written paper_extra_cdf.csv")


def summary():
    d, meta = runs()
    for fr in FR:
        vals = {}
        for pol in ("fifo", "aging", "lfu"):
            vals[pol] = round(wmean({s: v / d[(fr, "clock")][s] for s, v in d[(fr, pol)].items() if s in d[(fr, "clock")]})[0], 3)
        fm = [fm for (s, f2), (fm, _, _) in meta.items() if f2 == fr]
        print(f"{fr}: {vals}; resident limit {min(fm)}-{max(fm)} pages (median {sorted(fm)[len(fm) // 2]}) = "
              f"{min(fm) * 4 / 1024:.2f}-{max(fm) * 4 / 1024:.2f} MB")
    tot = defaultdict(float)
    n = 0
    for r in csv.DictReader(open(R / "kernel_eval_all.csv")):
        if r["status"] == "ok" and r["wall_s"]:
            tot[r["policy"] in ("ml",) and r["model"] in ("cnn-all", "mlp-all", "attention-all", "trees-all", "ranktrees-all")] += float(r["wall_s"])
            n += 1
    print(f"wall time of {n} runs (each on one core; Kaggle runs at Kaggle speed): heavier models {tot[True] / 3600:.0f} h, everything else {tot[False] / 3600:.0f} h")
    cl = sorted(((wl, t) for (s, fr), (_, _, t) in meta.items() for wl in [group(s)] if fr == "0.1"), key=lambda x: -x[1])
    print("longest Clock run at 10%:", cl[:3])


def s3_job(a):
    stem, frac, frames, acc, pct = a
    s = ps.load_stream(stem)
    if acc:
        s = kvs.prefix(s, acc)
    ps._lib.set_s3_small_pct(pct)
    out = (stem, frac, pct, ps.run(s, frames, "s3scan")["faults"], ps.run(s, frames, "clock")["faults"])
    ps._lib.set_s3_small_pct(10)
    return out


def s3():
    """S3-FIFO (accessed-bit form) with its small queue at 5, 10 (published), 20 and 30% of memory, simulator, the kernel's cells."""
    _, meta = runs()
    tasks = [(s, fr, fm, acc, pct) for (s, fr), (fm, acc, _) in meta.items() for pct in (5, 10, 20, 30)]
    with Pool(6) as pool:
        res = pool.map(s3_job, tasks, chunksize=4)
    with open(R / "paper_extra_s3.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stem", "fraction", "small_pct", "s3fifo_faults_sim", "clock_faults_sim"])
        w.writerows(res)
    for fr in FR:
        line = []
        for pct in (5, 10, 20, 30):
            line.append(f"{pct}%: {wmean({s: a / b for s, f2, p, a, b in res if f2 == fr and p == pct})[0]:.3f}")
        print(fr, "S3-FIFO vs Clock (simulator):", ", ".join(line))


if __name__ == "__main__":
    {"belady": belady, "tests": tests, "cdf": cdf, "summary": summary, "s3": s3}[sys.argv[1]]()
