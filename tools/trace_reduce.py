#!/usr/bin/env python3
"""Reduce a raw Valgrind Lackey memory trace to the Phase 3 trace format
(WORK_PROMPT3.md Phase 2) so tools/trace_decode.py and tools/sim.py
consume it unchanged.

Input: Lackey's own `--trace-mem=yes` output on stdin, e.g.:
    I  04892b74,5
     L 04a4ddf8,8
     S 1ffefff178,8
(I=instruction fetch, L=data load, S=data store; only L/S matter here
-- page-level DATA access is what the paging simulator reasons about,
not the instruction stream).

Pipeline:
  1. Keep only L/S lines, parse the hex address.
  2. Shift to page granularity (addr >> 12).
  3. Collapse consecutive duplicate page references (lossless for fault
     counting under a stack algorithm: repeatedly re-touching an
     already-resident page without anything else intervening can never
     cause an additional fault).
  4. Compact the sparse VPN space onto a dense 0..N-1 index (first-seen
     order) -- real address spaces are enormous and sparse; the
     simulator only cares about relative page identity, not real
     addresses.
  5. Emit in the existing "TRACEHDR ...\nT <vpn>\n..." format.

NOTE on what this loses: per Gate 2 of WORK_PROMPT.md's original Phase
5 sketch, a fancier byte-delta encoding was once envisioned; since
tools/trace_decode.py and tools/sim.py already consume the simpler
plain-text "T <vpn>" format built in Phase 3, this reduces to THAT
format directly rather than inventing a second one -- there is only
ever one trace format in this suite.
"""
import sys
import argparse


def reduce_stream(lines, workload, params):
    compact = {}
    next_index = 0
    out = []
    last_page = None
    total_raw = 0
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        stripped = line.lstrip()
        if not (stripped.startswith("L ") or stripped.startswith("S ")):
            continue
        # Format: "<op> <hexaddr>,<size>"
        rest = stripped[2:]
        comma = rest.find(",")
        addr_hex = rest[:comma] if comma >= 0 else rest
        try:
            addr = int(addr_hex, 16)
        except ValueError:
            continue
        total_raw += 1
        page = addr >> 12
        if page == last_page:
            continue  # collapse consecutive duplicate
        last_page = page
        if page not in compact:
            compact[page] = next_index
            next_index += 1
        out.append(compact[page])

    header = (f"TRACEHDR workload={workload} params={params} seed=0 "
              f"resident_limit=0 arena_cache_budget=0 policy=0 "
              f"prefetch_enabled=0 arena_start_vpn=0 "
              f"arena_pages={next_index}")
    return header, out, total_raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", required=True,
                     help="workload name, e.g. sqlite_real, redis_real")
    ap.add_argument("--params", default="(see collect_linux_trace.sh)")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    header, refs, total_raw = reduce_stream(sys.stdin, args.workload,
                                             args.params)
    with open(args.output, "w") as f:
        f.write(header + "\n")
        for vpn in refs:
            f.write(f"T {vpn}\n")

    print(f"reduced: {total_raw} raw L/S references -> {len(refs)} "
          f"collapsed page references ({header.split('arena_pages=')[1]} "
          f"unique pages) -> {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
