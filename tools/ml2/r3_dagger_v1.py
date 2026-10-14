#!/usr/bin/env python3
"""R3, rest: three DAgger rounds on the first-version data (graph only), current deterministic seeds.

First-version data = candidates sampled uniformly (n_recent = 0), no probation (protect_age 0). Round 0 fits the model on rows recorded
while LRU chose the victims; each later round records again while the previous round's model chooses, adds those rows to all earlier ones,
and refits. After every round the model is replayed on graph-pr2000x2-s2 (validation) at 10%. Three models are followed: the best of the 300
feature sets on that stream, the median one, and the one using every feature.

    python3 r3_dagger_v1.py [--jobs 2]   -> report/results2/r3_dagger_v1.csv
"""
import argparse
import csv
import zlib
from multiprocessing import Pool

import numpy as np

import build_datasets as B
import models as M
import pagesim as ps
import sweep_linear as SL

STEM, FRAC = "graph-pr2000x2-s2", "0.1"
OUT = ps.ROOT / "report" / "results2" / "r3_dagger_v1.csv"


def base_job(args):
    stem, frac = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    ev = max(ps.baselines()[(stem, frac)]["lru"] - cap, 1)
    per = min(B.MAX_CAND, cap)
    p = min(1.0, B.ROWS["train"] / (ev * per))
    seed = zlib.crc32(f"{stem}|{frac}|".encode()) & 0xFFFFFFFF
    r = ps.record(s, cap, "lru", p=p, max_rows=int(B.ROWS["train"] * 1.5) + 4 * per, seed=seed, max_cand=B.MAX_CAND, n_recent=0)
    return r["feat"], r["label"]


def dagger_job(args):
    stem, frac, spec, rnd = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    ev = max(ps.baselines()[(stem, frac)]["lru"] - cap, 1)
    per = min(B.MAX_CAND, cap)
    p = min(1.0, B.ROWS["train"] / (ev * per))
    r = ps.record(s, cap, "learned", p=p, max_rows=int(B.ROWS["train"] * 3) + 4 * per, seed=7 + rnd,
                  model=M.to_scored(spec, protect_age=0), max_cand=B.MAX_CAND, n_recent=0)
    return r["feat"], r["label"]


S = CAP = CLOCK = None


def init():
    global S, CAP, CLOCK
    S = ps.load_stream(STEM)
    CAP = S.capacities[FRAC]
    CLOCK = ps.run(S, CAP, "clock")["faults"]


def score(spec):
    r = ps.run(S, CAP, "learned", M.to_scored(spec, protect_age=0), max_faults=3 * CLOCK)
    return r["faults"] / CLOCK, r["aborted"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    init()                      # the main process scores the later rounds itself
    stems = [(st, fr) for st in ps.stems("train", "graph") for fr in B.TRAIN_FRACS]
    with Pool(a.jobs, initializer=init) as pool:
        parts = pool.map(base_job, stems)
        feat = np.concatenate([p[0] for p in parts])
        label = np.concatenate([p[1] for p in parts])
        print(f"round 0 data: {len(label):,} rows from {len(stems)} stream-sizes", flush=True)
        fs = SL.feature_sets()
        fit = M.LinearFitter({"feat": feat, "label": label, "weight": np.ones(len(label))})
        specs = [fit.fit(f) for f in fs]
        res = pool.map(score, specs, chunksize=4)
        ratio = np.array([r for r, _ in res])
        order = np.argsort(ratio)
        picks = {"best of 300": int(order[0]), "median of 300": int(order[len(order) // 2]), "all features": len(specs) - 1}
        rows = []
        for name, i in picks.items():
            rows.append([name, "+".join(fs[i]), 0, len(label), f"{ratio[i]:.3f}", int(res[i][1])])
            print(rows[-1], flush=True)
        cur_feat = {n: feat for n in picks}
        cur_label = {n: label for n in picks}
        cur_spec = {n: specs[i] for n, i in picks.items()}
        for rnd in (1, 2, 3):
            for name in picks:
                new = pool.map(dagger_job, [(st, fr, cur_spec[name], rnd) for st, fr in stems])
                cur_feat[name] = np.concatenate([cur_feat[name]] + [p[0] for p in new])
                cur_label[name] = np.concatenate([cur_label[name]] + [p[1] for p in new])
                f2 = M.LinearFitter({"feat": cur_feat[name], "label": cur_label[name], "weight": np.ones(len(cur_label[name]))})
                cur_spec[name] = f2.fit(fs[picks[name]])
                r, ab = score(cur_spec[name])
                rows.append([name, "+".join(fs[picks[name]]), rnd, len(cur_label[name]), f"{r:.3f}", int(ab)])
                print(rows[-1], flush=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "features", "dagger_round", "training_rows", "faults_over_clock", "stopped_at_3x"])
        w.writerows(rows)


if __name__ == "__main__":
    main()
