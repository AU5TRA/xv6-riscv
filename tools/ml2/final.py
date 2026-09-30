#!/usr/bin/env python3
"""Final model selection and evaluation for the linear scorers (phase B).

Nested selection, on validation data only (matmul, which has no validation
streams, uses its training streams):
  1. from the 10% sweep, the 5 best feature subsets of each scope x tier
     group by validation geo-mean faults/Clock;
  2. each with probation 0, 1, 2 or 4 scans, replayed on the validation
     cells at 5%, 10% and 20%;
  3. the best (subset, probation) of each scope x group is kept.
Only the kept models are then replayed on test and held-out, at all three
capacities.

    python3 final.py select [--jobs 6]   -> report/results2/final_val.csv
    python3 final.py test   [--jobs 6]   -> report/results2/final_test.csv,
                                            report/models2/final_linear.json
"""
import argparse
import csv
import math
import time
from collections import defaultdict
from multiprocessing import Pool

import numpy as np

import analyze
import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
FRACS = ("0.05", "0.1", "0.2")
PROTECT = (0, 1, 2, 4)
TOP = 5
GROUPS = ["F", "K", "K+K+", "F+K", "any"]
HEADER = ["scope", "group", "features", "protect_age", "stem", "split", "workload",
          "fraction", "frames", "faults", "writebacks", "aborted"]


def clock():
    return {(r["stem"], r["fraction"]): int(r["faults"])
            for r in csv.DictReader(open(R / "classical.csv")) if r["policy"] == "clock"}


CLOCK = clock()


def selection_stems(scope):
    wls = M.WORKLOADS if scope == "global" else [scope]
    out = []
    for wl in wls:
        out += ps.stems("train", "matmul") if wl == "matmul" else ps.stems("val", wl)
    return out


def job(args):
    stem, frac, todo = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    limit = min(5 * ps.baselines()[(stem, frac)]["fifo"], 3 * CLOCK[(stem, frac)])
    rows = []
    for scope, group, key, pa, spec in todo:
        r = ps.run(s, cap, "learned", M.to_scored(spec, protect_age=pa), max_faults=limit)
        rows.append([scope, group, key, pa, stem, s.split, s.workload, frac, cap,
                     r["faults"], r["writebacks"], int(r["aborted"])])
    return rows


def dispatch(tasks, out, jobs):
    with open(out, "w", newline="") as f, Pool(jobs) as pool:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            if i % 10 == 0 or i == len(tasks):
                print(f"  [{i}/{len(tasks)}]", flush=True)


def candidates():
    """scope x group -> the TOP subsets by validation score at 10%."""
    rows = list(csv.DictReader(open(R / "linear_sweep.csv")))
    extras = [r for r in csv.DictReader(open(R / "extras.csv"))
              if r["kind"] == "matmul_train"] if (R / "extras.csv").exists() else []
    score = defaultdict(list)          # (scope, features) -> log ratios
    for r in [x for x in rows if x["split"] == "val"] + extras:
        c = CLOCK[(r["stem"], r["fraction"])]
        score[(r["scope"], r["features"])].append(
            math.log(min(int(r["faults"]), 3 * c) / c))
    out = {}
    for scope in M.WORKLOADS + ["global"]:
        keyed = [(np.mean(v), f) for (sc, f), v in score.items() if sc == scope]
        for g in GROUPS:
            ok = [x for x in keyed if g == "any" or
                  (analyze.classify(x[1]) in ("K", "K+K+") if g == "K+K+" else
                   analyze.classify(x[1]) == g)]
            out[(scope, g)] = [f for _, f in sorted(ok)[:TOP]]
    return out


def select(jobs):
    cands = candidates()
    specs = {sc: M.load_models(f"linear_{sc}") for sc in M.WORKLOADS + ["global"]}
    per_stem = defaultdict(list)
    for (scope, g), feats in cands.items():
        for key in feats:
            for pa in PROTECT:
                for stem in selection_stems(scope):
                    per_stem[stem].append((scope, g, key, pa, specs[scope][key]))
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = []
    for stem, todo in per_stem.items():
        # de-duplicate (scope, key, pa) shared by several groups
        seen, uniq = set(), []
        for t in todo:
            k = (t[0], t[2], t[3])
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        chunk = 40 if refs[stem] > 2_000_000 else len(uniq)
        for frac in FRACS:
            for i in range(0, len(uniq), chunk):
                tasks.append((stem, frac, uniq[i:i + chunk]))
    tasks.sort(key=lambda t: -refs[t[0]] * len(t[2]))
    print(f"{len(tasks)} selection tasks", flush=True)
    dispatch(tasks, R / "final_val.csv", jobs)


def chosen():
    cands = candidates()
    score = defaultdict(list)
    for r in csv.DictReader(open(R / "final_val.csv")):
        c = CLOCK[(r["stem"], r["fraction"])]
        score[(r["scope"], r["features"], int(r["protect_age"]))].append(
            math.log(min(int(r["faults"]), 3 * c) / c))
    out = {}
    for (scope, g), feats in cands.items():
        best = min(((np.mean(score[(scope, f, pa)]), f, pa) for f in feats for pa in PROTECT
                    if score.get((scope, f, pa))), default=None)
        if best:
            out[(scope, g)] = (best[1], best[2], float(np.exp(best[0])))
    return out


def test(jobs):
    ch = chosen()
    specs = {sc: M.load_models(f"linear_{sc}") for sc in M.WORKLOADS + ["global"]}
    final = {}
    for (scope, g), (key, pa, v) in ch.items():
        final[f"{scope}|{g}"] = dict(specs[scope][key], protect_age=pa, val_geo_ratio=v)
        print(f"  {scope:<7} {g:<5} {key:<55} probation={pa} val={v:.3f}")
    M.save_models("final_linear", final)
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = []
    for stem in ps.stems(("test", "heldout")):
        wl = ps.index_entry(stem)["workload"]
        todo = [(sc, g, key, pa, specs[sc][key]) for (sc, g), (key, pa, _) in ch.items()
                if sc in (wl, "global")]
        for frac in FRACS:
            tasks.append((stem, frac, todo))
    tasks.sort(key=lambda t: -refs[t[0]])
    dispatch(tasks, R / "final_test.csv", jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["select", "test"])
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    (select if a.what == "select" else test)(a.jobs)
    print(f"{a.what} done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
