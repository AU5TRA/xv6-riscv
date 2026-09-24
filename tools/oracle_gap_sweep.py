#!/usr/bin/env python3
"""Run the full FIFO/Clock/Aging/LRU/Belady comparison across every run
in traces/ (AU5TRA's per-workload sweep archive), using sim.py's own
policy implementations directly (in-process, not 36 subprocess spawns).
Writes traces/oracle_gap.csv and prints a compact summary.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_decode import decode_split
from sim import run_policy, CAPACITY_FIELD

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "traces"

# folder -> (log glob, trace-file resolver)
WORKLOADS = ["btreebench", "kvbench", "sortbench", "graphbench", "lzwbench",
             "matmulbench"]


def trace_for(folder: Path, log: Path) -> Path:
    if folder.name == "matmulbench":
        variant = "naive" if log.stem.startswith("matmulN") else "blocked"
        return folder / f"matmulbench-{variant}.trace"
    traces = list(folder.glob("*.trace"))
    assert len(traces) == 1, f"{folder}: expected 1 .trace, found {traces}"
    return traces[0]


def main():
    rows = []
    for wl in WORKLOADS:
        folder = TRACES / wl
        if not folder.exists():
            print(f"skip {wl}: no traces/{wl}/", file=sys.stderr)
            continue
        for log in sorted(folder.glob("*.log")):
            trace = trace_for(folder, log)
            header, refs = decode_split(log, trace)
            if not refs:
                print(f"skip {log}: no references decoded", file=sys.stderr)
                continue
            capacity = int(header[CAPACITY_FIELD])
            variant = (log.stem.split("-")[0] if wl == "matmulbench"
                       else wl)
            result = {"workload": variant, "run": log.stem,
                      "capacity": capacity, "total_refs": len(refs)}
            for name in ("fifo", "clock", "aging", "lru", "belady"):
                r = run_policy(name, refs, capacity)
                result[f"{name}_faults"] = r["faults"]
                result[f"{name}_evictions"] = r["evictions"]
            rows.append(result)
            print(f"{result['run']:<24s} capacity={capacity:>6d} "
                  f"fifo={result['fifo_faults']:>7d} "
                  f"clock={result['clock_faults']:>7d} "
                  f"aging={result['aging_faults']:>7d} "
                  f"lru={result['lru_faults']:>7d} "
                  f"belady={result['belady_faults']:>7d}",
                  file=sys.stderr)

    out = TRACES / "oracle_gap.csv"
    fields = ["workload", "run", "capacity", "total_refs",
              "fifo_faults", "fifo_evictions", "clock_faults",
              "clock_evictions", "aging_faults", "aging_evictions",
              "lru_faults", "lru_evictions", "belady_faults",
              "belady_evictions"]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out} ({len(rows)} runs)", file=sys.stderr)


if __name__ == "__main__":
    main()
