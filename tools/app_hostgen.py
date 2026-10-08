#!/usr/bin/env python3
"""Write the appbench streams from the host model (tools/appbench_model.py) instead of booting xv6.

    python3 tools/app_hostgen.py [--jobs N] [--verify]

Like pat_hostgen.py: <stem>.trace/.log/.ok under traces/streams/app/ for every appbench manifest
row; the log carries a HOSTGEN line and no kernel fault counters. The model equals the kernel's
trace reference by reference for every mode (checked with `appbench_model.py check` on kernel runs).
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import appbench_model as am  # noqa: E402

OUT = ROOT / "traces/streams/app"
ARENA_VPN = 24          # arena_start_vpn of the appbench binary (same for every mode)


def rows():
    for line in open(ROOT / "tools/streams_manifest.tsv"):
        if line.startswith("#") or not line.strip():
            continue
        stem, _, _, cmd = line.rstrip("\n").split("\t")
        w = cmd.split()
        if w[0] == "appbench":
            yield stem, (int(w[1]), int(w[2]), int(w[3]), w[4])


def work(item):
    stem, (margin, N, seed, mode), verify = item
    text = "".join(f"{'W' if w else 'R'} {ARENA_VPN + p}\n" for p, w in am.generate(N, seed, mode))
    if verify:
        return stem, (OUT / f"{stem}.trace").read_text() == text
    s = am.summary(N, seed, mode)
    (OUT / f"{stem}.trace").write_text(text)
    (OUT / f"{stem}.log").write_text("\n".join([
        "HOSTGEN source=tools/app_hostgen.py model=tools/appbench_model.py (no xv6 run)",
        f"TRACEHDR workload=appbench params=see RESULT lines below for full parameters seed={seed} "
        f"resident_limit={margin + 4} arena_cache_budget={margin} policy=0 prefetch_enabled=0 "
        f"arena_start_vpn={ARENA_VPN} arena_pages={am.PAGES[mode]}",
        f"TRACEEND refs={N} bytes={len(text)}", f"RESULT footprint_pages={am.PAGES[mode]}",
        f"RESULT resident_margin={margin}", f"RESULT accesses={N}",
        *[f"RESULT {k}={s[k]}" for k in ("reads", "writes", "checksum", "word_sum")], "PASS", "# RESULT PASS", ""]))
    (OUT / f"{stem}.ok").write_text("host-generated\n")
    return stem, True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with Pool(a.jobs) as p:
        res = p.map(work, [(s, r, a.verify) for s, r in rows()], chunksize=1)
    bad = [s for s, ok in res if not ok]
    print(f"{'verified' if a.verify else 'generated'} {len(res)} streams, {len(bad)} differ", bad)
