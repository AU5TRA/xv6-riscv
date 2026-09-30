#!/usr/bin/env python3
"""Independent, deliberately naive Python re-implementation of the
kernel-faithful parts of pagesim.c, used only to check it:

  * Clock / Aging / decayed LFU fault and writeback counts, following
    kernel/vmpage.c choose_clock/choose_aging/choose_lfu and kernel/vm.c's
    "fault sets PTE_A (and PTE_D on a write)";
  * the K / K+ feature values of every candidate at recorded evictions.

    python3 validate_kernel.py
"""
import math
import sys

import numpy as np

import pagesim as ps


class Ref:
    def __init__(self, cap, policy):
        self.cap, self.policy = cap, policy
        self.order = []            # insertion order (Clock candidate list)
        self.A, self.D = {}, {}
        self.aging, self.sfreq, self.kfreq = {}, {}, {}
        self.load_seq, self.load_scan, self.last_seen = {}, {}, {}
        self.has_copy, self.evicted_at, self.refaults, self.rdist = {}, {}, {}, {}
        self.seen_now = {}
        self.seq = self.scans = self.hand = 0
        self.faults = self.writebacks = 0

    def scan(self):
        for p in self.order:
            a = self.A[p]
            self.seen_now[p] = a
            self.aging[p] = (self.aging[p] >> 1) | (0x80 if a else 0)
            if a:
                self.sfreq[p] += 1
                self.last_seen[p] = self.scans
                self.kfreq[p] += 1
            self.kfreq[p] = (self.kfreq[p] >> 1) + (1 if a else 0)
            self.A[p] = 0

    def k_features(self, p):
        return [self.seen_now[p], self.aging[p] / 255,
                math.log1p(self.sfreq[p]), math.log1p(self.scans - self.last_seen[p]),
                math.log1p(self.scans - self.load_scan[p]), self.D[p],
                math.log1p(self.refaults.get(p, 0)), math.log1p(self.rdist.get(p, 0))]

    def victim(self):
        if self.policy == "clock":
            n = len(self.order)
            for _ in range(2 * n):
                p = self.order[self.hand % n]
                self.hand += 1
                if not self.A[p]:
                    return p
                self.A[p] = 0
            p = self.order[self.hand % n]
            self.hand += 1
            return p
        self.scan()
        key = {"aging": lambda p: (self.aging[p], self.load_seq[p]),
               "lfu_kernel": lambda p: (self.kfreq[p], self.load_seq[p]),
               "fifo": lambda p: self.load_seq[p]}[self.policy]
        return min(self.order, key=key)

    def access(self, p, w, on_evict=None):
        if p in self.A:
            self.A[p] = 1
            self.D[p] |= w
            return
        self.faults += 1
        if len(self.order) >= self.cap:
            v = self.victim()
            if on_evict:
                on_evict(self)
            if self.D[v] or not self.has_copy.get(v):
                self.writebacks += 1
                self.has_copy[v] = True
            self.order.remove(v)
            del self.A[v], self.D[v]
            self.evicted_at[v] = self.scans
            self.scans += 1
        if p in self.evicted_at:
            self.refaults[p] = self.refaults.get(p, 0) + 1
            self.rdist[p] = self.scans - self.evicted_at[p]
        self.order.append(p)
        self.seq += 1
        self.load_seq[p] = self.seq
        self.load_scan[p] = self.last_seen[p] = self.scans
        self.aging[p], self.sfreq[p], self.kfreq[p] = 0xFF, 0, 1
        self.A[p], self.D[p] = 1, w


def main():
    ok = True
    for stem, frac in (("kv-A-s1", "0.1"), ("btree-mixed-s1", "0.05"),
                       ("sort-n20000-s1", "0.3"), ("matmul-naive64-s1", "0.3")):
        s = ps.load_stream(stem)
        cap = s.capacities[frac]
        pages, writes = s.page.tolist(), s.write.tolist()
        for pol in ("fifo", "clock", "aging", "lfu_kernel"):
            r = Ref(cap, pol)
            for p, w in zip(pages, writes):
                r.access(p, w)
            got = ps.run(s, cap, pol)
            same = got["faults"] == r.faults and got["writebacks"] == r.writebacks
            ok &= same
            print(f"{stem:<18} cap={cap:>4} {pol:<10} C faults={got['faults']:>8} "
                  f"py={r.faults:>8}  C writebacks={got['writebacks']:>7} "
                  f"py={r.writebacks:>7}  {'OK' if same else 'MISMATCH'}")

    # K / K+ features at every eviction of a small run, recorded under Aging
    s = ps.load_stream("kv-A-s1")
    cap = s.capacities["0.1"]
    rec = ps.record(s, cap, "aging", p=1.0, max_rows=3_000_000, seq=True)
    feat, grp, page = rec["feat"], rec["group"], rec["page"]
    starts = np.searchsorted(grp, np.arange(grp.max() + 2))
    r = Ref(cap, "aging")
    checked = [0]
    bad = [0]

    def on_evict(ref):
        g = checked[0]
        rows = range(starts[g], starts[g + 1])
        got = {int(page[i]): feat[i, 4:] for i in rows}
        for p in ref.order:
            want = np.array(ref.k_features(p), np.float32)
            if not np.allclose(got[p], want, atol=1e-5):
                if bad[0] < 3:
                    print("  K MISMATCH eviction", g, "page", p, "\n   want", want,
                          "\n   got ", got[p])
                bad[0] += 1
        checked[0] += 1

    for p, w in zip(s.page.tolist(), s.write.tolist()):
        r.access(p, w, on_evict)
    print(f"K/K+ features: {checked[0]} evictions x {cap} candidates compared, "
          f"{bad[0]} mismatching candidates")
    ok &= bad[0] == 0 and checked[0] == grp.max() + 1
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
