#!/usr/bin/env python3
"""Write the patbench streams from the host model instead of booting xv6.

    python3 tools/pat_hostgen.py [--jobs N] [--verify]

For each patbench row of tools/streams_manifest.tsv without a kernel-collected
.ok marker, writes <stem>.trace, <stem>.log and <stem>.ok under
traces/streams/pat/. The reference string is exactly what tools/patbench_model.py
yields, which matches the kernel's trace byte for byte on every kernel-collected
stream (--verify regenerates those and compares). The log has the TRACEHDR /
TRACEEND / RESULT lines stream_dataset.py reads, with the program-side results
(reads, writes, checksum, word_sum) from the model; kernel fault counters are
not invented, and a HOSTGEN line marks the file as host-generated.
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import patbench_model as pm  # noqa: E402

OUT = ROOT / "traces/streams/pat"
ARENA_VPN = 27          # arena_start_vpn of the patbench binary (same for every run)
MODE_ID = {m: i for i, m in enumerate(pm.MODES)}


def render(P, M, N, seed, mode):
    lines = [f"{'W' if w else 'R'} {ARENA_VPN + pg}\n" for pg, w in pm.generate(P, N, seed, mode)]
    return "".join(lines), len(lines)


def log_text(P, M, N, seed, mode, nbytes):
    s = pm.summary(P, N, seed, mode)
    out = [
        "HOSTGEN source=tools/pat_hostgen.py model=tools/patbench_model.py (no xv6 run)",
        f"TRACEHDR workload=patbench params=see RESULT lines below for full parameters seed={seed} "
        f"resident_limit={M + 4} arena_cache_budget={M} policy=0 prefetch_enabled=0 "
        f"arena_start_vpn={ARENA_VPN} arena_pages={P}",
        f"TRACEEND refs={N} bytes={nbytes}",
        f"RESULT footprint_pages={P}", f"RESULT resident_margin={M}", f"RESULT accesses={N}",
        f"RESULT write_permille={pm.WRITE_PERMILLE}",
    ]
    out += [f"RESULT {k}={s[k]}" for k in ("reads", "writes", "checksum", "word_sum")]
    out += ["PASS", "# RESULT PASS", ""]
    return "\n".join(out)


def rows():
    for line in open(ROOT / "tools/streams_manifest.tsv"):
        if line.startswith("#") or not line.strip():
            continue
        stem, _, _, cmd = line.rstrip("\n").split("\t")
        w = cmd.split()
        if w[0] == "patbench":
            yield stem, (int(w[1]), int(w[2]), int(w[3]), int(w[4]), w[5])


def work(item):
    stem, args, verify = item
    text, n = render(*args)
    t = OUT / f"{stem}.trace"
    if verify:
        return stem, t.read_text() == text
    t.write_text(text)
    (OUT / f"{stem}.log").write_text(log_text(*args, len(text)))
    (OUT / f"{stem}.ok").write_text("host-generated\n")
    return stem, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    kernel = {p.stem for p in OUT.glob("*.ok") if p.read_text().strip() != "host-generated"}
    todo = [(s, r, a.verify) for s, r in rows() if (s in kernel) == a.verify]
    with Pool(a.jobs) as p:
        res = p.map(work, todo, chunksize=1)
    bad = [s for s, ok in res if not ok]
    print(f"{'verified' if a.verify else 'generated'} {len(res)} streams, {len(bad)} differ", bad)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
