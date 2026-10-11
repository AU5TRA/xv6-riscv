#!/usr/bin/env python3
"""Merge every in-kernel result file into one: report/results2/kernel_eval_all.csv.

Sources, oldest first (a later file overrides an earlier one for the same run):
  kernel_eval.csv                    week 14 and the first lzw / Twitter / patbench / appbench runs
  kernel_eval_w16.csv .. w16f.csv    this week's runs on this machine
  kaggle_*.csv                       runs done on the four Kaggle notebooks (each started from copies of w16e / w16f, so
                                     the same rows appear in several files)
A run is identified by (stream, memory fraction, policy, model); only runs with status ok are kept. Prints how many rows
each source contributed and how many were duplicates.
"""
import csv
import glob
from pathlib import Path

R = Path(__file__).resolve().parents[2] / "report" / "results2"
SOURCES = ["kernel_eval.csv"] + [f"kernel_eval_w16{s}.csv" for s in ("", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o")]
OLD = "kernel_eval.csv"       # the week-14 build of the programs; later files use the current build


def main():
    files = [R / f for f in SOURCES if (R / f).exists()] + [Path(p) for p in sorted(glob.glob(str(R / "kaggle_*.csv")))]
    rows, header, stat = {}, [], []
    for f in files:
        n = dup = 0
        for r in csv.DictReader(open(f)):
            if r["status"] != "ok":
                continue
            for k in r:
                if k not in header:
                    header.append(k)
            key = (r["stem"], r["fraction"], r["policy"], r["model"])
            dup += key in rows
            rows[key] = dict(r, source=f.name)
            n += 1
        stat.append((f.name, n, dup))
    # The programs changed between the two builds, which moves every policy's fault counts by about 1% (results within one
    # build repeat exactly, and the Kaggle machines reproduce this machine's runs exactly). Never compare across builds:
    # in a (stream, memory size) group that has any current-build run, drop the old-build runs.
    groups = {}
    for (stem, fr, pol, mod), r in rows.items():
        groups.setdefault((stem, fr), set()).add(r["source"] == OLD)
    dropped = [k for k, r in rows.items() if r["source"] == OLD and False in groups[(k[0], k[1])]]
    for k in dropped:
        del rows[k]
    print(f"dropped {len(dropped)} old-build runs from groups that have current-build runs")
    header.append("source")
    with open(R / "kernel_eval_all.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows.values())
    for name, n, d in stat:
        print(f"{name:28s} {n:5d} ok rows, {d:4d} already present")
    print("merged:", len(rows), "distinct runs ->", R / "kernel_eval_all.csv")


if __name__ == "__main__":
    main()
