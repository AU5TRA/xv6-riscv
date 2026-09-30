#!/usr/bin/env python3
"""Turn the traces2 study's raw results into tables and figures.

Inputs  report/results2/{classical,linear_sweep,nn_eval,extras}.csv
Outputs report/results2/summary_*.csv, report/results2/tables.md,
        report/figures2/*.png

Metrics, per (stream, capacity) cell, against the kernel's best built-in
policy (Clock) and the oracle (Belady):
  ratio      faults / Clock faults                   (< 1 is better than Clock)
  gap        (Clock - faults) / (Clock - Belady)     (share of the headroom closed)
Aggregates: geometric mean of ratio, mean of gap, over the cells of a
workload x split (three capacities x the split's streams).

Model selection never looks at test or held-out data: a feature subset is
chosen by its geometric-mean ratio over the scope's validation cells.
matmul has no validation streams, so its per-workload subsets are chosen on
its training streams (report/results2/extras.csv, kind=matmul_train).
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "report" / "results2"
FIG = ROOT / "report" / "figures2"
WORKLOADS = ["btree", "graph", "kv", "matmul", "sort"]
FRACS = ("0.05", "0.1", "0.2")
F = ["rec", "freq", "sd", "wr"]
K = ["ref", "aging", "sfreq", "idle", "age", "dirty"]
KP = ["refaults", "rdist"]


def read(name):
    p = R / name
    return list(csv.DictReader(open(p))) if p.exists() else []


def load_classical():
    ref = defaultdict(dict)
    meta = {}
    for r in read("classical.csv"):
        ref[(r["stem"], r["fraction"])][r["policy"]] = int(r["faults"])
        ref[(r["stem"], r["fraction"])][r["policy"] + "_wb"] = int(r["writebacks"])
        meta[r["stem"]] = (r["split"], r["workload"], r["variant"])
    return ref, meta


def cell_metrics(faults, base):
    clock, bel = base["clock"], base["belady"]
    ratio = faults / clock
    gap = (clock - faults) / (clock - bel) if clock > bel else 0.0
    return ratio, gap


def agg(cells):
    """cells: list of (ratio, gap, aborted)."""
    if not cells:
        return None
    r = np.array([c[0] for c in cells])
    g = np.array([c[1] for c in cells])
    return {"geo_ratio": float(np.exp(np.log(r).mean())), "mean_gap": float(g.mean()),
            "n": len(cells), "aborted": int(sum(c[2] for c in cells))}


def classify(features):
    fs = set(features.split("+"))
    has_f, has_k, has_kp = fs & set(F), fs & set(K), fs & set(KP)
    if has_f and not (has_k or has_kp):
        return "F"
    if not has_f and not has_kp:
        return "K"
    if not has_f:
        return "K+K+"      # kernel-observable incl. refault bookkeeping
    return "F+K"


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    base, meta = load_classical()

    # ------------------------------------------------ classical summary
    cls_rows = []
    pols = ["fifo", "clock", "aging", "lru", "lfu_exact", "lfu_kernel", "sd_old", "belady"]
    cl = defaultdict(list)
    for (stem, frac), d in base.items():
        split, wl, _ = meta[stem]
        if frac not in FRACS or split not in ("val", "test", "heldout"):
            continue
        for p in pols:
            ratio, gap = cell_metrics(d[p], d)
            cl[(p, wl, split)].append((ratio, gap, 0))
    for (p, wl, split), cells in sorted(cl.items()):
        a = agg(cells)
        cls_rows.append([p, wl, split, f"{a['geo_ratio']:.4f}", f"{a['mean_gap']:.4f}", a["n"]])
    write("summary_classical.csv", ["policy", "workload", "split", "geo_ratio_vs_clock",
                                    "mean_gap_closed", "cells"], cls_rows)

    # ------------------------------------------------ linear sweep
    lin = defaultdict(list)       # (scope, features, workload, split) -> cells
    for r in read("linear_sweep.csv"):
        d = base[(r["stem"], r["fraction"])]
        ratio, gap = cell_metrics(int(r["faults"]), d)
        lin[(r["scope"], r["features"], r["workload"], r["split"])].append(
            (ratio, gap, int(r["aborted"])))
    extras = defaultdict(list)
    for r in read("extras.csv"):
        d = base[(r["stem"], r["fraction"])]
        ratio, gap = cell_metrics(int(r["faults"]), d)
        extras[(r["kind"], r["scope"], r["features"], r["workload"], r["split"])].append(
            (ratio, gap, int(r["aborted"])))
    lin_rows = []
    lin_agg = {}
    for key, cells in sorted(lin.items()):
        a = agg(cells)
        lin_agg[key] = a
        scope, feats, wl, split = key
        lin_rows.append([scope, feats, classify(feats), len(feats.split("+")), wl, split,
                         f"{a['geo_ratio']:.4f}", f"{a['mean_gap']:.4f}", a["n"], a["aborted"]])
    write("summary_linear.csv", ["scope", "features", "group", "n_features", "workload",
                                 "split", "geo_ratio_vs_clock", "mean_gap_closed", "cells",
                                 "aborted"], lin_rows)

    # ------------------------------------------------ selection on validation
    def val_score(scope, feats):
        """Geo-mean ratio over the scope's validation cells (all workloads
        for the global scope); matmul per-workload uses its training streams."""
        cells = []
        wls = WORKLOADS if scope == "global" else [scope]
        for wl in wls:
            if wl == "matmul":
                cells += extras.get(("matmul_train", scope, feats, "matmul", "train"), [])
            else:
                cells += lin.get((scope, feats, wl, "val"), [])
        if not cells:
            return None
        return float(np.exp(np.mean([math.log(c[0]) for c in cells])))

    feats_all = sorted({k[1] for k in lin})
    groups = {"F": lambda f: classify(f) == "F", "K": lambda f: classify(f) == "K",
              "K+K+": lambda f: classify(f) in ("K", "K+K+"),
              "F+K": lambda f: classify(f) == "F+K", "any": lambda f: True}
    chosen = {}
    for scope in WORKLOADS + ["global"]:
        for g, ok in groups.items():
            cands = [(val_score(scope, f), f) for f in feats_all if ok(f)]
            cands = [(v, f) for v, f in cands if v is not None]
            if cands:
                chosen[(scope, g)] = min(cands)[1]
    sel_rows = []
    for (scope, g), f in sorted(chosen.items()):
        for wl in (WORKLOADS if scope == "global" else [scope]):
            for split in ("test", "heldout"):
                a = lin_agg.get((scope, f, wl, split))
                if a:
                    sel_rows.append([scope, g, f, wl, split, f"{a['geo_ratio']:.4f}",
                                     f"{a['mean_gap']:.4f}", a["n"], a["aborted"]])
    write("summary_selected.csv", ["scope", "group", "features", "workload", "split",
                                   "geo_ratio_vs_clock", "mean_gap_closed", "cells",
                                   "aborted"], sel_rows)

    # ------------------------------------------------ neural models
    nn = defaultdict(list)
    for r in read("nn_eval.csv"):
        d = base[(r["stem"], r["fraction"])]
        ratio, gap = cell_metrics(int(r["faults"]), d)
        nn[(r["model"], r["kind"], r["scope"], r["features"], r["workload"], r["split"])].append(
            (ratio, gap, int(r["aborted"])))
    nn_rows = []
    for key, cells in sorted(nn.items()):
        a = agg(cells)
        nn_rows.append(list(key) + [f"{a['geo_ratio']:.4f}", f"{a['mean_gap']:.4f}", a["n"],
                                    a["aborted"]])
    write("summary_nn.csv", ["model", "kind", "scope", "features", "workload", "split",
                             "geo_ratio_vs_clock", "mean_gap_closed", "cells", "aborted"],
          nn_rows)

    # ------------------------------------------------ feature marginal value
    # Average change in log ratio (test split) from adding feature x to a
    # subset that lacks it, over every K u K+ subset pair in the sweep.
    marg_rows = []
    for scope in WORKLOADS + ["global"]:
        for wl in (WORKLOADS if scope == "global" else [scope]):
            for split in ("test", "heldout"):
                val = {f: lin_agg[(scope, f, wl, split)]["geo_ratio"]
                       for f in feats_all if (scope, f, wl, split) in lin_agg
                       and classify(f) in ("K", "K+K+")}
                for x in K + KP:
                    deltas = []
                    for f, v in val.items():
                        fs = f.split("+")
                        if x in fs:
                            continue
                        order = K + KP
                        g = "+".join(sorted(fs + [x], key=order.index))
                        if g in val:
                            deltas.append(math.log(val[g]) - math.log(v))
                    if deltas:
                        marg_rows.append([scope, wl, split, x, f"{np.mean(deltas):+.4f}",
                                          len(deltas)])
    write("summary_marginal.csv", ["scope", "workload", "split", "feature",
                                   "mean_delta_log_ratio", "pairs"], marg_rows)
    print("summaries written")
    return chosen


def write(name, header, rows):
    with open(R / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    main()
