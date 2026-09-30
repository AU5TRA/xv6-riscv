#!/usr/bin/env python3
"""Checks pagesim.c before anything is built on it.

1. FIFO / LRU / Belady fault counts must equal traces2/ML/baselines.tsv
   (computed independently by tools/stream_dataset.py) on every stream and
   every capacity of the grid.
2. Belady must be <= every other policy everywhere (it is optimal).
3. Recorded feature rows must match a brute-force Python recomputation on a
   small stream (tests/feature_check).

    python3 validate.py [--jobs 6]
"""
import argparse
import sys
from multiprocessing import Pool

import numpy as np

import pagesim as ps

OTHER = ["clock", "aging", "lfu_exact", "lfu_kernel", "sd_old"]


def check_stream(stem):
    s = ps.load_stream(stem)
    base = ps.baselines()
    bad, rows = [], []
    for frac, cap in s.capacities.items():
        want = base[(stem, frac)]
        assert want["frames"] == cap, (stem, frac)
        got = {p: ps.run(s, cap, p)["faults"] for p in ("fifo", "lru", "belady")}
        for p in got:
            if got[p] != want[p]:
                bad.append((stem, frac, p, got[p], want[p]))
        others = {p: ps.run(s, cap, p)["faults"] for p in OTHER}
        for p, f in others.items():
            if f < got["belady"]:
                bad.append((stem, frac, p + "<belady", f, got["belady"]))
        rows.append((stem, frac, cap, got, others))
    return bad, rows


def brute_features(s, cap, t_stop):
    """Python recomputation of the F features for residents at the first
    eviction at or after reference t_stop, under LRU behaviour."""
    from collections import OrderedDict
    res = OrderedDict()
    last, freq, writes = {}, {}, {}
    for t in range(s.n):
        p = int(s.page[t])
        if p not in res and len(res) >= cap and t >= t_stop:
            out = {}
            for q in res:
                sd = len({int(x) for x in s.page[last[q] + 1:t]})
                out[q] = (np.log1p(t - last[q]), np.log1p(freq[q]),
                          np.log1p(sd), writes[q] / freq[q])
            return t, out
        if p in res:
            res.move_to_end(p)
        else:
            if len(res) >= cap:
                res.popitem(last=False)
            res[p] = True
        last[p] = t
        freq[p] = freq.get(p, 0) + 1
        writes[p] = writes.get(p, 0) + int(s.write[t])
    return None, {}


def feature_check():
    s = ps.load_stream("kv-A-s1")
    cap = s.capacities["0.1"]
    rec = ps.record(s, cap, "lru", p=1.0, max_rows=4_000_000)
    assert not rec["overflow"]
    feat, grp = rec["feat"], rec["group"]
    # group g = g-th eviction; LRU fault count - cap evictions happen
    for g in (0, 17, 400, 3000):
        rows = np.nonzero(grp == g)[0]
        # find the reference index of the g-th eviction by replaying LRU
        from collections import OrderedDict
        res, ev, t_ev = OrderedDict(), -1, None
        for t in range(s.n):
            p = int(s.page[t])
            if p in res:
                res.move_to_end(p); continue
            if len(res) >= cap:
                ev += 1
                if ev == g:
                    t_ev = t; break
                res.popitem(last=False)
            res[p] = True
        t, want = brute_features(s, cap, t_ev)
        assert t == t_ev
        # candidate identity isn't recorded without seq=True; compare the two
        # row sets after sorting both the same way
        W = np.array(list(want.values()), np.float64)
        G = feat[rows, :4].astype(np.float64)
        W = W[np.lexsort(np.round(W, 3).T[::-1])]
        G = G[np.lexsort(np.round(G, 3).T[::-1])]
        if W.shape != G.shape or not np.allclose(W, G, atol=1e-4):
            print(f"FEATURE MISMATCH at eviction {g}: shapes {W.shape} {G.shape}")
            if W.shape == G.shape:
                i = np.nonzero(~np.isclose(W, G, atol=1e-4).all(1))[0][0]
                print("   want", W[i], "got", G[i])
            return False
        print(f"  eviction {g:>5}: {len(rows)} candidates, F features match brute force")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    stems = ps.stems()
    bad_all, n = [], 0
    with Pool(a.jobs) as pool:
        for bad, rows in pool.imap_unordered(check_stream, stems):
            bad_all += bad
            n += len(rows)
            for stem, frac, cap, got, oth in rows:
                if frac == "0.1":
                    print(f"{stem:<22} cap={cap:>5} fifo={got['fifo']:>9} "
                          f"lru={got['lru']:>9} belady={got['belady']:>9} "
                          f"clock={oth['clock']:>9} aging={oth['aging']:>9}",
                          flush=True)
    print(f"\n{n} stream x capacity cells checked against baselines.tsv")
    if bad_all:
        print(f"{len(bad_all)} MISMATCHES:")
        for b in bad_all[:30]:
            print("  ", b)
    else:
        print("FIFO, LRU and Belady match baselines.tsv exactly; "
              "Belady <= every other policy everywhere.")
    print("\nfeature check (F features vs brute force):")
    ok = feature_check()
    sys.exit(0 if not bad_all and ok else 1)


if __name__ == "__main__":
    main()
