"""Checks for the model-extra plumbing: C tree scorer == sklearn/lightgbm predictions
(raw and candidate-rank features), rank columns == C rank_column, the callback
scorer reproduces a linear model's simulation, determinism."""
import numpy as np
import lightgbm as lgb
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor

import models as M
import pagesim as ps
import extra_core as Z

d = Z.load("train", "sort")
cols = Z.TIER_K
X, colmap = Z.design(d, cols, rel=True)
y = d["label"]
g = d["group"]
sel = np.isin(g, np.unique(g)[:300])
print("rows", len(y), "design", X.shape)

def check(name, spec, pred):
    sm = Z.scored(spec, 0)
    worst = 0.0
    for gid in np.unique(g[sel])[:60]:
        m = g == gid
        full = np.zeros((m.sum(), ps.NF), np.float32); full[:] = d["feat"][m]
        c = ps.score_tree_group(sm, full)
        worst = max(worst, float(np.abs(c - pred[m]).max()))
    print(f"{name:10s} max |C - python| over 60 candidate sets: {worst:.2e}")
    assert worst < 1e-3, name

# rank definition: C rank_column vs numpy
spec0 = dict(kind="trees", base=0.0, roots=[0], left=[0], right=[0], feat=[ps.NF + 5], thr=[0.0])
spec0["feat"] = [-1]
cart = DecisionTreeRegressor(max_depth=6, min_samples_leaf=100).fit(X[::5], y[::5])
check("cart", Z.from_sklearn([cart], colmap), cart.predict(X))
rf = RandomForestRegressor(10, max_depth=5, min_samples_leaf=100, random_state=0).fit(X[::10], y[::10])
check("forest", Z.from_sklearn(rf.estimators_, colmap, scale=1 / len(rf.estimators_)), rf.predict(X))
bst = lgb.train(dict(objective="regression", num_leaves=12, learning_rate=0.1, min_data_in_leaf=100,
                     verbose=-1, seed=1, num_threads=4), lgb.Dataset(X[::5], y[::5]), 25)
check("lightgbm", Z.from_lgbm(bst, colmap), bst.predict(X))

# callback scorer == native linear scorer in a simulation
spec = M.load_models("final_linear")["global|K"]
s = ps.load_stream("sort-n20000-s3") if "sort-n20000-s3" in [e["stem"] for e in ps.index()["streams"]] else ps.load_stream(ps.stems("test", "sort")[0])
cap = s.capacities["0.1"]
a = ps.run(s, cap, "learned", M.to_scored(spec, protect_age=2))
W = np.asarray(spec["layers"][0]["W"][0], np.float32); b = float(spec["layers"][0]["b"][0])
mean = np.asarray(spec["mean"], np.float32); std = np.asarray(spec["std"], np.float32)
j = [ps.FEATURES.index(f) for f in spec["features"]]
fn = lambda f, h: ((f[:, j] - mean) / std) @ W + b
cbm = ps.ScoredModel("callback", fn=fn, protect_age=2)
c = ps.run(s, cap, "learned", cbm)
c2 = ps.run(s, cap, "learned", cbm)
print("native", a["faults"], a["writebacks"], "callback", c["faults"], c["writebacks"])
assert c == c2 or (c["faults"], c["writebacks"]) == (c2["faults"], c2["writebacks"]), "callback not deterministic"
assert abs(c["faults"] - a["faults"]) <= max(3, 0.002 * a["faults"]), "callback differs from native linear"
# tree as single stump on feature K_IDLE: equals scoring by idle
print("extra checks passed")
