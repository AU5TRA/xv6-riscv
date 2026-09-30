#!/usr/bin/env python3
"""Build the decision-point training sets from traces2/ML.

Each train- and val-split stream is replayed under LRU at several capacities;
at a random fraction of evictions, up to MAX_CAND resident candidates are
recorded (always including the one Belady would evict) with all NF features,
their true next-use distance (log1p, capped), and the sequence inputs the GRU
and embedding models need. The sampling rate is set per stream x capacity so
each contributes about ROWS rows.

Output (gitignored): traces2/ml2_cache/<split>_<workload>.npz
Summary:             report/results2/dataset_summary.csv
                     report/results2/feature_diagnostics.csv

    python3 build_datasets.py [--jobs 6]
"""
import argparse
import csv
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

import pagesim as ps

CACHE = ps.ROOT / "traces2" / "ml2_cache"
RESULTS = ps.ROOT / "report" / "results2"
TRAIN_FRACS = ("0.05", "0.1", "0.2")
MAX_CAND = 32
ROWS = {"train": 40_000, "val": 20_000}
BEHAVIOR = "lru"


def job(args):
    stem, frac, split = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    base = ps.baselines()[(stem, frac)]
    evictions = max(base["lru"] - cap, 1)
    per = min(MAX_CAND, cap)
    p = min(1.0, ROWS[split] / (evictions * per))
    max_rows = int(ROWS[split] * 1.5) + 4 * per
    seed = hash((stem, frac)) & 0xFFFFFFFF
    r = ps.record(s, cap, BEHAVIOR, p=p, max_rows=max_rows, seed=seed,
                  seq=True, max_cand=MAX_CAND)
    assert not r["overflow"], (stem, frac)
    assert r["faults"] == base["lru"], (stem, frac, r["faults"], base["lru"])
    vp = s.vpns
    page_vpn = vp[r["page"]]
    ctx = r["ctx"]
    ctx_vpn = np.where(ctx >= s.n_pages, -1, vp[np.minimum(ctx, s.n_pages - 1)])
    return dict(stem=stem, frac=frac, split=split, workload=s.workload,
                cap=cap, p=p, n=len(r["label"]), feat=r["feat"],
                label=r["label"], group=r["group"], is_opt=r["is_opt"],
                hist=r["hist"], page_vpn=page_vpn.astype(np.int32),
                ctx_vpn=ctx_vpn.astype(np.int32))


def within_group_spearman(x, y, g):
    """Mean over decisions of the rank correlation between x and y among
    that decision's candidates -- the ranking power a feature has at the
    moment an eviction is actually decided."""
    order = np.lexsort((x, g))
    rx = np.empty(len(x)); ry = np.empty(len(y))
    starts = np.r_[0, np.nonzero(np.diff(g[order]))[0] + 1, len(g)]
    vals = []
    for a, b in zip(starts[:-1], starts[1:]):
        idx = order[a:b]
        if b - a < 3:
            continue
        xa, ya = x[idx], y[idx]
        if xa.std() == 0 or ya.std() == 0:
            vals.append(0.0)
            continue
        rxa = np.argsort(np.argsort(xa)); rya = np.argsort(np.argsort(ya))
        vals.append(np.corrcoef(rxa, rya)[0, 1])
    return float(np.mean(vals)) if vals else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    jobs = [(stem, frac, split) for split in ("train", "val")
            for stem in ps.stems(split) for frac in TRAIN_FRACS]
    # longest first so the pool doesn't end on one big graph stream
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    jobs.sort(key=lambda j: -refs[j[0]])
    t0 = time.time()
    parts = {}
    summary = []
    with Pool(a.jobs) as pool:
        for d in pool.imap_unordered(job, jobs):
            parts.setdefault((d["split"], d["workload"]), []).append(d)
            summary.append([d["split"], d["workload"], d["stem"], d["frac"],
                            d["cap"], f"{d['p']:.6f}", d["n"]])
            print(f"  {d['split']:<5} {d['stem']:<22} frac={d['frac']:<4} "
                  f"cap={d['cap']:>4} p={d['p']:.5f} rows={d['n']:>6}", flush=True)
    stem_ids = {s: i for i, s in enumerate(ps.stems())}
    diag = []
    for (split, wl), ds in sorted(parts.items()):
        ds.sort(key=lambda d: (d["stem"], d["frac"]))
        off = 0
        groups = []
        for d in ds:            # make group ids unique across parts
            groups.append(d["group"].astype(np.int64) + off)
            off += int(d["group"].max()) + 1 if d["n"] else 0
        out = dict(
            feat=np.concatenate([d["feat"] for d in ds]),
            label=np.concatenate([d["label"] for d in ds]),
            group=np.concatenate(groups),
            is_opt=np.concatenate([d["is_opt"] for d in ds]),
            hist=np.concatenate([d["hist"] for d in ds]),
            page_vpn=np.concatenate([d["page_vpn"] for d in ds]),
            ctx_vpn=np.concatenate([d["ctx_vpn"] for d in ds]),
            stem_id=np.concatenate([np.full(d["n"], stem_ids[d["stem"]], np.int16) for d in ds]),
            frac=np.concatenate([np.full(d["n"], float(d["frac"]), np.float32) for d in ds]),
        )
        np.savez(CACHE / f"{split}_{wl}.npz", **out)
        print(f"{split}_{wl}: {len(out['label']):,} rows, "
              f"{len(np.unique(out['group'])):,} decisions", flush=True)
        if split == "train":
            y = out["label"]
            for j, f in enumerate(ps.FEATURES):
                x = out["feat"][:, j]
                c = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 else 0.0
                wg = within_group_spearman(x, y, out["group"])
                diag.append([wl, f, ps.TIER[f], f"{c:+.4f}", f"{wg:+.4f}"])
    with open(RESULTS / "dataset_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["split", "workload", "stem", "fraction", "frames",
                    "sample_p", "rows"])
        w.writerows(sorted(summary))
    with open(RESULTS / "feature_diagnostics.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["workload", "feature", "tier", "pearson_with_label",
                    "within_decision_spearman"])
        w.writerows(diag)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
