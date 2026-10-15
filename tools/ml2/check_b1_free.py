#!/usr/bin/env python3
"""Paper handoff B1, the free check: a stream that never has more than 32 candidates (candidates = memory limit + 4, from cost_grid) never
samples, so `ml:global@32` must reproduce `ml:global` exactly (faults, zero-fill faults, evictions, page writes).  Run after B1 is merged.
    python3 check_b1_free.py"""
import csv
from collections import defaultdict

import pagesim as ps

R = ps.ROOT / "report" / "results2"
runs = defaultdict(dict)
for r in csv.DictReader(open(R / "kernel_eval_all.csv")):
    if r["status"] == "ok" and r["policy"] == "ml" and r["model"] in ("global", "global@32"):
        runs[(r["stem"], r["fraction"])][r["model"]] = r
keys = ("swap_faults", "zero_faults", "evictions", "page_writes")
for fr in ("0.05", "0.1", "0.2"):
    small = same = 0
    bad = []
    for (stem, f), d in runs.items():
        if f != fr or len(d) < 2:
            continue
        frames = int(d["global"]["frames"])
        if frames + 4 <= 32:
            small += 1
            if all((d["global"][k] or "0") == (d["global@32"][k] or "0") for k in keys):
                same += 1
            else:
                bad.append(stem)
    both = sum(1 for (s, f), d in runs.items() if f == fr and len(d) == 2)
    print(f"{fr}: streams with both runs {both}; with at most 32 candidates {small}; identical {same}; different {bad}")
