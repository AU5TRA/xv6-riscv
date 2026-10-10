#!/usr/bin/env python3
"""Bring the new content of traces3/ (collected by AU5TRA with a memory sweep) into the stream layout.

traces3/sweep-rw has one trace per (workload, memory percent); the reference string of a program does not depend on the
memory limit, so the copies of one workload are identical (tools/traces3_inventory.py checks this) and one is imported.
What is imported:
  heap-small, heap-mixed, heap-churn   (heapbench: malloc/free churn)
  join-r4, join-uni, join-zipf         (joinbench: hash join)
  spmv-band, spmv-rand                 (spmvbench: sparse matrix-vector)
  patb-<mode>                          AU5TRA's own implementation of the patbench modes (2M accesses), a second implementation to
                                       check ours against
Not imported (identical to streams we already have): btree, graph, kv, lzw, matmul, sort traces, and the three npz files
in traces3/ml.

    python3 tools/import_traces3.py
"""
import re
import shutil
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "traces3" / "sweep-rw"
OUT = ROOT / "traces" / "streams"
NEW = ["heap-small", "heap-mixed", "heap-churn", "join-r4", "join-uni", "join-zipf", "spmv-band", "spmv-rand"]
PAT = ["loop", "scanhot", "scanhotlo", "zipf060", "zipf080", "zipf099", "zipf120", "uniform", "phase", "phaseshort", "switch"]


def pick(name):
    """the copy of this workload with the smallest memory percent"""
    cands = []
    for p in SRC.glob(f"{name}-p*-c*.trace"):
        m = re.fullmatch(rf"{re.escape(name)}-p(\d+)-c(\d+)", p.stem)
        if m:
            cands.append((int(m.group(1)), p))
    return min(cands)[1] if cands else None


def convert(src, wl, variant):
    stem = f"{wl}-{variant}-s1"
    d = OUT / wl
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, d / f"{stem}.trace")
    nrefs = sum(1 for _ in open(d / f"{stem}.trace"))
    nbytes = (d / f"{stem}.trace").stat().st_size
    vpn = np.fromregex(str(d / f"{stem}.trace"), r"[RW] (\d+)", [("v", np.int64)])["v"]
    (d / f"{stem}.log").write_text(
        f"HOSTGEN source=traces3/sweep-rw/{src.name} (AU5TRA's collection; the program is not in this tree)\n"
        f"TRACEHDR workload={wl}-{variant} params=traces3 seed=1 resident_limit=0 arena_cache_budget=0 policy=0 "
        f"prefetch_enabled=0 arena_start_vpn={int(vpn.min())} arena_pages={len(np.unique(vpn))}\n"
        f"TRACEEND refs={nrefs} bytes={nbytes}\nPASS\n# RESULT PASS\n")
    (d / f"{stem}.ok").write_text("traces3\n")
    print(stem, nrefs, len(np.unique(vpn)))


def register_generated(wl, variant, source):
    """a trace already written to traces/streams/<wl>/ by a host model: add its log and marker"""
    stem = f"{wl}-{variant}-s1"
    d = OUT / wl
    t = d / f"{stem}.trace"
    vpn = np.fromregex(str(t), r"[RW] (\d+)", [("v", np.int64)])["v"]
    nrefs = len(vpn)
    (d / f"{stem}.log").write_text(
        f"HOSTGEN source={source} (no xv6 run)\n"
        f"TRACEHDR workload={wl}-{variant} params=hostmodel seed=1 resident_limit=0 arena_cache_budget=0 policy=0 "
        f"prefetch_enabled=0 arena_start_vpn={int(vpn.min())} arena_pages={len(np.unique(vpn))}\n"
        f"TRACEEND refs={nrefs} bytes={t.stat().st_size}\nPASS\n# RESULT PASS\n")
    (d / f"{stem}.ok").write_text("host-generated\n")
    print(stem, nrefs, len(np.unique(vpn)))


def main():
    # chase and Bloom: AU5TRA's exact host models (tools/hostmodel/), run with the manifest's arguments
    for wl, variant in (("chase", "list"), ("chase", "tree"), ("chase", "n256"), ("bloom", "k3"), ("bloom", "k7")):
        if (OUT / wl / f"{wl}-{variant}-s1.trace").exists():
            register_generated(wl, variant, f"tools/hostmodel/{wl}bench.py")
    for name in NEW:
        src = pick(name)
        wl, variant = name.split("-", 1)
        convert(src, wl, variant)
    for mode in PAT:
        src = pick(f"pat-{mode}")
        if src:
            convert(src, "patb", mode)


if __name__ == "__main__":
    main()
