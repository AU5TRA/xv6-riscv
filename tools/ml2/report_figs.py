#!/usr/bin/env python3
"""Figures for report/week_14_update_report.pdf, from the CSVs in report/results2.

    python3 report_figs.py   -> report/week_14_update/figs/*.pdf

One colour per policy across every figure (colour-blind-checked adjacent
orders); Clock, the baseline, is the dashed line at 1.
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "report" / "results2"
OUT = ROOT / "report" / "week_14_update" / "figs"
OUT.mkdir(parents=True, exist_ok=True)

INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C = {"fifo": "#eda100", "lfu": "#008300", "aging": "#4a3aa7", "lru": "#e34948",
     "belady": "#52514e", "ml_global": "#eb6834", "ml_wl": "#2a78d6",
     "oracle": "#e87ba4", "kernel": "#1baf7a"}
WL = ["btree", "graph", "kv", "matmul", "sort"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "legend.frameon": False, "legend.fontsize": 7.5, "pdf.fonttype": 42,
})


def read(name):
    return list(csv.DictReader(open(R / name)))


def bars(ax, groups, series, values, ylabel, log=False, ylim=None):
    """Grouped bars; values[s][g] (None = no bar). Clock reference at 1."""
    n = len(series)
    width = 0.8 / n
    x = np.arange(len(groups))
    for i, (key, label) in enumerate(series):
        v = [values[key].get(g) for g in groups]
        xs = [x[j] + (i - (n - 1) / 2) * width for j in range(len(groups)) if v[j] is not None]
        ys = [vv for vv in v if vv is not None]
        ax.bar(xs, ys, width * 0.9, color=C[key], label=label, linewidth=0, zorder=3)
    ax.axhline(1, color=INK, lw=1, ls=(0, (4, 3)), zorder=4)
    ax.set_xticks(x, groups)
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, color=GRID, lw=0.6, zorder=0)
    ax.tick_params(length=0, axis="x")
    if log:
        ax.set_yscale("log")
    if ylim:
        ax.set_ylim(*ylim)


def save(fig, name):
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


# ---- 1. classical policies vs Clock (and the optimum) -------------------------
cl = {(r["policy"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
      for r in read("summary_classical.csv") if r["fraction"] == "all"}
fig, ax = plt.subplots(figsize=(6.3, 2.3))
series = [("fifo", "FIFO"), ("lfu", "LFU (decayed, xv6)"), ("aging", "Aging"),
          ("lru", "LRU (not implementable)"), ("belady", "Belady (optimal)")]
key = {"fifo": "fifo", "lfu": "lfu_kernel", "aging": "aging", "lru": "lru", "belady": "belady"}
groups = ["btree", "graph", "kv", "matmul*", "sort"]
vals = {s: {g: cl.get((key[s], g.rstrip("*"), "heldout" if g == "matmul*" else "test"))
            for g in groups} for s, _ in series}
bars(ax, groups, series, vals, "faults / Clock", ylim=(0, 1.5))
ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.22))
save(fig, "classical")

# ---- 2. what each kernel feature is worth ----------------------------------
mg = defaultdict(dict)
for r in read("summary_marginal.csv"):
    if r["scope"] == r["workload"] and (r["split"] == "test" or
                                        (r["workload"] == "matmul" and r["split"] == "heldout")):
        mg[r["feature"]][r["workload"]] = 100 * (math.exp(float(r["median_delta_log_ratio"])) - 1)
feats = ["idle", "sfreq", "dirty", "rdist", "refaults", "aging", "age", "ref"]
M = np.array([[mg[f].get(w, np.nan) for w in WL] for f in feats])
fig, ax = plt.subplots(figsize=(3.6, 2.6))
lim = 40
from matplotlib.colors import LinearSegmentedColormap
cmap = LinearSegmentedColormap.from_list("div", ["#1c5cab", "#86b6ef", "#f0efec", "#f0a3a2", "#b52f2f"])
im = ax.imshow(np.clip(M, -lim, lim), cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
for i in range(len(feats)):
    for j in range(len(WL)):
        v = M[i, j]
        if not np.isnan(v):
            ax.text(j, i, f"{v:+.0f}%", ha="center", va="center", fontsize=7,
                    color="white" if abs(v) > 25 else INK)
ax.set_xticks(range(len(WL)), WL)
ax.set_yticks(range(len(feats)), feats)
ax.tick_params(length=0)
for s in ax.spines.values():
    s.set_visible(False)
cb = fig.colorbar(im, ax=ax, fraction=0.05, pad=0.03)
cb.set_label("median change in faults\n(blue = fewer faults)", fontsize=7)
cb.outline.set_visible(False)
save(fig, "features")

# ---- 3. information tiers: oracle vs kernel-observable ------------------------
fin = {(r["scope"], r["group"], r["split"]): float(r["geo_ratio_vs_clock"])
       for r in read("summary_final.csv") if r["fraction"] == "all" and r["scope"] == r["workload"]}
fig, axs = plt.subplots(1, 2, figsize=(6.3, 2.3), sharey=True)
series = [("oracle", "linear, oracle features (F)"), ("ml_wl", "linear, kernel + refault (K∪K+)"),
          ("kernel", "linear, kernel only (K)"), ("belady", "Belady (optimal)")]
grp = {"oracle": "F", "ml_wl": "K+K+", "kernel": "K"}
for ax, split, title in [(axs[0], "test", "unseen seeds (test)"),
                         (axs[1], "heldout", "unseen variants (held-out)")]:
    groups = [w for w in WL if (w, "K", split) in fin]
    vals = {s: {g: (cl.get(("belady", g, split)) if s == "belady" else fin.get((g, grp[s], split)))
                for g in groups} for s, _ in series}
    bars(ax, groups, series, vals, "faults / Clock" if split == "test" else "", ylim=(0, 1.1))
    ax.set_title(title, fontsize=8, color=INK)
axs[0].legend(ncol=2, loc="upper center", bbox_to_anchor=(1.05, 1.42))
save(fig, "tiers")

# ---- 4/5. in-kernel results: faults and page writes ---------------------------
kern = {(r["policy"], r["workload"], r["split"]): r for r in read("summary_kernel.csv")}
series = [("fifo", "FIFO"), ("lfu", "LFU (decayed)"), ("aging", "Aging"),
          ("ml_global", "ML linear, one global model"), ("ml_wl", "ML linear, per-workload")]
kkey = {"fifo": "fifo", "lfu": "lfu", "aging": "aging", "ml_global": "ml/global",
        "ml_wl": "ml/workload"}
for col, name, ylabel, log, ylim in [
        ("geo_faults_vs_clock", "kernel_faults", "faults / Clock", False, (0, 2.2)),
        ("geo_writes_vs_clock", "kernel_writes", "page writes / Clock (log)", True, (0.02, 15))]:
    fig, axs = plt.subplots(1, 2, figsize=(6.3, 2.4), sharey=True,
                            gridspec_kw={"width_ratios": [4, 5]})
    for ax, split, title in [(axs[0], "test", "unseen seeds (test)"),
                             (axs[1], "heldout", "unseen variants (held-out)")]:
        groups = [w for w in WL if ("clock", w, split) in kern]
        vals = {s: {g: float(kern[(kkey[s], g, split)][col]) if (kkey[s], g, split) in kern else None
                    for g in groups} for s, _ in series}
        bars(ax, groups, series, vals, ylabel if split == "test" else "", log=log, ylim=ylim)
        ax.set_title(title, fontsize=8, color=INK)
        # direct labels for the per-workload ML bars
        n = len(series)
        for j, g in enumerate(groups):
            v = vals["ml_wl"][g]
            xpos = j + (n - 1 - (n - 1) / 2) * 0.8 / n
            ax.text(xpos, v * (1.15 if log else 1) + (0 if log else 0.04), f"{v:.2f}",
                    ha="center", va="bottom", fontsize=6.5, color=INK)
    axs[0].legend(ncol=5, loc="upper center", bbox_to_anchor=(1.15, 1.3))
    save(fig, name)

# ---- 6. kernel vs simulator --------------------------------------------------
kvs = read("kernel_vs_sim.csv")
by = defaultdict(dict)
for r in kvs:
    m, wl = r["model"], r["workload"]
    lab = r["policy"] if not m else ("ml_global" if m == "global" else
                                     "ml_k" if m.endswith("-k") else "ml_wl")
    by[r["stem"]][lab] = (int(r["kernel_faults"]), int(r["sim_faults"]))
pts = defaultdict(list)
for stem, d in by.items():
    if "clock" not in d:
        continue
    ck, cs = d["clock"]
    for lab, (k, s) in d.items():
        if lab in ("clock", "ml_k"):
            continue
        grp_ = lab if lab.startswith("ml") else "classical"
        pts[grp_].append((s / cs, k / ck, stem))
fig, ax = plt.subplots(figsize=(3.3, 3.1))
lo, hi = 0.25, 4
ax.plot([lo, hi], [lo, hi], color=INK2, lw=0.8, zorder=1)
for g, label, col in [("classical", "FIFO / Aging / LFU", "#8a8985"),
                      ("ml_global", "ML linear, global", C["ml_global"]),
                      ("ml_wl", "ML linear, per-workload", C["ml_wl"])]:
    p = np.array([(a, b) for a, b, _ in pts[g]])
    ax.scatter(p[:, 0], p[:, 1], s=14, color=col, label=label, edgecolor="white",
               linewidth=0.6, zorder=3)
cliff = [(a, b) for g in pts for a, b, s in pts[g] if s == "graph-pr2000x2-s3"]
ax.annotate("one PageRank stream\non a capacity cliff", xy=cliff[0], xytext=(0.27, 3.0),
            fontsize=6.5, color=INK2, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6))
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(lo, hi)
ax.set_ylim(lo, hi)
ticks = [0.25, 0.5, 1, 2, 4]
ax.set_xticks(ticks, [str(t) for t in ticks])
ax.set_yticks(ticks, [str(t) for t in ticks])
ax.minorticks_off()
ax.set_xlabel("simulator: faults / Clock")
ax.set_ylabel("xv6 kernel: faults / Clock")
ax.grid(True, color=GRID, lw=0.6, zorder=0)
ax.legend(loc="lower right")
save(fig, "kernel_vs_sim")

# ---- 7. model types compared (per-workload models, 10%) -----------------------
CAP = 1.6
nn = {}
for r in read("summary_nn.csv"):
    nn[(r["model"], r["workload"], r["split"])] = (float(r["geo_ratio_vs_clock"]), int(r["censored"]))
lin = {(r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
       for r in read("summary_final.csv")
       if r["fraction"] == "0.1" and r["scope"] == r["workload"] and r["group"] == "K+K+"}
KK = "ref+aging+sfreq+idle+age+dirty+refaults+rdist"
types = [("lin", "Linear (selected, used in the kernel)", "#2a78d6", lambda w: None),
         ("mlp", "MLP", "#e87ba4", lambda w: f"mlp_{w}_{KK}"),
         ("rmlp", "Ranking MLP", "#eda100", lambda w: f"rmlp_{w}_{KK}"),
         ("gru", "GRU", "#1baf7a", lambda w: f"gru_{w}"),
         ("emb", "Embedding", "#52514e", lambda w: f"embed_{w}")]
fig, axs = plt.subplots(1, 2, figsize=(6.3, 2.5), sharey=True, gridspec_kw={"width_ratios": [4, 5]})
for ax, split, title in [(axs[0], "test", "unseen seeds (test)"),
                         (axs[1], "heldout", "unseen variants (held-out)")]:
    groups = [w for w in WL if (w, split) in lin]
    n = len(types)
    width = 0.8 / n
    for i, (k, label, col, name) in enumerate(types):
        for j, g in enumerate(groups):
            if k == "lin":
                v, cens = lin[(g, split)], 0
            else:
                v, cens = nn.get((name(g), g, split), (None, 0))
            if v is None:
                continue
            x = j + (i - (n - 1) / 2) * width
            ax.bar(x, min(v, CAP), width * 0.9, color=col, linewidth=0, zorder=3,
                   label=label if j == 0 else None)
            if v > CAP or cens:
                ax.text(x, CAP + 0.02, ("≥" if cens else "") + f"{v:.1f}", ha="center",
                        va="bottom", fontsize=5.5, color=INK, rotation=90)
    ax.axhline(1, color=INK, lw=1, ls=(0, (4, 3)), zorder=4)
    ax.set_xticks(range(len(groups)), groups)
    ax.set_ylim(0, CAP + 0.35)
    ax.set_yticks([0, 0.5, 1, 1.5])
    ax.yaxis.grid(True, color=GRID, lw=0.6, zorder=0)
    ax.tick_params(length=0, axis="x")
    ax.set_title(title, fontsize=8, color=INK)
axs[0].set_ylabel("faults / Clock")
axs[0].legend(ncol=5, loc="upper center", bbox_to_anchor=(1.15, 1.3), fontsize=6.8)
save(fig, "models")
