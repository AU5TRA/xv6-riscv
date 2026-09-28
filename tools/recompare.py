#!/usr/bin/env python3
"""Rebuild the campaign-1 vs campaign-2 comparison with correct semantics.

The driver's inline comparison calls a reference sequence "different" when it
is in fact identical up to a constant page offset. That offset is real and has
a known cause: vmbench_trace_buf is a 4 KB BSS array, so adding it pushed the
program break up by one page and every sbrk-allocated arena now starts one VPN
higher. A constant relabelling of page numbers preserves every recurrence
distance, so it is irrelevant to Belady and to any replacement policy -- but a
byte-for-byte cmp cannot see that.

The same layout shift also moved the true frame limit, because all six
benchmarks set capacity as VM_SET_LIMIT(settled + margin) and `settled` is
itself a function of the layout. kvbench at margin 26 ran with 30 frames in
campaign 1 and 29 in campaign 2. A fault-count comparison across campaigns is
therefore comparing two capacities, not two instruments, and this tool reports
the limit delta alongside so the number is interpretable.

Usage:
    python3 tools/recompare.py [--out traces/sweep/COMPARISON-CORRECTED.tsv]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEW = ROOT / "traces" / "sweep"

# Reference lines: "R <vpn>" / "W <vpn>", or "T <vpn>" in captures made
# before the access type was recorded. Comparisons are on page numbers.
REF_PREFIXES = (b"T ", b"R ", b"W ")
OLD = ROOT / "traces" / "sweep-prefilesink"

FIELD = {
    "faults": re.compile(rb"swap_faults=(\d+)"),
    "evicts": re.compile(rb"evictions=(\d+)"),
    "limit": re.compile(rb"resident_limit=(\d+)"),
    "arena": re.compile(rb"arena_start_vpn=(\d+)"),
}


def scalar(path: Path, key: str):
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    m = FIELD[key].search(blob)
    return int(m.group(1)) if m else None


def refs_from_log(path: Path):
    """Reference VPNs from a campaign-1 console transcript."""
    # A campaign-1 transcript that was killed mid-flight can end with a
    # half-written line such as "T 4QEMU: Terminated". Skip anything that is
    # not a clean reference rather than aborting the whole comparison.
    out = []
    try:
        with path.open("rb") as fh:
            for line in fh:
                if line[:2] in REF_PREFIXES:
                    tok = line[2:].strip()
                    if tok.isdigit():
                        out.append(int(tok))
    except OSError:
        return None
    return out


def refs_from_trace(path: Path):
    """Reference VPNs from a campaign-2 extracted trace file."""
    return refs_from_log(path)


def count_refs(path: Path) -> int:
    """Line count only. The lzwbench traces are 67MB / 12.3M lines each, so
    parsing every VPN when there is no baseline to compare against would cost
    minutes for nothing."""
    n = 0
    try:
        with path.open("rb") as fh:
            for line in fh:
                if line[:2] in REF_PREFIXES:
                    n += 1
    except OSError:
        return 0
    return n


def compare_sequences(old, new):
    """Return (verdict, offset). Offset is None when not a constant shift."""
    if old is None or new is None:
        return "missing", None
    if len(old) != len(new):
        return "LENGTH %d vs %d" % (len(old), len(new)), None
    if not old:
        return "empty", None
    off = new[0] - old[0]
    for a, b in zip(old, new):
        if b - a != off:
            return "SEQUENCE DIFFERS", None
    return ("identical" if off == 0 else "identical (shift %+d)" % off), off


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(NEW / "COMPARISON-CORRECTED.tsv"))
    args = ap.parse_args()

    rows = []
    for trace in sorted(NEW.glob("*.trace")):
        stem = trace.stem
        newlog = NEW / (stem + ".log")
        oldlog = OLD / (stem + ".log")

        f_new = scalar(newlog, "faults")
        e_new = scalar(newlog, "evicts")
        l_new = scalar(newlog, "limit")

        if not oldlog.exists():
            rows.append((stem, "-", count_refs(trace), "-", f_new, "-",
                         l_new, "-", "no baseline (new)"))
            continue

        f_old = scalar(oldlog, "faults")
        e_old = scalar(oldlog, "evicts")
        l_old = scalar(oldlog, "limit")

        # A campaign-1 run that never reached its RESULT lines has no fault
        # count. Decide that before parsing millions of reference lines.
        if f_old is None:
            rows.append((stem, "-", count_refs(trace), "-", f_new, l_old,
                         l_new, "-", "baseline incomplete"))
            continue

        new_refs = refs_from_trace(trace)
        n_new = len(new_refs) if new_refs else 0
        old_refs = refs_from_log(oldlog)
        n_old = len(old_refs) if old_refs else 0

        if n_old == 0:
            rows.append((stem, n_old, n_new, f_old, f_new, l_old, l_new, "-",
                         "baseline incomplete"))
            continue

        verdict, _off = compare_sequences(old_refs, new_refs)

        # conservation: evictions minus faults should not move
        if e_old is not None and e_new is not None:
            gap_old, gap_new = e_old - f_old, e_new - f_new
            if gap_old != gap_new:
                verdict += "; gap %d->%d" % (gap_old, gap_new)

        dfault = "%+.2f%%" % (100.0 * (f_new - f_old) / f_old)
        rows.append((stem, n_old, n_new, f_old, f_new, l_old, l_new,
                     dfault, verdict))

    hdr = ("RUN", "REFS_OLD", "REFS_NEW", "FAULT_OLD", "FAULT_NEW",
           "LIM_OLD", "LIM_NEW", "DFAULT", "VERDICT")
    fmt = "%-18s %11s %11s %10s %10s %8s %8s %8s  %s"
    lines = [fmt % hdr, fmt % tuple("-" * len(h) for h in hdr)]
    for r in rows:
        lines.append(fmt % tuple("-" if v is None else v for v in r))

    lines += [
        "",
        "REFS_OLD/REFS_NEW  reference-string length. Must match exactly: the",
        "                   workload is deterministic given its seed.",
        "LIM_OLD/LIM_NEW    the frame limit the kernel actually applied. These",
        "                   differ across campaigns because capacity is set as",
        "                   settled+margin and the 4 KB trace buffer shifted",
        "                   the layout. A fault delta accompanied by a limit",
        "                   delta is a capacity difference, not an instrument",
        "                   difference.",
        "VERDICT            'identical (shift +N)' means every reference moved",
        "                   by the same constant -- a relabelling of page",
        "                   numbers that preserves all recurrence structure and",
        "                   is therefore irrelevant to Belady and to any",
        "                   replacement policy.",
    ]

    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text)
    print(text)
    print("wrote " + args.out)


if __name__ == "__main__":
    main()
