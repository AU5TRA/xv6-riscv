#!/usr/bin/env python3
"""Cheap follow-up to tools/ml_comprehensive.py: no training at all,
just the two new hand-written policies added to sim.py (Lfu,
StackDistance) run across every workload, to see whether a plain
counter-based heuristic captures the same gain the learned
global_frequency/stack_distance models found in ML_TESTING_REPORT.md,
without any training.

Writes traces/handwritten_results.csv and prints a comparison table
against the best classical (recency-based) policy and the best ML
result already recorded in traces/ml_comprehensive_results.csv.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_decode import decode_split
from sim import run_policy, CAPACITY_FIELD

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "traces"
OUT = TRACES / "handwritten_results.csv"

# same (workload, folder, train, eval, trace-stem) list as ml_comprehensive.py
WORKLOADS = [
    ("btreebench", "btreebench", "btree-p15-c266", "btree-p20-c355", "btreebench"),
    ("kvbench", "kvbench", "kv-p15-c79", "kv-p20-c106", "kvbench"),
    ("sortbench", "sortbench", "sort-p15-c12", "sort-p20-c16", "sortbench"),
    ("graphbench", "graphbench", "graph-p15-c200", "graph-p20-c267", "graphbench"),
    ("lzwbench", "lzwbench", "lzw-p15-c8", "lzw-p20-c10", "lzwbench"),
    ("matmulbench-naive", "matmulbench", "matmulN-c4", "matmulN-c8", "matmulbench-naive"),
    ("matmulbench-blocked", "matmulbench", "matmulB-c4", "matmulB-c8", "matmulbench-blocked"),
]


def main():
    rows = []
    for label, folder, train_stem, eval_stem, trace_stem in WORKLOADS:
        d = TRACES / folder
        train_log = d / f"{train_stem}.log"
        eval_log = d / f"{eval_stem}.log"
        trace_file = d / f"{trace_stem}.trace"
        _, train_refs = decode_split(train_log, trace_file)
        eval_header, eval_refs = decode_split(eval_log, trace_file)
        header, _ = decode_split(train_log, trace_file)
        cap = int(header[CAPACITY_FIELD])
        ev_cap = int(eval_header[CAPACITY_FIELD])

        print(f"\n{label} (capacity={cap}/{ev_cap})")
        for name in ("fifo", "clock", "aging", "lru", "lfu", "stackdist", "belady"):
            tr = run_policy(name, train_refs, cap)["faults"]
            ev = run_policy(name, eval_refs, ev_cap)["faults"]
            rows.append([label, name, cap, ev_cap, tr, ev])
            print(f"  {name:>10s}: train={tr:>8d} held_out={ev:>8d}")

    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workload", "policy", "capacity", "eval_capacity",
                     "train_faults", "held_out_faults"])
        w.writerows(rows)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
