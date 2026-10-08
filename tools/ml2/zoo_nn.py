#!/usr/bin/env python3
"""Neural scorers over candidate sets, trained on the GPU, run in the simulator as numpy callbacks.

  deep      MLP over the features (64-64-32-1)
  setctx    per-candidate encoder + attention pooling over the whole candidate set; the head sees
            [own encoding, set context, own - set mean]  (set-attention: "worst of this set")
  cnnmlp    1-D CNN over the page's last 8 reuse intervals, concatenated with the features, MLP head
  lstmmlp   LSTM over the same history, concatenated with the features, MLP head
  agecnn    CNN over the 8 bits of the aging register (the kernel's own scan history), + K features
  setcnn    setctx with the CNN history encoder in the per-candidate encoder (mixed model)

Inputs: feature tiers K (kernel-observable) or FK; the history models read the oracle interval
history (F) except agecnn (K). Loss: weighted MSE on log1p(next-use distance), as the other models.
Selection on validation, never on test (see zoo_trees.py select/test/report, which also handle these).

    python3 zoo_nn.py fit [--scopes global kv ...]
"""
import argparse
import time

import numpy as np
import torch
import torch.nn as nn

import models as M
import pagesim as ps
import zoo_core as Z

DEV = "cuda" if torch.cuda.is_available() else "cpu"
NH = 8                      # history length
MAXC = 32                   # candidates per recorded decision
SCOPES = M.WORKLOADS + ["global"]
GRID = [("deep", {}), ("setctx", {}), ("cnnmlp", {}), ("lstmmlp", {}), ("agecnn", {}), ("setcnn", {})]
FEATSETS = {"K": Z.TIER_K, "FK": Z.TIER_ALL}
AGING = ps.FEATURES.index("aging")
SAMPLE_CTX = 48             # set context at inference uses at most this many candidates


# ---- torch modules -----------------------------------------------------------
class Hist(nn.Module):
    """CNN or LSTM encoder of an [.., NH] history."""
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        if kind == "cnn":
            self.c1, self.c2 = nn.Conv1d(1, 8, 3), nn.Conv1d(8, 8, 3)   # 8 -> 6 -> 4
            self.out = 32
        else:
            self.lstm = nn.LSTM(1, 16, batch_first=True)
            self.out = 16

    def forward(self, h):                       # h [B, NH]
        if self.kind == "cnn":
            z = torch.relu(self.c1(h[:, None, :]))
            return torch.relu(self.c2(z)).flatten(1)
        return self.lstm(h[:, :, None])[0][:, -1]


class Net(nn.Module):
    def __init__(self, arch, n_feat):
        super().__init__()
        self.arch = arch
        hk = {"cnnmlp": "cnn", "agecnn": "cnn", "setcnn": "cnn", "lstmmlp": "lstm"}.get(arch)
        self.hist = Hist(hk) if hk else None
        d = n_feat + (self.hist.out if hk else 0)
        if arch == "deep":
            self.head = nn.Sequential(nn.Linear(d, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(),
                                      nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))
        elif arch in ("cnnmlp", "lstmmlp", "agecnn"):
            self.head = nn.Sequential(nn.Linear(d, 32), nn.ReLU(), nn.Linear(32, 32), nn.ReLU(),
                                      nn.Linear(32, 1))
        else:                                    # setctx, setcnn
            self.enc = nn.Sequential(nn.Linear(d, 32), nn.ReLU())
            self.q = nn.Linear(32, 1, bias=False)
            self.head = nn.Sequential(nn.Linear(96, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x, h, mask):              # x [G, C, F], h [G, C, NH], mask [G, C]
        G, C, _ = x.shape
        z = x.reshape(G * C, -1)
        if self.hist is not None:
            z = torch.cat([z, self.hist(h.reshape(G * C, NH))], 1)
        if self.arch not in ("setctx", "setcnn"):
            return self.head(z).reshape(G, C)
        e = self.enc(z).reshape(G, C, 32)
        s = self.q(e).squeeze(-1).masked_fill(~mask, -1e9)
        a = torch.softmax(s, 1)[:, :, None]
        ctx = (a * e).sum(1, keepdim=True)
        m = mask[:, :, None].float()
        mean = (e * m).sum(1, keepdim=True) / m.sum(1, keepdim=True)
        return self.head(torch.cat([e, ctx.expand_as(e), e - mean], 2)).squeeze(-1)


# ---- data --------------------------------------------------------------------
def sets(d, cols, arch, norm=None):
    """Group rows into [G, MAXC, ...] padded sets."""
    g = d["group"]
    order = np.argsort(g, kind="stable")
    ug, first, cnt = np.unique(g[order], return_index=True, return_counts=True)
    G = len(ug)
    pos = np.arange(len(g)) - np.repeat(first, cnt)
    gi = np.repeat(np.arange(G), cnt)
    keep = pos < MAXC
    X = d["feat"][order][:, cols].astype(np.float32)
    H = d["hist"][order].astype(np.float32)
    if arch == "agecnn":                          # unpack the aging register: 8 scan bits, oldest first
        a = np.rint(d["feat"][order][:, AGING] * 255).astype(np.uint8)
        H = ((a[:, None] >> np.arange(NH - 1, -1, -1)) & 1).astype(np.float32)
    if norm is None:
        w = d["weight"][order]
        mu = (X * w[:, None]).sum(0) / w.sum()
        sd = np.sqrt((((X - mu) ** 2) * w[:, None]).sum(0) / w.sum()) + 1e-6
        hm, hs = (0.0, 1.0) if arch == "agecnn" else (float(H.mean()), float(H.std() + 1e-6))
        norm = dict(mu=mu.astype(np.float32), sd=sd.astype(np.float32), hm=hm, hs=hs)
    Xt = np.zeros((G, MAXC, X.shape[1]), np.float32)
    Ht = np.zeros((G, MAXC, NH), np.float32)
    Y = np.zeros((G, MAXC), np.float32)
    W = np.zeros((G, MAXC), np.float32)
    M_ = np.zeros((G, MAXC), bool)
    Xt[gi[keep], pos[keep]] = (X[keep] - norm["mu"]) / norm["sd"]
    Ht[gi[keep], pos[keep]] = (H[keep] - norm["hm"]) / norm["hs"]
    Y[gi[keep], pos[keep]] = d["label"][order][keep]
    W[gi[keep], pos[keep]] = d["weight"][order][keep]
    M_[gi[keep], pos[keep]] = True
    t = lambda a: torch.from_numpy(a).to(DEV)
    return (t(Xt), t(Ht), t(Y), t(W), t(M_)), norm


def train(scope, arch, fs, epochs=40, seed=1):
    cols = FEATSETS[fs]
    tr, va = Z.load("train", scope, hist=True), Z.load("val", scope, hist=True)
    if va is None or scope == "matmul":
        ug = np.unique(tr["group"]); held = np.random.default_rng(0).choice(ug, max(1, len(ug) // 10), replace=False)
        m = np.isin(tr["group"], held)
        va = {k: v[m] for k, v in tr.items()}; tr = {k: v[~m] for k, v in tr.items()}
    (Xt, Ht, Yt, Wt, Mt), norm = sets(tr, cols, arch)
    (Xv, Hv, Yv, Wv, Mv), _ = sets(va, cols, arch, norm)
    torch.manual_seed(seed)
    net = Net(arch, len(cols)).to(DEV)
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)

    def loss(x, h, y, w, m):
        p = net(x, h, m)
        ww = w * m
        return (ww * (p - y) ** 2).sum() / ww.sum()

    best, bad, state = 1e9, 0, None
    G = len(Xt)
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(G, device=DEV)
        for i in range(0, G, 512):
            b = perm[i:i + 512]
            opt.zero_grad()
            loss(Xt[b], Ht[b], Yt[b], Wt[b], Mt[b]).backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            v = float(loss(Xv, Hv, Yv, Wv, Mv))
        if v < best - 1e-5:
            best, bad, state = v, 0, {k: x.detach().clone() for k, x in net.state_dict().items()}
        else:
            bad += 1
            if bad >= 4:
                break
    net.load_state_dict(state)
    return net, norm, cols, best


# ---- export and numpy forward -----------------------------------------------
def export(net, norm, cols, arch):
    sd = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in net.state_dict().items()}
    return dict(arch=arch, cols=list(cols), norm={k: (np.asarray(v) if k in ("mu", "sd") else float(v)) for k, v in norm.items()}, w=sd)


def _lin(x, W, b=None):
    y = x @ W.T
    return y if b is None else y + b


def _mlp(x, w, prefix):
    keys = sorted({int(k.split(".")[-2]) for k in w if k.startswith(prefix) and k.endswith("weight")})
    for i, k in enumerate(keys):
        x = _lin(x, w[f"{prefix}.{k}.weight"], w[f"{prefix}.{k}.bias"])
        if i + 1 < len(keys):
            x = np.maximum(x, 0)
    return x


def _conv(h, w):                                 # h [n, NH] -> [n, 32]
    def c(x, W, b):                              # x [n, Cin, L], W [Cout, Cin, 3]
        n, ci, L = x.shape
        win = np.stack([x[:, :, i:i + L - 2] for i in range(3)], 3)      # [n, Cin, L-2, 3]
        return np.maximum(np.einsum("ncls,ocs->nol", win, W) + b[None, :, None], 0)
    z = c(h[:, None, :], w["hist.c1.weight"], w["hist.c1.bias"])
    return c(z, w["hist.c2.weight"], w["hist.c2.bias"]).reshape(len(h), -1)


def _lstm(h, w):                                 # h [n, NH] -> [n, 16]
    Wi, Wh = w["hist.lstm.weight_ih_l0"], w["hist.lstm.weight_hh_l0"]
    b = w["hist.lstm.bias_ih_l0"] + w["hist.lstm.bias_hh_l0"]
    sg = lambda x: 1 / (1 + np.exp(-x))
    hh = np.zeros((len(h), 16), np.float32); cc = np.zeros_like(hh)
    for t in range(NH):
        z = h[:, t:t + 1] @ Wi.T + hh @ Wh.T + b
        i, f, g, o = z[:, :16], z[:, 16:32], z[:, 32:48], z[:, 48:]
        cc = sg(f) * cc + sg(i) * np.tanh(g)
        hh = sg(o) * np.tanh(cc)
    return hh


def make_fn(net):
    arch, cols, nm, w = net["arch"], net["cols"], net["norm"], net["w"]
    mu, sd, hm, hs = nm["mu"], nm["sd"], nm["hm"], nm["hs"]

    def fn(feat, hist):
        x = ((feat[:, cols] - mu) / sd).astype(np.float32)
        if arch == "agecnn":
            a = np.rint(feat[:, AGING] * 255).astype(np.uint8)
            h = ((a[:, None] >> np.arange(NH - 1, -1, -1)) & 1).astype(np.float32)
        else:
            h = ((hist - hm) / hs).astype(np.float32)
        z = x
        if arch in ("cnnmlp", "agecnn", "setcnn"):
            z = np.hstack([x, _conv(h, w)])
        elif arch == "lstmmlp":
            z = np.hstack([x, _lstm(h, w)])
        if arch not in ("setctx", "setcnn"):
            return _mlp(z, w, "head")[:, 0]
        e = np.maximum(_lin(z, w["enc.0.weight"], w["enc.0.bias"]), 0)
        n = len(e)
        sub = e if n <= SAMPLE_CTX else e[np.linspace(0, n - 1, SAMPLE_CTX).astype(int)]
        s = (sub @ w["q.weight"].T)[:, 0]
        a = np.exp(s - s.max()); a /= a.sum()
        ctx = a @ sub
        out = np.hstack([e, np.broadcast_to(ctx, e.shape), e - sub.mean(0)])
        return _mlp(out, w, "head")[:, 0]
    return fn


def name_of(scope, arch, fs):
    return f"{scope}.{arch}.{fs}.-"


def fit(scopes):
    for scope in scopes:
        t0 = time.time()
        for fs in FEATSETS:
            for arch, _ in GRID:
                nm = name_of(scope, arch, fs)
                if (Z.ZOO / f"{nm}.pkl").exists():
                    continue
                net, norm, cols, v = train(scope, arch, fs)
                Z.save_spec(nm, dict(kind="np", protect_age=0, net=export(net, norm, cols, arch), val_loss=v))
                print(f"  {nm} val mse {v:.4f}", flush=True)
        print(f"{scope}: done {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("--scopes", nargs="*", default=SCOPES)
    a = ap.parse_args()
    fit(a.scopes)
