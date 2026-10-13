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


def copies():
    for n in ["kmain_A_005", "kmain_A_01", "kmain_A_02", "kmain_B_005", "kmain_B_01", "kmain_B_02", "kmain_WA_005", "kmain_WA_01", "kmain_WA_02", "trainedall", "model_comparison", "transfer", "lecar"]:
        shutil.copy(W15 / f"{n}.tex", OUT / f"{n}.tex")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    ci_table(); cost_table(); breakeven_tables(); copies()
    print("written", OUT)
