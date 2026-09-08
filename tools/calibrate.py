#!/usr/bin/env python3
"""Calibrate native xv6 workloads against real SQLite/Redis traces
(WORK_PROMPT3.md Phase 3 / WORK_PROMPT2.md Phase 4).

Distance metric (proposed and documented here rather than silently
chosen -- see the module docstring of each component below for the
reasoning):

    distance(A, B) = 0.7 * JS(reuse_distance_dist_A, reuse_distance_dist_B)
                    + 0.3 * RMSE(normalized_working_set_A, normalized_working_set_B)

- Jensen-Shannon divergence over the log2-bucketed reuse-distance
  histograms (normalized to probability distributions), weighted 0.7:
  WORK_PROMPT3.md's own Phase 3 SS1 calls reuse-distance "the single
  most informative statistic for replacement behaviour," and JS
  divergence is symmetric and bounded in [0, 1] bit regardless of how
  different the two distributions' supports are (unlike KL divergence,
  which blows up on zero-probability buckets -- a near-certainty here
  since real and native traces have very different unique-page counts
  and thus different bucket ranges).
- RMSE over the working-set-size-over-time series, weighted 0.3, AFTER
  normalizing each series by its own trace's unique-page count. This
  compares SHAPE (how much does the working set fluctuate, are there
  phase changes) rather than absolute magnitude -- a real Redis
  process legitimately touches far more raw pages than a small native
  benchmark run ever will, and that scale difference is not the
  interesting comparison.

Both components are in [0, ~1], so the combined distance is roughly in
[0, 1] too (JS divergence in bits caps at 1 for base-2 log; RMSE of two
series each in [0,1] is at most 1). Lower is more similar.
"""
import sys
import math
import argparse
from trace_decode import decode, reuse_distances, bucket_log2, working_set_over_time


def js_divergence(hist_a, hist_b):
    all_buckets = sorted(set(hist_a) | set(hist_b))
    if not all_buckets:
        return 0.0
    total_a = sum(hist_a.values()) or 1
    total_b = sum(hist_b.values()) or 1
    p = [hist_a.get(b, 0) / total_a for b in all_buckets]
    q = [hist_b.get(b, 0) / total_b for b in all_buckets]
    m = [(pi + qi) / 2 for pi, qi in zip(p, q)]

    def kl(x, y):
        s = 0.0
        for xi, yi in zip(x, y):
            if xi > 0 and yi > 0:
                s += xi * math.log2(xi / yi)
        return s

    js = 0.5 * kl(p, m) + 0.5 * kl(q, m)
    return max(0.0, js)  # guard against tiny negative floating-point noise


def normalized_working_set(refs, unique_count):
    ws = working_set_over_time(refs)
    if unique_count <= 0:
        return ws
    return [w / unique_count for w in ws]


def rmse(a, b):
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    s = sum((a[i] - b[i]) ** 2 for i in range(n))
    return math.sqrt(s / n)


def trace_features(path):
    header, refs = decode(path)
    if header is None:
        raise ValueError(f"{path}: no TRACEHDR found")
    distances, infinite = reuse_distances(refs)
    hist = bucket_log2(distances)
    unique = len(set(refs))
    ws = normalized_working_set(refs, unique)
    return {
        "path": path,
        "header": header,
        "hist": hist,
        "ws": ws,
        "unique": unique,
        "total_refs": len(refs),
    }


def distance(feat_a, feat_b):
    js = js_divergence(feat_a["hist"], feat_b["hist"])
    ws_rmse = rmse(feat_a["ws"], feat_b["ws"])
    return 0.7 * js + 0.3 * ws_rmse, js, ws_rmse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace_a")
    ap.add_argument("trace_b")
    args = ap.parse_args()
    fa = trace_features(args.trace_a)
    fb = trace_features(args.trace_b)
    d, js, ws_rmse = distance(fa, fb)
    print(f"{args.trace_a} vs {args.trace_b}")
    print(f"  unique pages: {fa['unique']} vs {fb['unique']}")
    print(f"  JS divergence (reuse-distance):   {js:.4f}")
    print(f"  RMSE (normalized working set):    {ws_rmse:.4f}")
    print(f"  combined distance:                {d:.4f}")


if __name__ == "__main__":
    main()
