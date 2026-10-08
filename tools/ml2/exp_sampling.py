#!/usr/bin/env python3
"""Sampled scoring: how few pages can an eviction look at before the learned
policy's quality drops?

cache_ext's policies score 5-20 sampled candidates per eviction
(bpf_cache_ext_list_sample); ours scores every resident page (~106 on average
in the kernel runs). Here the selected linear models (8-bit integer weights,
K+K+ tier, per-workload and global) are replayed on the test and held-out
streams at 5/10/20% with only K random residents considered per eviction:

  score  every page is still scanned (A bits read, features updated); only
         the scoring is sampled          -> saves scoring time only
  scan   only the K sampled pages are scanned and scored; the scan-driven
         features (idle, aging, sfreq) of the rest go stale
                                         -> also saves the page-table walks

K in {4, 8, 16, 32, 64}, three sampling seeds each, plus the full-scoring
reference. No retraining: the models were fitted on full-scan features.

    python3 exp_sampling.py [--jobs 6]  -> report/results2/sampling_sweep.csv
"""
import argparse
import csv
import time
from multiprocessing import Pool

import numpy as np

import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
FRACS = ("0.05", "0.1", "0.2")
KS = (4, 8, 16, 32, 64)
SEEDS = (1, 2, 3)
HEADER = ["model", "mode", "k", "seed", "stem", "split", "workload", "fraction", "frames",
          "faults", "writebacks", "aborted", "evictions", "scanned", "scored"]


def int8_model(spec, **kw):
    layers = [(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32))
              for L in spec["layers"]]
    return ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"],
                          std=spec["std"], layers=layers, quant_w=8,
                          protect_age=spec.get("protect_age", 0), **kw)


CLOCK = {(r["stem"], r["fraction"]): int(r["faults"])
         for r in csv.DictReader(open(R / "classical.csv")) if r["policy"] == "clock"}
BASE = ps.baselines()
FINAL = M.load_models("final_linear")


def variants():
    yield "all", 0, 0, {}
    for k in KS:
        for mode, scan in (("score", 0), ("scan", 1)):
            for seed in SEEDS:
                yield mode, k, seed, dict(sample_k=k, sample_scan=scan, sample_seed=seed)


def job(args):
    stem, frac = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    limit = min(5 * BASE[(stem, frac)]["fifo"], 3 * CLOCK[(stem, frac)])
    rows = []
    for mname, key in (("ml_workload", f"{s.workload}|K+K+"), ("ml_global", "global|K+K+")):
        for mode, k, seed, kw in variants():
            r = ps.run(s, cap, "learned", int8_model(FINAL[key], **kw), max_faults=limit)
            rows.append([mname, mode, k, seed, stem, s.split, s.workload, frac, cap,
                         r["faults"], r["writebacks"], int(r["aborted"]), r["evictions"],
                         r["scanned"], r["scored"]])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = [(stem, frac) for stem in ps.stems(("test", "heldout")) for frac in FRACS]
    tasks.sort(key=lambda t: -refs[t[0]])
    out = R / "sampling_sweep.csv"
    t0 = time.time()
    with Pool(a.jobs) as pool, open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            if i % 10 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} cells, {time.time() - t0:.0f}s", flush=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
