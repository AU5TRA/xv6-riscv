#!/usr/bin/env python3
"""Tables from report/results2/sampling_heuristics.csv.  Per workload: geometric mean over its streams; then equal weight over workloads.
Reference points: Clock, the full linear score, and the kernel's own runs on the same cells."""
import csv
import math
from collections import defaultdict

import numpy as np

import pagesim as ps

R = ps.ROOT / "report" / "results2"


def gm(xs):
    return math.exp(sum(math.log(max(x, 1e-9)) for x in xs) / len(xs))


def main():
    rows = list(csv.DictReader(open(R / "sampling_heuristics.csv")))
    cell = defaultdict(dict)                       # stem -> {(variant, k): [faults of each seed]}
    wl, kern = {}, defaultdict(dict)
    for r in rows:
        cell[r["stem"]].setdefault((r["variant"], int(r["k"])), []).append(int(r["faults"]))
        wl[r["stem"]] = "kv-T" if r["stem"].startswith("kv-T") else r["stem"].split("-")[0]   # the paper's 14 groups
        if r["kernel_faults"]:
            kern[r["stem"]][(r["variant"], int(r["k"]))] = int(r["kernel_faults"])
    full = {s: c[("full", 0)][0] for s, c in cell.items()}
    clock = {s: c[("clock", 0)][0] for s, c in cell.items()}
    def score(value, base, streams=None):
        by = defaultdict(list)
        for s in (streams or cell):
            v = value(s)
            if v is not None:
                by[wl[s]].append(v / base[s])
        return gm([gm(v) for v in by.values()]), len(by), sum(len(v) for v in by.values())
    print("simulator on the kernel's cells: faults / Clock (workload-weighted geometric mean), and / full linear score")
    print(f"{'variant':10s} {'k':>3s}   vs Clock           vs full          seeds spread (vs full)")
    r0 = score(lambda s: full[s], clock)
    print(f"{'full':10s} {'':>3s}   {r0[0]:.3f}  ({r0[1]} workloads, {r0[2]} streams)")
    for k in (32, 16):
        for name in ("random", "newest", "window", "oldest", "spread", "unseen"):
            seeds = len(cell[next(iter(cell))][(name, k)])
            per_seed = []
            for i in range(seeds):
                per_seed.append((score(lambda s: cell[s][(name, k)][i], clock)[0], score(lambda s: cell[s][(name, k)][i], full)[0]))
            vc = np.mean([a for a, _ in per_seed]); vf = np.mean([b for _, b in per_seed])
            spread = max(b for _, b in per_seed) - min(b for _, b in per_seed)
            print(f"{name:10s} {k:3d}   {vc:.3f}              {vf:.3f}            {spread:.4f}")
    print("\nsimulator against the kernel, same cells (kernel faults / simulator faults, per stream)")
    for name, key in (("global", ("full", 0)), ("global@32", ("random", 32)), ("global@16", ("random", 16))):
        ratios = []
        for s in cell:
            kf = kern[s].get(key)
            if kf:
                ratios.append(kf / cell[s][key][0])
        print(f"{name:10s} {len(ratios)} streams: geometric mean {gm(ratios):.3f}, median {np.median(ratios):.3f}, range {min(ratios):.2f} to {max(ratios):.2f}")
    print("\nthe kernel's sampled / full, and the simulator's, same streams, workload-weighted")
    for k in (32, 16):
        kk = score(lambda s: kern[s].get(("random", k)) , {s: kern[s][("full", 0)] for s in cell})[0]
        ss = score(lambda s: cell[s][("random", k)][0], full)[0]
        print(f"k={k}: kernel {kk:.3f}, simulator (seed 1) {ss:.3f}")


if __name__ == "__main__":
    main()


def averaging():
    """Why the old sweep (exp_sampling.py) said 1.017 / 1.04 for K = 32 / 16 and the kernel runs 0.998 / 1.013: other cells, other averaging."""
    rows = list(csv.DictReader(open(R / "sampling_heuristics.csv")))
    cell = defaultdict(dict)
    for r in rows:
        if r["seed"] in ("0", "1"):
            cell[r["stem"]][(r["variant"], int(r["k"]))] = int(r["faults"])
    old = {r["stem"] for r in csv.DictReader(open(R / "sampling_sweep.csv")) if r["fraction"] == "0.1"}
    wl = {s: ("kv-T" if s.startswith("kv-T") else s.split("-")[0]) for s in cell}
    for k in (32, 16):
        allst = [s for s in cell if (("random", k) in cell[s])]
        def per_stream(streams):
            return gm([cell[s][("random", k)] / cell[s][("full", 0)] for s in streams])
        def per_workload(streams):
            by = defaultdict(list)
            for s in streams:
                by[wl[s]].append(cell[s][("random", k)] / cell[s][("full", 0)])
            return gm([gm(v) for v in by.values()])
        o = [s for s in allst if s in old]
        print(f"k={k}: 74 streams per workload {per_workload(allst):.3f}, per stream {per_stream(allst):.3f}; "
              f"the {len(o)} streams of the old sweep per workload {per_workload(o):.3f}, per stream {per_stream(o):.3f}")


if __name__ == "__main__":
    averaging()
