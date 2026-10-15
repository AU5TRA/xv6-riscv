#!/usr/bin/env python3
"""Tables for report/week_16_update (kernel results first). Reads report/results2; run after report_w15.py (which writes the kmain_* tables).

    python3 report_w16.py   -> report/week_16_update/tables/*.tex
"""
import csv
import shutil
import statistics as st
from collections import defaultdict

import pagesim as ps

R = ps.ROOT / "report" / "results2"
OUT = ps.ROOT / "report" / "week_16_update" / "tables"
W15 = ps.ROOT / "report" / "week_15_update" / "tables"
NAME = {"arck": "ARC", "lhd": "LHD", "s3fifo": "S3-FIFO", "ml:global": "linear, global", "ml:cnn-all": "CNN", "ml:mlp-all": "deeper MLP",
        "ml:attention-all": "set-attention", "ml:trees-all": "boosted trees", "ml:ranktrees-all": "ranking trees", "clock": "Clock", "lecar": "LeCaR", "ml:global@32": "linear, 32 sampled", "ml:global@16": "linear, 16 sampled"}


def tab(rows, head):
    s = "\\begin{tabular}{l" + "r" * (len(head) - 1) + "}\n\\toprule\n" + " & ".join(head) + " \\\\\n\\midrule\n"
    for r in rows:
        s += " & ".join(r) + " \\\\\n"
    return s + "\\bottomrule\n\\end{tabular}\n"


def ci_table():
    rows = list(csv.DictReader(open(R / "kernel_ci_classic.csv")))
    d = {(r["policy"], r["against"], r["fraction"]): r for r in rows}
    pairs = [("arck", "clock"), ("lhd", "clock"), ("s3fifo", "clock"), ("ml:global", "clock"), ("ml:global", "arck"), ("ml:global", "lhd"), ("lecar", "clock"), ("ml:global", "lecar"),
             ("ml:global@32", "clock"), ("ml:global@16", "clock"), ("ml:global@32", "ml:global"), ("ml:global@16", "ml:global"),
             ("ml:cnn-all", "clock"), ("ml:mlp-all", "clock"),
             ("ml:cnn-all", "arck"), ("ml:mlp-all", "arck"), ("ml:attention-all", "arck"), ("ml:trees-all", "arck"),
             ("ml:cnn-all", "ml:global"), ("ml:mlp-all", "ml:global"), ("ml:attention-all", "ml:global"),
             ("ml:trees-all", "ml:global"), ("ml:ranktrees-all", "ml:global")]
    body = []
    for a, b in pairs:
        line = [f"{NAME[a]} against {NAME[b]}"]
        for fr in ("0.05", "0.1", "0.2"):
            r = d.get((a, b, fr))
            if not r:
                line.append("--")
                continue
            lo, hi = float(r["ci95_low"]), float(r["ci95_high"])
            cell = f"{float(r['faults_ratio']):.3f} [{lo:.2f}, {hi:.2f}]"
            line.append(f"\\best{{{cell}}}" if hi < 1 else cell)
        body.append(line)
    (OUT / "ci_main.tex").write_text(tab(body, ["comparison", "5\\% memory", "10\\% memory", "20\\% memory"]))


def cost_table():
    """Exact instruction counts (QEMU instruction-counting mode) from cost_grid.csv at 64 frames (68 candidates per eviction)."""
    d = {}
    for r in csv.DictReader(open(R / "cost_grid.csv")):
        if r["frames"] == "64":
            d[(r["policy"], r["model"])] = float(r["select_instructions_per_eviction"])
    lin = d[("ml", "global")]
    body = []
    for k, n in [(("fifo", ""), "FIFO"), (("clock", ""), "Clock"), (("aging", ""), "Aging"), (("lfu", ""), "LFU"), (("s3fifo", ""), "S3-FIFO"),
                 (("arck", ""), "ARC"), (("lhd", ""), "LHD"), (("lecar", ""), "LeCaR"), (("ml", "global"), "linear, global"), (("ml", "trees-all"), "boosted trees"),
                 (("ml", "ranktrees-all"), "ranking trees"), (("ml", "attention-all"), "set-attention"), (("ml", "cnn-all"), "CNN"),
                 (("ml", "mlp-all"), "deeper MLP")]:
        if k not in d:
            continue
        body.append([n, f"{d[k]:,.0f}".replace(",", "\\,"), f"{d[k] / lin:.2f}" if d[k] / lin < 10 else f"{d[k] / lin:.0f}"])
    (OUT / "cost.tex").write_text(tab(body, ["policy", "instructions to choose one victim", "times the linear model"]))


def breakeven_tables():
    """Appendix tables from cost_benefit_*.csv (kernel runs at 10% memory; instruction counts from cost_grid.csv; device times measured)."""
    dev = list(csv.DictReader(open(R / "cost_benefit_measured_devices.csv")))      # measured devices, 1 ns per instruction
    allm = list(csv.DictReader(open(R / "cost_benefit_measured_all.csv")))         # measured devices, measured speed of this PC's core
    gm = lambda rows, k: st.geometric_mean([float(r[k]) for r in rows])
    body = []
    for pol, n in [("ml:global", "linear score, all candidates"), ("ml:global@32", "linear score, 32 sampled"), ("ml:global@16", "linear score, 16 sampled"),
                   ("arck", "ARC"), ("lhd", "LHD"), ("lecar", "LeCaR"), ("s3fifo", "S3-FIFO"), ("ml:cnn-all", "CNN"), ("ml:mlp-all", "deeper MLP"),
                   ("ml:attention-all", "set-attention"), ("ml:trees-all", "boosted trees"), ("ml:ranktrees-all", "ranking trees")]:
        a = [r for r in dev if r["policy"] == pol]
        b = [r for r in allm if r["policy"] == pol]
        if len(a) < 14 or len(b) < 14:
            continue
        cells = [gm(a, "time_vs_clock_ssd"), gm(a, "time_vs_clock_hdd"), gm(b, "time_vs_clock_ssd"), gm(b, "time_vs_clock_hdd")]
        body.append([n, f"{gm(a, 'faults_over_clock'):.3f}"] + [f"\\best{{{c:.2f}}}" if c < 0.995 else f"{c:.2f}" for c in cells])
    (OUT / "breakeven_summary.tex").write_text(tab(body, ["policy", "faults / Clock", "SSD, 1 ns", "disk, 1 ns", "SSD, 0.059 ns", "disk, 0.059 ns"]))

    def fmt(x):
        if x == "never":
            return "never"
        v = float(x)
        return f"{v:.1f}" if v < 100 else f"{v:,.0f}".replace(",", "\\,")
    by = {(r["workload"], r["policy"]): r for r in allm}
    pols = [("ml:global", "linear score"), ("arck", "ARC"), ("ml:cnn-all", "CNN")]
    body = []
    for w in sorted({r["workload"] for r in allm}):
        line = [w]
        for pol, _ in pols:
            r = by.get((w, pol))
            line += [r["faults_over_clock"], fmt(r["break_even_us"])] if r else ["--", "--"]
        body.append(line)
    head = ["workload"] + [f"{n} {k}" for _, n in pols for k in ("faults", "break-even $\\mu$s")]
    (OUT / "breakeven_by_workload.tex").write_text(tab(body, head))


def gmean(xs):
    import math
    xs = list(xs)
    return math.exp(sum(math.log(max(x, 1e-12)) for x in xs) / len(xs))


def wl_of(stem):
    return "kv-T" if stem.startswith("kv-T") else stem.split("-")[0]


def fmt_int(v):
    return f"{v:,.0f}".replace(",", "\\,")


GRID_ROWS = [(("fifo", ""), "FIFO"), (("clock", ""), "Clock"), (("aging", ""), "Aging"), (("lfu", ""), "LFU"), (("s3fifo", ""), "S3-FIFO"),
             (("arck", ""), "ARC"), (("lhd", ""), "LHD"), (("lecar", ""), "LeCaR"), (("ml", "global"), "linear score, all pages"),
             (("ml", "global@32"), "linear score, 32 sampled"), (("ml", "global@16"), "linear score, 16 sampled"),
             (("ml", "trees-all"), "boosted trees"), (("ml", "ranktrees-all"), "ranking trees"), (("ml", "attention-all"), "set-attention"),
             (("ml", "cnn-all"), "CNN"), (("ml", "mlp-all"), "deeper MLP")]


def cost_sizes_table():
    """Exact instructions to choose one victim at every size of the cost grid (patbench uniform), and the cost of one more page."""
    d = {}
    for r in csv.DictReader(open(R / "cost_grid.csv")):
        d[(r["policy"], r["model"], int(r["frames"]))] = float(r["select_instructions_per_eviction"])
    body = []
    for (p, m), name in GRID_ROWS:
        if (p, m, 64) not in d:
            continue
        cells = [fmt_int(d[(p, m, n)]) if (p, m, n) in d else "--" for n in (16, 64, 256, 512)]
        slope = (d[(p, m, 512)] - d[(p, m, 64)]) / (516 - 68) if (p, m, 512) in d else None
        body.append([name] + cells + [f"{slope:,.0f}".replace(",", "\\,") if slope is not None else "--"])
    (OUT / "cost_sizes.tex").write_text(tab(body, ["policy", "20 pages", "68 pages", "260 pages", "516 pages", "per extra page"]))


def cost_runs_table():
    """The rough check on the real programs (cost_from_runs.py): time spent choosing, relative to Aging on the same streams, 10% memory."""
    rows = [r for r in csv.DictReader(open(R / "cost_from_runs.csv")) if r["fraction"] == "0.1"]
    d = {(r["workload"], r["policy"]): r for r in rows}
    exact = {}
    for r in csv.DictReader(open(R / "cost_grid.csv")):
        if r["frames"] == "64":
            exact[r["policy"] + (":" + r["model"] if r["model"] else "")] = float(r["select_instructions_per_eviction"])
    cols = [("clock", "Clock"), ("lecar", "LeCaR"), ("arck", "ARC"), ("lhd", "LHD"), ("ml:global", "linear")]
    body = [["patbench uniform (exact count)", "68"] + [f"{exact[c] / exact['aging']:.2f}" for c, _ in cols]]
    for wl in sorted({w for w, _ in d}):
        if (wl, "aging") not in d:
            continue
        body.append([wl, d[(wl, "aging")]["pages_to_choose_from"]] + [f"{float(d[(wl, c)]['relative_to_aging']):.2f}" if (wl, c) in d and d[(wl, c)]["relative_to_aging"] else "--" for c, _ in cols])
    (OUT / "cost_runs.tex").write_text(tab(body, ["workload", "pages to choose from"] + [n for _, n in cols]))


def sampling_sweep_table():
    """The first simulator sweep (exp_sampling.py): global linear model, k random pages, 3 seeds; faults relative to scoring every page."""
    rows = [r for r in csv.DictReader(open(R / "sampling_sweep.csv")) if r["model"] == "ml_global" and r["aborted"] == "0"]
    full = {(r["stem"], r["fraction"]): int(r["faults"]) for r in rows if r["mode"] == "all"}
    acc = defaultdict(list)
    for r in rows:
        if r["mode"] != "all" and (r["stem"], r["fraction"]) in full:
            acc[(r["mode"], int(r["k"]), r["fraction"], r["stem"])].append(int(r["faults"]) / full[(r["stem"], r["fraction"])])
    cells = defaultdict(lambda: defaultdict(list))
    for (mode, k, fr, stem), v in acc.items():
        cells[(mode, k, fr)][wl_of(stem)].append(gmean(v))
    body = []
    for k in (4, 8, 16, 32, 64):
        line = [str(k)]
        for mode in ("score", "scan"):
            for fr in ("0.05", "0.1", "0.2"):
                c = cells.get((mode, k, fr))
                line.append(f"{gmean(gmean(v) for v in c.values()):.3f}" if c else "--")
        body.append(line)
    n = {fr: len({s for (s, f) in full if f == fr}) for fr in ("0.05", "0.1", "0.2")}
    (OUT / "sampling_sweep.tex").write_text(tab(body, ["pages looked at", "5\\%", "10\\%", "20\\%", "5\\%", "10\\%", "20\\%"]))
    (OUT / "sampling_sweep_n.txt").write_text(" ".join(f"{fr}:{v}" for fr, v in n.items()))


def sampling_heur_table():
    """Ways of choosing the sampled pages (exp_sampling_heur.py): simulator, the kernel's 74 streams at 10%; vs the full score and vs Clock."""
    rows = list(csv.DictReader(open(R / "sampling_heuristics.csv")))
    cell = defaultdict(lambda: defaultdict(list))
    for r in rows:
        cell[r["stem"]][(r["variant"], int(r["k"]))].append(int(r["faults"]))
    def score(name, k, base):
        by = defaultdict(list)
        for s, c in cell.items():
            by[wl_of(s)].append(gmean(c[(name, k)]) / c[base][0])
        return gmean(gmean(v) for v in by.values())
    names = [("random", "random (as in the kernel runs)"), ("newest", "the quarter newest loaded, rest random"), ("spread", "evenly spread over the load order"),
             ("window", "a window in load order that moves on"), ("unseen", "pages not seen at their latest scan first"), ("oldest", "the oldest loaded pages")]
    body = [["all pages (no sampling)", "1.000", "1.000", f"{score('full', 0, ('clock', 0)):.3f}", ""]]
    for v, label in names:
        body.append([label, f"{score(v, 32, ('full', 0)):.3f}", f"{score(v, 16, ('full', 0)):.3f}", f"{score(v, 32, ('clock', 0)):.3f}", f"{score(v, 16, ('clock', 0)):.3f}"])
    (OUT / "sampling_heur.tex").write_text(tab(body, ["which pages", "32: vs all pages", "16: vs all pages", "32: vs Clock", "16: vs Clock"]))


def native_timing_table():
    """The kernel's scoring code compiled for the thesis PC (native_timing.c), 68 pages: microseconds per decision."""
    def load(f):
        return {r["policy"].split(" + ")[0]: float(r["ns_per_decision_median"]) for r in csv.DictReader(open(R / f)) if r["candidates"] == "68"}
    a, b, c = load("native_timing.csv"), load("native_timing_walk.csv"), load("native_timing_cold.csv")
    body = []
    for k in a:
        body.append([k, f"{a[k] / 1000:.2f}", f"{b.get(k, 0) / 1000:.2f}", f"{c.get(k, 0) / 1000:.2f}"])
    (OUT / "native_timing.tex").write_text(tab(body, ["policy", "scoring only", "+ page-table walk", "+ walk, cold caches"]))


def compiler_flags_table():
    d = {(r["variant"], r["policy"] + (":" + r["model"] if r["model"] else "")): r["select_instructions_per_eviction"] for r in csv.DictReader(open(R / "compiler_flags.csv"))}
    names = [("O1_baseline", "-O (what every run used)"), ("O2", "-O2"), ("O2_nofp", "-O2 without frame pointer"), ("O3", "-O3"), ("Os", "-Os (smallest code)")]
    cols = ["clock", "aging", "ml:global", "ml:global@32"]
    body = [[n] + [fmt_int(float(d[(v, c)])) for c in cols] for v, n in names]
    (OUT / "compiler_flags.tex").write_text(tab(body, ["kernel built with", "Clock", "Aging", "linear, all pages", "linear, 32 sampled"]))


def dagger_table():
    rows = list(csv.DictReader(open(R / "r3_dagger_v1.csv")))
    d = defaultdict(dict)
    for r in rows:
        d[r["model"]][int(r["dagger_round"])] = (r["faults_over_clock"], r["stopped_at_3x"])
    body = []
    for m in ("best of 300", "median of 300", "all features"):
        body.append([m] + [(f"{float(d[m][i][0]):.2f}" + (" (stopped)" if d[m][i][1] == "1" else "")) for i in range(4)])
    (OUT / "dagger.tex").write_text(tab(body, ["model", "round 0", "round 1", "round 2", "round 3"]))


def fast_code_table():
    """Code changes to choose_ml that keep every victim (choose_ml_fast_test.py; exact counts, patbench uniform; faults identical in every row)."""
    d = {}
    for r in csv.DictReader(open(R / "choose_ml_fast.csv")):
        d[(r["variant"], r["frames"], r["policy"] + (":" + r["model"] if r["model"] else ""))] = int(r["select_instr"])
    rows = [("plain", "none (what every run used)"), ("logcache", "A1: store the two logs that rarely change"), ("onepass", "A2: one pass instead of two"),
            ("inline", "A3: feature code inlined"), ("log_inline", "A1 + A3"), ("log_inline_msb", "A1 + A3 + A4: faster highest-bit search in the log"),
            ("log_inline_unroll", "A1 + A3 + A5: features written out one by one"), ("all3", "A1 + A2 + A3"),
            ("both_O3_vm", "A1 + A2, page code at -O3 (also speeds up other policies)")]
    base = {k: d[("plain",) + k] for k in [("64", "ml:global"), ("256", "ml:global"), ("64", "ml:global@32")]}
    body = []
    for v, label in rows:
        cells = []
        for k in [("64", "ml:global"), ("256", "ml:global"), ("64", "ml:global@32")]:
            x = d.get((v,) + k)
            cells.append(f"{fmt_int(x)} ({100 * (x / base[k] - 1):+.0f}\\%)" if x is not None and v != "plain" else (fmt_int(x) if x is not None else "--"))
        body.append([label] + cells)
    (OUT / "fast_code.tex").write_text(tab(body, ["change", "68 pages", "260 pages", "68 pages, 32 sampled"]))


def sampling_more_table():
    """Pool and clock-filter sampling against random (exp_sampling_more.py): faults vs all pages at 5/10/20%, and the estimated instructions per eviction at 10%."""
    d = {}
    for fr in ("0.05", "0.1", "0.2"):
        for r in csv.DictReader(open(R / f"sampling_more_summary_{fr}.csv")):
            d[(fr, r["scheme"])] = r
    order = ["random 4", "random 8", "random 16", "random 32", "pool 4 new + 4 kept", "pool 4 new + 8 kept", "pool 8 new + 8 kept", "pool 8 new + 16 kept",
             "pool 16 new + 16 kept", "clock-filter 4", "clock-filter 8", "clock-filter 16", "clock-filter 32"]
    body = []
    for n in order:
        if ("0.1", n) not in d:
            continue
        body.append([n, f"{float(d[('0.1', n)]['scored_per_eviction']):.0f}", fmt_int(float(d[("0.1", n)]["estimated_instructions_per_eviction"]))] +
                    [f"{float(d[(fr, n)]['faults_vs_all_pages']):.3f}" for fr in ("0.05", "0.1", "0.2")])
    (OUT / "sampling_more.tex").write_text(tab(body, ["scheme", "pages scored per eviction (10\\%)", "estimated instructions (10\\%)", "5\\%", "10\\%", "20\\%"]))


def copies():
    for n in ["kmain_A_005", "kmain_A_01", "kmain_A_02", "kmain_B_005", "kmain_B_01", "kmain_B_02", "kmain_WA_005", "kmain_WA_01", "kmain_WA_02", "trainedall", "model_comparison", "transfer", "lecar"]:
        shutil.copy(W15 / f"{n}.tex", OUT / f"{n}.tex")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    ci_table(); cost_table(); breakeven_tables(); copies()
    cost_sizes_table(); cost_runs_table(); sampling_sweep_table(); sampling_heur_table(); native_timing_table(); compiler_flags_table(); dagger_table(); fast_code_table(); sampling_more_table()
    print("written", OUT)
