#!/usr/bin/env python3
"""Linear models on every feature combination, every scope, every eval
stream.

Feature sets (300):
  * every non-empty subset of the four full-stream features F (15)
  * every non-empty subset of the eight kernel-observable features K u K+ (255)
  * each F subset joined with all of K, and with all of K u K+ (30)
Scopes: per-workload (btree/graph/kv/matmul/sort) and one global model.
Each model is evaluated on its scope's val, test and held-out streams at
5%, 10% and 20% of distinct pages. A run that exceeds 5x FIFO's faults is
stopped and marked aborted (its counts are lower bounds).

    python3 sweep_linear.py [--jobs 6]
      -> report/models2/linear_<scope>.json
      -> report/results2/linear_sweep.csv   (resumable)
"""
import argparse
import csv
import itertools
import time
from multiprocessing import Pool

import numpy as np

import models as M
import pagesim as ps

F = ps.FEATURES[:4]
KK = ps.FEATURES[4:]
K = ps.FEATURES[4:10]
EVAL_FRACS = ("0.05", "0.1", "0.2")
EVAL_SPLITS = ("val", "test", "heldout")
SCOPES = M.WORKLOADS + ["global"]
OUT = ps.ROOT / "report" / "results2" / "linear_sweep.csv"
HEADER = ["scope", "features", "n_features", "tiers", "stem", "split",
          "workload", "variant", "fraction", "frames", "faults", "writebacks",
          "aborted"]


def subsets(xs):
    return [list(c) for r in range(1, len(xs) + 1)
            for c in itertools.combinations(xs, r)]


def feature_sets():
    sets = subsets(F) + subsets(KK)
    for fs in subsets(F):
        sets.append(fs + K)
        sets.append(fs + KK)
    seen, out = set(), []
    for s in sets:
        key = "+".join(s)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def tiers(fs):
    t = []
    for tier in ("F", "K", "K+"):
        if any(ps.TIER[f] == tier for f in fs):
            t.append(tier)
    return "+".join(t)


def job(args):
    stem, frac, jobs = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    limit = 5 * ps.baselines()[(stem, frac)]["fifo"]
    rows = []
    for scope, key, spec in jobs:
        r = ps.run(s, cap, "learned", M.to_scored(spec), max_faults=limit)
        rows.append([scope, key, len(spec["features"]), tiers(spec["features"]),
                     stem, s.split, s.workload, s.variant, frac, cap,
                     r["faults"], r["writebacks"], int(r["aborted"])])
    return stem, frac, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    sets = feature_sets()
    print(f"{len(sets)} feature sets x {len(SCOPES)} scopes", flush=True)
    specs = {}
    for scope in SCOPES:
        fitter = M.LinearFitter(M.load_scope("train", scope))
        specs[scope] = {"+".join(fs): fitter.fit(fs) for fs in sets}
        M.save_models(f"linear_{scope}", specs[scope])
        print(f"  fitted {scope} ({time.time() - t0:.0f}s)", flush=True)
    M.load_part.cache_clear()

    done = set()
    if OUT.exists():
        with open(OUT) as f:
            for r in csv.DictReader(f):
                done.add((r["stem"], r["fraction"]))
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = []
    for stem in ps.stems(EVAL_SPLITS):
        wl = ps.index_entry(stem)["workload"]
        for frac in EVAL_FRACS:
            if (stem, frac) in done:
                continue
            jobs = [(sc, key, spec) for sc in (wl, "global")
                    for key, spec in specs[sc].items()]
            tasks.append((stem, frac, jobs))
    tasks.sort(key=lambda t: -refs[t[0]] * float(t[1]) ** 0)
    print(f"{len(tasks)} stream x capacity tasks to run "
          f"({len(done)} already done)", flush=True)
    new = not OUT.exists()
    with open(OUT, "a", newline="") as f, Pool(a.jobs) as pool:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        for i, (stem, frac, rows) in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            nab = sum(r[-1] for r in rows)
            print(f"  [{i}/{len(tasks)}] {stem:<22} {frac:<4} {len(rows)} runs, "
                  f"{nab} aborted  ({time.time() - t0:.0f}s)", flush=True)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
