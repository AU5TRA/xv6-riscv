#!/usr/bin/env python3
"""Classical / hand-written policies on every stream at every grid capacity.

    python3 classical.py [--jobs 6]   -> report/results2/classical.csv

Policies: fifo, clock, aging (kernel-faithful), lru, lfu_exact (full-stream
counts), lfu_kernel (the decayed LFU from GawwyDev d1d247f), sd_old (the old
tools/sim.py "StackDistance", which counted first-touch pages rather than
distinct pages), belady.
"""
import argparse
import csv
from multiprocessing import Pool

import pagesim as ps

POLS = ["fifo", "clock", "aging", "lru", "lfu_exact", "lfu_kernel", "sd_old",
        "belady"]
OUT = ps.ROOT / "report" / "results2" / "classical.csv"


def job(stem):
    s = ps.load_stream(stem)
    base = ps.baselines()
    rows = []
    for frac, cap in s.capacities.items():
        fifo = base[(stem, frac)]["fifo"]
        for p in POLS:
            r = ps.run(s, cap, p, max_faults=0 if p in ("fifo", "lru", "belady")
                       else 20 * fifo)
            rows.append([stem, s.split, s.workload, s.variant, frac, cap, p,
                         r["faults"], r["writebacks"], int(r["aborted"])])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    stems = sorted(ps.stems(), key=lambda s: -refs[s])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f, Pool(a.jobs) as pool:
        w = csv.writer(f)
        w.writerow(["stem", "split", "workload", "variant", "fraction", "frames",
                    "policy", "faults", "writebacks", "aborted"])
        for rows in pool.imap_unordered(job, stems):
            w.writerows(rows)
            f.flush()
            print(f"  {rows[0][0]}", flush=True)


if __name__ == "__main__":
    main()
