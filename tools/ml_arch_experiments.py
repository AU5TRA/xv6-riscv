#!/usr/bin/env python3
"""Diagnose why the linear next-reuse-distance predictor lost to the
classical policies (tools/ml_policy_prototype.py), then try several
different model architectures on the same problem.

Input representation, shared across every model below (for a fair
comparison): each page's last K=8 inter-access intervals (the gaps
between consecutive touches of that SAME page), zero-padded if the page
has been seen fewer than 8 times. This generalizes the original
prototype's single "prev_interval" scalar into a short history a
sequence model can actually use -- if the failure was "one interval
isn't enough signal," a sequence model over 8 of them should help; if
it isn't, the problem is more likely the label/feature relationship
itself, not model capacity.

Label: same ground truth as before (Belady's own next-reuse-distance),
log1p-transformed for training stability. Monotonic transform, so it
never changes which resident page a trained model would pick to evict
-- argmax(log1p(x)) == argmax(x).

Runs on the venv with torch installed:
    /tmp/.../scratchpad/mlvenv/bin/python3 tools/ml_arch_experiments.py
"""
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_decode import decode_split
from sim import run_policy, CAPACITY_FIELD

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "traces" / "graphbench"
TRAIN_LOG = FOLDER / "graph-p15-c200.log"
EVAL_LOG = FOLDER / "graph-p20-c267.log"
TRACE_FILE = FOLDER / "graphbench.trace"

K = 8                  # interval-history window length
NEVER_AGAIN_CAP = 1 << 20
TRAIN_SUBSAMPLE = 300_000
EPOCHS = 6
DEVICE = "cpu"


def build_dataset(refs):
    """For every reference: an 8-long interval history (oldest first,
    zero-padded) for that page, and the true (capped, log1p) forward
    distance to its next reuse."""
    n = len(refs)
    hist = {}       # vpn -> list of up to K most recent intervals
    last_pos = {}
    X = np.zeros((n, K), dtype=np.float32)
    for i, vpn in enumerate(refs):
        h = hist.get(vpn, [])
        if h:
            X[i, K - len(h):] = h
        if vpn in last_pos:
            gap = i - last_pos[vpn]
            h = (h + [gap])[-K:]
            hist[vpn] = h
        last_pos[vpn] = i

    next_pos = {}
    y = np.zeros(n, dtype=np.float32)
    for i in range(n - 1, -1, -1):
        vpn = refs[i]
        dist = next_pos.get(vpn, NEVER_AGAIN_CAP) - i if vpn in next_pos \
            else NEVER_AGAIN_CAP
        y[i] = min(dist, 50_000)
        next_pos[vpn] = i
    return X, np.log1p(y).astype(np.float32)


# ---- Models: all take (batch, K) -> (batch,) ------------------------

class Linear8(nn.Module):
    """Linear model, but on the full 8-window (vs. the original
    prototype's 3 hand-picked scalars) -- isolates whether more RAW
    history helps even without any nonlinearity."""
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(K, 1)

    def forward(self, x):
        return self.fc(x).squeeze(-1)


class MLP(nn.Module):
    def __init__(self, hidden=32):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(K, hidden), nn.ReLU(),
                                  nn.Linear(hidden, hidden), nn.ReLU(),
                                  nn.Linear(hidden, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1)


class RecurrentModel(nn.Module):
    def __init__(self, cell="rnn", hidden=16):
        super().__init__()
        cls = {"rnn": nn.RNN, "lstm": nn.LSTM, "gru": nn.GRU}[cell]
        self.rnn = cls(input_size=1, hidden_size=hidden, batch_first=True)
        self.out = nn.Linear(hidden, 1)

    def forward(self, x):
        x = x.unsqueeze(-1)  # (batch, K, 1)
        _, h = self.rnn(x)
        hn = h[0] if isinstance(h, tuple) else h  # LSTM returns (h_n, c_n)
        return self.out(hn[-1]).squeeze(-1)


class CNN1D(nn.Module):
    def __init__(self, channels=16):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(1, channels, kernel_size=3, padding=1), nn.ReLU(),
            nn.Conv1d(channels, channels, kernel_size=3, padding=1), nn.ReLU(),
        )
        self.out = nn.Linear(channels * K, 1)

    def forward(self, x):
        x = x.unsqueeze(1)  # (batch, 1, K)
        x = self.conv(x).flatten(1)
        return self.out(x).squeeze(-1)


class TinyAttention(nn.Module):
    """A single self-attention block over the K interval positions,
    each treated as a length-1 'token' embedded up to d_model, plus a
    learned positional embedding (recency order matters)."""
    def __init__(self, d_model=16, heads=2):
        super().__init__()
        self.embed = nn.Linear(1, d_model)
        self.pos = nn.Parameter(torch.zeros(K, d_model))
        self.attn = nn.MultiheadAttention(d_model, heads, batch_first=True)
        self.out = nn.Linear(d_model * K, 1)

    def forward(self, x):
        x = self.embed(x.unsqueeze(-1)) + self.pos
        a, _ = self.attn(x, x, x)
        return self.out(a.flatten(1)).squeeze(-1)


MODELS = {
    "linear8": lambda: Linear8(),
    "mlp": lambda: MLP(),
    "rnn": lambda: RecurrentModel("rnn"),
    "lstm": lambda: RecurrentModel("lstm"),
    "gru": lambda: RecurrentModel("gru"),
    "cnn": lambda: CNN1D(),
    "attention": lambda: TinyAttention(),
}


def train(model, X, y, epochs=EPOCHS, batch=4096, lr=1e-3):
    model.to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossfn = nn.MSELoss()
    n = len(X)
    Xt = torch.from_numpy(X)
    yt = torch.from_numpy(y)
    for ep in range(epochs):
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            opt.zero_grad()
            pred = model(Xt[idx])
            loss = lossfn(pred, yt[idx])
            loss.backward()
            opt.step()
            total += loss.item() * len(idx)
    model.eval()
    return model


@torch.no_grad()
def simulate_policy(model, refs, capacity):
    """Same eviction loop shape as sim.py's policy classes, but predicts
    ALL resident candidates in ONE batched forward pass per eviction
    (not one-by-one) -- the only way this is fast enough at this scale.
    """
    resident_hist = {}   # vpn -> list of up to K intervals
    resident_last = {}   # vpn -> last access position
    t = 0
    faults = 0
    evictions = 0
    for vpn in refs:
        if vpn in resident_last:
            gap = t - resident_last[vpn]
            h = resident_hist.get(vpn, [])
            resident_hist[vpn] = (h + [gap])[-K:]
            resident_last[vpn] = t
            t += 1
            continue
        faults += 1
        if len(resident_last) >= capacity:
            vpns = list(resident_last.keys())
            feats = np.zeros((len(vpns), K), dtype=np.float32)
            for i, v in enumerate(vpns):
                h = resident_hist.get(v, [])
                if h:
                    feats[i, K - len(h):] = h
                # recency also matters and isn't in the interval
                # history alone -- fold it into the last slot's scale
                # by appending current gap-so-far implicitly via
                # training distribution; kept simple here on purpose.
            preds = model(torch.from_numpy(feats)).numpy()
            victim = vpns[int(np.argmax(preds))]
            del resident_last[victim]
            resident_hist.pop(victim, None)
            evictions += 1
        resident_last[vpn] = t
        resident_hist[vpn] = []
        t += 1
    return faults, evictions


def main():
    t0 = time.time()
    print("loading traces...", flush=True)
    _, train_refs = decode_split(TRAIN_LOG, TRACE_FILE)
    eval_header, eval_refs = decode_split(EVAL_LOG, TRACE_FILE)

    print("building dataset...", flush=True)
    X, y = build_dataset(train_refs)

    # ---- Diagnosis: does the 8-interval history even correlate with
    # the label better than the original 3 scalars did? ----
    finite = y < np.log1p(49_999)
    corrs = [np.corrcoef(X[finite, k], y[finite])[0, 1] for k in range(K)]
    print(f"\n[diagnosis] correlation(interval_k_steps_back, log next-dist) "
          f"for k=1..{K}:")
    print("  " + ", ".join(f"{c:+.3f}" for c in corrs))
    print(f"  never-again-capped fraction of labels: "
          f"{1 - finite.mean():.1%}")
    print(f"  training examples available: {len(X):,}")

    rng = np.random.default_rng(0)
    sub = rng.choice(len(X), size=min(TRAIN_SUBSAMPLE, len(X)),
                      replace=False)
    Xs, ys = X[sub], y[sub]

    results = {}
    for name, ctor in MODELS.items():
        t1 = time.time()
        torch.manual_seed(0)
        model = train(ctor(), Xs, ys)
        header, refs = decode_split(TRAIN_LOG, TRACE_FILE)
        cap = int(header[CAPACITY_FIELD])
        tr_faults, tr_ev = simulate_policy(model, train_refs, cap)
        ev_cap = int(eval_header[CAPACITY_FIELD])
        ev_faults, ev_ev = simulate_policy(model, eval_refs, ev_cap)
        results[name] = (tr_faults, ev_faults)
        print(f"[{name:>9s}] train_faults={tr_faults:>7d} "
              f"held_out_faults={ev_faults:>7d}  ({time.time()-t1:.0f}s)",
              flush=True)

    header, refs = decode_split(TRAIN_LOG, TRACE_FILE)
    cap = int(header[CAPACITY_FIELD])
    classical = {n: run_policy(n, train_refs, cap)["faults"]
                 for n in ("fifo", "clock", "aging", "lru", "belady")}
    ev_cap = int(eval_header[CAPACITY_FIELD])
    classical_ev = {n: run_policy(n, eval_refs, ev_cap)["faults"]
                    for n in ("fifo", "clock", "aging", "lru", "belady")}

    print("\n=== summary (train / held-out faults) ===")
    for n, f in classical.items():
        print(f"  {n:>9s}: {f:>7d} / {classical_ev[n]:>7d}")
    for n, (tr, ev) in results.items():
        print(f"  {n:>9s}: {tr:>7d} / {ev:>7d}")
    print(f"\ntotal wall time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
