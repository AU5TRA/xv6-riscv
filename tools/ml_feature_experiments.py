#!/usr/bin/env python3
"""Follow-up to ml_arch_experiments.py: that experiment showed every
architecture (linear/MLP/RNN/LSTM/GRU/CNN/attention) converges to
almost the SAME mediocre performance when given a page's own recent
inter-access-interval history -- strong evidence the bottleneck is the
FEATURE SET, not model capacity. This tries several different feature
sets instead, each first checked by raw correlation with the true
label (cheap, no training needed) before spending compute training
anything on it.

Feature sets tried, each computed per-reference for the SAME page:
  A. interval_history (K=8)        -- the original (from ml_arch_experiments.py)
  B. stack_distance                -- distinct pages touched since this
                                       page's last touch (the theoretically
                                       correct LRU-style distance, vs. raw
                                       reference-count recency)
  C. global_frequency               -- total touches to this page so far
  D. vpn_identity                   -- the page number itself, normalized
                                       (tests whether some pages are just
                                       intrinsically hot/cold regardless
                                       of recent history -- e.g. hub
                                       vertices in graphbench's graph)
  E. position_in_stream             -- i / n (which phase of the run:
                                       BFS vs PageRank have different
                                       access patterns)
  F. ALL OF THE ABOVE combined
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

NEVER_AGAIN_CAP = 1 << 20
TRAIN_SUBSAMPLE = 300_000


def build_labels(refs):
    n = len(refs)
    next_pos = {}
    y = np.zeros(n, dtype=np.float32)
    for i in range(n - 1, -1, -1):
        vpn = refs[i]
        dist = next_pos.get(vpn, NEVER_AGAIN_CAP) - i if vpn in next_pos \
            else NEVER_AGAIN_CAP
        y[i] = min(dist, 50_000)
        next_pos[vpn] = i
    return np.log1p(y).astype(np.float32)


def build_features(refs, arena_pages):
    """Returns a dict feature_name -> (n,) array, computed causally
    (only using information available AT reference i, never the
    future) so this is honest about what a real online policy could
    know."""
    n = len(refs)
    last_pos = {}     # vpn -> last position touched
    freq = {}          # vpn -> count so far
    distinct_seen = 0
    last_distinct_at = {}  # vpn -> "distinct-page clock" at last touch

    recency = np.zeros(n, dtype=np.float32)       # i - last_pos (0 if new)
    stack_distance = np.zeros(n, dtype=np.float32)  # distinct pages since
    global_frequency = np.zeros(n, dtype=np.float32)
    vpn_identity = np.zeros(n, dtype=np.float32)
    position = np.zeros(n, dtype=np.float32)

    for i, vpn in enumerate(refs):
        if vpn not in last_pos:
            distinct_seen += 1
        recency[i] = i - last_pos.get(vpn, i)
        stack_distance[i] = distinct_seen - last_distinct_at.get(vpn, distinct_seen)
        global_frequency[i] = freq.get(vpn, 0)
        vpn_identity[i] = vpn / max(arena_pages, 1)
        position[i] = i / n

        last_pos[vpn] = i
        freq[vpn] = freq.get(vpn, 0) + 1
        last_distinct_at[vpn] = distinct_seen

    return {
        "recency": recency,
        "stack_distance": stack_distance,
        "global_frequency": global_frequency,
        "vpn_identity": vpn_identity,
        "position": position,
    }


FEATURE_SETS = {
    "recency_only": ["recency"],
    "stack_distance": ["stack_distance"],
    "global_frequency": ["global_frequency"],
    "vpn_identity": ["vpn_identity"],
    "position": ["position"],
    "all_combined": ["recency", "stack_distance", "global_frequency",
                      "vpn_identity", "position"],
}


class Linear(nn.Module):
    def __init__(self, n_in):
        super().__init__()
        self.fc = nn.Linear(n_in, 1)

    def forward(self, x):
        return self.fc(x).squeeze(-1)


class MLP(nn.Module):
    def __init__(self, n_in, hidden=32):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_in, hidden), nn.ReLU(),
                                  nn.Linear(hidden, hidden), nn.ReLU(),
                                  nn.Linear(hidden, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1)


def train(model, X, y, epochs=6, batch=4096, lr=1e-3):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossfn = nn.MSELoss()
    Xt, yt = torch.from_numpy(X), torch.from_numpy(y)
    n = len(X)
    for _ in range(epochs):
        perm = torch.randperm(n)
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            opt.zero_grad()
            loss = lossfn(model(Xt[idx]), yt[idx])
            loss.backward()
            opt.step()
    model.eval()
    return model


@torch.no_grad()
def simulate_policy(model, refs, capacity, feat_names, arena_pages):
    """Same batched-eviction shape as ml_arch_experiments.py, but
    computes the chosen feature set online (causally) per candidate."""
    last_pos = {}
    freq = {}
    distinct_seen = 0
    last_distinct_at = {}
    resident = set()
    faults = 0
    evictions = 0

    def feat(vpn, i):
        vals = []
        for name in feat_names:
            if name == "recency":
                vals.append(i - last_pos.get(vpn, i))
            elif name == "stack_distance":
                vals.append(distinct_seen - last_distinct_at.get(vpn, distinct_seen))
            elif name == "global_frequency":
                vals.append(freq.get(vpn, 0))
            elif name == "vpn_identity":
                vals.append(vpn / max(arena_pages, 1))
            elif name == "position":
                vals.append(i / len(refs))
        return vals

    for i, vpn in enumerate(refs):
        if vpn not in last_pos:
            distinct_seen += 1
        if vpn in resident:
            last_pos[vpn] = i
            freq[vpn] = freq.get(vpn, 0) + 1
            last_distinct_at[vpn] = distinct_seen
            continue
        faults += 1
        if len(resident) >= capacity:
            cands = list(resident)
            feats = np.array([feat(v, i) for v in cands], dtype=np.float32)
            preds = model(torch.from_numpy(feats)).numpy()
            victim = cands[int(np.argmax(preds))]
            resident.discard(victim)
            evictions += 1
        resident.add(vpn)
        last_pos[vpn] = i
        freq[vpn] = freq.get(vpn, 0) + 1
        last_distinct_at[vpn] = distinct_seen
    return faults, evictions


def main():
    t0 = time.time()
    print("loading traces...", flush=True)
    train_header, train_refs = decode_split(TRAIN_LOG, TRACE_FILE)
    eval_header, eval_refs = decode_split(EVAL_LOG, TRACE_FILE)
    arena_pages = int(train_header["arena_pages"])

    print("building features + labels...", flush=True)
    feats = build_features(train_refs, arena_pages)
    y = build_labels(train_refs)

    print(f"\n[diagnosis] correlation(feature, log next-dist), "
          f"{len(train_refs):,} examples:")
    for name, vals in feats.items():
        c = np.corrcoef(vals, y)[0, 1]
        print(f"  {name:<18s} {c:+.4f}")

    rng = np.random.default_rng(0)
    sub = rng.choice(len(train_refs), size=min(TRAIN_SUBSAMPLE, len(train_refs)),
                      replace=False)

    cap = int(train_header[CAPACITY_FIELD])
    ev_cap = int(eval_header[CAPACITY_FIELD])
    classical = {n: run_policy(n, train_refs, cap)["faults"]
                 for n in ("fifo", "clock", "aging", "lru", "belady")}
    classical_ev = {n: run_policy(n, eval_refs, ev_cap)["faults"]
                    for n in ("fifo", "clock", "aging", "lru", "belady")}

    print("\n[feature-set experiments] (linear + MLP, train/held-out faults)")
    results = {}
    for fs_name, names in FEATURE_SETS.items():
        X = np.stack([feats[n] for n in names], axis=1).astype(np.float32)
        Xs, ys = X[sub], y[sub]
        for model_name, ctor in (("linear", lambda ni: Linear(ni)),
                                  ("mlp", lambda ni: MLP(ni))):
            t1 = time.time()
            torch.manual_seed(0)
            model = train(ctor(X.shape[1]), Xs, ys)
            tr_f, _ = simulate_policy(model, train_refs, cap, names, arena_pages)
            ev_f, _ = simulate_policy(model, eval_refs, ev_cap, names, arena_pages)
            key = f"{fs_name}/{model_name}"
            results[key] = (tr_f, ev_f)
            print(f"  {key:<28s} train={tr_f:>7d} held_out={ev_f:>7d} "
                  f"({time.time()-t1:.0f}s)", flush=True)

    print("\n=== final summary (train / held-out faults) ===")
    for n, f in classical.items():
        print(f"  {n:>28s}: {f:>7d} / {classical_ev[n]:>7d}")
    for k, (tr, ev) in results.items():
        print(f"  {k:>28s}: {tr:>7d} / {ev:>7d}")
    print(f"\ntotal wall time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
