#!/usr/bin/env python3
"""Neural scorers for the traces2 study, trained on the GPU.

  mlp    n_in -> 32 -> 32 -> 1 over a feature subset          (any tier)
  gru    GRU(1->16) over the page's last 8 inter-access intervals, head
         over [h, recency]                                     (F: oracle)
  embed  a learned vector per page (absolute vpn) and a GRU(16->16) over the
         embeddings of the last 16 pages referenced by the whole program;
         head over [h, candidate's vector]                     (F: oracle,
                                                                cross-page)

All regress log1p(next-use distance) with a weighted MSE (equal total weight
per workload in the global scope), Adam, early stopping on the validation
split (matmul has none: 10% of its training decisions are held back).
Every trained model is checked against pagesim.c's own scorer on
validation rows before it is saved.

    python3 train_nn.py mlp --scope kv --features freq,rec
    python3 train_nn.py gru --scope graph
    python3 train_nn.py embed --scope btree
"""
import argparse
import json
import time

import numpy as np
import torch
import torch.nn as nn

import models as M
import pagesim as ps

DEV = "cuda" if torch.cuda.is_available() else "cpu"
SEQ_KEYS = ("feat", "label", "group", "is_opt", "hist", "page_vpn", "ctx_vpn")


def split_data(scope, keys):
    tr = M.load_scope("train", scope, keys)
    va = M.load_scope("val", scope, keys)
    if va is None or scope == "matmul":
        # hold back 10% of training decisions
        g = tr["group"]
        rng = np.random.default_rng(0)
        ug = np.unique(g)
        held = set(rng.choice(ug, size=max(1, len(ug) // 10), replace=False).tolist())
        m = np.isin(g, list(held))
        va = {k: v[m] for k, v in tr.items()}
        tr = {k: v[~m] for k, v in tr.items()}
    return tr, va


class MLP(nn.Module):
    def __init__(self, n_in, h=32):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_in, h), nn.ReLU(), nn.Linear(h, h),
                                 nn.ReLU(), nn.Linear(h, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1)


class GRUScorer(nn.Module):
    def __init__(self, h=16):
        super().__init__()
        self.gru = nn.GRU(1, h, batch_first=True)
        self.head = nn.Sequential(nn.Linear(h + 1, 16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, hist, rec):
        _, h = self.gru(hist.unsqueeze(-1))
        return self.head(torch.cat([h[-1], rec.unsqueeze(-1)], -1)).squeeze(-1)


class EmbedScorer(nn.Module):
    def __init__(self, n_vpn, d=16, h=16):
        super().__init__()
        self.emb = nn.Embedding(n_vpn + 1, d)       # last row = padding/unknown
        self.gru = nn.GRU(d, h, batch_first=True)
        self.head = nn.Sequential(nn.Linear(h + d, 16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, ctx, page):
        _, h = self.gru(self.emb(ctx))
        return self.head(torch.cat([h[-1], self.emb(page)], -1)).squeeze(-1)


def fit(model, make_batch, n_tr, n_va, w_tr, w_va, epochs=60, batch=8192,
        lr=2e-3, patience=4):
    model.to(DEV)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    best, best_state, bad = float("inf"), None, 0
    wt = torch.as_tensor(w_tr, dtype=torch.float32, device=DEV)
    wv = torch.as_tensor(w_va, dtype=torch.float32, device=DEV)
    log = []
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n_tr, device=DEV)
        for i in range(0, n_tr, batch):
            idx = perm[i:i + batch]
            pred, y = make_batch("tr", idx)
            loss = (wt[idx] * (pred - y) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            tot, wsum = 0.0, 0.0
            for i in range(0, n_va, 65536):
                idx = torch.arange(i, min(i + 65536, n_va), device=DEV)
                pred, y = make_batch("va", idx)
                tot += float((wv[idx] * (pred - y) ** 2).sum())
                wsum += float(wv[idx].sum())
        v = tot / wsum
        log.append(v)
        if v < best - 1e-4:
            best, bad = v, 0
            best_state = {k: t.detach().clone() for k, t in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    model.load_state_dict(best_state)
    return best, log


def layers_of(seq):
    return [{"W": m.weight.detach().cpu().numpy().tolist(),
             "b": m.bias.detach().cpu().numpy().tolist()}
            for m in seq if isinstance(m, nn.Linear)]


def gru_flat(g):
    return np.concatenate([g.weight_ih_l0.detach().cpu().numpy().ravel(),
                           g.weight_hh_l0.detach().cpu().numpy().ravel(),
                           g.bias_ih_l0.detach().cpu().numpy().ravel(),
                           g.bias_hh_l0.detach().cpu().numpy().ravel()]).tolist()


def train_mlp(scope, features, seed=0):
    torch.manual_seed(seed)
    tr, va = split_data(scope, ("feat", "label", "group", "is_opt"))
    stats = M.LinearFitter(tr)          # same standardisation as the linear fits
    j = [ps.FEATURES.index(f) for f in features]
    mean, std = stats.mean[j], stats.std[j]
    X = {k: torch.as_tensor((d["feat"][:, j] - mean) / std, dtype=torch.float32,
                            device=DEV) for k, d in (("tr", tr), ("va", va))}
    Y = {k: torch.as_tensor(d["label"], device=DEV) for k, d in (("tr", tr), ("va", va))}
    model = MLP(len(j))
    best, log = fit(model, lambda s, idx: (model(X[s][idx]), Y[s][idx]),
                    len(tr["label"]), len(va["label"]), tr["weight"], va["weight"])
    spec = {"kind": "mlp", "features": list(features), "mean": mean.tolist(),
            "std": std.tolist(), "layers": layers_of(model.net),
            "val_mse": best, "val_curve": log}
    # the C scorer must reproduce the trained network
    with torch.no_grad():
        want = model(X["va"][:50000]).cpu().numpy()
    got = ps.score_rows(M.to_scored(spec), va["feat"][:50000])
    spec["c_check_max_abs_err"] = float(np.abs(want - got).max())
    assert spec["c_check_max_abs_err"] < 1e-3, spec["c_check_max_abs_err"]
    return spec


def train_gru(scope, seed=0):
    torch.manual_seed(seed)
    keys = ("feat", "label", "group", "is_opt", "hist")
    tr, va = split_data(scope, keys)
    ri = ps.FEATURES.index("rec")
    stats = M.LinearFitter(tr)
    rm, rs = float(stats.mean[ri]), float(stats.std[ri])
    T = {k: (torch.as_tensor(d["hist"], device=DEV),
             torch.as_tensor((d["feat"][:, ri] - rm) / rs, dtype=torch.float32, device=DEV),
             torch.as_tensor(d["label"], device=DEV)) for k, d in (("tr", tr), ("va", va))}
    model = GRUScorer()
    best, log = fit(model, lambda s, idx: (model(T[s][0][idx], T[s][1][idx]), T[s][2][idx]),
                    len(tr["label"]), len(va["label"]), tr["weight"], va["weight"])
    spec = {"kind": "gru", "gru_h": 16, "gru_w": gru_flat(model.gru),
            "head": layers_of(model.head), "mean": [rm], "std": [rs],
            "val_mse": best, "val_curve": log}
    with torch.no_grad():
        want = model(T["va"][0][:50000], T["va"][1][:50000]).cpu().numpy()
    n = min(50000, len(va["label"]))
    got = ps.score_seq_rows(M.to_scored(spec), va["hist"][:n], va["feat"][:n, ri],
                            np.zeros(n, np.int32), np.zeros((n, ps.EMB_W), np.int32))
    spec["c_check_max_abs_err"] = float(np.abs(want[:n] - got).max())
    assert spec["c_check_max_abs_err"] < 1e-3, spec["c_check_max_abs_err"]
    return spec


def train_embed(scope, seed=0):
    torch.manual_seed(seed)
    keys = ("feat", "label", "group", "is_opt", "page_vpn", "ctx_vpn")
    tr, va = split_data(scope, keys)
    n_vpn = int(max(tr["page_vpn"].max(), tr["ctx_vpn"].max(),
                    va["page_vpn"].max(), va["ctx_vpn"].max())) + 1
    pad = n_vpn                                  # also "never seen in training"
    seen = np.zeros(n_vpn + 1, bool)
    seen[np.unique(np.r_[tr["page_vpn"], tr["ctx_vpn"][tr["ctx_vpn"] >= 0]])] = True

    def idx_of(v):
        v = np.where(v < 0, pad, v)
        return np.where(seen[v], v, pad)

    T = {k: (torch.as_tensor(idx_of(d["ctx_vpn"]), dtype=torch.long, device=DEV),
             torch.as_tensor(idx_of(d["page_vpn"]), dtype=torch.long, device=DEV),
             torch.as_tensor(d["label"], device=DEV)) for k, d in (("tr", tr), ("va", va))}
    model = EmbedScorer(n_vpn)
    best, log = fit(model, lambda s, idx: (model(T[s][0][idx], T[s][1][idx]), T[s][2][idx]),
                    len(tr["label"]), len(va["label"]), tr["weight"], va["weight"])
    E = model.emb.weight.detach().cpu().numpy()
    spec = {"kind": "embed", "gru_h": 16, "emb_d": 16, "n_vpn": n_vpn,
            "gru_w": gru_flat(model.gru), "head": layers_of(model.head),
            "emb": E.tolist(), "seen": np.nonzero(seen)[0].tolist(),
            "val_mse": best, "val_curve": log}
    with torch.no_grad():
        want = model(T["va"][0][:50000], T["va"][1][:50000]).cpu().numpy()
    n = len(want)
    scored = ps.ScoredModel("embed", gru_h=16, gru_w=np.asarray(spec["gru_w"], np.float32),
                            head=[(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32))
                                  for L in spec["head"]], emb_d=16, emb=E)
    got = ps.score_seq_rows(scored, np.zeros((n, ps.GRU_K), np.float32), np.zeros(n, np.float32),
                            T["va"][1][:n].cpu().numpy(), T["va"][0][:n].cpu().numpy())
    spec["c_check_max_abs_err"] = float(np.abs(want - got).max())
    assert spec["c_check_max_abs_err"] < 1e-3, spec["c_check_max_abs_err"]
    return spec


def embed_scored(spec, stream):
    """Per-stream embedding table in the dense page order pagesim uses: row p
    is the vector of the stream's p-th page (unknown pages -> padding row),
    plus one padding row at index n_pages."""
    E = np.asarray(spec["emb"], np.float32)
    pad = spec["n_vpn"]
    seen = np.zeros(pad + 1, bool)
    seen[spec["seen"]] = True
    v = stream.vpns
    idx = np.where((v < pad) & seen[np.minimum(v, pad)], v, pad)
    table = np.vstack([E[idx], E[pad:pad + 1]])
    head = [(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32))
            for L in spec["head"]]
    return ps.ScoredModel("embed", gru_h=spec["gru_h"],
                          gru_w=np.asarray(spec["gru_w"], np.float32), head=head,
                          emb_d=spec["emb_d"], emb=table)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["mlp", "gru", "embed"])
    ap.add_argument("--scope", required=True)
    ap.add_argument("--features", default="")
    ap.add_argument("--name", default="")
    a = ap.parse_args()
    t0 = time.time()
    if a.kind == "mlp":
        spec = train_mlp(a.scope, a.features.split(","))
    elif a.kind == "gru":
        spec = train_gru(a.scope)
    else:
        spec = train_embed(a.scope)
    name = a.name or f"{a.kind}_{a.scope}" + (f"_{a.features.replace(',', '+')}" if a.features else "")
    path = M.MODELS / "nn" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(spec, open(path, "w"))
    print(f"{name}: val_mse={spec['val_mse']:.4f} epochs={len(spec['val_curve'])} "
          f"C-vs-torch max err={spec['c_check_max_abs_err']:.1e} "
          f"({time.time() - t0:.0f}s) -> {path.relative_to(ps.ROOT)}", flush=True)


if __name__ == "__main__":
    main()
