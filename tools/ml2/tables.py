#!/usr/bin/env python3
"""Results tables for the report (Markdown) and the slides (LaTeX), generated
from report/results2/summary_*.csv so no number is copied by hand.

    python3 tables.py   -> report/results2/tables.md, report/slides/tables/*.tex
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "report" / "results2"
TEX = ROOT / "report" / "slides" / "tables"
WL = ["btree", "graph", "kv", "matmul", "sort"]
SPLITS = ("test", "heldout")
GROUPS = [("F", "oracle (F)"), ("K", "kernel (K)"), ("K+K+", "kernel+refault (K∪K+)"),
          ("F+K", "oracle+kernel")]
KK = ["ref", "aging", "sfreq", "idle", "age", "dirty", "refaults", "rdist"]
F = ["rec", "freq", "sd", "wr"]


def read(name):
    p = R / name
    return list(csv.DictReader(open(p))) if p.exists() else []


def fmt(v, cens=0):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    s = f"{v:.3f}"
    return f"≥{s}" if cens else s


def pct(v):
    return f"{(v - 1) * 100:+.1f}%"


class Table:
    def __init__(self, title, header, note=""):
        self.title, self.header, self.rows, self.note = title, header, [], note

    def add(self, row):
        self.rows.append([str(c) for c in row])

    def md(self):
        out = [f"**{self.title}**", "", "| " + " | ".join(self.header) + " |",
               "|" + "|".join("---" for _ in self.header) + "|"]
        out += ["| " + " | ".join(r) + " |" for r in self.rows]
        if self.note:
            out += ["", f"*{self.note}*"]
        return "\n".join(out) + "\n"

    def tex(self):
        def esc(x):
            return (str(x).replace("_", r"\_").replace("≥", r"$\geq$").replace("—", "--")
                    .replace("%", r"\%").replace("&", r"\&").replace("∪", r"$\cup$")
                    .replace("→", r"$\to$").replace("+", r"{+}"))
        cols = "l" + "r" * (len(self.header) - 1)
        out = [r"\begin{tabular}{" + cols + "}", r"\toprule",
               " & ".join(esc(h) for h in self.header) + r" \\", r"\midrule"]
        out += [" & ".join(esc(c) for c in r) + r" \\" for r in self.rows]
        out += [r"\bottomrule", r"\end{tabular}"]
        return "\n".join(out) + "\n"


def main():
    TEX.mkdir(parents=True, exist_ok=True)
    cls = {(r["policy"], r["workload"], r["split"], r["fraction"]):
           (float(r["geo_ratio_vs_clock"]), int(r["censored"]), float(r["mean_gap_closed"]),
            float(r["geo_writebacks_vs_clock"]))
           for r in read("summary_classical.csv")}
    fin = {(r["scope"], r["group"], r["workload"], r["split"], r["fraction"]):
           (float(r["geo_ratio_vs_clock"]), float(r["mean_gap_closed"]), r["features"],
            int(r["protect_age"]), int(r["censored"]), float(r["geo_ratio_vs_lru"]),
            float(r["geo_writebacks_vs_clock"]))
           for r in read("summary_final.csv")}
    lin = {(r["scope"], r["features"], r["workload"], r["split"]):
           (float(r["geo_ratio_vs_clock"]), int(r["censored"])) for r in read("summary_linear.csv")}
    lin1 = {(r["scope"], r["features"], r["workload"], r["split"]):
            (float(r["geo_ratio_vs_clock"]), int(r["censored"])) for r in read("summary_linear_v1.csv")}
    lin2m = {(r["scope"], r["features"], r["workload"], r["split"]):
             (float(r["geo_ratio_vs_clock"]), int(r["censored"]))
             for r in read("summary_linear_v2_matched.csv")}
    nn = {(r["model"], r["workload"], r["split"]):
          (float(r["geo_ratio_vs_clock"]), int(r["censored"]), int(r["protect_age"]))
          for r in read("summary_nn.csv")}
    ex = {(r["kind"], r["scope"], r["features"], r["workload"], r["split"]):
          (float(r["geo_ratio_vs_clock"]), int(r["censored"])) for r in read("summary_extras.csv")}
    T = {}

    # ---- 1 classical ------------------------------------------------------
    pols = [("fifo", "FIFO"), ("aging", "Aging"), ("lfu_kernel", "decayed LFU"),
            ("lru", "LRU"), ("lfu_exact", "exact LFU"), ("sd_old", "old SD"), ("belady", "Belady")]
    for split in SPLITS:
        t = Table(f"Classical policies, {split} streams — faults / Clock (geo-mean over 5/10/20%)",
                  ["workload"] + [n for _, n in pols],
                  "Clock = 1; below 1 is better. ≥: some runs stopped at 3× Clock (lower bound).")
        for wl in WL:
            vals = [cls.get((p, wl, split, "all")) for p, _ in pols]
            if any(vals):
                t.add([wl] + [fmt(v[0], v[1]) if v else "—" for v in vals])
        T[f"classical_{split}"] = t

    # ---- 2 headline (final, all capacities) --------------------------------
    for sk in ("workload", "global"):
        for split in SPLITS:
            t = Table(f"Validation-selected linear model per tier "
                      f"({'per-workload' if sk == 'workload' else 'one global'} model), {split} — "
                      "faults / Clock, geo-mean over 5/10/20% (share of the Clock→Belady gap closed)",
                      ["workload", "LRU"] + [n for _, n in GROUPS] + ["Belady"],
                      "Feature subset and probation chosen on validation only (matmul: its "
                      "training streams).")
            for wl in WL:
                sc = wl if sk == "workload" else "global"
                row = [wl, fmt(*cls[("lru", wl, split, "all")][:2]) if ("lru", wl, split, "all") in cls else "—"]
                have = False
                for g, _ in GROUPS:
                    v = fin.get((sc, g, wl, split, "all"))
                    if v:
                        have = True
                        row.append(f"{fmt(v[0], v[4])} ({v[1]:+.0%})")
                    else:
                        row.append("—")
                row.append(fmt(cls[("belady", wl, split, "all")][0]) if ("belady", wl, split, "all") in cls else "—")
                if have:
                    t.add(row)
            T[f"headline_{sk}_{split}"] = t

    # ---- 3 per capacity, kernel tier ----------------------------------------
    for g in ("K+K+", "F"):
        t = Table(f"By capacity: the selected {dict(GROUPS)[g]} model (per-workload) — faults / Clock",
                  ["workload", "split", "5%", "10%", "20%", "Belady 5%", "Belady 10%", "Belady 20%"])
        for wl in WL:
            for split in SPLITS:
                vs = [fin.get((wl, g, wl, split, f)) for f in ("0.05", "0.1", "0.2")]
                if not any(vs):
                    continue
                bs = [cls.get(("belady", wl, split, f)) for f in ("0.05", "0.1", "0.2")]
                t.add([wl, split] + [fmt(v[0], v[4]) if v else "—" for v in vs] +
                      [fmt(b[0]) if b else "—" for b in bs])
        T[f"bycap_{g.replace('+', 'p')}"] = t

    # ---- 4 chosen models ----------------------------------------------------
    t = Table("Models chosen on validation: feature subset (probation, in scans)",
              ["scope"] + [n for _, n in GROUPS])
    for sc in WL + ["global"]:
        row = [sc]
        for g, _ in GROUPS:
            v = next((v for k, v in fin.items() if k[0] == sc and k[1] == g), None)
            row.append(f"{v[2].replace('+', ' + ')} ({v[3]})" if v else "—")
        t.add(row)
    T["chosen"] = t

    # ---- 5 writebacks -------------------------------------------------------
    t = Table("Page writes (disk writebacks) relative to Clock, geo-mean over 5/10/20%",
              ["workload", "split", "LRU", "kernel+refault", "oracle", "Belady"],
              "Below 1: fewer writes than Clock. Belady minimises faults, not writes.")
    for wl in WL:
        for split in SPLITS:
            a = fin.get((wl, "K+K+", wl, split, "all"))
            b = fin.get((wl, "F", wl, split, "all"))
            l = cls.get(("lru", wl, split, "all"))
            bl = cls.get(("belady", wl, split, "all"))
            if a or b:
                t.add([wl, split, fmt(l[3]) if l else "—", fmt(a[6]) if a else "—",
                       fmt(b[6]) if b else "—", fmt(bl[3]) if bl else "—"])
    T["writebacks"] = t

    # ---- 6 every F subset ---------------------------------------------------
    fsubs = sorted({k[1] for k in lin if set(k[1].split("+")) <= set(F)},
                   key=lambda s: (len(s.split("+")), [F.index(x) for x in s.split("+")]))
    for sk in ("workload", "global"):
        for split in SPLITS:
            t = Table(f"All 15 full-stream (F) subsets, linear, "
                      f"{'per-workload' if sk == 'workload' else 'global'} models, {split}, 10% — faults / Clock",
                      ["features"] + WL)
            for f in fsubs:
                t.add([f] + [fmt(*lin[(wl if sk == 'workload' else 'global', f, wl, split)])
                             if (wl if sk == 'workload' else 'global', f, wl, split) in lin else "—"
                             for wl in WL])
            T[f"fsubsets_{sk}_{split}"] = t

    # ---- 7 the 255 kernel subsets -------------------------------------------
    for sk in ("workload", "global"):
        for split in SPLITS:
            t = Table(f"The 255 kernel-observable (K ∪ K+) subsets, "
                      f"{'per-workload' if sk == 'workload' else 'global'} models, {split}, 10% — "
                      "distribution of faults / Clock",
                      ["workload", "best", "10th pct", "median", "90th pct", "beat Clock",
                       "≥3× Clock"])
            for wl in WL:
                sc = wl if sk == "workload" else "global"
                v = sorted(val[0] for k, val in lin.items() if k[0] == sc and k[2] == wl
                           and k[3] == split and set(k[1].split("+")) <= set(KK))
                if not v:
                    continue
                a = np.array(v)
                t.add([wl, fmt(a[0]), fmt(np.percentile(a, 10)), fmt(float(np.median(a))),
                       fmt(np.percentile(a, 90)), f"{int((a < 1).sum())}/{len(a)}",
                       f"{int((a >= 2.999).sum())}"])
            T[f"kksubsets_{sk}_{split}"] = t

    # ---- 8 marginal ---------------------------------------------------------
    marg = {(r["scope"], r["workload"], r["split"], r["feature"]): float(r["median_delta_log_ratio"])
            for r in read("summary_marginal.csv")}
    t = Table("Median change in faults from adding one kernel feature to a subset that lacks it "
              "(per-workload models, test; matmul: held-out; over all such subset pairs)",
              ["feature"] + WL)
    for f in KK:
        t.add([f] + [pct(math.exp(marg[(wl, wl, 'heldout' if wl == 'matmul' else 'test', f)]))
                     if (wl, wl, 'heldout' if wl == 'matmul' else 'test', f) in marg else "—"
                     for wl in WL])
    T["marginal"] = t

    # ---- 9 neural -----------------------------------------------------------
    kinds = [("mlp_{s}_rec+freq+sd+wr", "MLP F"),
             ("rmlp_{s}_rec+freq+sd+wr", "rank-MLP F"),
             ("mlp_{s}_ref+aging+sfreq+idle+age+dirty+refaults+rdist", "MLP K∪K+"),
             ("rmlp_{s}_ref+aging+sfreq+idle+age+dirty+refaults+rdist", "rank-MLP K∪K+"),
             ("rlin_{s}_ref+aging+sfreq+idle+age+dirty+refaults+rdist", "rank-linear K∪K+"),
             ("mlp_{s}_rec+freq+sd+wr+ref+aging+sfreq+idle+age+dirty+refaults+rdist", "MLP all"),
             ("gru_{s}", "GRU (F)"), ("embed_{s}", "embedding (F)")]
    for sk in ("workload", "global"):
        for split in SPLITS:
            t = Table(f"Neural and ranking-loss scorers ({'per-workload' if sk == 'workload' else 'global'} "
                      f"models), {split}, 10% — faults / Clock",
                      ["workload", "linear K∪K+ (sel.)"] + [n for _, n in kinds],
                      "Probation (0 or 2 scans) chosen per model on validation.")
            for wl in WL:
                sc = wl if sk == "workload" else "global"
                vals = [nn.get((k.format(s=sc), wl, split)) for k, _ in kinds]
                lk = fin.get((sc, "K+K+", wl, split, "0.1"))
                if any(vals):
                    t.add([wl, fmt(lk[0], lk[4]) if lk else "—"] +
                          [fmt(v[0], v[1]) if v else "—" for v in vals])
            T[f"nn_{sk}_{split}"] = t

    # ---- 10 probation ablation (validation) ---------------------------------
    FIXED = [("rec+freq+sd+wr", "F"), ("ref+aging+sfreq+idle+age+dirty", "K"),
             ("ref+aging+sfreq+idle+age+dirty+refaults+rdist", "K∪K+"),
             ("rec+freq+sd+wr+ref+aging+sfreq+idle+age+dirty+refaults+rdist", "all")]
    t = Table("Probation ablation (per-workload linear models, validation streams, 10%; matmul: "
              "its training streams) — faults / Clock", ["workload", "features", "0", "1", "2", "4"])
    for wl in WL:
        split = "train" if wl == "matmul" else "val"
        for key, name in FIXED:
            vs = [ex.get((f"protect{p}", wl, key, wl, split)) for p in (0, 1, 2, 4)]
            if any(vs):
                t.add([wl, name] + [fmt(v[0], v[1]) if v else "—" for v in vs])
    T["protect"] = t

    # ---- 11 v1 vs v2 (sampling + probation) ---------------------------------
    t = Table("Effect of the two fixes on the same linear models (per-workload, 10%) — "
              "faults / Clock; v1: uniform candidate sampling, no probation; v2: recency-stratified "
              "sampling + probation 2", ["workload", "split", "features", "v1", "v2"])
    for wl in WL:
        for split in ("val", "test", "heldout"):
            for key, name in FIXED:
                a, b = lin1.get((wl, key, wl, split)), lin2m.get((wl, key, wl, split))
                if a and b:
                    t.add([wl, split, name, fmt(*a), fmt(*b)])
    T["v1v2"] = t
    t = Table("Share of the 300 feature sets that are catastrophic (≥3× Clock), per-workload "
              "models, 10%", ["workload", "split", "v1", "v2"])
    for wl in WL:
        for split in ("val", "test", "heldout"):
            n1 = [v for k, v in lin1.items() if k[0] == wl and k[2] == wl and k[3] == split]
            n2 = [v for k, v in lin2m.items() if k[0] == wl and k[2] == wl and k[3] == split]
            if n1 and n2:
                t.add([wl, split, f"{sum(v[0] >= 2.999 for v in n1)}/{len(n1)}",
                       f"{sum(v[0] >= 2.999 for v in n2)}/{len(n2)}"])
    T["catastrophic"] = t

    # ---- 12 integer scoring, DAgger ------------------------------------------
    t = Table("Integer-only scoring of the selected linear models (per-workload) — faults / Clock",
              ["workload", "split", "tier", "float", "int, 4-bit", "int, 8-bit", "int, 12-bit"],
              "Features in Q8 fixed point; weights with the standardisation folded in, rounded "
              "to b fractional bits.")
    for wl in WL:
        for split in SPLITS:
            for g, name in GROUPS:
                v = fin.get((wl, g, wl, split, "all"))
                if not v:
                    continue
                qs = [ex.get((f"quant{q}", wl, v[2], wl, split)) for q in (4, 8, 12)]
                if any(qs):
                    t.add([wl, split, name, fmt(v[0], v[4])] +
                          [fmt(*q) if q else "—" for q in qs])
    T["quant"] = t
    t = Table("One DAgger round (per-workload linear models) — faults / Clock, geo-mean 5/10/20%",
              ["workload", "split", "tier", "trained under LRU", "after DAgger"])
    for wl in WL:
        for split in SPLITS:
            for g, name in GROUPS:
                v = fin.get((wl, g, wl, split, "all"))
                e = ex.get(("dagger", wl, v[2], wl, split)) if v else None
                if v and e:
                    t.add([wl, split, name, fmt(v[0], v[4]), fmt(*e)])
    T["dagger"] = t

    # ---- 13 in-kernel ---------------------------------------------------------
    kern = {(r["policy"], r["workload"], r["split"]): r for r in read("summary_kernel.csv")}
    kpol = [("fifo", "FIFO"), ("aging", "Aging"), ("lfu", "LFU (decayed)"),
            ("ml/global", "ML global"), ("ml/workload", "ML per-workload"),
            ("ml/workload-k", "ML per-workload, K only")]
    for split in SPLITS:
        t = Table(f"In xv6 itself: faults relative to Clock, {split} streams, 10% "
                  "(kernel counters; geo-mean over streams)",
                  ["workload"] + [n for _, n in kpol],
                  "Every policy runs the same workload command with the same resident limit; "
                  "faults = zero-fill + swap faults.")
        for wl in WL:
            vals = [kern.get((p_, wl, split)) for p_, _ in kpol]
            if any(vals):
                t.add([wl] + [fmt(float(v["geo_faults_vs_clock"])) if v else "—" for v in vals])
        T[f"kernel_{split}"] = t
        t = Table(f"In xv6 itself: page writes relative to Clock, {split} streams, 10%",
                  ["workload"] + [n for _, n in kpol])
        for wl in WL:
            vals = [kern.get((p_, wl, split)) for p_, _ in kpol]
            if any(vals):
                t.add([wl] + [fmt(float(v["geo_writes_vs_clock"])) if v else "—" for v in vals])
        T[f"kernel_writes_{split}"] = t
    t = Table("Victim-selection cost in xv6: timer ticks (10 MHz, emulated) and candidates "
              "per eviction, mean over all runs", ["policy", "ticks / eviction",
                                                   "candidates / eviction"])
    cost = defaultdict(list)
    for (p_, wl, split), r in kern.items():
        cost[p_].append((float(r["select_ticks_per_eviction"]), float(r["candidates_per_eviction"])))
    for p_, name in [("clock", "Clock")] + kpol:
        if cost.get(p_):
            v = np.array(cost[p_])
            t.add([name, f"{v[:, 0].mean():.1f}", f"{v[:, 1].mean():.1f}"])
    T["kernel_cost"] = t
    kvs = read("summary_kernel_vs_sim.csv")
    if kvs:
        t = Table("Kernel vs simulator: kernel faults / simulated faults for the same stream, "
                  "frames and policy (median over runs)", ["policy", "workload", "runs",
                                                            "median", "min", "max"])
        for r in kvs:
            t.add([r["policy"], r["workload"], r["runs"], r["median_kernel_over_sim"],
                   r["min"], r["max"]])
        T["kernel_vs_sim"] = t

    # compact versions for the slides: the kernel+refault tier only
    for name in ("quant", "dagger"):
        full = T[name]
        c = Table(full.title.replace("the selected linear models", "the selected kernel+refault model"),
                  [h for h in full.header if h != "tier"], full.note)
        ti = full.header.index("tier")
        for r in full.rows:
            if r[ti].startswith("kernel+refault"):
                c.add([x for i, x in enumerate(r) if i != ti])
        T[name + "_compact"] = c

    with open(R / "tables.md", "w") as f:
        for name, t in T.items():
            f.write(f"<!-- {name} -->\n" + t.md() + "\n")
    for name, t in T.items():
        (TEX / f"{name}.tex").write_text(t.tex())
    print(f"{len(T)} tables -> {R / 'tables.md'}, {TEX}")


if __name__ == "__main__":
    main()
