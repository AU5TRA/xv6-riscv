#!/usr/bin/env python3
"""Turn the traces2 study's raw results into summary tables.

Inputs (report/results2/): classical.csv, linear_sweep.csv (v2, all 300
feature sets at 10%), linear_sweep_v1.csv (v1 ablation), final_val.csv and
final_test.csv (nested selection, final.py), nn_eval.csv, extras.csv.

Per stream x capacity cell, against the kernel's best built-in policy (Clock)
and the oracle (Belady):
  ratio  faults / Clock faults                  (< 1: better than Clock)
  gap    (Clock - faults) / (Clock - Belady)    (share of the headroom closed)
A run is stopped at 3x Clock's faults; every source is censored there the
same way (ratio 3, flagged). A workload x split is summarised by the
geometric-mean ratio and mean gap over its cells.

Selection never uses test or held-out data (validation streams; matmul, which
has none, uses its training streams).
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "report" / "results2"
WORKLOADS = ["btree", "graph", "kv", "matmul", "sort"]
FRACS = ("0.05", "0.1", "0.2")
F = ["rec", "freq", "sd", "wr"]
K = ["ref", "aging", "sfreq", "idle", "age", "dirty"]
KP = ["refaults", "rdist"]
CENSOR = 3.0


def read(name):
    p = R / name
    return list(csv.DictReader(open(p))) if p.exists() else []


def write(name, header, rows):
    with open(R / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def classify(features):
    fs = set(features.split("+"))
    has_f, has_k, has_kp = fs & set(F), fs & set(K), fs & set(KP)
    if has_f and not (has_k or has_kp):
        return "F"
    if not has_f and not has_kp:
        return "K"
    if not has_f:
        return "K+K+"
    return "F+K"


BASE, META = None, None


def load_classical():
    global BASE, META
    if BASE is None:
        BASE, META = defaultdict(dict), {}
        for r in read("classical.csv"):
            BASE[(r["stem"], r["fraction"])][r["policy"]] = int(r["faults"])
            BASE[(r["stem"], r["fraction"])][r["policy"] + "_wb"] = int(r["writebacks"])
            META[r["stem"]] = (r["split"], r["workload"], r["variant"])
    return BASE, META


def cell(faults, stem, frac, aborted=0, writebacks=None):
    d = BASE[(stem, frac)]
    clock, bel = d["clock"], d["belady"]
    cens = int(aborted or faults >= CENSOR * clock)
    f = min(faults, CENSOR * clock)
    out = {"ratio": f / clock, "gap": (clock - f) / (clock - bel) if clock > bel else 0.0,
           "vs_lru": f / d["lru"], "cens": cens}
    if writebacks is not None:
        out["wb_ratio"] = (writebacks if not cens else CENSOR * d["clock_wb"]) / max(d["clock_wb"], 1)
    return out


def agg(cells):
    if not cells:
        return None
    r = np.array([c["ratio"] for c in cells])
    out = {"geo_ratio": float(np.exp(np.log(r).mean())),
           "mean_gap": float(np.mean([c["gap"] for c in cells])),
           "geo_vs_lru": float(np.exp(np.mean([math.log(c["vs_lru"]) for c in cells]))),
           "n": len(cells), "cens": int(sum(c["cens"] for c in cells))}
    wb = [c["wb_ratio"] for c in cells if "wb_ratio" in c]
    if wb:
        out["geo_wb"] = float(np.exp(np.mean(np.log(np.maximum(wb, 1e-9)))))
    return out


def f4(x):
    return f"{x:.4f}"


def main():
    load_classical()
    # ---------------------------------------------------------------- classical
    cl = defaultdict(list)
    pols = ["fifo", "clock", "aging", "lru", "lfu_exact", "lfu_kernel", "sd_old", "belady"]
    for (stem, frac), d in BASE.items():
        split, wl, _ = META[stem]
        if frac not in FRACS or split not in ("val", "test", "heldout"):
            continue
        for p in pols:
            cl[(p, wl, split)].append(cell(d[p], stem, frac, 0, d[p + "_wb"]))
            cl[(p, wl, split, frac)].append(cell(d[p], stem, frac, 0, d[p + "_wb"]))
    rows = []
    for key, cells in sorted(cl.items(), key=lambda kv: tuple(map(str, kv[0]))):
        a = agg(cells)
        frac = key[3] if len(key) == 4 else "all"
        rows.append([key[0], key[1], key[2], frac, f4(a["geo_ratio"]), f4(a["mean_gap"]),
                     f4(a["geo_vs_lru"]), f4(a.get("geo_wb", float("nan"))), a["n"], a["cens"]])
    write("summary_classical.csv", ["policy", "workload", "split", "fraction",
                                    "geo_ratio_vs_clock", "mean_gap_closed", "geo_ratio_vs_lru",
                                    "geo_writebacks_vs_clock", "cells", "censored"], rows)

    # ---------------------------------------------------------------- sweeps
    for src, out in (("linear_sweep.csv", "summary_linear.csv"),
                     ("linear_sweep_v1.csv", "summary_linear_v1.csv")):
        lin = defaultdict(list)
        for r in read(src):
            lin[(r["scope"], r["features"], r["workload"], r["split"])].append(
                cell(int(r["faults"]), r["stem"], r["fraction"], int(r["aborted"])))
        rows = []
        for (scope, feats, wl, split), cells in sorted(lin.items()):
            a = agg(cells)
            rows.append([scope, feats, classify(feats), len(feats.split("+")), wl, split,
                         f4(a["geo_ratio"]), f4(a["mean_gap"]), a["n"], a["cens"]])
        write(out, ["scope", "features", "group", "n_features", "workload", "split",
                    "geo_ratio_vs_clock", "mean_gap_closed", "cells", "censored"], rows)
        if src == "linear_sweep.csv":
            lin_v2 = lin
    # v2 restricted to the stream x capacity cells v1 finished, so the v1/v2
    # ablation compares identical cells
    v1cells = {(r["stem"], r["fraction"]) for r in read("linear_sweep_v1.csv")}
    matched = defaultdict(list)
    for r in read("linear_sweep.csv"):
        if (r["stem"], r["fraction"]) in v1cells:
            matched[(r["scope"], r["features"], r["workload"], r["split"])].append(
                cell(int(r["faults"]), r["stem"], r["fraction"], int(r["aborted"])))
    rows = []
    for (scope, feats, wl, split), cells in sorted(matched.items()):
        a = agg(cells)
        rows.append([scope, feats, classify(feats), len(feats.split("+")), wl, split,
                     f4(a["geo_ratio"]), f4(a["mean_gap"]), a["n"], a["cens"]])
    write("summary_linear_v2_matched.csv", ["scope", "features", "group", "n_features",
                                            "workload", "split", "geo_ratio_vs_clock",
                                            "mean_gap_closed", "cells", "censored"], rows)

    # ---------------------------------------------------------------- marginal
    agg2 = {k: agg(v)["geo_ratio"] for k, v in lin_v2.items()}
    order = K + KP
    rows = []
    for scope in WORKLOADS + ["global"]:
        for wl in (WORKLOADS if scope == "global" else [scope]):
            for split in ("val", "test", "heldout"):
                val = {f: v for (sc, f, w, sp), v in agg2.items()
                       if sc == scope and w == wl and sp == split and classify(f) in ("K", "K+K+")}
                for x in order:
                    d = []
                    for f, v in val.items():
                        fs = f.split("+")
                        if x in fs:
                            continue
                        g = "+".join(sorted(fs + [x], key=order.index))
                        if g in val:
                            d.append(math.log(val[g]) - math.log(v))
                    if d:
                        rows.append([scope, wl, split, x, f"{np.mean(d):+.4f}",
                                     f"{np.median(d):+.4f}", len(d)])
    write("summary_marginal.csv", ["scope", "workload", "split", "feature",
                                   "mean_delta_log_ratio", "median_delta_log_ratio", "pairs"], rows)

    # ---------------------------------------------------------------- final
    fin = defaultdict(list)
    for r in read("final_test.csv"):
        c = cell(int(r["faults"]), r["stem"], r["fraction"], int(r["aborted"]), int(r["writebacks"]))
        for frac in ("all", r["fraction"]):
            fin[(r["scope"], r["group"], r["features"], r["protect_age"], r["workload"],
                 r["split"], frac)].append(c)
    rows = []
    for key, cells in sorted(fin.items()):
        a = agg(cells)
        rows.append(list(key) + [f4(a["geo_ratio"]), f4(a["mean_gap"]), f4(a["geo_vs_lru"]),
                                 f4(a.get("geo_wb", float("nan"))), a["n"], a["cens"]])
    write("summary_final.csv", ["scope", "group", "features", "protect_age", "workload", "split",
                                "fraction", "geo_ratio_vs_clock", "mean_gap_closed",
                                "geo_ratio_vs_lru", "geo_writebacks_vs_clock", "cells",
                                "censored"], rows)

    # ---------------------------------------------------------------- neural
    nn = defaultdict(list)
    for r in read("nn_eval.csv"):
        nn[(r["model"], r["kind"], r["scope"], r["features"], r["protect_age"],
            r["workload"], r["split"])].append(
            cell(int(r["faults"]), r["stem"], r["fraction"], int(r["aborted"]), int(r["writebacks"])))
    # probation chosen per model on its selection cells
    sel_score = defaultdict(list)
    for (model, kind, scope, feats, pa, wl, split), cells in nn.items():
        if split == "val" or (wl == "matmul" and split == "train"):
            if scope == "global" or wl == scope:
                sel_score[(model, pa)] += [math.log(c["ratio"]) for c in cells]
    best_pa = {}
    for (model, pa), v in sel_score.items():
        if model not in best_pa or np.mean(v) < best_pa[model][1]:
            best_pa[model] = (pa, float(np.mean(v)))
    rows = []
    for (model, kind, scope, feats, pa, wl, split), cells in sorted(nn.items()):
        if split not in ("test", "heldout") or best_pa.get(model, (None,))[0] != pa:
            continue
        a = agg(cells)
        rows.append([model, kind, scope, feats, pa, f4(math.exp(best_pa[model][1])), wl, split,
                     f4(a["geo_ratio"]), f4(a["mean_gap"]), f4(a["geo_vs_lru"]),
                     f4(a.get("geo_wb", float("nan"))), a["n"], a["cens"]])
    write("summary_nn.csv", ["model", "kind", "scope", "features", "protect_age",
                             "selection_geo_ratio", "workload", "split", "geo_ratio_vs_clock",
                             "mean_gap_closed", "geo_ratio_vs_lru", "geo_writebacks_vs_clock",
                             "cells", "censored"], rows)

    # ---------------------------------------------------------------- extras
    ex = defaultdict(list)
    for r in read("extras.csv"):
        ex[(r["kind"], r["scope"], r["features"], r["workload"], r["split"])].append(
            cell(int(r["faults"]), r["stem"], r["fraction"], int(r["aborted"]), int(r["writebacks"])))
    rows = []
    for key, cells in sorted(ex.items()):
        a = agg(cells)
        rows.append(list(key) + [f4(a["geo_ratio"]), f4(a["mean_gap"]), a["n"], a["cens"]])
    write("summary_extras.csv", ["kind", "scope", "features", "workload", "split",
                                 "geo_ratio_vs_clock", "mean_gap_closed", "cells", "censored"], rows)
    print("summaries written")


if __name__ == "__main__":
    main()
