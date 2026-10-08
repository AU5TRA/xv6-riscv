"""Training-data access and model fitting for the traces2 study.

Scopes: a model is trained either on one workload's train split
("btree", "graph", "kv", "lzw", "matmul", "sort") or on all of them ("global",
each workload weighted equally so kv's 2.2M rows don't drown sort's 82K).

Linear models are fitted in closed form. The weighted moment matrix of
[1, standardised features] is computed once per scope; the fit for any
feature subset is then a solve on its sub-block, so all 4095 subsets
would cost milliseconds.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

import pagesim as ps

CACHE = ps.ROOT / "traces2" / "ml2_cache"
MODELS = ps.ROOT / "report" / "models2"
WORKLOADS = ["btree", "graph", "kv", "lzw", "matmul", "sort"]
RIDGE = 1e-4
PROTECT_AGE = 2   # probation for newly loaded pages, chosen on validation (§7)


@lru_cache(maxsize=None)
def load_part(split, workload, keys=("feat", "label", "group", "is_opt")):
    path = CACHE / f"{split}_{workload}.npz"
    if not path.exists():
        return None
    z = np.load(path)
    return {k: z[k] for k in keys}


def load_scope(split, scope, keys=("feat", "label", "group", "is_opt")):
    """Rows of one scope, plus per-row weights (equal total per workload)."""
    wls = WORKLOADS if scope == "global" else [scope]
    parts = [(wl, load_part(split, wl, keys)) for wl in wls]
    parts = [(wl, p) for wl, p in parts if p is not None]
    if not parts:
        return None
    out = {k: np.concatenate([p[k] for _, p in parts]) for k in keys}
    out["weight"] = np.concatenate(
        [np.full(len(p["label"]), 1.0 / len(p["label"]), np.float64) for _, p in parts])
    out["weight"] *= len(out["weight"]) / out["weight"].sum()
    out["workload"] = np.concatenate([np.full(len(p["label"]), wl) for wl, p in parts])
    return out


class LinearFitter:
    """Closed-form weighted ridge regression over any feature subset."""

    def __init__(self, data):
        X = data["feat"].astype(np.float64)
        w = data["weight"]
        self.mean = (w[:, None] * X).sum(0) / w.sum()
        var = (w[:, None] * (X - self.mean) ** 2).sum(0) / w.sum()
        self.std = np.sqrt(np.maximum(var, 1e-12))
        Z = np.hstack([np.ones((len(X), 1)), (X - self.mean) / self.std])
        self.M = (Z * w[:, None]).T @ Z
        self.r = (Z * w[:, None]).T @ data["label"].astype(np.float64)

    def fit(self, features):
        idx = [0] + [1 + ps.FEATURES.index(f) for f in features]
        A = self.M[np.ix_(idx, idx)].copy()
        A[1:, 1:] += RIDGE * self.M[0, 0] * np.eye(len(idx) - 1)
        theta = np.linalg.solve(A, self.r[idx])
        j = [ps.FEATURES.index(f) for f in features]
        return {"kind": "linear", "features": list(features), "protect_age": PROTECT_AGE,
                "mean": self.mean[j].tolist(), "std": self.std[j].tolist(),
                "layers": [{"W": [theta[1:].tolist()], "b": [float(theta[0])]}]}


def to_scored(spec, protect_age=None):
    """JSON model spec -> pagesim.ScoredModel. protect_age overrides the
    spec's own probation setting (spec["protect_age"], default 0)."""
    pa = spec.get("protect_age", 0) if protect_age is None else protect_age
    if spec["kind"] in ("linear", "mlp"):
        layers = [(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32))
                  for L in spec["layers"]]
        return ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"],
                              std=spec["std"], layers=layers, protect_age=pa)
    head = [(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32))
            for L in spec["head"]]
    if spec["kind"] == "gru":
        return ps.ScoredModel("gru", gru_h=spec["gru_h"],
                              gru_w=np.asarray(spec["gru_w"], np.float32),
                              head=head, mean=spec["mean"], std=spec["std"],
                              protect_age=pa)
    raise ValueError("embedding models need a per-stream table: use embed_scored")


def predict(spec, feat):
    """numpy forward pass of a linear/MLP spec over raw feature rows, for
    checking the C scorer against the trained model."""
    j = [ps.FEATURES.index(f) for f in spec["features"]]
    a = (feat[:, j] - np.asarray(spec["mean"])) / np.asarray(spec["std"])
    for i, L in enumerate(spec["layers"]):
        a = a @ np.asarray(L["W"]).T + np.asarray(L["b"])
        if i + 1 < len(spec["layers"]):
            a = np.maximum(a, 0)
    return a[:, 0]


def save_models(name, specs):
    MODELS.mkdir(parents=True, exist_ok=True)
    path = MODELS / f"{name}.json"
    with open(path, "w") as f:
        json.dump(specs, f)
    return path


def load_models(name):
    return json.load(open(MODELS / f"{name}.json"))
