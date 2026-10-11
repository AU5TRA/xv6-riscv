#!/usr/bin/env python3
"""Do the Kaggle machines give the same results as this machine, and how much slower are they?

Runs that were done on Kaggle (kaggle_*.csv) were repeated here (xcheck_local.csv, made with kernel_eval.py on the same streams and
memory sizes). Compares faults, zero-fill faults, evictions and page writes exactly, and the wall time (Kaggle / local).
Rows that are exact copies (same wall time) are the seed rows each notebook started from, not repeats, and are skipped.

    python3 xcheck_kaggle.py
"""
import csv
import glob
import statistics as st
from pathlib import Path

R = Path(__file__).resolve().parents[2] / "report" / "results2"
KEYS = ("swap_faults", "zero_faults", "evictions", "page_writes")


def main():
    loc = {(r["stem"], r["fraction"], r["policy"], r["model"]): r for r in csv.DictReader(open(R / "xcheck_local.csv")) if r["status"] == "ok"}
    n = same = 0
    ratios = []
    for f in sorted(glob.glob(str(R / "kaggle_*.csv"))):
        for r in csv.DictReader(open(f)):
            k = (r["stem"], r["fraction"], r["policy"], r["model"])
            if r["status"] != "ok" or k not in loc or loc[k]["wall_s"] == r["wall_s"]:
                continue
            n += 1
            same += all(loc[k][c] == r[c] for c in KEYS)
            if float(loc[k]["wall_s"]) >= 20:
                ratios.append(float(r["wall_s"]) / float(loc[k]["wall_s"]))
    print(f"independent repeats: {n}; identical in {', '.join(KEYS)}: {same}")
    q = st.quantiles(ratios, n=4)
    print(f"Kaggle wall / local wall (local run >= 20 s, {len(ratios)} runs): median {st.median(ratios):.2f}, quartiles {q[0]:.2f}-{q[2]:.2f}")


if __name__ == "__main__":
    main()
