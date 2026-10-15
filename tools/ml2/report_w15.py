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
    # LeCaR (a learned-cache baseline from the literature): as published (needs every access) and in the form a kernel can run
    lec = []
    for sc in scopes:
        for g in ("test", "held-out"):
            d = val.get((sc, g))
            if not d or "lecar" not in d:
                continue
            cells = [d.get(k) for k in ("lru", "arc", "lhd", "lecar_exact", "lecar")] + [pick(d, "lin-K+K+")]
            lec.append([sc, g] + ["--" if c is None else f"{c:.3f}" for c in cells])
    write("lecar.tex", tab(lec, ["scope", "split", "LRU", "ARC", "LHD", "LeCaR, as published", "LeCaR, kernel form", "linear K"], "ll" + "r" * 6))
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
    rows = [r for r in csv.DictReader(open(R / "kernel_eval_all.csv")) if r["status"] == "ok" and r["fraction"] == "0.1"
            and r["stem"].startswith(("lzw", "kv-T", "pat", "app"))]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    clock = {r["stem"]: f(r) for r in rows if r["policy"] == "clock"}
    grp = lambda s: "kv-T" if s.startswith("kv-T") else s.split("-")[0]
    by, tk = defaultdict(list), defaultdict(list)
    sampled = defaultdict(set)         # streams on which the sampled variants were run: every row of a group uses just these
    for r in rows:
        if r["policy"] == "ml" and r["model"].endswith("@32"):
            sampled[grp(r["stem"])].add(r["stem"])
    for r in rows:
        if sampled.get(grp(r["stem"])) and r["stem"] not in sampled[grp(r["stem"])]:
            continue
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
        ms = [m for m in ms if by.get((g, m))]      # a bar is skipped while its runs are missing
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
    p = R / "kernel_eval_all.csv"
    if not p.exists():
        return
    rows = [r for r in csv.DictReader(open(p)) if r["status"] == "ok" and r["fraction"] == "0.1"]
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
    p = R / "kernel_eval_all.csv"
    if not p.exists():
        return
    reps = set((R / "stage2_streams.txt").read_text().strip().split(","))     # the same 42 streams at every memory size
    rows = [r for r in csv.DictReader(open(p)) if r["status"] == "ok" and r["stem"] in reps]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    clock = {(r["stem"], r["fraction"]): f(r) for r in rows if r["policy"] == "clock"}
    grp = lambda r: "kv-T" if r["stem"].startswith("kv-T") else r["stem"].split("-")[0]
    # one set of streams per column and memory size: the streams the five extra models were run on, or every stream when they
    # were not run for that workload; every row of the column then averages over the same streams
    have = defaultdict(set)
    for r in rows:
        if r["policy"] == "ml" and r["model"] == "cnn-kv":
            have[(r["fraction"], grp(r))].add(r["stem"])
    by = defaultdict(list)
    for r in rows:
        if (r["stem"], r["fraction"]) in clock:
            sel = have.get((r["fraction"], grp(r)))
            if sel and r["stem"] not in sel:
                continue
            by[(r["fraction"], grp(r), r["policy"] + (":" + r["model"] if r["model"] else ""))].append(f(r) / clock[(r["stem"], r["fraction"])])
    cols = ["btree", "graph", "kv", "kv-T", "lzw", "matmul", "sort", "heap", "join", "spmv", "chase", "bloom"]
    pols = [("fifo", "FIFO"), ("aging", "Aging"), ("lfu", "LFU"), ("ml:global", "linear, global"), ("ml:own", "linear, own workload"),
            ("ml:cnn-kv", "CNN on aging bits"), ("ml:mlp-kv", "deeper MLP"), ("ml:trees-kv", "boosted trees"),
            ("ml:attention-graph", "set-attention"), ("ml:ranktrees-graph", "ranking trees")]
    for frac in sorted({r["fraction"] for r in rows}):
        body = []
        for key, name in pols:
            line = [name]
            for c in cols:
                k = (frac, c, key if key != "ml:own" else "ml:" + ("kv" if c == "kv-T" else c))
                if key == "ml:own" and k not in by:
                    k = (frac, c, "ml:global")        # workloads without a model of their own run the global one
                line.append(f"{gm(by[k]):.2f}" if k in by else "--")
            body.append(line)
        write(f"full_{frac.replace('.', '')}.tex", tab(body, ["policy"] + cols))


def kernel_main(metric="faults"):
    """Main kernel tables (kernel results first): faults relative to Clock per workload, at each memory size.
    kmain_A: classical policies and the global linear model on every stream that has all of them (the streams of a workload are averaged
    with a geometric mean). kmain_B: the five models trained on all workloads against the global linear model and the best classical
    policies, on the ten streams they were run on."""
    p = R / "kernel_eval_all.csv"
    if not p.exists():
        return
    rows = [r for r in csv.DictReader(open(p)) if r["status"] == "ok"]
    f = (lambda r: int(r["swap_faults"]) + int(r["zero_faults"] or 0)) if metric == "faults" else (lambda r: max(int(r["page_writes"] or 0), 1))
    grp = lambda s: "kv-T" if s.startswith("kv-T") else s.split("-")[0]
    d = defaultdict(dict)
    for r in rows:
        d[(r["fraction"], r["policy"] + (":" + r["model"] if r["model"] else ""))][r["stem"]] = f(r)
    cols = ["btree", "graph", "kv", "kv-T", "lzw", "matmul", "sort", "heap", "join", "spmv", "chase", "bloom", "pat", "app"]
    A = [("fifo", "FIFO"), ("aging", "Aging"), ("lfu", "LFU"), ("s3fifo", "S3-FIFO"), ("lecar", "LeCaR"), ("lhd", "LHD"), ("arck", "ARC"), ("ml:global", "linear, global"), ("ml:global@32", "linear, 32 sampled")]
    B = [("ml:global", "linear, global"), ("arck", "ARC"), ("lhd", "LHD"), ("ml:cnn-all", "CNN"), ("ml:mlp-all", "deeper MLP"),
         ("ml:attention-all", "set-attention"), ("ml:trees-all", "boosted trees"), ("ml:ranktrees-all", "ranking trees")]
    for tag, pols in (("A", A), ("B", B)):
        for fr in ("0.05", "0.1", "0.2"):
            clock = d.get((fr, "clock"), {})
            have = [set(d.get((fr, k), {})) & set(clock) for k, _ in pols]
            common = set.intersection(*have) if all(have) else set()
            if not common:
                continue
            body = []
            for key, name in pols:
                line = [name]
                allv = []
                for c in cols:
                    v = [d[(fr, key)][s] / clock[s] for s in common if grp(s) == c]
                    line.append(f"{gm(v):.2f}" if v else "--")
                    allv += [gm(v)] if v else []
                line.append(f"{gm(allv):.2f}")
                body.append(line)
            write(f"kmain_{tag if metric == 'faults' else 'W' + tag}_{fr.replace('.', '')}.tex", tab(body, ["policy"] + cols + ["mean"]))


def cost_tables():
    """cost against the number of candidates, break-even fault cost, starting-state sensitivity, populated start"""
    cg = R / "cost_grid.csv"
    if cg.exists():
        rows = list(csv.DictReader(open(cg)))
        d = defaultdict(dict)
        for r in rows:
            d[r["policy"] + (":" + r["model"] if r["model"] else "")][int(r["frames"])] = float(r["select_instructions_per_eviction"])
        names = [("fifo", "FIFO"), ("clock", "Clock"), ("aging", "Aging"), ("lfu", "LFU"), ("ml:global", "linear, full scan"),
                 ("ml:global@32", "linear, 32 sampled"), ("ml:global@16", "linear, 16 sampled"), ("ml:trees-kv", "boosted trees"),
                 ("ml:ranktrees-graph", "ranking trees"), ("ml:attention-graph", "set-attention"), ("ml:cnn-kv", "CNN on aging bits"),
                 ("ml:mlp-kv", "deeper MLP"), ("ml:cnn-kv@32", "CNN, 32 sampled"), ("ml:mlp-kv@32", "MLP, 32 sampled")]
        sizes = sorted({n for v in d.values() for n in v})
        body = [[nm] + [f"{int(d[k][n]):,}" if n in d[k] else "--" for n in sizes] for k, nm in names if k in d]
        write("costgrid.tex", tab(body, ["policy"] + [f"{n} candidates" for n in sizes]))
    cb = R / "cost_benefit.csv"
    if cb.exists():
        rows = list(csv.DictReader(open(cb)))
        pick = {"ml:own": "linear, own workload", "ml:cnn-kv": "CNN", "ml:mlp-kv": "MLP", "ml:trees-kv": "boosted trees"}
        body = []
        extra = {"lzw": {"ml:lzw@32": "linear, own, 32 sampled", "ml:lzw@16": "linear, own, 16 sampled"},
                 "kv-T": {"ml:kv@32": "linear, own, 32 sampled", "ml:kv@16": "linear, own, 16 sampled"}}
        for wl in ("btree", "graph", "kv", "kv-T", "lzw", "heap", "join", "sort"):
            for k, nm in {**pick, **extra.get(wl, {})}.items():
                r = next((x for x in rows if x["workload"] == wl and x["policy"] == k), None)
                if r:
                    be = r["break_even_us"]
                    be = be if be == "never" else (f"{float(be):,.0f}" if float(be) < 1e6 else ">1,000,000")
                    body.append([wl, nm, r["faults_over_clock"], f"{int(r['choose_instructions']):,}", be, r["time_vs_clock_ssd"], r["time_vs_clock_hdd"]])
        write("breakeven.tex", tab(body, ["workload", "policy", "faults / Clock", "instructions to choose", "break-even (\\textmu s per fault)",
                                          "time / Clock, SSD", "time / Clock, disk"], "llrrrrr"))
    ss = R / "state_sensitivity.csv"
    if ss.exists():
        rows = list(csv.DictReader(open(ss)))
        dd = defaultdict(dict)
        for r in rows:
            dd[(r["stem"], r["policy"])][r["start"]] = int(r["faults"])
        sp = defaultdict(list)
        for (stem, pol), v in dd.items():
            if len(v) == 5:
                sp[pol].append(max(v.values()) / min(v.values()))
        order = ["clock", "global", "kv", "graph", "btree", "lzw", "sort", "matmul", "cnn-kv", "mlp-kv", "trees-kv", "ranktrees-graph", "attention-graph"]
        body = [[p, len(sp[p]), f"{np.median(sp[p]):.3f}", f"{max(sp[p]):.2f}"] for p in order if p in sp]
        write("statesens.tex", tab(body, ["policy", "streams", "median spread", "largest spread"], "lrrr"))
    wc = R / "kernel_vs_sim_w16warm.csv"
    wn = R / "kernel_vs_sim_w16.csv"
    if wc.exists() and wn.exists():
        def load(f):
            by = defaultdict(list)
            for r in csv.DictReader(open(f)):
                g = "kv-T" if r["stem"].startswith("kv-T") else r["stem"].split("-")[0]
                by[(g, r["policy"] + (":" + r["model"] if r["model"] else ""))].append(float(r["kernel_over_sim"]))
            return by
        a, b = load(wn), load(wc)
        body = []
        for key, nm in (("clock", "Clock"), ("ml:global", "linear, global"), ("ml:kv", "linear, kv"), ("ml:cnn-kv", "CNN"), ("ml:mlp-kv", "MLP"), ("ml:trees-kv", "boosted trees")):
            for g in ("kv", "kv-T"):
                if (g, key) in a and (g, key) in b:
                    body.append([g, nm, f"{gm(a[(g, key)]):.3f}", f"{gm(b[(g, key)]):.3f}"])
        write("warmstart.tex", tab(body, ["streams", "policy", "kernel / simulator, empty start", "kernel / simulator, populated start"], "llrr"))


def ci_tables():
    """in-kernel results with 95% intervals across the streams of each workload (10% memory)"""
    c = R / "kernel_ci.csv"
    if not c.exists():
        return
    rows = {(r["workload"], r["policy"]): r for r in csv.DictReader(open(c))}
    fmt = lambda r: f"{r['faults_over_clock']} [{r['ci95_low']}, {r['ci95_high']}]" if r else "--"
    cols = [("ml:own", "linear, own workload"), ("ml:global", "linear, global"), ("ml:cnn-kv", "CNN"), ("ml:mlp-kv", "MLP"), ("ml:trees-kv", "boosted trees")]
    body = []
    for wl in ("btree", "graph", "kv", "kv-T", "lzw", "sort", "heap", "join", "pat", "app"):
        own = "ml:" + ("kv" if wl == "kv-T" else wl)
        n = next((r["streams"] for (w, p), r in rows.items() if w == wl), "")
        line = [wl, n]
        for key, _ in cols:
            k = own if key == "ml:own" else key
            line.append(fmt(rows.get((wl, k))) if (key != "ml:own" or (wl, own) in rows) else "--")
        body.append(line)
    write("kernelci.tex", tab(body, ["workload", "streams"] + [n for _, n in cols], "lr" + "r" * len(cols)))
    pr = R / "kernel_ci_paired.csv"
    if pr.exists():
        sel = {("kv", "ml:cnn-kv"), ("kv", "ml:mlp-kv"), ("kv", "ml:trees-kv"), ("kv-T", "ml:cnn-kv"), ("kv-T", "ml:mlp-kv"), ("kv-T", "ml:trees-kv"),
               ("graph", "ml:attention-graph"), ("graph", "ml:ranktrees-graph"), ("btree", "ml:cnn-kv"), ("btree", "ml:mlp-kv"), ("lzw", "ml:cnn-kv"),
               ("lzw", "ml:mlp-kv"), ("sort", "ml:cnn-kv"), ("sort", "ml:mlp-kv")}
        names = {"ml:cnn-kv": "CNN", "ml:mlp-kv": "MLP", "ml:trees-kv": "boosted trees", "ml:attention-graph": "set-attention", "ml:ranktrees-graph": "ranking trees"}
        body = []
        for r in csv.DictReader(open(pr)):
            if (r["workload"], r["model"]) in sel:
                lo, hi = float(r["ci95_low"]), float(r["ci95_high"])
                body.append([r["workload"], names[r["model"]], r["streams"], f"{r['faults_ratio']} [{r['ci95_low']}, {r['ci95_high']}]",
                             "fewer faults" if hi < 1 else ("more faults" if lo > 1 else "no difference")])
        write("paired.tex", tab(body, ["workload", "model", "streams", "faults vs linear [95\\% interval]", "result"], "llrrl"))


def guard_tables():
    """safety-guard prototype (simulator): learned policy alone against guarded versions, on the streams the settings were tuned on and on others"""
    out = {}
    for tag, f, keep in (("tuned", "guard.csv", ("learned", "guard W=n/200 K=20 margin=0.0", "guard W=n/100 K=10 margin=0.0")),
                         ("heldout", "guard_heldout.csv", ("learned", "guard W=n/200 K=20 margin=0.0", "guard W=n/100 K=10 margin=0.0"))):
        p = R / f
        if not p.exists():
            return
        cells = defaultdict(dict)
        for r in csv.DictReader(open(p)):
            cells[(r["stem"], r["fraction"])][r["policy"]] = int(r["faults"])
        n = max(len(v) for v in cells.values())
        done = [k for k, v in cells.items() if len(v) == n]
        lose = [k for k in done if cells[k]["learned"] / cells[k]["clock"] > 1.02]
        win = [k for k in done if cells[k]["learned"] / cells[k]["clock"] < 0.95]
        rat = lambda pol, ks: [cells[k][pol] / cells[k]["clock"] for k in ks]
        body = []
        for pol in keep:
            name = "learned policy alone" if pol == "learned" else "guarded, window n/%s, retest every %s windows" % (pol.split("n/")[1].split(" ")[0], pol.split("K=")[1].split(" ")[0])
            body.append([name, f"{gm(rat(pol, done)):.3f}", f"{gm(rat(pol, lose)):.3f}", f"{gm(rat(pol, win)):.3f}", f"{max(rat(pol, done)):.3f}"])
        write(f"guard_{tag}.tex", tab(body, ["policy", f"all {len(done)} cells", f"{len(lose)} cells where learned loses", f"{len(win)} cells where it wins", "worst cell"], "lrrrr"))


def trained_all_table():
    p = R / "trained_on_all.csv"
    if not p.exists():
        return
    cells = defaultdict(dict)
    for r in csv.DictReader(open(p)):
        cells[(r["stem"], r["fraction"])][r["policy"]] = int(r["faults"])
    done = [k for k, v in cells.items() if len(v) >= 12]
    rat = lambda pol: [max(cells[k][pol], 1) / cells[k]["clock"] for k in done]
    body = [["linear, global", "--", f"{gm(rat('linear, global')):.3f}"]]
    for kind in ("CNN on aging bits", "deeper MLP", "boosted trees", "set-attention", "ranking trees"):
        body.append([kind, f"{gm(rat(kind + ' | one workload')):.3f}", f"{gm(rat(kind + ' | all workloads')):.3f}"])
    write("trainedall.tex", tab(body, ["model", "trained on one workload", "trained on all workloads"], "lrr"))
    NUM["trainedall_cells"] = len(done)


def kernel_all_table():
    """in the kernel at 10%: the five kinds trained on one workload and on all workloads, against the global linear model, on the ten streams"""
    p = R / "kernel_eval_all.csv"
    if not p.exists():
        return
    rows = [r for r in csv.DictReader(open(p)) if r["status"] == "ok" and r["fraction"] == "0.1"]
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"])
    clock = {r["stem"]: f(r) for r in rows if r["policy"] == "clock"}
    d = defaultdict(dict)
    for r in rows:
        if r["policy"] == "ml":
            d[r["model"]][r["stem"]] = f(r)
    streams = ["btree-mixed-s5", "kv-A-s5", "kv-T17-s1", "sort-n40000-s3", "matmul-blocked128-s1", "heap-small-s1", "join-zipf-s1", "spmv-band-s1",
               "chase-tree-s1", "bloom-k7-s1"]
    pairs = [("CNN on aging bits", "cnn-kv", "cnn-all"), ("deeper MLP", "mlp-kv", "mlp-all"), ("boosted trees", "trees-kv", "trees-all"),
             ("set-attention", "attention-graph", "attention-all"), ("ranking trees", "ranktrees-graph", "ranktrees-all")]
    need = [sm for sm in streams if all(sm in d[m] for _, a, b in pairs for m in (a, b)) and sm in d["global"] and sm in clock]
    if len(need) < 3:
        return
    rng = np.random.default_rng(1)
    lin = np.array([math.log(d["global"][sm] / clock[sm]) for sm in need])

    def ci(x):
        bs = np.sort([math.exp(x[rng.integers(0, len(x), len(x))].mean()) for _ in range(10000)])
        return f"{math.exp(x.mean()):.3f} [{bs[250]:.3f}, {bs[9749]:.3f}]"
    body = [["linear, global", "--", f"{gm([d['global'][sm] / clock[sm] for sm in need]):.3f}", "--"]]
    for nm, a, b in pairs:
        one = np.array([math.log(d[a][sm] / clock[sm]) for sm in need])
        al = np.array([math.log(d[b][sm] / clock[sm]) for sm in need])
        body.append([nm, f"{math.exp(one.mean()):.3f}", f"{math.exp(al.mean()):.3f}", ci(al - lin)])
    write("kernelall.tex", tab(body, ["model", "trained on one workload", "trained on all workloads", "all-workloads vs global linear [95\\% interval]"], "lrrr"))
    NUM["kernelall_streams"] = len(need)


if __name__ == "__main__":
    dataset()
    extra()
    transfer()
    kernel()
    kernel2()
    five_models()
    full_tests()
    kernel_main()
    kernel_main("writes")
    cost_tables()
    ci_tables()
    guard_tables()
    trained_all_table()
    kernel_all_table()
    noise()
    (OUT / "tables" / "numbers.tex").write_text("".join(f"\\expandafter\\def\\csname v@{k}\\endcsname{{{v}}}\n" for k, v in NUM.items()))
    print("written", OUT)
