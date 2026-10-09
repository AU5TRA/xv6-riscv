#!/usr/bin/env python3
"""Noise floor of the linear model: rebuild the training data with different sampling seeds
(BUILD_SEED_SALT), refit the same feature set, and replay it on the same test / held-out cells.
The spread across salts is the part of any model difference that data sampling alone can produce.

    python3 exp_noise.py build [A B ...]   rebuild datasets under traces2/ml2_cache_<salt> (3 min each)
    python3 exp_noise.py run               refit + replay -> report/results2/noise_floor.csv
"""
import csv
import math
import os
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SALTS = ["", "A", "B", "C"]
OUT = ROOT / "report" / "results2" / "noise_floor.csv"
GROUPS = ("K+K+", "F+K")


def cache(salt):
    return ROOT / "traces2" / ("ml2_cache" + (f"_{salt}" if salt else ""))


def build(salts):
    for s in salts:
        env = dict(os.environ, BUILD_SEED_SALT=s, ML2_CACHE=str(cache(s)))
        print("building salt", s, flush=True)
        subprocess.run([sys.executable, "-u", "build_datasets.py", "--jobs", "6"], cwd=HERE, env=env, check=True,
                       stdout=subprocess.DEVNULL)


def job(a):
    salt, group, stem, frac = a
    import models as M
    import pagesim as ps
    spec = SPECS[(salt, group)]
    s = ps.load_stream(stem)
    r = ps.run(s, s.capacities[frac], "learned", M.to_scored(spec), max_faults=3 * CLOCK[(stem, frac)])
    return [salt, group, stem, frac, r["faults"]]


def main():
    global SPECS, CLOCK
    import models as M
    import pagesim as ps
    CLOCK = {(r["stem"], r["fraction"]): int(r["faults"]) for r in csv.DictReader(open(ROOT / "report/results2/classical.csv"))
             if r["policy"] == "clock"}
    final = M.load_models("final_linear")
    SPECS = {}
    for salt in SALTS:
        M.CACHE = cache(salt)
        M.load_part.cache_clear()
        data = M.load_scope("train", "global")
        fitter = M.LinearFitter(data)
        for g in GROUPS:
            f = final[f"global|{g}"]
            spec = fitter.fit(f["features"])
            spec["protect_age"] = f["protect_age"]
            SPECS[(salt, g)] = spec
    stems = [s for s in ps.stems(("test", "heldout")) if (s, "0.1") in CLOCK]
    tasks = [(salt, g, st, fr) for salt in SALTS for g in GROUPS for st in stems for fr in ("0.05", "0.1", "0.2")]
    with Pool(6) as p, open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["salt", "group", "stem", "fraction", "faults"])
        w.writerows(p.map(job, tasks, chunksize=4))
    rows = list(csv.DictReader(open(OUT)))
    for g in GROUPS:
        for salt in SALTS:
            v = [min(int(r["faults"]), 3 * CLOCK[(r["stem"], r["fraction"])]) / CLOCK[(r["stem"], r["fraction"])]
                 for r in rows if r["salt"] == salt and r["group"] == g]
            print(f"{g:5s} salt {salt or '-':2s}  faults/Clock geo-mean {math.exp(np.mean(np.log(v))):.4f} over {len(v)} cells")


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2:] or [s for s in SALTS if s])
    else:
        main()
