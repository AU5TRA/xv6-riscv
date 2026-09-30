#!/usr/bin/env python3
"""Figures for report/ML_REPORT.md and the slides, from the summaries that
analyze.py writes. Output: report/figures2/*.png (and .pdf for LaTeX)."""
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "report" / "results2"
FIG = ROOT / "report" / "figures2"
WL = ["btree", "graph", "kv", "matmul", "sort"]
COL = {"clock": "#7f7f7f", "F": "#b5540a", "K": "#2c6e8f", "K+K+": "#2e7d4f",
       "F+K": "#8e44ad", "belady": "#222222", "lru": "#bbbbbb", "fifo": "#dddddd",
       "aging": "#999999", "lfu_exact": "#e0a458", "lfu_kernel": "#6ea8c8"}
LABEL = {"F": "best full-stream (oracle)", "K": "best kernel-observable",
         "K+K+": "best kernel + refault", "F+K": "best oracle + kernel",
         "belady": "Belady (optimal)", "clock": "Clock (xv6 best)"}
plt.rcParams.update({"font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.dpi": 160})


def read(name):
    p = R / name
    return list(csv.DictReader(open(p))) if p.exists() else []


def save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIG / f"{name}.png")
    fig.savefig(FIG / f"{name}.pdf")
    plt.close(fig)


def classical():
    rows = read("summary_classical.csv")
    d = {(r["policy"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"]) for r in rows
         if r.get("fraction", "all") == "all"}
    pols = ["fifo", "aging", "lfu_kernel", "lru", "clock", "lfu_exact", "belady"]
    names = {"fifo": "FIFO", "aging": "Aging", "lfu_kernel": "decayed LFU (kernel)",
             "lru": "LRU", "clock": "Clock", "lfu_exact": "exact LFU (oracle)",
             "belady": "Belady"}
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2), sharey=True)
    for ax, split in zip(axes, ("test", "heldout")):
        x = np.arange(len(WL))
        w = 0.8 / len(pols)
        for i, p in enumerate(pols):
            vals = [min(d.get((p, wl, split), np.nan), 3.0) for wl in WL]
            ax.bar(x + (i - len(pols) / 2 + .5) * w, vals, w, label=names[p],
                   color=COL.get(p, "#555"))
        ax.axhline(1, color="k", lw=.6)
        ax.set_xticks(x, WL)
        ax.set_title(f"{split} streams")
        ax.set_ylim(0, 3.05)
    axes[0].set_ylabel("faults / Clock (geo-mean, capped at 3)")
    axes[1].legend(fontsize=7, frameon=False, loc="upper left", ncol=2)
    save(fig, "classical")


def final_table():
    """(scope, group, workload, split) -> geo ratio over all capacities."""
    return {(r["scope"], r["group"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
            for r in read("summary_final.csv") if r["fraction"] == "all"}


def classical_all():
    return {(r["policy"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
            for r in read("summary_classical.csv") if r.get("fraction", "all") == "all"}


def tiers(scope_kind):
    """scope_kind: 'workload' (per-workload models) or 'global'."""
    fin = final_table()
    cls = classical_all()
    groups = ["F", "K", "K+K+", "F+K"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2), sharey=True)
    for ax, split in zip(axes, ("test", "heldout")):
        x = np.arange(len(WL))
        bars = ["clock"] + groups + ["belady"]
        w = 0.8 / len(bars)
        for i, g in enumerate(bars):
            if g == "clock":
                vals = [1.0 if (("clock", wl, split) in cls) else np.nan for wl in WL]
            elif g == "belady":
                vals = [cls.get(("belady", wl, split), np.nan) for wl in WL]
            else:
                vals = [fin.get((wl if scope_kind == "workload" else "global", g, wl, split),
                                np.nan) for wl in WL]
            ax.bar(x + (i - len(bars) / 2 + .5) * w, [min(v, 2.0) for v in vals], w,
                   label=LABEL.get(g, g), color=COL[g])
        ax.axhline(1, color="k", lw=.6)
        ax.set_xticks(x, WL)
        ax.set_title(f"{split} streams" + (" (matmul has none)" if split == "test" else ""))
        ax.set_ylim(0, 1.25)
    axes[0].set_ylabel("faults / Clock (geo-mean, 5/10/20%)")
    axes[1].legend(fontsize=7, frameon=False, loc="upper left", ncol=2)
    save(fig, f"tiers_{scope_kind}")


def f_heatmap():
    rows = read("summary_linear.csv")
    F = ["rec", "freq", "sd", "wr"]
    subsets = sorted({r["features"] for r in rows if r["group"] == "F"},
                     key=lambda s: (len(s.split("+")), [F.index(f) for f in s.split("+")]))
    for scope in ("workload", "global"):
        fig, axes = plt.subplots(1, 2, figsize=(9, 4.4), sharey=True)
        for ax, split in zip(axes, ("test", "heldout")):
            M = np.full((len(subsets), len(WL)), np.nan)
            for r in rows:
                if r["group"] != "F" or r["split"] != split:
                    continue
                if (scope == "global") != (r["scope"] == "global"):
                    continue
                M[subsets.index(r["features"]), WL.index(r["workload"])] = float(
                    r["geo_ratio_vs_clock"])
            im = ax.imshow(np.log2(np.clip(M, 0.25, 4)), cmap="RdBu_r", vmin=-1.2, vmax=1.2,
                           aspect="auto")
            for i in range(M.shape[0]):
                for j in range(M.shape[1]):
                    if not np.isnan(M[i, j]):
                        ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=6.5)
            ax.set_xticks(range(len(WL)), WL)
            ax.set_yticks(range(len(subsets)), subsets, fontsize=7)
            ax.set_title(f"{split}")
        fig.suptitle(f"All 15 full-stream feature subsets, linear, "
                     f"{'per-workload' if scope == 'workload' else 'global'} model "
                     f"(faults / Clock; blue = better)", fontsize=9)
        save(fig, f"f_subsets_{scope}")


def kk_distribution():
    rows = read("summary_linear.csv")
    sel = {(r["scope"], r["group"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
           for r in read("summary_final.csv") if r["fraction"] == "0.1"}
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.3), sharey=True)
    for ax, split in zip(axes, ("test", "heldout")):
        for j, wl in enumerate(WL):
            vals = [float(r["geo_ratio_vs_clock"]) for r in rows
                    if r["scope"] == wl and r["workload"] == wl and r["split"] == split
                    and r["group"] in ("K", "K+K+")]
            if not vals:
                continue
            v = np.clip(vals, 0, 3)
            ax.scatter(np.full(len(v), j) + np.random.default_rng(j).uniform(-.25, .25, len(v)),
                       v, s=4, alpha=.45, color=COL["K"])
            b = sel.get((wl, "K+K+", wl, split))
            if b:
                ax.scatter([j], [b], marker="*", s=90, color=COL["K+K+"], zorder=3,
                           label="selected on validation" if j == 0 else None)
        ax.axhline(1, color="k", lw=.6)
        ax.set_xticks(range(len(WL)), WL)
        ax.set_title(f"{split}: all 255 kernel-observable subsets")
        ax.set_ylim(0, 3.05)
    axes[0].set_ylabel("faults / Clock (capped at 3)")
    axes[0].legend(fontsize=7, frameon=False)
    save(fig, "kk_subsets")


def marginal():
    rows = read("summary_marginal.csv")
    feats = ["ref", "aging", "sfreq", "idle", "age", "dirty", "refaults", "rdist"]
    M = np.full((len(feats), len(WL)), np.nan)
    for r in rows:
        want = "heldout" if r["workload"] == "matmul" else "test"
        if r["scope"] == r["workload"] and r["split"] == want:
            M[feats.index(r["feature"]), WL.index(r["workload"])] = float(
                r["mean_delta_log_ratio"])
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    pct = (np.exp(M) - 1) * 100
    im = ax.imshow(np.clip(pct, -40, 40), cmap="RdBu_r", vmin=-40, vmax=40, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{pct[i, j]:+.0f}%", ha="center", va="center", fontsize=7)
    ax.set_xticks(range(len(WL)), [w if w != "matmul" else "matmul*" for w in WL])
    ax.set_yticks(range(len(feats)), feats)
    ax.set_title("Average change in faults from adding a feature\n"
                 "(over all kernel subsets lacking it; test, *held-out; blue = helps)", fontsize=8)
    save(fig, "marginal")


def diagnostics():
    rows = read("feature_diagnostics.csv")
    feats = []
    for r in rows:
        if r["feature"] not in feats:
            feats.append(r["feature"])
    M = np.full((len(feats), len(WL)), np.nan)
    for r in rows:
        M[feats.index(r["feature"]), WL.index(r["workload"])] = float(r["within_decision_spearman"])
    fig, ax = plt.subplots(figsize=(5.2, 4))
    ax.imshow(M, cmap="PuOr", vmin=-.9, vmax=.9, aspect="auto")
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, f"{M[i, j]:+.2f}", ha="center", va="center", fontsize=7)
    ax.set_xticks(range(len(WL)), WL)
    ax.set_yticks(range(len(feats)), [f"{f} ({'F' if i < 4 else 'K' if i < 10 else 'K+'})"
                                      for i, f in enumerate(feats)])
    ax.set_title("Rank correlation with true next use,\nwithin each eviction decision", fontsize=8)
    save(fig, "diagnostics")


def nn_vs_linear():
    nn = read("summary_nn.csv")
    fin = {(r["scope"], r["group"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
           for r in read("summary_final.csv") if r["fraction"] == "0.1"}
    cls = {(r["policy"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
           for r in read("summary_classical.csv") if r.get("fraction") == "0.1"}
    groups = {"rec+freq+sd+wr": "F", "ref+aging+sfreq+idle+age+dirty": "K",
              "ref+aging+sfreq+idle+age+dirty+refaults+rdist": "K+K+",
              "rec+freq+sd+wr+ref+aging+sfreq+idle+age+dirty+refaults+rdist": "all"}
    series = [("lin", "K+K+", "linear K+K+ (selected)", "#2e7d4f"),
              ("mlp", "K+K+", "MLP K+K+", "#1b4f5c"), ("rmlp", "K+K+", "rank-MLP K+K+", "#6ea8c8"),
              ("lin", "F", "linear F (selected)", "#b5540a"), ("mlp", "F", "MLP F", "#d98c3f"),
              ("mlp", "all", "MLP all", "#8e44ad"), ("gru", None, "GRU (F)", "#c0392b"),
              ("embed", None, "embedding (F)", "#e67e22"), ("belady", None, "Belady", "#222222")]
    for split in ("test", "heldout"):
        d = defaultdict(dict)
        for r in nn:
            if r["scope"] != r["workload"] or r["split"] != split:
                continue
            kind = r["model"].split("_")[0]
            g = groups.get(r["features"]) if kind in ("mlp", "rmlp", "rlin") else None
            d[(kind, g)][r["workload"]] = float(r["geo_ratio_vs_clock"])
        for wl in WL:
            for g in ("K+K+", "F"):
                if (wl, g, wl, split) in fin:
                    d[("lin", g)][wl] = fin[(wl, g, wl, split)]
            d[("belady", None)][wl] = cls.get(("belady", wl, split), np.nan)
        fig, ax = plt.subplots(figsize=(9, 3.2))
        x = np.arange(len(WL))
        w = .8 / len(series)
        for i, (kind, g, lab, c) in enumerate(series):
            vals = [min(d[(kind, g)].get(wl, np.nan), 2.0) for wl in WL]
            ax.bar(x + (i - len(series) / 2 + .5) * w, vals, w, label=lab, color=c)
        ax.axhline(1, color="k", lw=.6)
        ax.set_xticks(x, WL)
        ax.set_ylim(0, 1.6)
        ax.set_ylabel("faults / Clock (geo-mean, 10%)")
        ax.set_title(f"Linear vs neural scorers, per-workload models, {split} streams")
        ax.legend(fontsize=7, frameon=False, ncol=5, loc="upper left")
        save(fig, f"nn_{split}")


def main():
    for f in (classical, lambda: tiers("workload"), lambda: tiers("global"), f_heatmap,
              kk_distribution, marginal, diagnostics, nn_vs_linear):
        try:
            f()
        except Exception as e:           # a missing input shouldn't stop the rest
            print("figure failed:", getattr(f, "__name__", f), e)
    print("figures in", FIG)


if __name__ == "__main__":
    main()
