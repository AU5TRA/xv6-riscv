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
        "ml:attention-all": "set-attention", "ml:trees-all": "boosted trees", "ml:ranktrees-all": "ranking trees", "clock": "Clock"}


def tab(rows, head):
    s = "\\begin{tabular}{l" + "r" * (len(head) - 1) + "}\n\\toprule\n" + " & ".join(head) + " \\\\\n\\midrule\n"
    for r in rows:
        s += " & ".join(r) + " \\\\\n"
    return s + "\\bottomrule\n\\end{tabular}\n"


def ci_table():
    rows = list(csv.DictReader(open(R / "kernel_ci_classic.csv")))
    d = {(r["policy"], r["against"], r["fraction"]): r for r in rows}
    pairs = [("arck", "clock"), ("lhd", "clock"), ("s3fifo", "clock"), ("ml:global", "clock"), ("ml:global", "arck"), ("ml:global", "lhd"),
             ("ml:cnn-all", "arck"), ("ml:mlp-all", "arck"), ("ml:attention-all", "arck"), ("ml:trees-all", "arck"),
             ("ml:cnn-all", "ml:global"), ("ml:mlp-all", "ml:global")]
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
                 (("arck", ""), "ARC"), (("lhd", ""), "LHD"), (("ml", "global"), "linear, global"), (("ml", "trees-all"), "boosted trees"),
                 (("ml", "ranktrees-all"), "ranking trees"), (("ml", "attention-all"), "set-attention"), (("ml", "cnn-all"), "CNN"),
                 (("ml", "mlp-all"), "deeper MLP")]:
        if k not in d:
            continue
        body.append([n, f"{d[k]:,.0f}".replace(",", "\\,"), f"{d[k] / lin:.2f}" if d[k] / lin < 10 else f"{d[k] / lin:.0f}"])
    (OUT / "cost.tex").write_text(tab(body, ["policy", "instructions to choose one victim", "times the linear model"]))


def copies():
    for n in ["kmain_A_005", "kmain_A_01", "kmain_A_02", "kmain_B_005", "kmain_B_01", "kmain_B_02", "kmain_WA_005", "kmain_WA_01", "kmain_WA_02", "trainedall", "model_comparison", "transfer", "lecar"]:
        shutil.copy(W15 / f"{n}.tex", OUT / f"{n}.tex")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    ci_table(); cost_table(); copies()
    print("written", OUT)
