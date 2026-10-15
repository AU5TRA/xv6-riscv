#!/usr/bin/env python3
"""More ways of sampling, aimed at fewer pages per eviction (simulator; the kernel's 74 streams, memory sizes and global linear score).

  random     k random pages (as the kernel runs), seeds 1-2
  pool       k new random pages + the best P candidates kept from the previous eviction (as Redis does), seeds 1-2
  clock      walk the pages in load order from a moving hand, clearing used bits, and score the first k pages found unused
Every run records pages scanned (used bit read) and pages scored per eviction, so a cost can be estimated from the kernel's measured
cost per scanned page and per scored page (exp_sampling_more_report.py).

    python3 exp_sampling_more.py --fraction 0.1 [--jobs 3]  -> report/results2/sampling_more.csv (appends; resumable per stream and fraction)
"""
import argparse
import csv
import time
from multiprocessing import Pool

import kernel_vs_sim as kvs
import pagesim as ps
import exp_sampling_heur as H

R = ps.ROOT / "report" / "results2"
OUT = R / "sampling_more.csv"
HEADER = ["stem", "workload", "fraction", "frames", "accesses", "variant", "k", "pool", "seed", "faults", "aborted", "evictions", "scanned", "scored"]
VARIANTS = [("full", 0, 0, (0,))] + [("random", k, 0, (1, 2)) for k in (4, 8, 16, 32)] + \
           [("pool", k, p, (1, 2)) for k, p in ((4, 4), (4, 8), (8, 8), (8, 16), (16, 16))] + [("clock", k, 0, (0,)) for k in (4, 8, 16, 32)]


def cells(fraction):
    import csv as _c
    f = lambda r: int(r["swap_faults"]) + int(r["zero_faults"] or 0)
    out = {}
    for r in _c.DictReader(open(R / "kernel_eval_all.csv")):
        if r["status"] == "ok" and r["fraction"] == fraction and r["policy"] == "clock":
            out[r["stem"]] = {"frames": int(r["frames"]), "accesses": int(r["accesses"] or 0), "workload": r["workload"]}
    return out


def job(args):
    stem, cell, fraction = args
    s = ps.load_stream(stem)
    if cell["accesses"]:
        s = kvs.prefix(s, cell["accesses"])
    fr = cell["frames"]
    clock = ps.run(s, fr, "clock")
    lim = 3 * clock["faults"]
    rows = [[stem, cell["workload"], fraction, fr, cell["accesses"], "clock", 0, 0, 0, clock["faults"], 0, clock["evictions"], clock["scanned"], 0]]
    for name, k, pool, seeds in VARIANTS:
        for seed in seeds:
            kw = {} if name == "full" else dict(sample_k=k, sample_scan=1, sample_seed=seed,
                                                 sample_mode={"random": 0, "pool": 6, "clock": 7}[name], sample_pool=pool)
            r = ps.run(s, fr, "learned", H.model(**kw), max_faults=lim)
            rows.append([stem, cell["workload"], fraction, fr, cell["accesses"], name, k, pool, seed, r["faults"], int(r["aborted"]),
                         r["evictions"], r["scanned"], r["scored"]])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fraction", default="0.1")
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    c = cells(a.fraction)
    done = set()
    if OUT.exists():
        done = {(r["stem"], r["fraction"]) for r in csv.DictReader(open(OUT))}
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = sorted(((s, v, a.fraction) for s, v in c.items() if (s, a.fraction) not in done), key=lambda t: -(t[1]["accesses"] or refs[t[0]]))
    print(len(tasks), "streams at", a.fraction, flush=True)
    new = not OUT.exists()
    t0 = time.time()
    with Pool(a.jobs) as pool, open(OUT, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            print(f"  {i}/{len(tasks)} {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
