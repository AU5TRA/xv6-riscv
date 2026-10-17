#!/usr/bin/env python3
"""Figure data for the review revision (main2.tex), from report/results2; complements make_figdata.py (not changed).

  figures/data/cdf_<policy>.csv   per-stream faults / Clock at 10% memory, sorted, with the cumulative share of streams (Figure fig:dist)
  figures/data/kval_<size>.csv    validation streams: faults with k sampled pages / faults scoring every page (Figure fig:dist, right)

    python3 make_figdata2.py
"""
import csv
import math
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
R = HERE.parents[1] / "report" / "results2"
OUT = HERE / "figures" / "data"


def gm(xs):
    xs = list(xs)
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def cdf():
    d = defaultdict(list)
    for r in csv.DictReader(open(R / "paper_extra_cdf.csv")):
        if r["fraction"] == "0.1":
            d[r["policy"]].append(float(r["ratio"]))
    for pol, name in (("ml:global@32", "policy"), ("arck", "arc"), ("lhd", "lhd")):
        v = sorted(d[pol])
        with open(OUT / f"cdf_{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ratio", "share"])
            w.writerow([round(min(v[0], 0.5), 4), 0])
            for i, x in enumerate(v, 1):
                w.writerow([round(min(x, 2.0), 4), round(i / len(v), 4)])     # clipped at 2 for the axis
        print(name, len(v), "streams; worse than Clock on", sum(x > 1.005 for x in v), "; better on", sum(x < 0.995 for x in v))


def kval():
    rows = list(csv.DictReader(open(R / "sampling_val.csv")))
    full = {(r["stem"], r["fraction"]): int(r["faults"]) for r in rows if r["variant"] == "full"}
    res = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["variant"] == "random":
            res[(int(r["k"]), r["fraction"])][r["stem"]].append(int(r["faults"]) / full[(r["stem"], r["fraction"])])
    for fr, name in (("0.05", "05"), ("0.1", "10"), ("0.2", "20")):
        with open(OUT / f"kval_{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["k", "ratio"])
            for k in sorted({k for k, f2 in res if f2 == fr}):
                by = defaultdict(list)
                for s, v in res[(k, fr)].items():
                    by[s.split("-")[0]].append(gm(v))
                w.writerow([k, round(gm(gm(v) for v in by.values()), 4)])


if __name__ == "__main__":
    cdf()
    kval()
