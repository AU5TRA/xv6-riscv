#!/usr/bin/env python3
"""How many pages should a sampled eviction look at, chosen on VALIDATION streams only (simulator).

The kernel's global linear score (final_linear global|K+K+, 8-bit integer weights, probation), scan-and-score sampling of k random pages,
on the streams the global model itself was selected on (validation streams of the six training workloads; matmul has none, so its
training streams, as in final.py) at 5, 10 and 20% of their pages, two sampling seeds. Rule, fixed before
running: the smallest k whose faults are within 1% of scoring every page at every memory size (workload-weighted geometric mean).

    python3 exp_sampling_val.py [--jobs 6]   -> report/results2/sampling_val.csv
"""
import argparse
import csv
from multiprocessing import Pool

import exp_sampling_heur as H
import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
KS = (4, 8, 16, 24, 32, 48, 64)
FRACS = ("0.05", "0.1", "0.2")


def job(args):
    stem, frac = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    clock = ps.run(s, cap, "clock")
    rows = [[stem, s.workload, frac, cap, "clock", 0, 0, clock["faults"], clock["evictions"], 0]]
    full = ps.run(s, cap, "learned", H.model())
    rows.append([stem, s.workload, frac, cap, "full", 0, 0, full["faults"], full["evictions"], full["scored"]])
    for k in KS:
        for seed in (1, 2):
            r = ps.run(s, cap, "learned", H.model(sample_k=k, sample_scan=1, sample_seed=seed))
            rows.append([stem, s.workload, frac, cap, "random", k, seed, r["faults"], r["evictions"], r["scored"]])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    six = ("btree", "graph", "kv", "lzw", "matmul", "sort")      # the global model's training workloads; final.py selection_stems at the time
    stems = [st for wl in six for st in (ps.stems("train", "matmul") if wl == "matmul" else ps.stems("val", wl))]
    tasks = [(s, f) for s in stems for f in FRACS]
    with Pool(a.jobs) as pool, open(R / "sampling_val.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stem", "workload", "fraction", "frames", "variant", "k", "seed", "faults", "evictions", "scored"])
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            print(f"  {i}/{len(tasks)}", flush=True)


if __name__ == "__main__":
    main()
