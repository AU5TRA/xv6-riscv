#!/usr/bin/env python3
"""Tree-family models (the roadmap's own first models, never run in ml2): logistic
regression, CART, random forest, GBDT (regression and lambdarank), each on kernel-
observable features (K: K and K+ tiers) or all features (FK), with and without
candidate-set rank features ("r"). The grid is fixed below, before any result.

    python3 zoo_trees.py fit [--scopes global kv ...]   fit the grid -> report/models2/zoo/*.pkl
    python3 zoo_trees.py select [--jobs 6]              each fit on validation cells at 10%
    python3 zoo_trees.py test [--jobs 6]                best per scope x family on test/held-out/transfer
    python3 zoo_trees.py report                         tables

Selection is on validation only (matmul has no validation streams: its training streams).
"""
import argparse
import csv
import math
import time
from collections import defaultdict

import lightgbm as lgb
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeRegressor

import models as M
import pagesim as ps
import zoo_core as Z

SCOPES = M.WORKLOADS + ["global"]
FEATSETS = {"K": Z.TIER_K, "FK": Z.TIER_ALL}
# family, params (fixed grid)
GRID = [("cart", dict(depth=4)), ("cart", dict(depth=8)),
        ("gbdt", dict(trees=30, leaves=8)), ("gbdt", dict(trees=30, leaves=16)),
        ("gbdt", dict(trees=100, leaves=8)), ("gbdt", dict(trees=100, leaves=16)),
        ("rank", dict(trees=100, leaves=16)), ("rf", dict(trees=30, depth=8)),
        ("logit", dict())]
ROW_CAP = {"cart": 400_000, "rf": 400_000, "logit": 400_000, "gbdt": 1_500_000, "rank": 1_000_000}
PROTECT = (0, 2)
SEL_FRAC = "0.1"


def pname(p):
    return "-".join(f"{k}{v}" for k, v in p.items()) or "-"


def name_of(scope, fam, p, fs, rel):
    return f"{scope}.{fam}.{fs}{'r' if rel else ''}.{pname(p)}"


def subsample(n, cap, seed=1):
    if n <= cap:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, cap, replace=False))


def fit_one(d, scope, fam, p, fs, rel):
    cols = FEATSETS[fs]
    X, colmap = Z.design(d, cols, rel)
    y, w = d["label"], d["weight"]
    idx = subsample(len(y), ROW_CAP[fam])
    if fam == "cart":
        m = DecisionTreeRegressor(max_depth=p["depth"], min_samples_leaf=200, random_state=1)
        m.fit(X[idx], y[idx], sample_weight=w[idx])
        return Z.from_sklearn([m], colmap)
    if fam == "rf":
        m = RandomForestRegressor(p["trees"], max_depth=p["depth"], min_samples_leaf=100,
                                  max_features=0.5, n_jobs=6, random_state=1)
        m.fit(X[idx], y[idx], sample_weight=w[idx])
        return Z.from_sklearn(m.estimators_, colmap, scale=1.0 / len(m.estimators_))
    if fam == "logit":
        if rel:
            return None
        mu, sd = X[idx].mean(0), X[idx].std(0) + 1e-9
        m = LogisticRegression(C=1.0, class_weight="balanced", max_iter=300)
        m.fit((X[idx] - mu) / sd, d["is_opt"][idx])
        j = [ps.FEATURES[c] for c in cols]
        return dict(kind="linear", features=j, protect_age=0, mean=mu.tolist(), std=sd.tolist(),
                    layers=[dict(W=[m.coef_[0].tolist()], b=[float(m.intercept_[0])])])
    params = dict(num_leaves=p["leaves"], learning_rate=0.1, min_data_in_leaf=200, verbose=-1,
                  seed=1, num_threads=6, feature_fraction=1.0)
    if fam == "gbdt":
        ds = lgb.Dataset(X[idx], y[idx], weight=w[idx])
        b = lgb.train(dict(params, objective="regression"), ds, p["trees"])
    else:  # lambdarank: relevance = quantile grade of the true next-use distance
        g = d["group"]
        order = np.argsort(g[idx], kind="stable")
        ii = idx[order]
        grade = np.digitize(y[ii], np.quantile(y[ii], np.linspace(0, 1, 17)[1:-1])).astype(int)
        _, first, cnt = np.unique(g[ii], return_index=True, return_counts=True)
        sizes = cnt[np.argsort(first)]
        ds = lgb.Dataset(X[ii], grade, group=sizes)
        b = lgb.train(dict(params, objective="lambdarank", lambdarank_truncation_level=20,
                           label_gain=list(range(17))), ds, p["trees"])
    return Z.from_lgbm(b, colmap)


def fit(scopes):
    for scope in scopes:
        d = Z.load("train", scope)
        t0 = time.time()
        n = 0
        for fs in FEATSETS:
            for rel in (False, True):
                for fam, p in GRID:
                    name = name_of(scope, fam, p, fs, rel)
                    if (Z.ZOO / f"{name}.pkl").exists():
                        continue
                    spec = fit_one(d, scope, fam, p, fs, rel)
                    if spec is not None:
                        Z.save_spec(name, spec)
                        n += 1
        print(f"{scope}: {n} fits, {time.time() - t0:.0f}s", flush=True)


def names(scope):
    """Every fitted model of the scope (any family: trees here, neural nets from zoo_nn.py)."""
    return sorted(p.stem for p in Z.ZOO.glob(f"{scope}.*.pkl"))


def select(jobs):
    tasks = []
    for scope in SCOPES:
        for nm in names(scope):
            for pa in PROTECT:
                tasks += [(nm, pa, st, SEL_FRAC, scope) for st in Z.val_stems(scope)]
    print(len(tasks), "validation cells", flush=True)
    Z.evaluate(tasks, jobs)


def best(scope):
    """Best (model, protect_age) per family key (family.featset) by validation geo-mean."""
    stems = set(Z.val_stems(scope))
    res = {}
    for nm in names(scope):
        fam = nm.split(".")[1] + "." + nm.split(".")[2]
        for pa in PROTECT:
            r = Z.ratios(f"{nm}|pa{pa}", stems, {SEL_FRAC})
            if r and (fam not in res or r[0] < res[fam][0]):
                res[fam] = (r[0], nm, pa)
    return res


def test(jobs):
    tasks = []
    for scope in SCOPES:
        keep = set()
        for fam, (v, nm, pa) in best(scope).items():
            keep.add((nm, pa))
        for nm, pa in keep:
            for st in Z.test_stems():
                wl = ps.index_entry(st)["workload"]
                if scope != "global" and wl != scope and not (scope == "kv" and st.startswith("kv-T")):
                    continue
                tasks += [(nm, pa, st, f, scope) for f in ("0.05", "0.1", "0.2")]
    print(len(tasks), "test cells", flush=True)
    Z.evaluate(tasks, jobs)


def report():
    rows = list(csv.DictReader(open(Z.CELLS)))
    groups = {"test": lambda r: r["split"] == "test", "held-out": lambda r: r["split"] == "heldout"
              and not r["stem"].startswith(("pat", "kv-T", "redis", "sqlite")),
              "pat": lambda r: r["stem"].startswith("pat"), "kv-T": lambda r: r["stem"].startswith("kv-T"),
              "real": lambda r: r["stem"].startswith(("redis", "sqlite"))}
    print(f"{'scope':8s}{'family.featset':12s}{'val':>7s}  " + "".join(f"{g:>9s}" for g in groups) + "   model")
    for scope in SCOPES:
        for fam, (v, nm, pa) in sorted(best(scope).items(), key=lambda kv: kv[1][0]):
            line = f"{scope:8s}{fam:12s}{v:7.3f}  "
            for g, pred in groups.items():
                vals = [min(int(r["faults"]), 3 * Z.CLOCK[(r["stem"], r["fraction"])]) / Z.CLOCK[(r["stem"], r["fraction"])]
                        for r in rows if r["model"] == f"{nm}|pa{pa}" and pred(r)]
                line += f"{math.exp(np.mean(np.log(np.maximum(vals, 1e-9)))):9.3f}" if vals else f"{'-':>9s}"
            print(line + f"   {nm.split('.', 1)[1]} pa{pa}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--scopes", nargs="*", default=SCOPES)
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    {"fit": lambda: fit(a.scopes), "select": lambda: select(a.jobs), "test": lambda: test(a.jobs),
     "report": report}[a.cmd]()
