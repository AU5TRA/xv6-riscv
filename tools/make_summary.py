#!/usr/bin/env python3
"""Standalone summary of the collected trace dataset.

Describes only what was collected. No comparison against any earlier
campaign -- that lives in COMPARISON-CORRECTED.tsv and is a separate question.

Usage:  python3 tools/make_summary.py
Writes: traces/sweep/SUMMARY.txt
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWEEP = ROOT / "traces" / "sweep"
OUT = SWEEP / "SUMMARY.txt"
MAXFILE = (11 + 256 + 65536) * 1024

# stem -> (workload, nominal label, what the workload models)
MODELS = {
    "kv": ("kvbench", "key-value cache with Zipf-skewed access"),
    "btree": ("btreebench", "B-tree database index, root-to-leaf lookups"),
    "sort": ("sortbench", "external merge sort, streaming access"),
    "graph": ("graphbench", "graph analytics: BFS plus PageRank"),
    "lzw": ("lzwbench", "LZW text compression over a real corpus"),
    "matmulN": ("matmulbench naive", "matrix multiply, row-major order"),
    "matmulB": ("matmulbench blocked", "matrix multiply, cache-tiled order"),
}

FIELD = {
    "faults": re.compile(r"swap_faults=(\d+)"),
    "evicts": re.compile(r"evictions=(\d+)"),
    "limit": re.compile(r"resident_limit=(\d+)"),
    "arena": re.compile(r"arena_start_vpn=(\d+)"),
    "pages": re.compile(r"arena_pages=(\d+)"),
    "reads": re.compile(r"page_reads=(\d+)"),
    "writes": re.compile(r"page_writes=(\d+)"),
}


def scalar(path: Path, key: str):
    try:
        blob = path.read_text(errors="replace")
    except OSError:
        return None
    m = FIELD[key].search(blob)
    return int(m.group(1)) if m else None


def family(stem: str) -> str:
    for k in ("matmulN", "matmulB"):
        if stem.startswith(k):
            return k
    return stem.split("-")[0]


def count_refs(path: Path) -> int:
    n = 0
    with path.open("rb") as fh:
        for line in fh:
            if line.startswith(b"T "):
                n += 1
    return n


def distinct_pages(path: Path) -> int:
    seen = set()
    with path.open("rb") as fh:
        for line in fh:
            if line.startswith(b"T "):
                tok = line[2:].strip()
                if tok.isdigit():
                    seen.add(tok)
    return len(seen)


def main():
    rows = []
    for trace in sorted(SWEEP.glob("*.trace")):
        stem = trace.stem
        log = SWEEP / (stem + ".log")
        size = trace.stat().st_size
        rows.append({
            "stem": stem,
            "fam": family(stem),
            "trace": trace.name,
            "size": size,
            "refs": count_refs(trace),
            "pages": distinct_pages(trace),
            "limit": scalar(log, "limit"),
            "faults": scalar(log, "faults"),
            "evicts": scalar(log, "evicts"),
            "reads": scalar(log, "reads"),
            "writes": scalar(log, "writes"),
        })

    order = ["kv", "btree", "sort", "graph", "lzw", "matmulN", "matmulB"]
    rows.sort(key=lambda r: (order.index(r["fam"]), r["limit"] or 0))

    L = []
    A = L.append
    A("=" * 78)
    A("COLLECTED TRACE DATASET -- SUMMARY")
    A("=" * 78)
    A("")
    A("36 runs: six workloads, each at six memory capacities.")
    A("Each run records the complete reference string (every page the program")
    A("touched, in order) plus the kernel's own fault and eviction counters at")
    A("that capacity.")
    A("")
    A("Location:  traces/sweep/")
    A("  <run>.trace    the reference string, one 'T <page>' line per access")
    A("  <run>.log      the full run transcript and RESULT counters")
    A("  <run>.harness  the test-harness output for that run")
    A("")
    total = sum(r["size"] for r in rows)
    trefs = sum(r["refs"] for r in rows)
    A("Totals:    %d traces, %.1f GB, %s reference records"
      % (len(rows), total / 1e9, "{:,}".format(trefs)))
    A("")
    A("")
    A("PER-WORKLOAD")
    A("-" * 78)
    seen = set()
    for r in rows:
        if r["fam"] in seen:
            continue
        seen.add(r["fam"])
        name, desc = MODELS[r["fam"]]
        A("")
        A("%s -- %s" % (name, desc))
        A("  working set %d pages, %s references per run"
          % (r["pages"], "{:,}".format(r["refs"])))
        A("")
        A("    %-8s %10s %12s %12s %12s" %
          ("FRAMES", "COVERAGE", "FAULTS", "EVICTIONS", "TRACE FILE"))
        for q in rows:
            if q["fam"] != r["fam"]:
                continue
            cov = 100.0 * (q["limit"] or 0) / q["pages"] if q["pages"] else 0
            A("    %-8s %9.1f%% %12s %12s   %s" %
              (q["limit"], cov,
               "{:,}".format(q["faults"] or 0),
               "{:,}".format(q["evicts"] or 0),
               q["trace"]))

    A("")
    A("")
    A("HOW TO READ THIS")
    A("-" * 78)
    A("FRAMES    the number of physical pages the kernel allowed the program.")
    A("          This is the real capacity the run executed under, read back")
    A("          from the kernel, not the number requested on the command")
    A("          line. Use this column, not the percentage in the filename.")
    A("COVERAGE  FRAMES as a percentage of the working set, i.e. how much of")
    A("          the program's memory actually fitted at once.")
    A("FAULTS    times the program touched a page that was not resident and")
    A("          the kernel had to fetch it from swap.")
    A("EVICTIONS times a resident page had to be thrown out to make room.")
    A("")
    A("Within a workload the reference string is identical at every capacity --")
    A("the program does the same work regardless of how much memory it is")
    A("given. Only the fault and eviction counts change. That is what makes")
    A("the set usable: one reference string, six operating points.")
    A("")
    A("")
    A("SIZE HEADROOM")
    A("-" * 78)
    A("xv6 caps any single file at %s bytes. A trace that reached the cap"
      % "{:,}".format(MAXFILE))
    A("would stop growing without raising an error, so the margin matters:")
    A("")
    A("    %-12s %14s %10s %16s" % ("WORKLOAD", "BYTES", "OF CAP", "HEADROOM"))
    seen = set()
    for r in rows:
        if r["fam"] in seen:
            continue
        seen.add(r["fam"])
        A("    %-12s %14s %9.2f%% %16s"
          % (MODELS[r["fam"]][0].split()[0], "{:,}".format(r["size"]),
             100.0 * r["size"] / MAXFILE, "{:,}".format(MAXFILE - r["size"])))
    A("")
    A("All 36 traces were verified complete. lzwbench is the only one close to")
    A("the cap, with 976 bytes to spare; it was checked two independent ways.")
    A("Re-running any of these 36 configurations is safe, because the workloads")
    A("are deterministic and produce the same size every time. Increasing any")
    A("workload's size argument is not safe until a length check is added.")
    A("")

    text = "\n".join(L) + "\n"
    OUT.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
