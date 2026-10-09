"""Turn a trained extra model (deeper MLP, aging-bit CNN, set-attention net, boosted trees) into the integer
layout of kernel/mlnet.h, for the simulator (pagesim kind "intnet") and for the kernel's generated tables.

Input standardisation is folded into the first layer, so the kernel feeds raw Q8 features. Weights are
Q8 integers, biases Q16 (see kernel/mlnet.h). Only models whose inputs are the 8 kernel features (K tier,
columns 4..11 of pagesim.FEATURES) and, for the CNN, the aging register can be exported.
"""
import ctypes as C

import numpy as np

import pagesim as ps

K0 = 4                      # first kernel feature in pagesim.FEATURES
MLP, CNN, SET, TREES = 1, 2, 3, 4
_P = C.POINTER(C.c_int32)


class Net(C.Structure):     # mirrors struct mlnet in kernel/mlnet.h
    _fields_ = [("kind", C.c_int), ("n_layers", C.c_int), ("sizes", C.c_int * 6),
                ("w", _P), ("c1w", _P), ("c1b", _P), ("c2w", _P), ("c2b", _P),
                ("encw", _P), ("encb", _P), ("qw", _P),
                ("n_trees", C.c_int),
                ("root", _P), ("nf", _P), ("nthr", _P), ("nl", _P), ("nr", _P)]


class IntNet:
    def __init__(self, kind):
        self.c = Net()
        self.c.kind = kind
        self.arrays = {}

    def put(self, field, a):
        a = np.ascontiguousarray(np.asarray(a, np.int64))
        assert np.abs(a).max(initial=0) < 2 ** 31, f"{field} overflows int32"
        a = a.astype(np.int32)
        self.arrays[field] = a
        setattr(self.c, field, a.ctypes.data_as(_P))


def q8(x):
    return np.rint(np.asarray(x, np.float64) * 256)


def q16(x):
    return np.rint(np.asarray(x, np.float64) * 65536)


def fold(W, b, mu, sd):
    """first layer on raw features: W' = W / sd, b' = b - W (mu / sd)"""
    Wf = W / sd[None, :]
    return Wf, b - (W * (mu / sd)[None, :]).sum(1)


def dense_flat(layers):
    """[(W, b)] -> flat int array: per layer W (Q8) then b (Q16)"""
    return np.concatenate([np.concatenate([q8(W).ravel(), q16(b).ravel()]) for W, b in layers])


def from_spec(spec):
    """spec: {'kind': 'np', 'net': ...} or {'kind': 'trees', ...} -> IntNet"""
    if spec["kind"] == "trees":
        return _trees(spec)
    net = spec["net"]
    w = {k: v.astype(np.float64) for k, v in net["w"].items()}
    arch, nm = net["arch"], net["norm"]
    assert net["cols"] == list(range(K0, ps.NF)), "only the 8 kernel features can be exported"
    mu, sd = np.asarray(nm["mu"], np.float64), np.asarray(nm["sd"], np.float64)
    heads = sorted({int(k.split(".")[1]) for k in w if k.startswith("head.") and k.endswith("weight")})
    hl = [(w[f"head.{i}.weight"], w[f"head.{i}.bias"]) for i in heads]
    if arch == "deep":
        W0, b0 = fold(hl[0][0], hl[0][1], mu, sd)
        n = IntNet(MLP)
        _head(n, [(W0, b0)] + hl[1:])
        return n
    if arch == "agecnn":
        W0 = hl[0][0]                                   # [32, 8 features + 32 conv]
        Wf, b0 = fold(W0[:, :8], hl[0][1], mu, sd)
        n = IntNet(CNN)
        _head(n, [(np.hstack([Wf, W0[:, 8:]]), b0)] + hl[1:])
        n.put("c1w", q8(w["hist.c1.weight"]).reshape(8, 3))
        n.put("c1b", q16(w["hist.c1.bias"]))
        n.put("c2w", q8(w["hist.c2.weight"]).reshape(8, 24))
        n.put("c2b", q16(w["hist.c2.bias"]))
        return n
    if arch == "setctx":
        We, be = fold(w["enc.0.weight"], w["enc.0.bias"], mu, sd)
        n = IntNet(SET)
        _head(n, hl)
        n.put("encw", q8(We))
        n.put("encb", q16(be))
        n.put("qw", q8(w["q.weight"]).ravel())
        return n
    raise ValueError(arch)


def _head(n, layers):
    sizes = [layers[0][0].shape[1]] + [W.shape[0] for W, _ in layers]
    assert layers[-1][0].shape[0] == 1 and len(sizes) <= 6
    n.c.n_layers = len(layers)
    for i, s in enumerate(sizes):
        n.c.sizes[i] = s
    n.put("w", dense_flat(layers))


def _trees(spec):
    n = IntNet(TREES)
    feat = np.asarray(spec["feat"], np.int64)
    thr = np.asarray(spec["thr"], np.float64)
    leaf = feat < 0
    assert (feat[~leaf] >= K0).all() and (feat[~leaf] < ps.NF).all(), "trees must split on the 8 kernel features"
    nf = np.where(leaf, -1, feat - K0)
    # x <= thr in float; the kernel compares Q8 integers: x_q8 <= floor(thr * 256 + 0.5)
    nthr = np.where(leaf, q16(thr), np.floor(thr * 256 + 0.5))
    n.c.n_trees = len(spec["roots"])
    n.put("root", spec["roots"])
    n.put("nf", nf)
    n.put("nthr", nthr)
    n.put("nl", spec["left"])
    n.put("nr", spec["right"])
    return n


def scored(spec, protect_age=0, **kw):
    """ScoredModel running the integer network in the simulator"""
    return ps.ScoredModel("intnet", net=from_spec(spec), protect_age=protect_age, **kw)


# ---- C tables for the kernel ---------------------------------------------------------
def c_array(name, a):
    body = ", ".join(str(int(x)) for x in a)
    return f"static const int {name}[] = {{ {body} }};\n"


def c_struct(prefix, n):
    """C definition of a `struct mlnet` initialiser and its data arrays, as text"""
    out, ref = "", {}
    for f, a in n.arrays.items():
        out += c_array(f"{prefix}_{f}", a.ravel())
        ref[f] = f"{prefix}_{f}"
    g = lambda f: ref.get(f, "0")
    sizes = ", ".join(str(n.c.sizes[i]) for i in range(6))
    out += (f"static const struct mlnet {prefix} = {{ {n.c.kind}, {n.c.n_layers}, {{ {sizes} }}, {g('w')}, "
            f"{g('c1w')}, {g('c1b')}, {g('c2w')}, {g('c2b')}, {g('encw')}, {g('encb')}, {g('qw')}, "
            f"{n.c.n_trees}, {g('root')}, {g('nf')}, {g('nthr')}, {g('nl')}, {g('nr')} }};\n")
    return out
