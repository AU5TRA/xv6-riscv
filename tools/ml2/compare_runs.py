#!/usr/bin/env python3
"""Compare runs in a new results file with the same runs in kernel_eval_all.csv: faults, zero-fill faults, evictions and page writes must be
identical when a code change keeps every victim.   python3 compare_runs.py report/results2/kernel_eval_A_check.csv"""
import csv
import sys

import pagesim as ps

R = ps.ROOT / "report" / "results2"
old = {(r["stem"], r["fraction"], r["policy"], r["model"]): r for r in csv.DictReader(open(R / "kernel_eval_all.csv")) if r["status"] == "ok"}
same = diff = missing = 0
for r in csv.DictReader(open(sys.argv[1])):
    if r["status"] != "ok":
        print("not ok:", r["stem"], r["model"], r["status"]); continue
    o = old.get((r["stem"], r["fraction"], r["policy"], r["model"]))
    if not o:
        missing += 1; continue
    keys = ("swap_faults", "zero_faults", "evictions", "page_writes")
    if all((r[k] or "0") == (o[k] or "0") for k in keys):
        same += 1
    else:
        diff += 1
        print("DIFFERENT:", r["stem"], r["fraction"], r["policy"], r["model"], {k: (o[k], r[k]) for k in keys})
print(f"identical {same}, different {diff}, no earlier run {missing}")
