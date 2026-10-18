#!/usr/bin/env python3
"""Training time of the five heavier models the kernel runs (global scope, kernel features).

    python3 time_training.py   -> report/results2/training_times.csv
"""
# Times training of the five heavier models the kernel runs (global scope, kernel features), with the training code
# itself; nothing is saved (the stored models in report/models2/extra are untouched).
import sys, time, csv
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import torch
import extra_core as Z, extra_nn as N, extra_trees as T
out = []
print("device:", N.DEV, torch.cuda.get_device_name(0) if torch.cuda.is_available() else "", flush=True)
t = time.time(); d = Z.load("train", "global"); print(f"tree data load {time.time()-t:.1f}s rows {len(d['label'])}", flush=True)
for fam, p, name in (("gbdt", dict(trees=100, leaves=16), "boosted trees"), ("rank", dict(trees=100, leaves=16), "ranking trees")):
    t = time.time(); T.fit_one(d, "global", fam, p, "K", False); s = time.time() - t
    out.append((name, "CPU (6 threads)", round(s, 1))); print(out[-1], flush=True)
t = time.time(); cache = {k: Z.load(k, "global", hist=True) for k in ("train", "val")}; load = time.time() - t
print(f"network data load {load:.1f}s (kept in memory, so the timings below are training only)", flush=True)
N.Z.load = lambda split, scope, hist=False: cache[split]
for arch, name in (("deep", "deeper MLP"), ("agecnn", "CNN on aging bits"), ("setctx", "set-attention")):
    t = time.time(); N.train("global", arch, "K"); s = time.time() - t
    out.append((name, N.DEV, round(s, 1))); print(out[-1], flush=True)
with open(Z.ps.ROOT / "report" / "results2" / "training_times.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["model", "device", "train_seconds"]); w.writerows(out)
print("done", flush=True)
