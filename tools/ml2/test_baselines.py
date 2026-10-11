#!/usr/bin/env python3
"""Tests for the list-based baseline policies in pagesim.c (MRU, ARC, S3-FIFO, MGLRU, LHD).

Each policy is checked against an independent pure-Python reference written
from the paper's pseudocode, fault for fault and eviction for eviction, on
many random traces (uniform, skewed, cyclic, phased) at many cache sizes; MRU
is also checked against its known answer (it equals Belady on a cyclic loop).

    PAGESIM_SRC=pagesim_dev.c PAGESIM_LIB=libpagesim_dev.so python test_baselines.py
"""
import random
from collections import OrderedDict, deque

import numpy as np

import pagesim as ps


class Fake:
    """Just enough of pagesim.Stream for ps.run()."""
    def __init__(self, pages, writes=None):
        pages = np.asarray(pages)
        uniq, dense = np.unique(pages, return_inverse=True)
        self.n, self.n_pages = len(pages), len(uniq)
        self.page = np.ascontiguousarray(dense.astype(np.uint32))
        self.write = np.ascontiguousarray((writes if writes is not None else np.zeros(self.n)).astype(np.uint8))
        nu = np.full(self.n, ps.NEVER, np.uint32)
        last = {}
        for i in range(self.n - 1, -1, -1):
            p = int(self.page[i])
            if p in last:
                nu[i] = last[p] - i
            last[p] = i
        self.next_use = np.ascontiguousarray(nu)


# ---- references --------------------------------------------------------------
def arc_ref(trace, c):
    T1, T2, B1, B2 = OrderedDict(), OrderedDict(), OrderedDict(), OrderedDict()
    st = {"p": 0, "ev": 0}

    def replace(in_b2):
        if len(T1) >= 1 and ((in_b2 and len(T1) == st["p"]) or len(T1) > st["p"]):
            k, _ = T1.popitem(last=False); B1[k] = None
        else:
            k, _ = T2.popitem(last=False); B2[k] = None
        st["ev"] += 1

    faults = 0
    for x in trace:
        if x in T1:
            del T1[x]; T2[x] = None; continue
        if x in T2:
            T2.move_to_end(x); continue
        faults += 1
        if x in B1:
            d = 1 if len(B1) >= len(B2) else len(B2) // len(B1)
            st["p"] = min(c, st["p"] + d); replace(False); del B1[x]; T2[x] = None
        elif x in B2:
            d = 1 if len(B2) >= len(B1) else len(B1) // len(B2)
            st["p"] = max(0, st["p"] - d); replace(True); del B2[x]; T2[x] = None
        else:
            l1 = len(T1) + len(B1)
            if l1 == c:
                if len(T1) < c:
                    B1.popitem(last=False); replace(False)
                else:
                    T1.popitem(last=False); st["ev"] += 1
            else:
                tot = l1 + len(T2) + len(B2)
                if tot >= c:
                    if tot == 2 * c:
                        B2.popitem(last=False)
                    replace(False)
            T1[x] = None
    return faults, st["ev"]


def arck_ref(trace, c):
    """ARC as a kernel that only reads accessed bits at eviction scans runs it: hits are not seen; at each fault with memory full every
    resident page's accessed bit is read (the touch that loaded a page is ignored); a page found accessed moves to the head of T2."""
    T1, T2, B1, B2 = OrderedDict(), OrderedDict(), OrderedDict(), OrderedDict()
    st = {"p": 0, "ev": 0}
    abit, fresh = {}, {}

    def replace(in_b2):
        if len(T1) >= 1 and ((in_b2 and len(T1) == st["p"]) or len(T1) > st["p"]):
            k, _ = T1.popitem(last=False); B1[k] = None
        else:
            k, _ = T2.popitem(last=False); B2[k] = None
        st["ev"] += 1

    def scan():
        for lst in (T1, T2):
            for k in list(lst.keys()):               # least recent first
                if fresh.get(k):
                    fresh[k] = False; abit[k] = 0
                elif abit.get(k):
                    abit[k] = 0
                    lst.pop(k, None); T2[k] = None   # head of T2

    faults = 0
    for x in trace:
        if x in T1 or x in T2:
            abit[x] = 1
            continue
        faults += 1
        if len(T1) + len(T2) >= c:
            scan()
        if x in B1:
            d = 1 if len(B1) >= len(B2) else len(B2) // len(B1)
            st["p"] = min(c, st["p"] + d); replace(False); del B1[x]; T2[x] = None
        elif x in B2:
            d = 1 if len(B2) >= len(B1) else len(B1) // len(B2)
            st["p"] = max(0, st["p"] - d); replace(True); del B2[x]; T2[x] = None
        else:
            l1 = len(T1) + len(B1)
            if l1 == c:
                if len(T1) < c:
                    B1.popitem(last=False); replace(False)
                else:
                    T1.popitem(last=False); st["ev"] += 1
            else:
                tot = l1 + len(T2) + len(B2)
                if tot >= c:
                    if tot == 2 * c:
                        B2.popitem(last=False)
                    replace(False)
            T1[x] = None
        abit[x] = 1; fresh[x] = True
    return faults, st["ev"]


def s3_ref(trace, c, scan):
    small_cap = max(1, c // 10)
    main_cap = c - small_cap
    S, M, G = deque(), deque(), OrderedDict()      # appendleft = head, pop() = tail
    freq, fresh, abit, res = {}, {}, {}, set()
    ev = 0

    def examine(p):
        if not scan:
            return
        if fresh.get(p):
            fresh[p] = False; abit[p] = 0; return
        if abit.get(p):
            freq[p] = min(freq[p] + 1, 3); abit[p] = 0

    def evict_main():
        while True:
            t = M.pop(); examine(t)
            if freq[t] > 0:
                freq[t] -= 1; M.appendleft(t)
            else:
                return t

    def evict():
        if len(S) * 10 >= c or len(M) == 0:
            while S:
                t = S.pop(); examine(t)
                if freq[t] > 1:
                    M.appendleft(t)
                    if len(M) > main_cap:
                        return evict_main()
                else:
                    G[t] = None
                    if len(G) > main_cap:
                        G.popitem(last=False)
                    return t
        return evict_main()

    faults = 0
    for x in trace:
        if x in res:
            abit[x] = 1
            if not scan:
                freq[x] = min(freq[x] + 1, 3)
            continue
        faults += 1
        if len(res) >= c:
            res.discard(evict()); ev += 1
        ghost = x in G                    # after evicting, as in the paper
        freq[x] = 0; fresh[x] = True; abit[x] = 1
        if ghost:
            del G[x]; M.appendleft(x)
        else:
            S.appendleft(x)
        res.add(x)
    return faults, ev


def mglru_ref(trace, c):
    """Generations + aging walk + rescue-at-eviction, from the rules in pagesim.c's
    header comment (cache_ext's aging thresholds)."""
    MIN, MAX = 2, 4
    st = {"gmin": 0, "gmax": 0, "ctr": 0}
    gen, gst, abit = {}, {}, {}

    def cnt(q):
        return sum(1 for g in gen.values() if g == q)

    def move(p, to):
        st["ctr"] += 1
        gen[p] = to; gst[p] = st["ctr"]

    def retire():
        while cnt(st["gmin"]) == 0 and st["gmin"] < st["gmax"]:
            st["gmin"] += 1

    def should_age():
        n = st["gmax"] - st["gmin"] + 1
        if n <= MIN:
            return True
        if n >= MAX:
            return False
        total = len(gen)
        return cnt(st["gmax"]) * MIN > total or cnt(st["gmax"] - MIN) * (MIN + 2) < total

    def age():
        if st["gmax"] - st["gmin"] + 1 == MAX:
            if cnt(st["gmin"]) != 0:
                return
            st["gmin"] += 1
        st["gmax"] += 1
        for p in sorted((q for q in gen if abit[q]), key=lambda q: gst[q]):
            abit[p] = 0; move(p, st["gmax"])

    def victim():
        retire()
        if should_age():
            age()
        while True:
            retire()
            best = min((p for p in gen if gen[p] == st["gmin"]), key=lambda p: gst[p])
            if abit[best]:
                abit[best] = 0; move(best, st["gmax"]); continue
            return best

    faults = ev = 0
    for x in trace:
        if x in gen:
            abit[x] = 1; continue
        faults += 1
        if len(gen) >= c:
            v = victim(); del gen[v]; del gst[v]; ev += 1
        abit[x] = 1; move(x, st["gmax"])
    return faults, ev


def lhd_ref(trace, c):
    """LHD, scan form, from the description in pagesim.c (cache_ext's structure)."""
    CL, AGES, HS, SCALE = 16, 256, 256, 1 << 20
    sh = 0
    while (AGES << sh) < 4 * c:
        sh += 1
    h = [[0] * AGES for _ in range(CL)]
    e = [[0] * AGES for _ in range(CL)]
    d = [[SCALE * (ci + 1) // (a + 1) for a in range(AGES)] for ci in range(CL)]

    def cls(x):
        if x == 0:
            return 0
        k = 0
        while x < AGES and k < CL - 1:
            x <<= 1; k += 1
        return k

    st = {"scans": 0, "nev": 0}

    def bucket(pg):
        a = (st["scans"] - pg["ls"]) >> sh
        return AGES - 1 if a >= AGES else a

    def reconf():
        for ci in range(CL):
            for a in range(AGES):
                h[ci][a] = h[ci][a] * 9 // 10; e[ci][a] = e[ci][a] * 9 // 10
            hits = h[ci][AGES - 1]; events = hits + e[ci][AGES - 1]; life = events
            for a in range(AGES - 2, -1, -1):
                hits += h[ci][a]; events += h[ci][a] + e[ci][a]; life += events
                d[ci][a] = hits * SCALE // life if events > HS else 0

    res, faults, ev, seq = {}, 0, 0, 0
    for x in trace:
        if x in res:
            res[x]["abit"] = 1; continue
        faults += 1
        if len(res) >= c:
            for pg in res.values():
                if pg["fresh"]:
                    pg["fresh"] = 0; pg["abit"] = 0; continue
                if not pg["abit"]:
                    continue
                b = bucket(pg)
                h[cls(pg["la1"] + pg["la2"])][b] += HS
                pg["la2"] = pg["la1"]; pg["la1"] = b; pg["ls"] = st["scans"]; pg["abit"] = 0
            best, bd = None, 0
            for k, pg in res.items():
                b = bucket(pg)
                dd = 0 if b == AGES - 1 else d[cls(pg["la1"] + pg["la2"])][b]
                if best is None or dd < bd or (dd == bd and pg["load"] < res[best]["load"]):
                    best, bd = k, dd
            bp = res[best]
            e[cls(bp["la1"] + bp["la2"])][bucket(bp)] += HS
            st["nev"] += 1
            if st["nev"] >= 4 * c + 256:
                st["nev"] = 0; reconf()
            del res[best]; ev += 1
            st["scans"] += 1
        seq += 1
        res[x] = dict(ls=st["scans"], la1=0, la2=AGES, abit=1, fresh=1, load=seq)
    return faults, ev


# ---- traces --------------------------------------------------------------------
def traces(rng):
    out = []
    for n_pages in (12, 40, 150):
        n = 4000
        out.append(("uniform", [rng.randrange(n_pages) for _ in range(n)]))
        w = [1 / (k + 1) for k in range(n_pages)]
        out.append(("zipf", rng.choices(range(n_pages), w, k=n)))
        out.append(("loop", [i % n_pages for i in range(n)]))
        t = []
        for ph in range(8):
            hot = rng.sample(range(n_pages), max(2, n_pages // 8))
            t += [rng.choice(hot) if rng.random() < .8 else rng.randrange(n_pages) for _ in range(n // 8)]
        out.append(("phase", t))
        scan = []
        hot = list(range(max(2, n_pages // 10)))
        for i in range(n):
            scan.append(rng.choice(hot) if i % 2 else (i // 2) % n_pages)
        out.append(("scanhot", scan))
    return out


def main():
    rng = random.Random(7)
    checked = bad = 0
    for kind, tr in traces(rng):
        n_pages = len(set(tr))
        s = Fake(tr)
        for c in sorted({2, 3, 5, max(2, n_pages // 10), max(2, n_pages // 4), max(2, n_pages // 2), n_pages - 1}):
            if c < 2 or c >= n_pages:
                continue
            for name, ref in (("arc", lambda: arc_ref(tr, c)),
                              ("arck", lambda: arck_ref(tr, c)),
                              ("s3fifo", lambda: s3_ref(tr, c, False)),
                              ("s3scan", lambda: s3_ref(tr, c, True)),
                              ("mglru", lambda: mglru_ref(tr, c)),
                              ("lhd", lambda: lhd_ref(tr, c))):
                r = ps.run(s, c, name)
                want = ref()
                got = (r["faults"], r["evictions"])
                checked += 1
                if r["aborted"] or got != want:
                    bad += 1
                    if bad <= 5:
                        print(f"MISMATCH {name} {kind} pages={n_pages} c={c}: C {got} aborted={r['aborted']} ref {want}")
    print(f"ARC / ARC-kernel / S3-FIFO / S3-scan / MGLRU / LHD vs references: {checked - bad}/{checked} identical")

    # MRU: exact, equals Belady on a pure cyclic loop (the textbook result)
    ok = 0
    for L in (10, 37, 100):
        s = Fake([i % L for i in range(6 * L + 5)])
        for c in (2, L // 3, L - 1):
            if c >= 2:
                m, b = ps.run(s, c, "mru")["faults"], ps.run(s, c, "belady")["faults"]
                assert m == b, (L, c, m, b)
                ok += 1
    print(f"MRU == Belady on cyclic loops: {ok}/{ok}")
    # and LRU/FIFO/Clock miss every access of a loop larger than the cache
    s = Fake([i % 20 for i in range(400)])
    for pol in ("lru", "fifo", "clock"):
        assert ps.run(s, 10, pol)["faults"] == 400, pol
    print("LRU, FIFO, Clock miss every access of a loop larger than the cache: ok")
    # determinism and writeback accounting
    w = np.array([random.Random(3).random() < .2 for _ in range(4000)])
    s = Fake(traces(random.Random(9))[0][1], w[:4000])
    for pol in ("arc", "arck", "s3fifo", "s3scan", "mru", "mglru", "lhd"):
        a, b = ps.run(s, 5, pol), ps.run(s, 5, pol)
        assert a == b, pol
        assert 0 <= a["writebacks"] <= a["evictions"], pol
    print("determinism: ok")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
