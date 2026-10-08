"""Python side of tools/ml2/pagesim.c: stream loading, simulation, and
training-data recording for the traces2/ ML study.

    from pagesim import load_stream, run, record, FEATURES
    s = load_stream("kv-A-s5")
    run(s, s.capacities["0.1"], "lru")          # -> {'faults': ..., ...}
"""
from __future__ import annotations

import csv
import ctypes as C
import json
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "traces2" / "ML"
SRC = HERE / "pagesim.c"
LIB = HERE / "libpagesim.so"

POLICIES = ["fifo", "clock", "aging", "lru", "lfu_exact", "lfu_kernel",
            "belady", "learned", "sd_old", "gru", "embed"]
FEATURES = ["rec", "freq", "sd", "wr",                       # F: full-stream
            "ref", "aging", "sfreq", "idle", "age", "dirty",  # K: kernel-observable
            "refaults", "rdist"]                              # K+: refault bookkeeping
TIER = {f: "F" for f in FEATURES[:4]}
TIER.update({f: "K" for f in FEATURES[4:10]})
TIER.update({f: "K+" for f in FEATURES[10:]})
NF = len(FEATURES)
MAXL = 6
NEVER = 0xFFFFFFFF


def _build():
    # Compile to a temporary name and rename into place: processes that
    # already have the old library mapped (a running sweep) keep their copy.
    if not LIB.exists() or LIB.stat().st_mtime < SRC.stat().st_mtime:
        import os
        tmp = LIB.with_suffix(f".{os.getpid()}.tmp")
        subprocess.run(["gcc", "-O3", "-march=native", "-shared", "-fPIC",
                        "-Wall", "-Wextra", "-o", str(tmp), str(SRC), "-lm"],
                       check=True)
        os.replace(tmp, LIB)
    return C.CDLL(str(LIB))


class Model(C.Structure):
    _fields_ = [("kind", C.c_int), ("n_in", C.c_int),
                ("feat", C.c_int * NF), ("mean", C.c_float * NF),
                ("std", C.c_float * NF), ("n_layers", C.c_int),
                ("sizes", C.c_int * (MAXL + 1)), ("w", C.POINTER(C.c_float)),
                ("gru_h", C.c_int), ("gru_w", C.POINTER(C.c_float)),
                ("head_w", C.POINTER(C.c_float)), ("head_layers", C.c_int),
                ("head_sizes", C.c_int * (MAXL + 1)), ("emb_d", C.c_int),
                ("emb", C.POINTER(C.c_float)), ("quant_w", C.c_int),
                ("qa", C.c_int32 * NF), ("protect_age", C.c_int)]


class Result(C.Structure):
    _fields_ = [("faults", C.c_int64), ("evictions", C.c_int64),
                ("writebacks", C.c_int64), ("rows", C.c_int64),
                ("overflow", C.c_int64), ("aborted", C.c_int64)]


class Recorder(C.Structure):
    _fields_ = [("p", C.c_double), ("rng", C.c_uint64), ("max_cand", C.c_int),
                ("cap", C.c_int64),
                ("feat", C.POINTER(C.c_float)), ("label", C.POINTER(C.c_float)),
                ("group", C.POINTER(C.c_int32)), ("is_opt", C.POINTER(C.c_uint8)),
                ("hist", C.POINTER(C.c_float)), ("page", C.POINTER(C.c_int32)),
                ("ctx", C.POINTER(C.c_int32)), ("n_recent", C.c_int)]


_lib = _build()
_lib.simulate.restype = C.c_int
_lib.simulate.argtypes = [C.c_int64, C.c_int, C.c_int, C.c_void_p, C.c_void_p,
                          C.c_void_p, C.c_int, C.POINTER(Model),
                          C.POINTER(Recorder), C.c_int64, C.POINTER(Result)]
_lib.score_rows.argtypes = [C.POINTER(Model), C.c_void_p, C.c_int64, C.c_void_p]
_lib.score_seq_rows.argtypes = [C.POINTER(Model), C.c_void_p, C.c_void_p,
                                C.c_void_p, C.c_void_p, C.c_int64, C.c_void_p]
assert _lib.pagesim_nf() == NF, "feature list out of sync with pagesim.c"
GRU_K = _lib.pagesim_gru_k()
EMB_W = _lib.pagesim_emb_w()


def _fptr(a):
    return a.ctypes.data_as(C.POINTER(C.c_float)) if a is not None else None


class Stream:
    def __init__(self, stem, entry):
        self.stem = stem
        self.meta = entry
        self.split = entry["split"]
        self.workload = entry["workload"]
        self.variant = entry["variant"]
        self.capacities = {k: int(v) for k, v in entry["capacities"].items()}
        z = np.load(DATA / f"{stem}.npz")
        vpn = z["vpn"]
        uniq, dense = np.unique(vpn, return_inverse=True)
        self.page = np.ascontiguousarray(dense.astype(np.uint32))
        self.write = np.ascontiguousarray(z["write"].astype(np.uint8))
        self.next_use = np.ascontiguousarray(z["next_use"].astype(np.uint32))
        self.n_pages = len(uniq)
        self.vpns = uniq.astype(np.int64)   # dense id -> absolute vpn
        self.n = len(vpn)

    def __repr__(self):
        return f"<Stream {self.stem} {self.split} n={self.n:,} pages={self.n_pages}>"


@lru_cache(maxsize=1)
def index():
    return json.load(open(DATA / "index.json"))


def stems(split=None, workload=None):
    out = []
    for e in index()["streams"]:
        if split and e["split"] not in ([split] if isinstance(split, str) else split):
            continue
        if workload and e["workload"] != workload:
            continue
        out.append(e["stem"])
    return out


def load_stream(stem):
    entry = next(e for e in index()["streams"] if e["stem"] == stem)
    return Stream(stem, entry)


def baselines():
    """(stem, fraction) -> {'frames', 'fifo', 'lru', 'belady'} from baselines.tsv."""
    out = {}
    with open(DATA / "baselines.tsv") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            out[(r["stem"], r["fraction"])] = {k: int(r[k]) for k in
                                               ("frames", "fifo", "lru", "belady")}
    return out


def _call(s, cap, policy, model=None, rec=None, max_faults=0):
    res = Result()
    m = C.byref(model) if model is not None else None
    r = C.byref(rec) if rec is not None else None
    rc = _lib.simulate(s.n, s.n_pages, cap, s.page.ctypes.data,
                       s.write.ctypes.data, s.next_use.ctypes.data,
                       POLICIES.index(policy), m, r, int(max_faults),
                       C.byref(res))
    if rc != 0:
        raise MemoryError("pagesim: allocation failed")
    return res


def run(s, cap, policy, model=None, max_faults=0):
    """Simulate `policy` (one of POLICIES) at `cap` frames from empty memory.
    With max_faults > 0 the run stops once it exceeds that many faults and
    reports aborted=True (counts are then lower bounds)."""
    if policy in ("learned", "gru", "embed") and model is None:
        raise ValueError("learned policies need a model")
    res = _call(s, cap, policy, model.c if model is not None else None,
                max_faults=max_faults)
    return {"faults": res.faults, "evictions": res.evictions,
            "writebacks": res.writebacks, "aborted": bool(res.aborted)}


def record(s, cap, behavior, p, max_rows, seed=1, model=None, seq=False,
           max_cand=0, n_recent=0):
    """Replay under `behavior` and record every candidate at a random fraction
    `p` of evictions. Returns dict of arrays (features for all NF features)."""
    feat = np.zeros((max_rows, NF), np.float32)
    label = np.zeros(max_rows, np.float32)
    group = np.zeros(max_rows, np.int32)
    is_opt = np.zeros(max_rows, np.uint8)
    hist = np.zeros((max_rows, GRU_K), np.float32) if seq else None
    page = np.zeros(max_rows, np.int32) if seq else None
    ctx = np.zeros((max_rows, EMB_W), np.int32) if seq else None
    rec = Recorder(p=p, rng=seed * 0x9E3779B97F4A7C15 % (1 << 64) or 1,
                   max_cand=max_cand, n_recent=n_recent,
                   cap=max_rows, feat=_fptr(feat), label=_fptr(label),
                   group=group.ctypes.data_as(C.POINTER(C.c_int32)),
                   is_opt=is_opt.ctypes.data_as(C.POINTER(C.c_uint8)),
                   hist=_fptr(hist),
                   page=page.ctypes.data_as(C.POINTER(C.c_int32)) if seq else None,
                   ctx=ctx.ctypes.data_as(C.POINTER(C.c_int32)) if seq else None)
    res = _call(s, cap, behavior, model.c if model is not None else None, rec)
    n = res.rows
    out = {"feat": feat[:n], "label": label[:n], "group": group[:n],
           "is_opt": is_opt[:n], "overflow": bool(res.overflow),
           "faults": res.faults}
    if seq:
        out.update(hist=hist[:n], page=page[:n], ctx=ctx[:n])
    return out


class ScoredModel:
    """A trained scorer in the layout pagesim.c expects. Keeps the numpy
    buffers alive for as long as the C struct points at them."""

    def __init__(self, kind, **kw):
        self.kind = kind
        self.kw = kw
        self.c = Model()
        self.c.kind = {"mlp": 0, "gru": 1, "embed": 2}[kind]
        self.c.protect_age = int(kw.get("protect_age", 0))
        self._keep = []
        if kind == "mlp":
            feats = kw["features"]
            self.c.n_in = len(feats)
            for j, f in enumerate(feats):
                self.c.feat[j] = FEATURES.index(f)
                self.c.mean[j] = kw["mean"][j]
                self.c.std[j] = kw["std"][j]
            self._set_mlp("w", "n_layers", "sizes", kw["layers"])
            q = kw.get("quant_w", 0)
            if q:
                assert len(kw["layers"]) == 1, "integer scoring is for linear models"
                W = kw["layers"][0][0].ravel().astype(np.float64)
                for j in range(len(feats)):
                    self.c.qa[j] = int(round(W[j] / kw["std"][j] * (1 << q)))
                self.c.quant_w = q
        else:
            self.c.gru_h = kw["gru_h"]
            g = np.ascontiguousarray(kw["gru_w"], np.float32)
            self._keep.append(g)
            self.c.gru_w = _fptr(g)
            self._set_mlp("head_w", "head_layers", "head_sizes", kw["head"])
            if kind == "gru":
                self.c.mean[0] = kw["mean"][0]
                self.c.std[0] = kw["std"][0]
            else:
                self.c.emb_d = kw["emb_d"]
                e = np.ascontiguousarray(kw["emb"], np.float32)
                self._keep.append(e)
                self.c.emb = _fptr(e)

    def _set_mlp(self, wfield, nfield, sfield, layers):
        """layers: list of (W[out][in], b[out]) numpy arrays."""
        flat = np.concatenate([np.concatenate([W.ravel(), b.ravel()])
                               for W, b in layers]).astype(np.float32)
        flat = np.ascontiguousarray(flat)
        self._keep.append(flat)
        setattr(self.c, wfield, _fptr(flat))
        setattr(self.c, nfield, len(layers))
        sizes = getattr(self.c, sfield)
        sizes[0] = layers[0][0].shape[1]
        for l, (W, _) in enumerate(layers):
            sizes[l + 1] = W.shape[0]


def score_rows(model, feat):
    """C scorer over raw feature rows [n][NF] (checks against the trainer)."""
    feat = np.ascontiguousarray(feat, np.float32)
    out = np.zeros(len(feat), np.float32)
    _lib.score_rows(C.byref(model.c), feat.ctypes.data, len(feat), out.ctypes.data)
    return out


def index_entry(stem):
    return next(e for e in index()["streams"] if e["stem"] == stem)


def score_seq_rows(model, hist, rec, page, ctx):
    """C GRU/embedding scorer over recorded rows: hist [n][GRU_K], raw rec
    feature [n], page / ctx indices into the model's own embedding table."""
    hist = np.ascontiguousarray(hist, np.float32)
    rec = np.ascontiguousarray(rec, np.float32)
    page = np.ascontiguousarray(page, np.int32)
    ctx = np.ascontiguousarray(ctx, np.int32)
    out = np.zeros(len(rec), np.float32)
    _lib.score_seq_rows(C.byref(model.c), hist.ctypes.data, rec.ctypes.data,
                        page.ctypes.data, ctx.ctypes.data, len(rec),
                        out.ctypes.data)
    return out
