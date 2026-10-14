#!/usr/bin/env python3
"""Which k pages should a sampled eviction look at?  Simulator, the 74 kernel streams at 10%.

Same model as the kernel's global linear score (final_linear global|K+K+, 8-bit integer weights, probation), same memory sizes as the
kernel runs (the kernel's 'frames'), the same stream lengths (short pattern / application streams cut to the kernel's access count).
Only the k sampled pages are scanned and scored (sample_scan = 1, as in the kernel).  Variants, for k = 16 and 32:

  random      k random pages (what the kernel runs used), seeds 1-3
  newest      the k/4 most recently loaded pages + random rest, seeds 1-3
  window      k pages in a row in load order, the start moves on by k at each eviction
  oldest      the k oldest loaded pages
  spread      every (count/k)-th page in load order, the start moves on at each eviction
  unseen      pages not seen at their latest scan first (random among them), then random, seeds 1-3

Also the kernel's own numbers for global, global@32 and global@16 and for Clock on the same cells, so the simulator can be checked
against the kernel.   python3 exp_sampling_heur.py [--jobs 3]  -> report/results2/sampling_heuristics.csv
"""
import argparse
import csv
import time
from multiprocessing import Pool

import numpy as np

import kernel_vs_sim as kvs
import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
SPEC = M.load_models("final_linear")["global|K+K+"]
MODES = {"random": 0, "newest": 1, "window": 2, "oldest": 3, "spread": 4, "unseen": 5}
SEEDED = ("random", "newest", "unseen")
HEADER = ["stem", "workload", "frames", "accesses", "variant", "k", "seed", "faults", "aborted", "kernel_faults"]


def model(**kw):
    layers = [(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32)) for L in SPEC["layers"]]
    return ps.ScoredModel("mlp", features=SPEC["features"], mean=SPEC["mean"], std=SPEC["std"], layers=layers, quant_w=8,
                          protect_age=SPEC.get("protect_age", 0), **kw)


def kernel_cells():
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"] or 0)
    d = {}
    for r in csv.DictReader(open(R / "kernel_eval_all.csv")):
        if r["status"] == "ok" and r["fraction"] == "0.1" and (r["policy"], r["model"]) in (("clock", ""), ("ml", "global"), ("ml", "global@32"), ("ml", "global@16")):
            d.setdefault(r["stem"], {"frames": int(r["frames"]), "accesses": int(r["accesses"] or 0), "workload": r["workload"]})[(r["policy"], r["model"])] = f(r)
    return d


def job(args):
    stem, cell = args
    s = ps.load_stream(stem)
    if cell["accesses"]:
        s = kvs.prefix(s, cell["accesses"])
    fr = cell["frames"]
    clock = ps.run(s, fr, "clock")["faults"]
    lim = 3 * clock
    rows = []
    def add(variant, k, seed, r, kern):
        rows.append([stem, cell["workload"], fr, cell["accesses"], variant, k, seed, r["faults"], int(r["aborted"]), kern])
    add("clock", 0, 0, {"faults": clock, "aborted": False}, cell[("clock", "")])
    add("full", 0, 0, ps.run(s, fr, "learned", model(), max_faults=lim), cell[("ml", "global")])
    for k in (32, 16):
        for name, mode in MODES.items():
            for seed in ((1, 2, 3) if name in SEEDED else (1,)):
                r = ps.run(s, fr, "learned", model(sample_k=k, sample_scan=1, sample_seed=seed, sample_mode=mode), max_faults=lim)
                add(name, k, seed, r, cell.get(("ml", f"global@{k}"), "") if name == "random" and seed == 1 else "")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    cells = {s: c for s, c in kernel_cells().items() if all(k in c for k in (("clock", ""), ("ml", "global"), ("ml", "global@32"), ("ml", "global@16")))}
    if a.only:
        cells = {s: c for s, c in cells.items() if s in a.only.split(",")}
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = sorted(cells.items(), key=lambda t: -(t[1]["accesses"] or refs[t[0]]))
    print(len(tasks), "streams", flush=True)
    t0 = time.time()
    with Pool(a.jobs) as pool, open(R / "sampling_heuristics.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            print(f"  {i}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
