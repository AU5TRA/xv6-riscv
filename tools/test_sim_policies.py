#!/usr/bin/env python3
"""Hand-made traces for the simulator's MRU and ARC (tools/sim.py), checked
against answers worked out by hand. Run before trusting either policy:

    python3 tools/test_sim_policies.py

Exits non-zero on the first wrong answer.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Arc, Lru, Mru, belady_faults_evictions, run_policy  # noqa: E402


def run(cls, refs, capacity, check=False):
    sim = cls(capacity)
    for vpn in refs:
        sim.access(vpn)
        if check:
            sim.check_invariants()
    return sim


def expect(what, got, want):
    if got != want:
        sys.exit("FAIL %s: got %r, want %r" % (what, got, want))
    print("ok   %s: %r" % (what, got))


def test_arc_by_hand():
    # c = 2. Step by step (T1, T2, B1, B2 listed LRU first):
    #   1  miss        T1=[1]
    #   2  miss        T1=[1,2]
    #   1  hit in T1   T1=[2]  T2=[1]
    #   3  miss, IV.B: REPLACE evicts T1's 2 to B1 (|T1|=1 > p=0)
    #                  T1=[3]  T2=[1]  B1=[2]
    #   4  miss, IV.A (|L1|=2=c, |T1|<c): drop ghost 2; REPLACE evicts 3
    #                  T1=[4]  T2=[1]  B1=[3]
    #   1  hit in T2   T2=[1]
    #   3  B1 ghost hit: p = 0+1 = 1; REPLACE: |T1|=1 not > p, so T2's 1
    #      goes to B2  T1=[4]  T2=[3]  B2=[1]
    #   1  B2 ghost hit: p = 1-1 = 0; REPLACE(in B2): |T1|=1 > p, so 4
    #      goes to B1  T2=[3,1]  B1=[4]
    #   5  miss, IV.B (|L1|=1 < c, |L1|+|L2|=3 >= c): REPLACE: T1 empty,
    #      so T2's 3 goes to B2   T1=[5]  T2=[1]  B1=[4]  B2=[3]
    # 7 faults (every request but the two hits and the T2 hit), 5 evictions.
    refs = [1, 2, 1, 3, 4, 1, 3, 1, 5]
    a = run(Arc, refs, 2, check=True)
    expect("arc hand trace faults", a.faults, 7)
    expect("arc hand trace evictions", a.evictions, 5)
    expect("arc hand trace lists",
           (list(a.t1), list(a.t2), list(a.b1), list(a.b2), a.p),
           ([5], [1], [4], [3], 0.0))


def test_arc_scan_resistance():
    # Two pages used twice each land in T2; a one-time scan of 50 new pages
    # then passes through T1 only (p stays 0, so REPLACE always takes T1's
    # LRU page) and both T2 pages survive it. LRU loses both to the scan.
    refs = [100, 101, 100, 101] + list(range(50)) + [100, 101]
    a = run(Arc, refs, 4, check=True)
    lru = run(Lru, refs, 4)
    expect("arc scan: faults (2 cold + 50 scan, hot pages kept)", a.faults, 52)
    expect("lru scan: faults (hot pages lost)", lru.faults, 54)


def test_arc_invariants_random():
    # Invariants of DBL(2c) after every request, on traces mixing a loop, a
    # skewed hot set and uniform noise -- the request kinds that drive p up
    # and down.
    rng = random.Random(12345)
    for c in (1, 2, 3, 8, 32):
        refs = []
        for _ in range(4000):
            r = rng.random()
            if r < 0.4:
                refs.append(rng.randrange(c // 2 + 2))         # hot
            elif r < 0.7:
                refs.append(1000 + len(refs) % (3 * c + 1))     # loop
            else:
                refs.append(2000 + rng.randrange(10 * c))       # noise
        a = run(Arc, refs, c, check=True)
        # A fault is either a cold miss or follows an eviction, and nothing
        # is evicted without a fault.
        cold = len(set(refs))
        assert a.evictions <= a.faults
        assert a.faults >= cold
        assert a.faults - a.evictions == len(a.t1) + len(a.t2)
    print("ok   arc invariants on 5 random traces x 4000 requests")


def test_mru_by_hand():
    # A 5-page loop, 3 frames, 4 passes. Recency order after each step:
    # pass 1: 0 1 2 fill; 3 evicts 2; 4 evicts 3          -> 5 faults
    # pass 2: 0,1 hit; 2 evicts 1; 3 evicts 2; 4 hit      -> 2 faults
    # pass 3: 0 hit; 1 evicts 0; 2 evicts 1; 3,4 hit      -> 2 faults
    # pass 4: 0 evicts 4; 1 evicts 0; 2,3 hit; 4 evicts 3 -> 3 faults
    refs = list(range(5)) * 4
    m = run(Mru, refs, 3)
    expect("mru loop faults", m.faults, 12)
    expect("mru loop evictions", m.evictions, 9)
    expect("lru loop faults (every access)", run(Lru, refs, 3).faults, 20)


def test_loop_known_answer():
    # patbench loop's expectation in miniature: L = 100, C = 90, 50 passes.
    # LRU misses all 5000; MRU and Belady miss about L - C (+1) per pass.
    L, C, passes = 100, 90, 50
    refs = list(range(L)) * passes
    lru = run_policy("lru", refs, C)["faults"]
    mru = run_policy("mru", refs, C)["faults"]
    opt, _ = belady_faults_evictions(refs, C)
    expect("loop lru faults", lru, L * passes)
    warm_mru = (mru - L) / (passes - 1)
    warm_opt = (opt - L) / (passes - 1)
    print("ok   loop mru %.2f, belady %.2f misses per warm pass (L-C = %d)"
          % (warm_mru, warm_opt, L - C))
    if not (L - C <= warm_mru <= L - C + 2 and L - C <= warm_opt <= L - C + 2):
        sys.exit("FAIL loop: MRU/Belady not near L-C misses per pass")


if __name__ == "__main__":
    test_arc_by_hand()
    test_arc_scan_resistance()
    test_arc_invariants_random()
    test_mru_by_hand()
    test_loop_known_answer()
    print("all simulator policy tests passed")
