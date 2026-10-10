"""The integer networks (kernel/mlnet.h) against their float originals: do they pick the same victim
from recorded candidate sets, and do they give the same faults in the simulator?"""
import numpy as np

import extra_core as Z
import extra_nn as N
import netint
import pagesim as ps

MODELS = ["kv.agecnn.K.-", "graph.setctx.K.-", "kv.deep.K.-", "graph.rank.K.trees100-leaves16", "kv.gbdt.K.trees100-leaves16",
          "global.agecnn.K.-", "global.setctx.K.-", "global.deep.K.-", "global.rank.K.trees100-leaves16", "global.gbdt.K.trees100-leaves16"]
AG = ps.FEATURES.index("aging")


def float_scores(spec, feat, hist):
    if spec["kind"] == "trees":
        return ps.score_tree_group(Z.scored(spec, 0), feat)
    return N.make_fn(spec["net"])(feat, hist)


for name in MODELS:
    scope = "kv" if name.split(".")[0] == "global" else name.split(".")[0]      # validation candidate sets of one workload
    spec = Z.load_spec(name)
    d = Z.load("val", scope, hist=True)
    inet = netint.from_spec(spec)
    sm = netint.scored(spec, 0)
    g = d["group"]
    agree = n = 0
    ranks = []
    for gid in np.unique(g)[:400]:
        m = g == gid
        if m.sum() < 4:
            continue
        feat, hist = d["feat"][m], d["hist"][m]
        f = float_scores(spec, feat, hist)
        q = np.rint(feat[:, 4:12] * 256).astype(np.int32)
        i = ps.score_net_group(sm, q, np.rint(feat[:, AG] * 255).astype(np.int32))
        agree += int(np.argmax(f) == np.argmax(i))
        n += 1
        ranks.append(np.corrcoef(f, i)[0, 1] if f.std() > 0 and i.std() > 0 else 1.0)
    # faults in the simulator: float model vs integer network on three validation streams at 10%
    fa, ia = [], []
    for st in Z.val_stems(scope)[:3]:
        s = ps.load_stream(st)
        cap = s.capacities["0.1"]
        fa.append(ps.run(s, cap, "learned", Z.scored(spec, 2))["faults"])
        ia.append(ps.run(s, cap, "learned", netint.scored(spec, 2))["faults"])
    print(f"{name:34s} same victim {agree}/{n}  score corr {np.mean(ranks):.4f}  faults float {fa} int {ia}")
    assert agree / n > 0.8 and np.mean(ranks) > 0.97, name
print("integer networks match their float originals")
