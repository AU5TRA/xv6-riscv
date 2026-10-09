#!/usr/bin/env python3
"""What is in traces3/: for every trace, its workload, memory setting, length, pages, and a fingerprint of the
reference string with the arena offset removed (so identical programs/seeds collapse), and whether the same
string already exists in our own streams (traces/streams).

    python3 tools/traces3_inventory.py   -> traces3/INVENTORY.tsv
"""
import hashlib
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from stream_dataset import read_trace  # noqa: E402


def fingerprint(path):
    vpn, write = read_trace(str(path))
    base = int(vpn.min())
    rel = (vpn - base).astype(np.uint32)
    h = hashlib.sha1(rel.tobytes() + write.tobytes()).hexdigest()[:12]
    return len(vpn), int(len(np.unique(vpn))), int(write.sum()), h, rel, write


def main():
    ours = {}
    for p in sorted((ROOT / "traces/streams").glob("*/*.trace")):
        if "-rep" in p.stem:
            continue
        n, d, w, h, _, _ = fingerprint(p)
        ours.setdefault(h, []).append(p.stem)
    rows = []
    for p in sorted((ROOT / "traces3/sweep-rw").glob("*.trace")):
        m = re.match(r"(.+?)(?:-p(\d+))?-c(\d+)$", p.stem)
        name, pct, cap = m.group(1), m.group(2) or "", m.group(3)
        n, d, w, h, _, _ = fingerprint(p)
        rows.append([p.stem, name, pct, cap, n, d, w, h, ",".join(ours.get(h, []))])
        print(rows[-1], flush=True)
    with open(ROOT / "traces3/INVENTORY.tsv", "w") as f:
        f.write("trace\tworkload\tpercent\tframes\trefs\tpages\twrites\tfingerprint\tsame_as_ours\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")


if __name__ == "__main__":
    main()
