#!/usr/bin/env python3
"""Tables and figures of the week-15 update, straight from report/results2/*.csv.

    python3 report_w15.py   -> report/week_15_update/tables/*.tex, figs/*.pdf, tables/numbers.tex
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import pagesim as ps

R = ps.ROOT / "report" / "results2"
OUT = ps.ROOT / "report" / "week_15_update"
(OUT / "tables").mkdir(parents=True, exist_ok=True)
(OUT / "figs").mkdir(parents=True, exist_ok=True)
FR = ("0.05", "0.1", "0.2")
NUM = {}


def gm(v):
    return math.exp(sum(math.log(max(x, 1e-9)) for x in v) / len(v))


def write(name, text):
    (OUT / "tables" / name).write_text(text)


def tab(rows, header, align=None):
    a = align or "l" + "r" * (len(header) - 1)
    out = [r"\begin{tabular}{%s}" % a, r"\toprule", " & ".join(header) + r" \\", r"\midrule"]
    out += [" & ".join(str(c) for c in r) + r" \\" for r in rows]
    return "\n".join(out + [r"\bottomrule", r"\end{tabular}"]) + "\n"


# ---- dataset ------------------------------------------------------------------
def dataset():
    idx = json.load(open(ps.DATA / "index.json"))["streams"]
    by = defaultdict(lambda: [0, 0, 0, set()])
    for e in idx:
        w = e["workload"]
        by[w][0] += 1
        by[w][1] += e["refs"]
        by[w][2] += e["split"] in ("heldout",)
        by[w][3].add(e["variant"])
    rows = [[w, len(v[3]), v[0], f"{v[1] / 1e6:.1f}M", v[2]] for w, v in sorted(by.items())]
    write("dataset.tex", tab(rows, ["workload", "variants", "streams", "references", "held-out streams"]))
    NUM["nstreams"] = len(idx)


# ---- extra / baselines ------------------------------------------------------------
def extra():
    rows = [r for r in csv.DictReader(open(R / "extra_summary.csv"))]
    val = defaultdict(dict)
    for r in rows:
        if "/" not in r["system"]:
            val[(r["scope"], r["group"])][r["system"]] = float(r["geo_ratio_vs_clock"])
    scopes = ["btree", "graph", "kv", "lzw", "matmul", "sort", "global"]

    def pick(d, prefix):
        k = [s for s in d if s.startswith(prefix)]
        return d[k[0]] if k else None

    out = []
    for sc in scopes:
        for g in ("test", "held-out"):
            d = val.get((sc, g))
            if not d:
                continue
            cells = [pick(d, p) for p in ("lru", "arc", "s3fifo", "lhd", "lin-K+K+", "extraK-trees", "extraKF-nn", "extraK-nn", "extra-trees", "extra-nn", "belady")]
            out.append([sc, g] + ["--" if c is None else f"{c:.3f}" for c in cells])
    hdr = ["scope", "split", "LRU", "ARC", "S3F", "LHD", "linear K", "tree K", "NN K", "NN K$^{\\dagger}$", "tree FK", "NN FK", "Belady"]
    write("model_comparison.tex", tab(out, hdr, "ll" + "r" * 11))
    # forest plot: ratio vs the matching linear model with 95% CI
    pts = []
    for r in rows:
        if "/" in r["system"] and "CI95" in str(r["cells"]):
            lo, hi = [float(x) for x in r["cells"].split()[1].split("-")]
            pts.append((r["scope"], r["group"], r["system"].split(":")[0], float(r["geo_ratio_vs_clock"]), lo, hi))
    fig, ax = plt.subplots(figsize=(7.6, 6.4))
    classes = ["extraS-trees", "extraK-trees", "extraKF-nn", "extraK-nn", "extra-trees", "extra-nn"]
    colors = dict(zip(classes, ["#1b9e77", "#1c5cab", "#7570b3", "#d95f02", "#8da0cb", "#fc8d62"]))
    legend = {"extraS-trees": "GBDT, 4-16 trees, kernel inputs", "extraK-trees": "best tree model, kernel inputs",
              "extraKF-nn": "NN, kernel inputs only (deployable)", "extraK-nn": "best NN, kernel inputs + oracle history",
              "extra-trees": "best tree model, oracle inputs", "extra-nn": "best NN, oracle inputs"}
    labels = []
    for sc in scopes:
        for g in ("test", "held-out", "pat", "kv-T", "app", "real"):
            sel = [p for p in pts if p[0] == sc and p[1] == g]
            if not sel:
                continue
            y = len(labels)
            labels.append(f"{sc} / {g}")
            for i, p in enumerate(sorted(sel, key=lambda p: classes.index(p[2]) if p[2] in classes else 9)):
                if p[2] not in colors:
                    continue
                ax.plot([p[4], p[5]], [y + i * 0.13 - 0.2] * 2, color=colors[p[2]], lw=1.2)
                ax.plot(p[3], y + i * 0.13 - 0.2, "o", color=colors[p[2]], ms=3.5)
    ax.axvline(1.0, color="k", lw=.8)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("faults relative to the best linear scorer (<1: better)")
    for c in classes:
        ax.plot([], [], "o-", color=colors[c], label=legend[c])
    ax.legend(fontsize=7, loc="lower right")
    ax.set_xlim(0.8, 1.6)
    fig.tight_layout()
    fig.savefig(OUT / "figs" / "model_comparison.pdf")
    plt.close(fig)


# ---- transfer ---------------------------------------------------------------------
def transfer():
    rows = []
    for f in ("transfer.csv", "transfer_real.csv", "transfer_app.csv"):
        rows += list(csv.DictReader(open(R / f)))
    g = {(r["model"], r["stem"], r["fraction"]): int(r["faults"]) for r in rows}
    stems = sorted({r["stem"] for r in rows})
    groups = defaultdict(list)
    for s in stems:
        key = s.rsplit("-s", 1)[0] if s.startswith(("pat", "app")) else ("kv-T" if s.startswith("kv-T") else s.split("-s")[0])
        groups[key].append(s)
    pols = ["lru", "arc", "s3fifo", "lhd", "belady", "linear:global|K+K+", "linear:global|F+K", "linear:kv|K+K+"]
    names = ["LRU", "ARC", "S3-FIFO", "LHD", "Belady", "linear K+", "linear F+K", "linear kv K+"]
    body = []
    for k, sts in groups.items():
        line = [k]
        for p in pols:
            v = [min(g[(p, s, f)], 3 * g[("clock", s, f)]) / g[("clock", s, f)] for s in sts for f in FR if (p, s, f) in g]
            line.append(f"{gm(v):.3f}" if v else "--")
        body.append(line)
    write("transfer.tex", tab(body, ["stream"] + names))
    # figure: the main policies per group
    show = [("lru", "LRU"), ("arc", "ARC"), ("lhd", "LHD"), ("linear:global|K+K+", "linear (K+)"), ("belady", "Belady")]
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    ks = list(groups)
    w = 0.16
    for i, (p, lab) in enumerate(show):
        ys = []
        for k in ks:
            v = [min(g[(p, s, f)], 3 * g[("clock", s, f)]) / g[("clock", s, f)] for s in groups[k] for f in FR if (p, s, f) in g]
            ys.append(gm(v) if v else np.nan)
        ax.bar(np.arange(len(ks)) + i * w, ys, w, label=lab)
    ax.axhline(1, color="k", lw=.7)
    ax.set_xticks(np.arange(len(ks)) + 2 * w)
    ax.set_xticklabels(ks, rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("faults / Clock")
    ax.legend(fontsize=7, ncol=5)
    fig.tight_layout()
    fig.savefig(OUT / "figs" / "transfer.pdf")
    plt.close(fig)


# ---- kernel -----------------------------------------------------------------------
def kernel():
    p = R / "kernel_vs_sim.csv"
    if not p.exists():
        return
    rows = [r for r in csv.DictReader(open(p)) if r["workload"] in ("lzw", "pat", "app") or r["workload"] == "kv" and "kv-T" in r["stem"]]
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        key = r["workload"] if not r["stem"].startswith("kv-T") else "kv-T"
        by[key][(r["policy"], r["model"])].append(r)
    body = []
    for k, d in by.items():
        for (pol, model), rs in sorted(d.items()):
            ratio = gm([float(r["kernel_over_sim"]) for r in rs])
            body.append([k, pol + (":" + model if model else ""), len(rs), f"{ratio:.3f}"])
    write("kernelsim.tex", tab(body, ["workload", "policy", "runs", "kernel / simulator faults"], "llrr"))


def kernel2():
    rows = [r for r in csv.DictReader(open(R / "kernel_eval.csv")) if r["status"] == "ok"
            and r["stem"].startswith(("lzw", "kv-T", "pat", "app"))]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    clock = {r["stem"]: f(r) for r in rows if r["policy"] == "clock"}
    grp = lambda s: "kv-T" if s.startswith("kv-T") else s.split("-")[0]
    by, tk = defaultdict(list), defaultdict(list)
    for r in rows:
        k = (grp(r["stem"]), r["policy"] + (":" + r["model"] if r["model"] else ""))
        by[k].append(f(r) / clock[r["stem"]])
        tk[k].append(int(r["select_ticks"]) / max(int(r["evictions"]), 1))
    order = ["fifo", "clock", "aging", "lfu", "ml:global", "ml:global@32", "ml:global@16", "ml:global-k", "ml:kv", "ml:kv@32", "ml:kv@16",
             "ml:lzw", "ml:lzw@64", "ml:lzw@32", "ml:lzw@16"]
    body = []
    for g in ("lzw", "kv-T", "pat", "app"):
        for p in order:
            if (g, p) in by:
                body.append([g, p.replace("ml:", "ml "), len(by[(g, p)]), f"{gm(by[(g, p)]):.3f}", f"{np.mean(tk[(g, p)]):.0f}"])
    write("kernelruns.tex", tab(body, ["workload", "policy", "runs", "faults / Clock", "select ticks / eviction"], "llrrr"))
    # figure: faults/Clock and cost, ML variants
    fig, axs = plt.subplots(1, 2, figsize=(8.4, 3.2))
    for ax, g, ms in ((axs[0], "lzw", ["clock", "aging", "ml:global", "ml:lzw", "ml:lzw@32", "ml:lzw@16"]),
                      (axs[1], "kv-T", ["clock", "aging", "ml:global", "ml:global@32", "ml:kv", "ml:kv@16"])):
        ys = [gm(by[(g, m)]) for m in ms]
        cs = [np.mean(tk[(g, m)]) for m in ms]
        ax.bar(range(len(ms)), ys, color=["#999", "#999", "#1c5cab", "#1c5cab", "#7fa6d6", "#7fa6d6"])
        for i, (y, c) in enumerate(zip(ys, cs)):
            ax.text(i, y + 0.01, f"{c:.0f}", ha="center", fontsize=6.5)
        ax.set_xticks(range(len(ms)))
        ax.set_xticklabels([m.replace("ml:", "") for m in ms], rotation=40, ha="right", fontsize=7)
        ax.set_title(f"{g} (in xv6; label = select ticks per eviction)", fontsize=8)
        ax.axhline(1, color="k", lw=.7)
        ax.set_ylim(0.6, max(ys) + 0.1)
    axs[0].set_ylabel("faults / Clock")
    fig.tight_layout()
    fig.savefig(OUT / "figs" / "kernel.pdf")
    plt.close(fig)


def noise():
    p = R / "noise_floor.csv"
    if not p.exists():
        return
    rows = list(csv.DictReader(open(p)))
    clock = {(r["stem"], r["fraction"]): int(r["faults"]) for r in csv.DictReader(open(R / "classical.csv")) if r["policy"] == "clock"}
    body = []
    for g in sorted({r["group"] for r in rows}):
        vals = []
        for salt in sorted({r["salt"] for r in rows}):
            v = [min(int(r["faults"]), 3 * clock[(r["stem"], r["fraction"])]) / clock[(r["stem"], r["fraction"])]
                 for r in rows if r["salt"] == salt and r["group"] == g]
            vals.append(gm(v))
        body.append([g, " / ".join(f"{x:.4f}" for x in vals), f"{(max(vals) - min(vals)):.4f}"])
    write("noise.tex", tab(body, ["feature group", "faults/Clock per data seed", "range"], "lll"))


def five_models():
    """In-kernel results of the five extra models next to the linear scorers, and their measured cost."""
    p = R / "kernel_eval_w16.csv"
    if not p.exists():
        return
    rows = [r for r in csv.DictReader(open(p)) if r["status"] == "ok"]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    clock = {r["stem"]: f(r) for r in rows if r["policy"] == "clock"}
    grp = lambda r: ("kv-T" if r["stem"].startswith("kv-T") else "kv " + r["split"]) if r["stem"].startswith("kv-") \
        else "graph " + r["split"]
    by = defaultdict(list)
    for r in rows:
        if r["stem"] in clock:
            by[(grp(r), r["policy"] + (":" + r["model"] if r["model"] else ""))].append(f(r) / clock[r["stem"]])
    cols = ["kv test", "kv heldout", "kv-T", "graph test", "graph heldout"]
    pols = [("fifo", "FIFO"), ("aging", "Aging"), ("ml:global", "linear, global"), ("ml:kv", "linear, kv"), ("ml:graph", "linear, graph"),
            ("ml:cnn-kv", "CNN on aging bits (kv)"), ("ml:mlp-kv", "deeper MLP (kv)"), ("ml:trees-kv", "boosted trees (kv)"),
            ("ml:attention-graph", "set-attention (graph)"), ("ml:ranktrees-graph", "ranking trees (graph)")]
    body = []
    for key, name in pols:
        body.append([name] + [f"{gm(by[(c, key)]):.3f}" if (c, key) in by else "--" for c in cols])
    write("fivemodels.tex", tab(body, ["policy"] + cols))
    t = list(csv.DictReader(open(R / "timing.csv")))
    first = {}
    for r in t:
        first.setdefault((r["policy"], r["model"]), r)
    names = {("fifo", ""): "FIFO (floor)", ("clock", ""): "Clock", ("aging", ""): "Aging", ("lfu", ""): "LFU",
             ("ml", "global"): "linear, global", ("ml", "kv"): "linear, kv", ("ml", "kv@32"): "linear, kv, 32 sampled",
             ("ml", "kv@16"): "linear, kv, 16 sampled", ("ml", "cnn-kv"): "CNN on aging bits", ("ml", "mlp-kv"): "deeper MLP",
             ("ml", "trees-kv"): "boosted trees", ("ml", "attention-graph"): "set-attention", ("ml", "ranktrees-graph"): "ranking trees"}
    lin = int(float(first[("ml", "kv")]["select_instructions_per_eviction"]))
    body = []
    for k, name in names.items():
        r = first[k]
        ins = int(float(r["select_instructions_per_eviction"]))
        body.append([name, f"{ins:,}", f"{ins / lin:.2f}", f"{int(float(r['path_ticks_per_eviction']) * 100):,}"])
    write("timing.tex", tab(body, ["policy", "instructions to choose", "x linear (kv)", "instructions, whole eviction"]))
    # figure: cost against faults on the kv streams
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    pts = [("clock", "Clock"), ("aging", "Aging"), ("ml:global", "linear, global"), ("ml:kv", "linear, kv"),
           ("ml:cnn-kv", "CNN"), ("ml:mlp-kv", "MLP"), ("ml:trees-kv", "trees")]
    tk = {("clock", ""): "clock", ("aging", ""): "aging", ("ml", "global"): "ml:global", ("ml", "kv"): "ml:kv", ("ml", "cnn-kv"): "ml:cnn-kv",
          ("ml", "mlp-kv"): "ml:mlp-kv", ("ml", "trees-kv"): "ml:trees-kv"}
    inv = {v: k for k, v in tk.items()}
    for key, name in pts:
        x = float(first[inv[key]]["select_instructions_per_eviction"])
        y = gm(by[("kv test", key)] + by[("kv heldout", key)])
        ax.scatter(x, y)
        ax.annotate(name, (x, y), fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax.set_xscale("log")
    ax.set_xlabel("instructions to choose one victim (log scale)")
    ax.set_ylabel("faults / Clock, kv streams in xv6")
    fig.tight_layout()
    fig.savefig(OUT / "figs" / "cost_vs_faults.pdf")
    plt.close(fig)


def full_tests():
    """Every policy on every workload in xv6, for each memory size run: faults relative to Clock (geometric mean over
    the test and held-out streams of the workload)."""
    p = R / "kernel_eval_w16.csv"
    if not p.exists():
        return
    rows = [r for r in csv.DictReader(open(p)) if r["status"] == "ok"]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    clock = {(r["stem"], r["fraction"]): f(r) for r in rows if r["policy"] == "clock"}
    grp = lambda r: "kv-T" if r["stem"].startswith("kv-T") else r["stem"].split("-")[0]
    by = defaultdict(list)
    for r in rows:
        if (r["stem"], r["fraction"]) in clock:
            by[(r["fraction"], grp(r), r["policy"] + (":" + r["model"] if r["model"] else ""))].append(f(r) / clock[(r["stem"], r["fraction"])])
    cols = ["btree", "graph", "kv", "kv-T", "lzw", "matmul", "sort", "pat", "app"]
    pols = [("fifo", "FIFO"), ("aging", "Aging"), ("lfu", "LFU"), ("ml:global", "linear, global"), ("ml:own", "linear, own workload"),
            ("ml:cnn-kv", "CNN on aging bits"), ("ml:mlp-kv", "deeper MLP"), ("ml:trees-kv", "boosted trees"),
            ("ml:attention-graph", "set-attention"), ("ml:ranktrees-graph", "ranking trees")]
    for frac in sorted({r["fraction"] for r in rows}):
        body = []
        for key, name in pols:
            line = [name]
            for c in cols:
                k = (frac, c, key if key != "ml:own" else "ml:" + ("kv" if c == "kv-T" else c))
                line.append(f"{gm(by[k]):.2f}" if k in by else "--")
            body.append(line)
        write(f"full_{frac.replace('.', '')}.tex", tab(body, ["policy"] + cols))


if __name__ == "__main__":
    dataset()
    extra()
    transfer()
    kernel()
    kernel2()
    five_models()
    full_tests()
    noise()
    (OUT / "tables" / "numbers.tex").write_text("".join(f"\\expandafter\\def\\csname v@{k}\\endcsname{{{v}}}\n" for k, v in NUM.items()))
    print("written", OUT)
