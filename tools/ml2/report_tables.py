#!/usr/bin/env python3
"""Results tables for report/week_14_update_report.pdf, from the CSVs in
report/results2 (the report \\input's each one).

    python3 report_tables.py   -> report/week_14_update/tables/*.tex

Only the tabular itself is generated; captions stay in week_14_update_report.tex.
Values below 1 relative to Clock (better than Clock) are highlighted in the
per-workload columns.
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "report" / "results2"
OUT = ROOT / "report" / "week_14_update" / "tables"
OUT.mkdir(parents=True, exist_ok=True)
WL = ["btree", "graph", "kv", "matmul", "sort"]
SPLITS = [("test", "test"), ("heldout", "held-out")]
KK = "ref+aging+sfreq+idle+age+dirty+refaults+rdist"


def read(name):
    return list(csv.DictReader(open(R / name)))


def r3(v, cens=0):
    return (r"$\geq$" if cens else "") + f"{v:.3f}"


def best(s, v, highlight=True):
    return rf"\best{{{s}}}" if highlight and v < 1 else s


def pct(v):
    x = (v - 1) * 100
    return ("$-$" if x < 0 else "$+$") + f"{abs(x):.1f}\\%"


def tabular(cols, header, rows, mid=None):
    out = [rf"\begin{{tabular}}{{{cols}}}", r"\toprule"] + header + [r"\midrule"]
    for i, r in enumerate(rows):
        if mid and i in mid:
            out.append(r"\midrule")
        out.append(" & ".join(r) + r" \\")
    out += [r"\bottomrule", r"\end{tabular}", ""]
    return "\n".join(out)


def write(name, text):
    (OUT / f"{name}.tex").write_text(text)
    print("wrote", name)


kern = {(r["policy"], r["workload"], r["split"]): r for r in read("summary_kernel.csv")}
fin = {(r["scope"], r["group"], r["workload"], r["split"], r["fraction"]): r
       for r in read("summary_final.csv")}
cl = {(r["policy"], r["workload"], r["split"], r["fraction"]): float(r["geo_ratio_vs_clock"])
      for r in read("summary_classical.csv")}
nn = {(r["model"], r["workload"], r["split"]): (float(r["geo_ratio_vs_clock"]), int(r["censored"]))
      for r in read("summary_nn.csv")}
ex = {(r["kind"], r["scope"], r["features"], r["workload"], r["split"]):
      (float(r["geo_ratio_vs_clock"]), int(r["censored"])) for r in read("summary_extras.csv")}


def kv(policy, wl, split, col):
    r = kern.get((policy, wl, split))
    return float(r[col]) if r else None


# ---- results at a glance (Summary) -------------------------------------------
rows = []
for wl in WL:
    f = [kv("ml/workload", wl, s, "geo_faults_vs_clock") for s, _ in SPLITS]
    w = [kv("ml/workload", wl, s, "geo_writes_vs_clock") for s, _ in SPLITS]
    tsplit = "test" if kern.get(("ml/workload", wl, "test")) else "heldout"
    ml = kv("ml/workload", wl, tsplit, "select_ticks_per_eviction") / 10
    ck = kv("clock", wl, tsplit, "select_ticks_per_eviction") / 10
    rows.append([wl,
                 " / ".join(best(pct(v), v) if v is not None else "--" for v in f),
                 " / ".join(best(pct(v), v) if v is not None else "--" for v in w),
                 rf"{ml:.1f}\,\textmu s vs {ck:.1f}\,\textmu s"])
write("glance", tabular("@{}lccc@{}", [
    r"& \textbf{Page faults vs Clock} & \textbf{Disk writes vs Clock} & \textbf{Decision time per eviction} \\",
    r"\textbf{Benchmark} & test / held-out & test / held-out & ML vs Clock \\"], rows))

# ---- simulated headline: selected linear K+K+ model -------------------------
rows = []
for wl in WL:
    pw = [fin.get((wl, "K+K+", wl, s, "all")) for s, _ in SPLITS]
    gl = [fin.get(("global", "K+K+", wl, s, "all")) for s, _ in SPLITS]
    bsplit = "test" if pw[0] else "heldout"
    b = cl.get(("belady", wl, bsplit, "all"))
    rows.append([wl] +
                [best(f"{float(r['geo_ratio_vs_clock']):.3f}", float(r["geo_ratio_vs_clock"]))
                 if r else "--" for r in pw] +
                [f"{float(r['geo_ratio_vs_clock']):.3f}" if r else "--" for r in gl] +
                [f"{b:.3f}" + ("" if bsplit == "test" else r"$^\dagger$")])
write("headline", tabular("@{}lrrrrr@{}", [
    r"& \multicolumn{2}{c}{\textbf{per-workload model}} & \multicolumn{2}{c}{\textbf{one global model}} & \textbf{optimum} \\",
    r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}",
    r"\textbf{Workload} & test & held-out & test & held-out & Belady (test) \\"], rows))

# ---- model types (per-workload, test, 10%) ----------------------------------
rows = []
for wl in WL:
    lin = fin.get((wl, "K+K+", wl, "test", "0.1"))
    if not lin:
        continue
    cells = [r3(float(lin["geo_ratio_vs_clock"]), int(lin["censored"]))]
    for m in (f"mlp_{wl}_{KK}", f"rmlp_{wl}_{KK}", f"gru_{wl}", f"embed_{wl}"):
        v = nn.get((m, wl, "test"))
        cells.append(r3(*v) if v else "--")
    rows.append([wl] + cells)
write("nn", tabular("@{}lrrrrr@{}", [
    r"\textbf{Workload} & \textbf{Linear} (selected) & \textbf{MLP} & \textbf{Ranking MLP} & \textbf{GRU} & \textbf{Embedding} \\"],
    rows))

# ---- in-kernel results (per-workload + global) ------------------------------
rows = []
for wl in WL:
    cells = []
    for col in ("geo_faults_vs_clock", "geo_writes_vs_clock"):
        for s, _ in SPLITS:
            v = kv("ml/workload", wl, s, col)
            cells.append(best(f"{v:.3f}", v) if v is not None else "--")
    for s, _ in SPLITS:
        v = kv("ml/global", wl, s, "geo_faults_vs_clock")
        cells.append(f"{v:.3f}" if v is not None else "--")
    rows.append([wl] + cells)
write("kernel", tabular("@{}lrrrrrr@{}", [
    r"& \multicolumn{2}{c}{\textbf{faults / Clock}} & \multicolumn{2}{c}{\textbf{writes / Clock}} & \multicolumn{2}{c}{\textbf{global model, faults}} \\",
    r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}",
    r"\textbf{Workload} & test & held-out & test & held-out & test & held-out \\"], rows))

# ---- decision cost ------------------------------------------------------------
rows = []
for wl in WL:
    for s, sname in SPLITS:
        if ("ml/workload", wl, s) not in kern:
            continue
        t = {p: kv(p, wl, s, "select_ticks_per_eviction")
             for p in ("clock", "aging", "ml/global", "ml/workload")}
        cand = kv("ml/workload", wl, s, "candidates_per_eviction")
        rows.append([wl, sname, f"{cand:.0f}"] +
                    [f"{t[p]:.1f}" for p in ("clock", "aging", "ml/global", "ml/workload")] +
                    [rf"{t['ml/workload'] / 10:.1f}\,\textmu s"])
write("cost", tabular("@{}llrrrrrr@{}", [
    r"& & \textbf{pages in} & \multicolumn{4}{c}{\textbf{timer ticks per eviction}} & \textbf{ML time} \\",
    r"\cmidrule(lr){4-7}",
    r"\textbf{Workload} & \textbf{Split} & \textbf{memory} & Clock & Aging & ML global & ML per-wl. & \textbf{per eviction} \\"],
    rows))

# ---- A1: the traces -----------------------------------------------------------
LABEL = {"btree-insert": "insert", "btree-lookup": "lookup", "btree-mixed": "mixed",
         "btree-mixedwal": "mixed+WAL", "btree-scan": "scan",
         "graph-both2000x1": r"BFS+PageRank 2000$\times$1",
         "graph-both1000x3": r"BFS+PageRank 1000$\times$3",
         "graph-pr2000x2": r"PageRank 2000$\times$2", "graph-bfs2000": "BFS 2000",
         "kv-A": "A", "kv-B": "B", "kv-C": "C", "kv-D": "D", "kv-F": "F",
         "kv-Arehash": "A+rehash", "kv-Avsize": "A+value sizes",
         "sort-n20000": "n = 20,000", "sort-n40000": "n = 40,000", "sort-n60000": "n = 60,000"}


def big(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}K"


def pages(n):
    return f"{n / 1e3:.1f}K" if n >= 1000 else str(n)


def rng(vals, f):
    lo, hi = min(vals), max(vals)
    return f(lo) if f(lo) == f(hi) else f"{f(lo)}--{f(hi)}"


st = read("streams_table.csv")
groups = defaultdict(list)
for r in st:
    held = r["splits"].startswith("heldout")
    cls = "held-out" if held else ("train" if r["splits"].startswith("train") and "test" not in r["splits"]
                                   else "train/val/test")
    groups[(r["workload"], cls)].append(r)
rows, mid, first = [], [], True
for wl in WL:
    keys = [k for k in (("train/val/test",), ("train",), ("held-out",)) if (wl, k[0]) in groups]
    for ki, (cls,) in enumerate(keys):
        rs = groups[(wl, cls)]
        if wl == "graph":
            parts = [[r] for r in rs]
        else:
            parts = [rs]
        for pi, p in enumerate(parts):
            if wl == "matmul":
                ns = sorted({int(r["variant"].split("ed" if "blocked" in r["variant"] else "naive")[-1]) for r in p})
                label = "naive / blocked, n = " + ", ".join(str(n) for n in ns)
            elif wl == "sort":
                label = "n = " + ", ".join(LABEL[r["variant"]][4:] for r in p)
            else:
                label = ", ".join(LABEL[r["variant"]] for r in p)
            counts = {int(r["streams"]) for r in p}
            traces = (f"{counts.pop()} each" if len(p) > 1 and len(counts) == 1 else
                      " / ".join(str(int(r["streams"])) for r in p))
            refs = rng([int(r["mean_refs"]) for r in p], big)
            pg = rng([int(r["mean_distinct_pages"]) for r in p], pages)
            rows.append([wl if (ki == 0 and pi == 0) else "", label, traces, refs, pg, cls])
    mid.append(len(rows))
write("variants", tabular("@{}llrrrl@{}", [
    r"\textbf{Workload} & \textbf{Variant} & \textbf{Traces} & \textbf{Accesses (mean)} & \textbf{Pages} & \textbf{Split} \\"],
    rows, mid=set(mid[:-1])))

# ---- A2: the selected models ------------------------------------------------
rows = []
for scope in WL + ["global"]:
    r = next((v for k, v in fin.items() if k[0] == scope and k[1] == "K+K+"), None)
    if r:
        rows.append([scope, r["features"].replace("+", " + ") + f" ({r['protect_age']})"])
write("chosen", tabular("@{}ll@{}", [r"\textbf{Model} & \textbf{Features (probation in scans)} \\"], rows))

# ---- A3: float vs integer scoring -------------------------------------------
rows = []
for wl in WL:
    for s, sname in SPLITS:
        r = fin.get((wl, "K+K+", wl, s, "all"))
        if not r:
            continue
        qs = [ex.get((f"quant{q}", wl, r["features"], wl, s)) for q in (4, 8, 12)]
        rows.append([wl, sname, r3(float(r["geo_ratio_vs_clock"]), int(r["censored"]))] +
                    [r3(*q) if q else "--" for q in qs])
write("quant", tabular("@{}llrrrr@{}", [
    r"\textbf{Workload} & \textbf{Split} & \textbf{float} & \textbf{4-bit} & \textbf{8-bit} & \textbf{12-bit} \\"],
    rows))

# ---- A4: all in-kernel results -----------------------------------------------
pols = ["fifo", "aging", "lfu", "ml/global", "ml/workload", "ml/workload-k"]
rows = []
for s, sname in SPLITS:
    for wl in WL:
        if ("clock", wl, s) not in kern:
            continue
        rows.append([wl, sname] + [f"{kv(p, wl, s, 'geo_faults_vs_clock'):.3f}" for p in pols])
write("kernelall", tabular("@{}llrrrrrr@{}", [
    r"\textbf{Workload} & \textbf{Split} & \textbf{FIFO} & \textbf{Aging} & \textbf{LFU} & \textbf{ML global} & \textbf{ML per-wl.} & \textbf{ML K only} \\"],
    rows))


# ---- numbers quoted in the text: \val{key} ----------------------------------
V = {}


def put(k, x, fmt="{:.1f}"):
    V[k] = fmt.format(x)


def red(r):                                # ratio -> % fewer than Clock
    return (1 - r) * 100


for wl in WL:
    for s_, _ in SPLITS:
        f = kv("ml/workload", wl, s_, "geo_faults_vs_clock")
        if f is None:
            continue
        put(f"k-f-{wl}-{s_}", red(f))
        put(f"k-w-{wl}-{s_}", red(kv("ml/workload", wl, s_, "geo_writes_vs_clock")))
        put(f"k-g-f-{wl}-{s_}", (kv("ml/global", wl, s_, "geo_faults_vs_clock") - 1) * 100)
        r = fin.get((wl, "K+K+", wl, s_, "all"))
        put(f"s-f-{wl}-{s_}", red(float(r["geo_ratio_vs_clock"])))
        put(f"s-w-{wl}-{s_}", red(float(r["geo_writebacks_vs_clock"])))
        put(f"s-r-{wl}-{s_}", float(r["geo_ratio_vs_clock"]), "{:.3f}")
        g = fin.get(("global", "K+K+", wl, s_, "all"))
        put(f"s-g-r-{wl}-{s_}", float(g["geo_ratio_vs_clock"]), "{:.3f}")
put("k-maxw", max(red(kv("ml/workload", w, s_, "geo_writes_vs_clock"))
                  for w in WL for s_, _ in SPLITS if kv("ml/workload", w, s_, "geo_writes_vs_clock")))
for wl in WL:
    bs = "test" if (wl, "K+K+", wl, "test", "all") in fin else "heldout"
    put(f"b-{wl}", red(cl[("belady", wl, bs, "all")]))
    for frac in ("0.05", "0.1", "0.2"):
        r = fin.get((wl, "K+K+", wl, "test", frac)) or fin.get((wl, "K+K+", wl, "heldout", frac))
        put(f"s-r-{wl}-{frac}", float(r["geo_ratio_vs_clock"]), "{:.3f}")
for r in read("summary_marginal.csv"):
    if r["scope"] == r["workload"] and r["feature"] == "idle" and (
            r["split"] == "test" or (r["workload"] == "matmul" and r["split"] == "heldout")):
        put(f"idle-{r['workload']}", -100 * (math.exp(float(r["median_delta_log_ratio"])) - 1))
for wl in WL:
    for s_, _ in SPLITS:
        lin = fin.get((wl, "K+K+", wl, s_, "0.1"))
        if lin:
            put(f"lin-{wl}-{s_}", float(lin["geo_ratio_vs_clock"]), "{:.3f}")
        v = nn.get((f"mlp_{wl}_{KK}", wl, s_))
        if v:
            put(f"mlp-{wl}-{s_}", v[0], "{:.3f}")
q8, q4 = [], []
for wl in WL:
    for s_, _ in SPLITS:
        r = fin.get((wl, "K+K+", wl, s_, "all"))
        if not r:
            continue
        fl = float(r["geo_ratio_vs_clock"])
        q8.append(abs(ex[("quant8", wl, r["features"], wl, s_)][0] - fl))
        q4.append(abs(ex[("quant4", wl, r["features"], wl, s_)][0] / fl - 1) * 100)
put("q8-maxdiff", max(q8), "{:.3f}")
put("q4-maxrel", max(q4))
kvs = read("summary_kernel_vs_sim.csv")
core = [float(r["median_kernel_over_sim"]) for r in kvs
        if r["policy"] in ("clock", "aging", "lfu", "ml/workload", "ml/workload-k")
        or (r["policy"] == "ml/global" and r["workload"] != "matmul")]
put("kvs-min", min(core), "{:.3f}")
put("kvs-max", max(core), "{:.3f}")
put("kvs-gmatmul", next(float(r["median_kernel_over_sim"]) for r in kvs
                        if r["policy"] == "ml/global" and r["workload"] == "matmul"), "{:.3f}")
xc, xa, tp = [], [], []
for wl in WL:
    for s_, _ in SPLITS:
        m = kv("ml/workload", wl, s_, "select_ticks_per_eviction")
        if m is None:
            continue
        xc.append(m / kv("clock", wl, s_, "select_ticks_per_eviction"))
        xa.append(m / kv("aging", wl, s_, "select_ticks_per_eviction"))
        tp.append(m / kv("ml/workload", wl, s_, "candidates_per_eviction"))
put("xclock-min", min(xc)); put("xclock-max", max(xc))
put("xaging-min", min(xa)); put("xaging-max", max(xa))
put("tpp-min", min(tp)); put("tpp-max", max(tp))
for wl in ("sort", "btree"):
    put(f"us-{wl}", kv("ml/workload", wl, "test", "select_ticks_per_eviction") / 10)
    put(f"pages-{wl}", kv("ml/workload", wl, "test", "candidates_per_eviction"), "{:.0f}")
rel = []
for wl in ("btree", "graph", "kv"):
    for s_, _ in SPLITS:
        o, k = fin.get((wl, "F", wl, s_, "all")), fin.get((wl, "K+K+", wl, s_, "all"))
        if o and k:
            rel.append((float(o["geo_ratio_vs_clock"]) / float(k["geo_ratio_vs_clock"]) - 1) * 100)
put("orc-worse", max(rel)); put("orc-better", -min(rel))
pts = [(kv("ml/workload", w, s_, "candidates_per_eviction"), kv("ml/workload", w, s_, "select_ticks_per_eviction"))
       for w in WL for s_, _ in SPLITS if kv("ml/workload", w, s_, "select_ticks_per_eviction")]
n_ = len(pts); mx = sum(x for x, _ in pts) / n_; my = sum(y for _, y in pts) / n_
slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
put("fit-slope", slope); put("fit-base", my - slope * mx, "{:.0f}")
lines = ["% generated by tools/ml2/report_tables.py -- numbers quoted in the text"]
lines += [f"\\expandafter\\def\\csname v@{k}\\endcsname{{{v}}}" for k, v in sorted(V.items())]
(OUT / "numbers.tex").write_text("\n".join(lines) + "\n")
print("wrote numbers (%d values)" % len(V))
