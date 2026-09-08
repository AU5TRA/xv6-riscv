#!/usr/bin/env python3
"""Decode a vmbench reference trace (WORK_PROMPT.md Phase 3).

Reads a test-harness transcript (or any file containing the same lines)
that has a "TRACEHDR ..." line followed by a stream of "T <vpn>" lines
(emitted by user/vmbench.h's touch_r/touch_w/vmbench_trace_ref when a
workload is run with tracing enabled -- see user/btreebench.c's trailing
`trace` CLI argument for the pattern other workloads should follow).

Usage:
    python3 tools/trace_decode.py <transcript.log> [--json out.json]

Prints a human-readable summary: header fields, unique pages touched,
total references, a reuse-distance histogram (log2-bucketed), and
working-set size sampled over the run. All computed on the host in
plain Python -- this tool does not run inside xv6 and has no
floating-point restriction, but is kept in pure integer arithmetic
anyway since the histogram buckets are naturally integral.
"""
import sys
import re
import json
import argparse

TRACEHDR_RE = re.compile(r"^TRACEHDR (.*)$")
REF_RE = re.compile(r"^T (-?\d+)$")


def parse_header(line):
    fields = {}
    rest = line
    # Fields are "key=value" space-separated, except "params=..." whose
    # value itself may contain spaces and runs to the next known key.
    # Simple approach: split on known key names.
    known_keys = ["workload", "params", "seed", "resident_limit",
                  "arena_cache_budget", "policy", "prefetch_enabled",
                  "arena_start_vpn", "arena_pages"]
    positions = []
    for k in known_keys:
        m = re.search(rf"\b{k}=", rest)
        if m:
            positions.append((m.start(), k))
    positions.sort()
    for i, (pos, key) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(rest)
        value = rest[pos + len(key) + 1:end].strip()
        fields[key] = value
    return fields


def decode(path):
    header = None
    refs = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = TRACEHDR_RE.match(line)
            if m:
                header = parse_header(line)
                refs = []  # a later TRACEHDR (e.g. a second policy run)
                           # starts a fresh trace -- keep the last one
                continue
            m = REF_RE.match(line)
            if m:
                refs.append(int(m.group(1)))
    return header, refs


def reuse_distances(refs):
    """Exact stack (reuse) distances: for each reference after the
    first to a given page, the number of DISTINCT pages referenced
    since that page's previous reference. Returns (distances,
    infinite_count) where distances is the list of finite distances in
    trace order (first-touch references excluded, counted separately).

    O(n log n) via a Fenwick tree (binary indexed tree) over time
    positions: position i holds 1 iff it is still the MOST RECENT
    occurrence of its page (cleared -- decremented -- once that page
    is seen again later). A reference's distance is then the number of
    still-"most recent" positions strictly between its previous
    occurrence and now -- a prefix-sum difference, O(log n) per
    reference. Upgraded from an earlier O(n * unique) list-based
    version (still correct, just too slow for multi-million-reference
    real-application traces) -- both were cross-checked to produce
    IDENTICAL output on the hand-computed example in _selftest()
    before this one replaced it.
    """
    n = len(refs)
    tree = [0] * (n + 1)

    def bit_add(i, delta):
        i += 1  # 1-indexed internally
        while i <= n:
            tree[i] += delta
            i += i & (-i)

    def bit_sum(i):
        # Sum of 0-indexed positions [0, i).
        s = 0
        while i > 0:
            s += tree[i]
            i -= i & (-i)
        return s

    last_pos = {}
    distances = []
    infinite = 0
    for i, vpn in enumerate(refs):
        if vpn in last_pos:
            j = last_pos[vpn]
            distance = bit_sum(i) - bit_sum(j + 1)
            distances.append(distance)
            bit_add(j, -1)
        else:
            infinite += 1
        bit_add(i, 1)
        last_pos[vpn] = i
    return distances, infinite


def bucket_log2(distances):
    """log2-bucketed histogram: bucket i covers [2^i, 2^(i+1))."""
    hist = {}
    for distance in distances:
        bucket = 0
        d = distance
        while d > 0:
            d >>= 1
            bucket += 1
        hist[bucket] = hist.get(bucket, 0) + 1
    return hist


def reuse_distance_histogram(refs):
    """Back-compat wrapper: log2-bucketed histogram + first-touch count."""
    distances, infinite = reuse_distances(refs)
    return bucket_log2(distances), infinite


def miss_ratio_curve(refs, cache_sizes=None):
    """Fault rate as a function of cache size, derived from the exact
    reuse-distance distribution: for a stack algorithm (LRU is the
    canonical one this is exact for), a reference is a HIT at cache
    size C iff its reuse distance is < C. A first-touch reference is
    always a miss regardless of C. Returns a list of (cache_size,
    miss_ratio) pairs.
    """
    distances, infinite = reuse_distances(refs)
    total = len(refs)
    if total == 0:
        return []
    if cache_sizes is None:
        max_d = max(distances) if distances else 0
        # A handful of representative points rather than every integer.
        cache_sizes = sorted(set(
            [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
            + [max_d, max_d + 1]
        ))
        cache_sizes = [c for c in cache_sizes if c >= 0]
    sorted_d = sorted(distances)
    curve = []
    import bisect
    for c in cache_sizes:
        hits = bisect.bisect_left(sorted_d, c)  # count of distances < c
        misses = infinite + (len(sorted_d) - hits)
        curve.append((c, misses / total))
    return curve


def phase_boundaries(ws_series, rel_threshold=0.5):
    """Segments working_set_over_time's samples where the distinct
    -page count changes by more than rel_threshold (relative) from one
    sample to the next. Returns a list of sample-indices where a new
    phase starts (index 0 always starts the first phase)."""
    if not ws_series:
        return []
    boundaries = [0]
    for i in range(1, len(ws_series)):
        prev, cur = ws_series[i - 1], ws_series[i]
        base = max(prev, 1)
        if abs(cur - prev) / base > rel_threshold:
            boundaries.append(i)
    return boundaries


def conditional_entropy(refs, k=1):
    """Conditional entropy (bits) of the next page given the previous
    k pages: H(X_i | X_{i-k..i-1}) = sum_context P(context) * H(X_i |
    context). Estimated empirically from the trace's own frequency
    counts (no floating-point restriction here -- this is host-side
    Python). Directly estimates how much signal a learned model could
    theoretically exploit from short local context: 0 bits means the
    next page is fully determined by the last k; log2(unique pages)
    bits means it's indistinguishable from uniform-random."""
    import math
    if len(refs) <= k:
        return 0.0
    context_counts = {}
    joint_counts = {}
    for i in range(k, len(refs)):
        context = tuple(refs[i - k:i])
        nxt = refs[i]
        context_counts[context] = context_counts.get(context, 0) + 1
        joint_counts[(context, nxt)] = joint_counts.get((context, nxt), 0) + 1
    total = len(refs) - k
    h = 0.0
    for (context, nxt), count in joint_counts.items():
        p_joint = count / total
        p_cond = count / context_counts[context]
        h -= p_joint * math.log2(p_cond)
    return h


def working_set_over_time(refs, n_samples=10):
    """Distinct-page count within each of n_samples equal chunks of the
    reference stream (a crude working-set-over-time signal, not a
    sliding window)."""
    if not refs:
        return []
    chunk = max(1, len(refs) // n_samples)
    out = []
    for i in range(0, len(refs), chunk):
        window = refs[i:i + chunk]
        out.append(len(set(window)))
    return out


def _selftest():
    """Validates reuse_distances against a hand-computed answer (Gate 3
    requirement) before trusting it on real data. Trace: A B C A B D A
    -- distinct pages referenced between consecutive same-page
    references:
      A@0: first touch (infinite)
      B@1: first touch (infinite)
      C@2: first touch (infinite)
      A@3: since A@0, distinct pages seen are {B, C} -> distance 2
      B@4: since B@1, distinct pages seen are {C, A} -> distance 2
      D@5: first touch (infinite)
      A@6: since A@3, distinct pages seen are {B, D} -> distance 2
    Expected: distances = [2, 2, 2], infinite = 4.
    """
    refs = ["A", "B", "C", "A", "B", "D", "A"]
    distances, infinite = reuse_distances(refs)
    expected_distances = [2, 2, 2]
    expected_infinite = 4
    assert distances == expected_distances, (
        f"reuse_distances self-test FAILED: got {distances}, "
        f"expected {expected_distances}")
    assert infinite == expected_infinite, (
        f"reuse_distances self-test FAILED: infinite={infinite}, "
        f"expected {expected_infinite}")
    print("[selftest] reuse_distances: PASS (hand-computed trace "
          "A B C A B D A matches)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--json", default=None)
    ap.add_argument("--selftest", action="store_true",
                     help="validate reuse_distances against a "
                          "hand-computed example, then exit")
    ap.add_argument("--entropy-k", type=int, default=1,
                     help="context length for conditional entropy")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    header, refs = decode(args.transcript)
    if header is None:
        print("no TRACEHDR line found -- was this program run with "
              "tracing enabled?")
        sys.exit(1)

    unique = len(set(refs))
    hist, infinite = reuse_distance_histogram(refs)
    ws = working_set_over_time(refs)

    print(f"workload:         {header.get('workload')}")
    print(f"seed:             {header.get('seed')}")
    print(f"resident_limit:   {header.get('resident_limit')}")
    print(f"arena_cache_budget: {header.get('arena_cache_budget')}")
    print(f"policy:           {header.get('policy')}")
    print(f"prefetch_enabled: {header.get('prefetch_enabled')}")
    print(f"arena_start_vpn:  {header.get('arena_start_vpn')}")
    print(f"arena_pages:      {header.get('arena_pages')}")
    print()
    print(f"total references: {len(refs)}")
    print(f"unique pages:      {unique}")
    print(f"first-touch (infinite reuse distance): {infinite}")
    print()
    print("reuse-distance histogram (log2 bucket -> count):")
    for b in sorted(hist):
        lo = 1 << b if b > 0 else 0
        hi = (1 << (b + 1)) - 1
        print(f"  [{lo:>6},{hi:>6}]: {hist[b]}")
    print()
    print("working-set size over time (distinct pages per 1/10th of run):")
    print(" ", ws)

    boundaries = phase_boundaries(ws)
    print()
    print(f"phase changes detected: {max(0, len(boundaries) - 1)} "
          f"(working-set-size samples where it shifts >50% from the "
          f"previous sample)")
    if len(boundaries) > 1:
        print("  phase boundaries (sample indices):", boundaries)

    curve = miss_ratio_curve(refs)
    print()
    print("miss-ratio curve (cache size in pages -> miss ratio, exact "
          "for a stack/LRU algorithm):")
    for c, ratio in curve:
        print(f"  C={c:>6}: {ratio:.4f}")

    h = conditional_entropy(refs, k=args.entropy_k)
    import math
    max_h = math.log2(unique) if unique > 1 else 0.0
    print()
    print(f"conditional entropy H(next page | previous {args.entropy_k}): "
          f"{h:.3f} bits (max possible, uniform over {unique} unique "
          f"pages: {max_h:.3f} bits -- lower means more predictable, "
          f"more exploitable signal for a learned policy)")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({
                "header": header,
                "total_references": len(refs),
                "unique_pages": unique,
                "first_touch": infinite,
                "reuse_distance_histogram": hist,
                "working_set_over_time": ws,
                "phase_boundaries": boundaries,
                "miss_ratio_curve": curve,
                "conditional_entropy_bits": h,
                "conditional_entropy_max_bits": max_h,
            }, f, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
