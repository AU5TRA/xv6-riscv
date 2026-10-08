#!/usr/bin/env python3
"""Evaluate every trained neural scorer (report/models2/nn/*.json) on its
scope's val / test / held-out streams at 5%, 10% and 20% of distinct pages.

    python3 eval_nn.py [--jobs 6] [--only NAME_SUBSTR]
      -> report/results2/nn_eval.csv (resumable)
"""
import argparse
import csv
import json
import time
from multiprocessing import Pool

import models as M
import pagesim as ps
import train_nn as T

EVAL_FRACS = ("0.1",)
PROTECT = (0, 2)   # probation chosen per model on validation
EVAL_SPLITS = ("val", "test", "heldout")
OUT = ps.ROOT / "report" / "results2" / "nn_eval.csv"
HEADER = ["model", "kind", "scope", "features", "tiers", "protect_age", "stem", "split",
          "workload", "variant", "fraction", "frames", "faults", "writebacks",
          "aborted"]
POLICY = {"mlp": "learned", "gru": "gru", "embed": "embed"}
CLOCK = {(r["stem"], r["fraction"]): int(r["faults"]) for r in
         csv.DictReader(open(ps.ROOT / "report" / "results2" / "classical.csv"))
         if r["policy"] == "clock"}


def tiers_of(spec):
    if spec["kind"] in ("gru", "embed"):
        return "F"
    t = [x for x in ("F", "K", "K+") if any(ps.TIER[f] == x for f in spec["features"])]
    return "+".join(t)


def job(args):
    stem, frac, names = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    limit = min(5 * ps.baselines()[(stem, frac)]["fifo"], 3 * CLOCK[(stem, frac)])
    rows = []
    for name in names:
        spec = json.load(open(M.MODELS / "nn" / f"{name}.json"))
        for pa in PROTECT:
            spec["protect_age"] = pa
            sm = T.embed_scored(spec, s) if spec["kind"] == "embed" else M.to_scored(spec)
            r = ps.run(s, cap, POLICY[spec["kind"]], sm, max_faults=limit)
            scope = name.split("_")[1]
            rows.append([name, spec["kind"], scope, "+".join(spec.get("features", [])),
                         tiers_of(spec), pa, stem, s.split, s.workload, s.variant, frac,
                         cap, r["faults"], r["writebacks"], int(r["aborted"])])
    return stem, frac, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    names = sorted(p.stem for p in (M.MODELS / "nn").glob("*.json") if a.only in p.stem)
    done = set()
    if OUT.exists():
        with open(OUT) as f:
            done = {(r["model"], r["stem"], r["fraction"]) for r in csv.DictReader(f)}
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = []
    for stem in ps.stems(EVAL_SPLITS) + ps.stems("train", "matmul"):
        wl = ps.index_entry(stem)["workload"]
        mine = [n for n in names if n.split("_")[1] in (wl, "global")]
        for frac in EVAL_FRACS:
            todo = [n for n in mine if (n, stem, frac) not in done]
            # one task per model on the big streams so the pool stays balanced
            chunk = 1 if refs[stem] > 2_000_000 else len(todo) or 1
            for i in range(0, len(todo), chunk):
                tasks.append((stem, frac, todo[i:i + chunk]))
    tasks.sort(key=lambda t: -refs[t[0]] * len(t[2]))
    print(f"{len(names)} models, {len(tasks)} tasks", flush=True)
    t0 = time.time()
    new = not OUT.exists()
    with open(OUT, "a", newline="") as f, Pool(a.jobs) as pool:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        for i, (stem, frac, rows) in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            if i % 20 == 0 or i == len(tasks):
                print(f"  [{i}/{len(tasks)}] ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
