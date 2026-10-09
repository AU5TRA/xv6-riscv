#!/usr/bin/env python3
"""Cost of choosing a victim, measured so it does not depend on how busy the host is.

QEMU runs with `-icount shift=0,sleep=off` (Makefile: QEMU_ICOUNT=1): its clock advances with the
instructions the guest executes, 1 timer tick = 100 instructions, so tick counts repeat to within
0.01% whatever else the machine is doing. One run at a time, every policy on the same stream at the
same memory size, each repeated; the kernel counts, per eviction,
  collect_ticks  building the candidate list
  select_ticks   scanning the candidates and choosing the victim (the policy itself)
  path_ticks     the whole eviction except waiting for the swap-out write
FIFO is the floor (it scans nothing): its numbers are the cost of the timer reads and the surrounding code.

    python3 timing_runs.py [--stem kv-A-s5] [--frac 0.1] [--repeats 2]   -> report/results2/timing.csv
"""
import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

import kernel_eval as ke

ROOT = ke.ROOT
OUT = ROOT / "report" / "results2" / "timing.csv"
POLICIES = [("fifo", ""), ("clock", ""), ("aging", ""), ("lfu", ""), ("ml", "global"), ("ml", "kv"),
            ("ml", "kv@32"), ("ml", "kv@16"), ("ml", "cnn-kv"), ("ml", "mlp-kv"), ("ml", "trees-kv"),
            ("ml", "attention-graph"), ("ml", "ranktrees-graph")]


def one(stem, frames, pol, model):
    cmd = ["vmrun", pol] + ([model] if model else []) + ke.command(stem, frames)
    env = dict(os.environ, QEMU_ICOUNT="1")
    p = subprocess.run(["python3", "tools/run_xv6_tests.py", "--cpus", "1", "--timeout", "7200", " ".join(cmd)],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    m = re.search(r"(/\S+\.log)", p.stdout + p.stderr)
    d = ke.parse(open(m.group(1)).read()) if m else None
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stem", default="kv-A-s5")
    ap.add_argument("--frac", default="0.1")
    ap.add_argument("--repeats", type=int, default=2)
    a = ap.parse_args()
    entry = next(e for e in ke.json.load(open(ke.INDEX))["streams"] if e["stem"] == a.stem)
    frames = entry["capacities"][a.frac]
    new = not OUT.exists()
    with open(OUT, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["stem", "fraction", "frames", "policy", "model", "repeat", "evictions", "faults",
                        "candidates_per_eviction", "collect_ticks_per_eviction", "select_ticks_per_eviction",
                        "path_ticks_per_eviction", "select_instructions_per_eviction"])
        for pol, model in POLICIES:
            for rep in range(a.repeats):
                d = one(a.stem, frames, pol, model)
                if not d:
                    print("FAILED", pol, model, flush=True)
                    continue
                ev = max(d["evictions"], 1)
                row = [a.stem, a.frac, frames, pol, model, rep, d["evictions"], d["swap_faults"] + d["zero_faults"],
                       round(d["candidates_scanned"] / ev, 1), round(d["collect_ticks"] / ev, 2),
                       round(d["select_ticks"] / ev, 2), round(d["path_ticks"] / ev, 2),
                       round(100 * d["select_ticks"] / ev)]
                w.writerow(row)
                f.flush()
                print(row, flush=True)


if __name__ == "__main__":
    main()
