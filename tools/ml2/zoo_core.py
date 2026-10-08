"""Model zoo core: training data with candidate-set ranks, tree converters, spec ->
simulator model, and cell evaluation with a resumable CSV.

A spec is a pickled dict in report/models2/zoo/<name>.pkl:
  {"kind": "trees", roots, left, right, feat, thr, base, protect_age}   (feat < NF raw, >= NF rank)
  {"kind": "linear", ...}   (models.py layout)
  {"kind": "np", "net": <zoo_nn net dict>, "protect_age": n}   (numpy set / sequence model)
"""
from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")   # one process per cell: BLAS threads only oversubscribe the cores

import csv
import math
import pickle
import time
from multiprocessing import Pool

import numpy as np

import models as M
import pagesim as ps

NF = ps.NF
R = ps.ROOT / "report" / "results2"
ZOO = ps.ROOT / "report" / "models2" / "zoo"
CELLS = R / "zoo_cells.csv"
HEADER = ["model", "scope", "stem", "split", "fraction", "faults", "writebacks", "aborted"]
TIER_K = list(range(4, NF))          # kernel-observable: K and K+ features
TIER_ALL = list(range(NF))
TIER_F = [0, 1, 2, 3]


# ---- data --------------------------------------------------------------------
def load(split, scope, hist=False):
    keys = ("feat", "label", "group", "is_opt") + (("hist",) if hist else ())
    wls = M.WORKLOADS if scope == "global" else [scope]
    parts, off = [], 0
    for wl in wls:
        p = M.load_part(split, wl, keys)
        if p is None:
            continue
        g = p["group"].astype(np.int64) + off
        off = int(g.max()) + 1
        parts.append((wl, {**p, "group": g}))
    if not parts:
        return None
    out = {k: np.concatenate([p[k] for _, p in parts]) for k in keys}
    w = np.concatenate([np.full(len(p["label"]), 1.0 / len(p["label"])) for _, p in parts])
    out["weight"] = w * len(w) / w.sum()
    return out


def rank_pct(x, group):
    """Per-feature percentile of each candidate within its set, as pagesim.c's
    rank_column(): (#less + 0.5 (#equal - 1)) / (n - 1), 0.5 for a single candidate."""
    import pandas as pd
    _, inv, cnt = np.unique(group, return_inverse=True, return_counts=True)
    n = cnt[inv].astype(np.float32)
    r = pd.DataFrame(x).groupby(group).rank(method="average").to_numpy(np.float32) - 1.0
    out = r / np.maximum(n - 1, 1)[:, None]
    out[n == 1] = 0.5
    return out


def design(data, cols, rel):
    """Matrix of the model's input columns: raw feature cols (+ their ranks)."""
    X = data["feat"][:, cols]
    if rel:
        X = np.hstack([X, rank_pct(data["feat"][:, cols], data["group"])])
    return X, list(cols) + [NF + c for c in cols] if rel else list(cols)


# ---- tree converters ---------------------------------------------------------
def flatten(trees, colmap):
    """trees: list of (left, right, feature, value_or_threshold, is_leaf) per tree."""
    roots, L, Rr, F, T = [], [], [], [], []
    for left, right, feat, thr, leaf in trees:
        o = len(F)
        roots.append(o)
        for i in range(len(feat)):
            if leaf[i]:
                F.append(-1); L.append(0); Rr.append(0)
            else:
                F.append(colmap[feat[i]]); L.append(left[i] + o); Rr.append(right[i] + o)
            T.append(thr[i])
    return dict(roots=roots, left=L, right=Rr, feat=F, thr=T)


def from_sklearn(estimators, colmap, scale=1.0, base=0.0):
    ts = []
    for e in estimators:
        t = e.tree_ if hasattr(e, "tree_") else e
        leaf = t.children_left < 0
        thr = np.where(leaf, t.value[:, 0, 0] * scale, t.threshold)
        ts.append((t.children_left, t.children_right, t.feature, thr, leaf))
    return dict(kind="trees", base=base, **flatten(ts, colmap))


def from_lgbm(booster, colmap):
    df = booster.trees_to_dataframe()
    ts = []
    for _, tr in df.groupby("tree_index", sort=True):
        ids = {n: i for i, n in enumerate(tr["node_index"])}
        left = [ids.get(x, 0) if isinstance(x, str) else 0 for x in tr["left_child"]]
        right = [ids.get(x, 0) if isinstance(x, str) else 0 for x in tr["right_child"]]
        leaf = tr["split_feature"].isna().to_numpy()
        feat = [int(str(f).split("_")[1]) if isinstance(f, str) and f.startswith("Column_") else
                -1 for f in tr["split_feature"]]
        thr = np.where(leaf, tr["value"], tr["threshold"]).astype(np.float64)
        ts.append((left, right, feat, thr, leaf))
    return dict(kind="trees", base=0.0, **flatten(ts, colmap))


def save_spec(name, spec):
    ZOO.mkdir(parents=True, exist_ok=True)
    with open(ZOO / f"{name}.pkl", "wb") as f:
        pickle.dump(spec, f)


def load_spec(name):
    with open(ZOO / f"{name}.pkl", "rb") as f:
        return pickle.load(f)


def scored(spec, protect_age=None):
    pa = spec.get("protect_age", 0) if protect_age is None else protect_age
    if spec["kind"] == "trees":
        return ps.ScoredModel("trees", roots=spec["roots"], left=spec["left"], right=spec["right"],
                              feat=spec["feat"], thr=spec["thr"], base=spec["base"], protect_age=pa)
    if spec["kind"] == "linear":
        return M.to_scored(spec, protect_age=pa)
    import zoo_nn
    return ps.ScoredModel("callback", fn=zoo_nn.make_fn(spec["net"]), protect_age=pa)


# ---- evaluation --------------------------------------------------------------
def clock_table():
    t = {}
    for f in ("classical.csv", "transfer.csv", "transfer_real.csv", "transfer_app.csv"):
        p = R / f
        if p.exists():
            for r in csv.DictReader(open(p)):
                if r.get("policy", r.get("model")) == "clock":
                    t[(r["stem"], r["fraction"])] = int(r["faults"])
    return t


CLOCK = clock_table()
TRANSFER_STEMS = ([f"pat-{m}-s{s}" for m in ("loop", "scanhot", "scanhotlo", "zipf060", "zipf080",
                  "zipf099", "zipf120", "uniform", "phase", "phaseshort", "switch") for s in (1, 5)]
                  + [f"kv-T{c}-s1" for c in (4, 17, 18, 24, 35, 52)]
                  + ["redis-real-s1", "sqlite-real-s1"]
                  + [f"app-{m}-s{k}" for m in ("chase", "spmv", "hashjoin", "bloom") for k in (1, 3)])


def val_stems(scope):
    wls = M.WORKLOADS if scope == "global" else [scope]
    out = []
    for wl in wls:
        out += ps.stems("train", "matmul") if wl == "matmul" else ps.stems("val", wl)
    return out


def test_stems():
    """test + held-out dataset streams and the transfer streams that have Clock reference counts
    (patbench seeds 1 and 5 only; the other patbench seeds are not scored)."""
    out = list(dict.fromkeys(list(ps.stems(("test", "heldout"))) + TRANSFER_STEMS))
    return [s for s in out if (s, "0.1") in CLOCK]


def _job(a):
    name, pa, stem, frac, scope = a
    spec = load_spec(name)
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    r = ps.run(s, cap, "learned", scored(spec, pa), max_faults=3 * CLOCK[(stem, frac)])
    return [f"{name}|pa{pa}", scope, stem, s.split, frac, r["faults"], r["writebacks"], int(r["aborted"])]


def evaluate(tasks, jobs=6, out=CELLS):
    """tasks: (name, protect_age, stem, fraction, scope). Skips cells already in the CSV."""
    done = set()
    if out.exists():
        done = {(r["model"], r["stem"], r["fraction"]) for r in csv.DictReader(open(out))}
    todo = [t for t in tasks if (f"{t[0]}|pa{t[1]}", t[2], t[3]) not in done]
    new = not out.exists()
    t0 = time.time()
    with Pool(jobs) as pool, open(out, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        for i, row in enumerate(pool.imap_unordered(_job, todo, chunksize=1), 1):
            w.writerow(row); f.flush()
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} cells, {time.time() - t0:.0f}s", flush=True)
    return len(todo)


def ratios(model_key, stems, fracs=None):
    """geo-mean faults/Clock of a model over its recorded cells on `stems`."""
    rows = [r for r in csv.DictReader(open(CELLS)) if r["model"] == model_key and r["stem"] in stems
            and (fracs is None or r["fraction"] in fracs)]
    if not rows:
        return None
    v = [min(int(r["faults"]), 3 * CLOCK[(r["stem"], r["fraction"])]) / CLOCK[(r["stem"], r["fraction"])]
         for r in rows]
    return math.exp(sum(math.log(max(x, 1e-9)) for x in v) / len(v)), len(v)
