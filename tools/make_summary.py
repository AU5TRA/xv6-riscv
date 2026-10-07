#!/usr/bin/env python3
"""Standalone summary of the collected trace dataset.

Describes only what was collected. No comparison against any earlier
campaign -- that lives in COMPARISON-CORRECTED.tsv and is a separate question.

Usage:  python3 tools/make_summary.py
Writes: traces/sweep/SUMMARY.txt
"""

from __future__ import annotations

import collections
import json
import os
import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The campaign to summarise: SWEEP=traces/sweep-rw python3 tools/make_summary.py
SWEEP = ROOT / os.environ.get("SWEEP", "traces/sweep")
OUT = SWEEP / "SUMMARY.txt"
MAXFILE = (11 + 256 + 65536) * 1024

# Reference lines: "R <vpn>" / "W <vpn>", or "T <vpn>" in captures made
# before the access type was recorded.
REF_PREFIXES = (b"T ", b"R ", b"W ")

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

# Workloads whose trace leaves part of the arena itself untraced. Those pages
# compete for frames in ways the FIFO model below cannot represent, and a fit
# would still land on some h, so these are excluded by construction rather
# than by fit quality.
#
# graphbench has traced all five arrays since graph_trace() was added, so its
# entry applies only to captures made before that -- the ones in the legacy
# "T <vpn>" format (see no_fit_reason). lzwbench has traced its input and
# output since it became compress(1)'s encoder; those runs print
# "RESULT hash_slots=", and the entry applies only to runs that do not.
NO_FIT = {
    "graph": "only the edge array is traced; rank, next_rank, visited and "
             "queue are not",
    "lzw": "only the dictionary table is traced; the input and output "
           "buffers are not",
}

# A fit further off than this is printed, but its ARENA/COVERAGE are not
# trusted. The misses are all matmul runs on an eviction cliff, where one
# frame of h changes the eviction count several-fold.
FIT_TOLERANCE = 0.05

FIELD = {
    "faults": re.compile(r"swap_faults=(\d+)"),
    "evicts": re.compile(r"RESULT evictions=(\d+)"),
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
            if line[:2] in REF_PREFIXES:
                n += 1
    return n


def distinct_pages(path: Path) -> int:
    seen = set()
    with path.open("rb") as fh:
        for line in fh:
            if line[:2] in REF_PREFIXES:
                tok = line[2:].strip()
                if tok.isdigit():
                    seen.add(tok)
    return len(seen)


def load_refs(path: Path) -> list:
    with path.open("rb") as fh:
        return [int(line[2:]) for line in fh if line[:2] in REF_PREFIXES]


def no_fit_reason(fam: str, trace: Path, log: Path):
    """Why a workload's trace cannot be fitted, or None if it can."""
    if fam == "graph":
        with trace.open("rb") as fh:
            legacy = fh.read(2) == b"T "
        return NO_FIT["graph"] if legacy else None
    if fam == "lzw":
        legacy = "RESULT hash_slots=" not in log.read_text(errors="replace")
        return NO_FIT["lzw"] if legacy else None
    return NO_FIT.get(fam)


def traceend(log: Path):
    """(refs, bytes) from the run's TRACEEND line, or None if it predates it."""
    m = re.search(r"TRACEEND refs=(\d+) bytes=(\d+)", log.read_text(errors="replace"))
    return (int(m.group(1)), int(m.group(2))) if m else None


def fifo_hot_evictions(refs, limit: int, hot: int) -> int:
    """Evictions FIFO makes at `limit` frames when `hot` untraced pages
    (code, stack) are always in use: an evicted hot page faults straight
    back in, taking the next-oldest frame. Mirrors choose_fifo() in
    kernel/vmpage.c, which evicts by load order with no exemption for the
    program's own text."""
    queue = collections.deque(-(i + 1) for i in range(hot))
    resident = set(queue)
    evictions = 0
    for vpn in refs:
        if vpn in resident:
            continue
        pending = [vpn]
        while pending:
            page = pending.pop()
            if len(resident) >= limit:
                victim = queue.popleft()
                resident.discard(victim)
                evictions += 1
                if victim < 0:
                    pending.append(victim)
            resident.add(page)
            queue.append(page)
    return evictions


def fit_untraced(refs, limit: int, kernel_evictions: int, max_hot: int):
    """The number of always-hot untraced pages that best reproduces the
    kernel's eviction count, and the relative error of that fit. `max_hot`
    bounds the search by the pages that exist outside the arena at all."""
    if not kernel_evictions:
        return None
    best = None
    for hot in range(0, min(limit - 1, max_hot) + 1):
        ev = fifo_hot_evictions(refs, limit, hot)
        err = (ev - kernel_evictions) / kernel_evictions
        if best is None or abs(err) < abs(best[1]):
            best = (hot, err)
        if ev > 1.5 * kernel_evictions:
            break
    return best


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
            "below_arena": scalar(log, "arena"),
            "faults": scalar(log, "faults"),
            "evicts": scalar(log, "evicts"),
            "reads": scalar(log, "reads"),
            "writes": scalar(log, "writes"),
            "traceend": traceend(log),
            "no_fit": no_fit_reason(family(stem), trace, log),
        })

    order = ["kv", "btree", "sort", "graph", "lzw", "matmulN", "matmulB"]
    rows.sort(key=lambda r: (order.index(r["fam"]), r["limit"] or 0))

    # The reference string is identical at every capacity of a workload
    # configuration, so it is loaded once per configuration for the fits. A
    # workload can have more than one (lzw at two repeat counts); keying by
    # family alone fitted every lzw run against the first one's string.
    refs_by_cfg = {}
    for r in rows:
        r["fit"] = None
        if r["no_fit"] or not r["limit"]:
            continue
        cfg = (r["fam"], r["refs"])
        if cfg not in refs_by_cfg:
            refs_by_cfg[cfg] = load_refs(SWEEP / r["trace"])
        # Pages below the arena (text, data, stack) are the only untraced
        # pages these workloads have, so they bound the fit.
        r["fit"] = fit_untraced(refs_by_cfg[cfg], r["limit"],
                                r["evicts"], r["below_arena"] or 0)
    refs_by_cfg.clear()

    L = []
    A = L.append
    A("=" * 78)
    A("COLLECTED TRACE DATASET -- SUMMARY")
    A("=" * 78)
    A("")
    # matmulN/matmulB are one workload in two variants, at fewer capacities.
    per_fam = collections.Counter(r["fam"] for r in rows)
    workloads = sorted({MODELS[f][0].split()[0] for f in per_fam})
    caps = sorted(set(per_fam.values()), reverse=True)
    A("%d runs: %d workload%s%s, at %s memory"
      % (len(rows), len(workloads), "" if len(workloads) == 1 else "s",
         " (matmulbench in two variants)" if "matmulN" in per_fam else "",
         " or ".join(str(c) for c in caps)))
    A("capacities each.")
    A("Each run records the reference string of the workload's own data (every")
    A("traced arena page it touched, in order) plus the kernel's own fault and")
    A("eviction counters at that capacity. The program's code and stack are not")
    A("traced, but they share the frame limit; see UNTRACED below.")
    A("")
    A("Location:  %s/" % SWEEP.relative_to(ROOT).as_posix())
    A("  <run>.trace    the reference string, one 'R <page>' (read) or 'W <page>'")
    A("                 (write) line per access; 'T <page>' in captures")
    A("                 made before the access type was recorded")
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
        for pages, refs in sorted({(q["pages"], q["refs"]) for q in rows
                                   if q["fam"] == r["fam"]}):
            A("  working set %d traced pages, %s references per run"
              % (pages, "{:,}".format(refs)))
        A("")
        A(" %5s %8s %5s %8s %6s %9s %9s %s" %
          ("LIMIT", "UNTRACED", "ARENA", "COVERAGE", "FIT",
           "FAULTS", "EVICTIONS", "TRACE FILE"))
        for q in rows:
            if q["fam"] != r["fam"]:
                continue
            fit = q["fit"]
            if fit is None:
                untraced = arena = cover = err = "-"
            else:
                hot, e = fit
                untraced = str(hot)
                err = "%+.1f%%" % (100.0 * e)
                if abs(e) <= FIT_TOLERANCE and q["pages"]:
                    arena = str(q["limit"] - hot)
                    cover = "%.1f%%" % (100.0 * (q["limit"] - hot) / q["pages"])
                else:
                    arena = cover = "?"
            A(" %5s %8s %5s %8s %6s %9s %9s %s" %
              (q["limit"], untraced, arena, cover, err,
               "{:,}".format(q["faults"] or 0),
               "{:,}".format(q["evicts"] or 0),
               q["trace"]))
        if r["no_fit"]:
            A("")
            for line in textwrap.wrap(
                    "No UNTRACED/ARENA/COVERAGE: %s. FAULTS and EVICTIONS "
                    "include those untraced pages, so they cannot be "
                    "reproduced by replaying this trace." % r["no_fit"],
                    width=76):
                A("  " + line)

    A("")
    A("")
    A("HOW TO READ THIS")
    A("-" * 78)
    A("LIMIT     the number of physical pages the kernel allowed the whole")
    A("          process -- traced data AND its own code and stack. Read back")
    A("          from the kernel, not the number requested on the command")
    A("          line. Use this column, not the percentage in the filename.")
    A("UNTRACED  estimated frames held by untraced code/stack pages. Measured,")
    A("          not assumed: the number of always-in-use extra pages for which")
    A("          FIFO over this trace reproduces the kernel's EVICTIONS. FIFO")
    A("          evicts the program's own text like any other page, and it")
    A("          faults straight back in, so these pages hold frames")
    A("          throughout the run.")
    A("ARENA     LIMIT - UNTRACED: frames actually available to the traced")
    A("          pages. This is the capacity to simulate the trace at.")
    A("COVERAGE  ARENA as a percentage of the traced working set.")
    A("FIT       how far that FIFO replay lands from the kernel's EVICTIONS.")
    A("          Beyond +/-%.0f%% ARENA and COVERAGE are shown as '?': those runs"
      % (100 * FIT_TOLERANCE))
    A("          sit on an eviction cliff, where one frame changes evictions")
    A("          several-fold, so no single UNTRACED value is meaningful.")
    A("FAULTS    times the process touched a page that was not resident and")
    A("          the kernel had to fetch it from swap (code and stack included).")
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
    A("would lose its tail, so the margin matters:")
    A("")
    A("    %-12s %14s %10s %16s" % ("WORKLOAD", "BYTES", "OF CAP", "HEADROOM"))
    seen = set()
    for r in rows:
        if (r["fam"], r["size"]) in seen:
            continue
        seen.add((r["fam"], r["size"]))
        A("    %-12s %14s %9.2f%% %16s"
          % (MODELS[r["fam"]][0].split()[0], "{:,}".format(r["size"]),
             100.0 * r["size"] / MAXFILE, "{:,}".format(MAXFILE - r["size"])))
    A("")
    checked = [r for r in rows if r["traceend"]]
    matched = [r for r in checked if r["traceend"] == (r["refs"], r["size"])]
    if checked and len(checked) == len(rows):
        for line in textwrap.wrap(
                "Completeness: %d of %d traces match the TRACEEND count their "
                "run reported (references and bytes). A trace that would outgrow "
                "the cap now stops its run with an error instead of passing."
                % (len(matched), len(rows)), width=78):
            A(line)
    else:
        for line in textwrap.wrap(
                "Completeness: these traces predate the TRACEEND check, so "
                "nothing in the capture proves they are whole. lzwbench's are "
                "known to be truncated: they end 976 bytes short of the cap, at "
                "58%% of the references the run made.", width=78):
            A(line)
    A("")

    text = "\n".join(L) + "\n"
    with open(OUT, "w", newline="\n") as fh:
        fh.write(text)
    # The same numbers, machine-readable, for documents built from them.
    with open(SWEEP / "SUMMARY.json", "w", newline="\n") as fh:
        json.dump(rows, fh, indent=1)
    print(text)


if __name__ == "__main__":
    main()
