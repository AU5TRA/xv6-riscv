#!/usr/bin/env python3
"""Run the host models over the stream manifest before collecting it.

    python3 tools/hostmodel/preflight.py [workload ...]

For every manifest row whose program has a host model (optionally only the
named workloads -- the stem's part before the first "-"), runs the model
with that row's arguments and reports the reference count, the trace's
size, and the pages touched. Fails a row the model rejects (a footprint too
small for that seed, a heap that runs out) or whose trace would exceed the
budget tools/check_streams.py enforces, 90% of xv6's MAXFILE. Trace sizes
assume an arena starting at VPN 30, a little above where every benchmark's
arena starts (22-27), so they are slight overestimates.

Exits non-zero if any row fails. Collecting the manifest costs hours; this
costs minutes.
"""
from __future__ import annotations

import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .check_run import MODELS, predict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST = os.path.join(ROOT, "tools", "streams_manifest.tsv")
MAXFILE = (11 + 256 + 65536) * 1024
BUDGET = int(MAXFILE * 0.9)
ARENA_VPN = 30


def main():
    only = set(sys.argv[1:])
    rows = []
    for line in open(MANIFEST):
        if line.startswith("#") or not line.strip():
            continue
        stem, _est, _phase, cmd = line.rstrip("\n").split("\t")
        if stem.endswith("-rep"):
            continue                      # same arguments as its original
        argv = cmd.split()
        if argv[0] not in MODELS:
            continue
        if only and stem.split("-")[0] not in only:
            continue
        rows.append((stem, argv))
    bad = 0
    print("%-22s %10s %12s %6s %6s  %s" % ("STREAM", "REFS", "BYTES", "PAGES", "W%", "STATUS"))
    for stem, argv in rows:
        t0 = time.time()
        pages = set()
        try:
            res, sink = predict(argv[0], argv[1:], ARENA_VPN)
            # pages touched need a second pass; cheap next to collecting
            from importlib import import_module
            import_module("." + MODELS[argv[0]], __package__).run(
                argv[1:], lambda p, w: pages.add(p))
        except SystemExit as e:
            print("%-22s %10s %12s %6s %6s  FAILED: %s" % (stem, "-", "-", "-", "-", e))
            bad += 1
            continue
        status = "ok"
        if sink.bytes > BUDGET:
            status = "OVER BUDGET"
            bad += 1
        print("%-22s %10s %12s %6d %5.1f%%  %s (%.0fs)"
              % (stem, "{:,}".format(sink.refs), "{:,}".format(sink.bytes), len(pages),
                 100.0 * sink.writes / max(1, sink.refs), status, time.time() - t0),
              flush=True)
    print("%d row(s), %d failed" % (len(rows), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
