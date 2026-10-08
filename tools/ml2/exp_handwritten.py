#!/usr/bin/env python3
"""Do hand-written rules match the learned policy?

The learned policy's two headline effects are fewer faults and far fewer disk
writes (it prefers clean pages). cache_ext's policies hard-code the second
(they never evict dirty folios). This replays the test and held-out streams,
at 5/10/20%, under rules whose weights are set by hand -- a priori, not
fitted to any data -- using the same kernel-observable features, the same
integer scorer and the same tie-break as the learned models:

  idle        evict the page longest unseen at a scan (LRU by scan)
  clean       idle, but never a dirty page while a clean one exists
  clean+p4    the same with probation 4
  softdirty   idle, with a dirty page counted as ~7x less idle
  mru         evict the most recently seen page (loops larger than memory)

next to the selected linear models (per-workload and global, K+K+ tier, 8-bit
integer weights) and Clock / FIFO / Aging / LRU / Belady from classical.csv.

    python3 exp_handwritten.py [--jobs 6]  -> report/results2/handwritten_vs_ml.csv
"""
import argparse
import csv
import time
from multiprocessing import Pool

import numpy as np

import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
FRACS = ("0.05", "0.1", "0.2")
HEADER = ["policy", "stem", "split", "workload", "fraction", "frames",
          "faults", "writebacks", "aborted"]

# name -> (feature weights, probation). Weight 1 on the Q8 log1p feature is
# qa = 256; the dirty feature is 0 or 256.
HAND = {
    "idle":      ({"idle": 1.0}, 0),
    "clean":     ({"idle": 1.0, "dirty": -1000.0}, 0),
    "clean+p4":  ({"idle": 1.0, "dirty": -1000.0}, 4),
    "softdirty": ({"idle": 1.0, "dirty": -2.0}, 0),
    "mru":       ({"idle": -1.0}, 0),
}


def hand_model(weights, protect):
    feats = list(weights)
    n = len(feats)
    return ps.ScoredModel("mlp", features=feats, mean=[0.0] * n, std=[1.0] * n,
                          layers=[(np.array([[weights[f] for f in feats]], np.float32),
                                   np.zeros(1, np.float32))],
                          quant_w=8, protect_age=protect)


def learned_int8(spec):
    layers = [(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32))
              for L in spec["layers"]]
    return ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"],
                          std=spec["std"], layers=layers, quant_w=8,
                          protect_age=spec.get("protect_age", 0))


def clock_faults():
    return {(r["stem"], r["fraction"]): int(r["faults"])
            for r in csv.DictReader(open(R / "classical.csv")) if r["policy"] == "clock"}


CLOCK = clock_faults()
BASE = ps.baselines()
FINAL = M.load_models("final_linear")


def policies_for(workload):
    out = {name: hand_model(w, p) for name, (w, p) in HAND.items()}
    out["ml_workload"] = learned_int8(FINAL[f"{workload}|K+K+"])
    out["ml_global"] = learned_int8(FINAL["global|K+K+"])
    return out


def job(args):
    stem, frac = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    limit = min(5 * BASE[(stem, frac)]["fifo"], 3 * CLOCK[(stem, frac)])
    rows = []
    for name, model in policies_for(s.workload).items():
        r = ps.run(s, cap, "learned", model, max_faults=limit)
        rows.append([name, stem, s.split, s.workload, frac, cap,
                     r["faults"], r["writebacks"], int(r["aborted"])])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    refs = {e["stem"]: e["refs"] for e in ps.index()["streams"]}
    tasks = [(stem, frac) for stem in ps.stems(("test", "heldout")) for frac in FRACS]
    tasks.sort(key=lambda t: -refs[t[0]])
    t0 = time.time()
    out = R / "handwritten_vs_ml.csv"
    with Pool(a.jobs) as pool, open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows)
            f.flush()
            if i % 10 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} cells, {time.time() - t0:.0f}s", flush=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
