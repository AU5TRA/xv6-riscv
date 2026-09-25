#!/usr/bin/env python3
"""The "expensive" cross-page experiment suggested in ML_TESTING_REPORT.md's
next steps: every model so far only ever saw a single page's own
history (recency/frequency/interval) or a static per-page identity in
isolation -- never any information about OTHER pages, so nothing tried
could learn anything like "these pages tend to be touched together,"
which is closer to what graph topology (graphbench) or a matrix's
memory-access order (matmulbench) actually is.

This model: a learned embedding per page (not just a normalized VPN
number, as vpn_identity was -- an embedding the model shapes freely
during training), combined with a summary of the last W=16 GLOBALLY
touched pages (not the candidate's own history -- the actual recent
context of the whole process), to predict the candidate's own next
-reuse-distance. The global-context part is shared across every
candidate compared at a given eviction (same caveat as the "position"
feature in Experiment 2 -- see ML_TESTING_REPORT.md), but each
candidate's own embedding still differs, so the model can express
"given what's been happening recently, how does THIS specific page's
behavior look" -- a real step toward cross-page structure, short of
full attention over all pairs (which would be the further, even more
expensive step if this one shows promise).

Run across all seven workloads, same train/held-out split and
subsampling budget as ml_comprehensive.py, for direct comparability.
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
import ml_feature_experiments as feat  # build_labels()

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "traces"
MODELS_DIR = ROOT / "models"

WORKLOADS = [
    ("btreebench", "btreebench", "btree-p15-c266", "btree-p20-c355", "btreebench"),
    ("kvbench", "kvbench", "kv-p15-c79", "kv-p20-c106", "kvbench"),
    ("sortbench", "sortbench", "sort-p15-c12", "sort-p20-c16", "sortbench"),
    ("graphbench", "graphbench", "graph-p15-c200", "graph-p20-c267", "graphbench"),
    ("lzwbench", "lzwbench", "lzw-p15-c8", "lzw-p20-c10", "lzwbench"),
    ("matmulbench-naive", "matmulbench", "matmulN-c4", "matmulN-c8", "matmulbench-naive"),
    ("matmulbench-blocked", "matmulbench", "matmulB-c4", "matmulB-c8", "matmulbench-blocked"),
]

# rows from the already-completed pre-bugfix run (vpn_pad off-by-one only
# affected lzwbench, whose vpns start at 22 -- these four are unaffected
# and not worth re-training)
_PRECOMPUTED = [
    ("btreebench", 270, 359, 74148, 61625),
    ("kvbench", 82, 109, 39358, 36801),
    ("sortbench", 16, 20, 492119, 379422),
    ("graphbench", 204, 271, 143017, 134510),
]

W = 16              # global-context window length
EMBED_DIM = 16
TRAIN_SUBSAMPLE = 300_000


def build_context_dataset(refs, vpn_pad):
    """For each reference i to page v: the W page-ids immediately
    preceding i (zero-padded at the start of the run), plus v itself.
    """
    n = len(refs)
    ctx = np.full((n, W), vpn_pad, dtype=np.int64)
    target = np.zeros(n, dtype=np.int64)
    window = [vpn_pad] * W
    for i, vpn in enumerate(refs):
        ctx[i] = window
        target[i] = vpn
        window = window[1:] + [vpn]
    return ctx, target


class GlobalContextModel(nn.Module):
    def __init__(self, vocab_size, embed_dim=EMBED_DIM, hidden=16):
        super().__init__()
        self.embed = nn.Embedding(vocab_size + 1, embed_dim)
        self.gru = nn.GRU(embed_dim, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden + embed_dim, hidden),
                                   nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, ctx, target):
        ctx_emb = self.embed(ctx)               # (batch, W, embed_dim)
        _, h = self.gru(ctx_emb)                 # h: (1, batch, hidden)
        tgt_emb = self.embed(target)             # (batch, embed_dim)
        combined = torch.cat([h[-1], tgt_emb], dim=-1)
        return self.head(combined).squeeze(-1)


def train(model, ctx, target, y, epochs=6, batch=4096, lr=1e-3):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossfn = nn.MSELoss()
    ctx_t = torch.from_numpy(ctx)
    tgt_t = torch.from_numpy(target)
    y_t = torch.from_numpy(y)
    n = len(ctx)
    for _ in range(epochs):
        perm = torch.randperm(n)
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            opt.zero_grad()
            loss = lossfn(model(ctx_t[idx], tgt_t[idx]), y_t[idx])
            loss.backward()
            opt.step()
    model.eval()
    return model


@torch.no_grad()
def simulate_policy(model, refs, capacity, vpn_pad):
    resident = set()
    faults = 0
    evictions = 0
    window = [vpn_pad] * W
    for vpn in refs:
        if vpn in resident:
            window = window[1:] + [vpn]
            continue
        faults += 1
        if len(resident) >= capacity:
            cands = list(resident)
            ctx_batch = torch.tensor([window] * len(cands), dtype=torch.long)
            tgt_batch = torch.tensor(cands, dtype=torch.long)
            preds = model(ctx_batch, tgt_batch).numpy()
            victim = cands[int(np.argmax(preds))]
            resident.discard(victim)
            evictions += 1
        resident.add(vpn)
        window = window[1:] + [vpn]
    return faults, evictions


def main():
    t0 = time.time()
    results = list(_PRECOMPUTED)
    done = {r[0] for r in _PRECOMPUTED}
    for label, folder, train_stem, eval_stem, trace_stem in WORKLOADS:
        if label in done:
            continue
        t1 = time.time()
        d = TRACES / folder
        train_log = d / f"{train_stem}.log"
        eval_log = d / f"{eval_stem}.log"
        trace_file = d / f"{trace_stem}.trace"
        train_header, train_refs = decode_split(train_log, trace_file)
        eval_header, eval_refs = decode_split(eval_log, trace_file)
        cap = int(train_header[CAPACITY_FIELD])
        ev_cap = int(eval_header[CAPACITY_FIELD])
        # vpns are absolute (arena_start_vpn + offset), not 0-indexed, and
        # can exceed the header's arena_pages count -- size the embedding
        # table off the real observed max instead.
        max_vpn = max(max(train_refs), max(eval_refs))
        vpn_pad = max_vpn + 1  # reserved "no page" index, out of real range

        print(f"\n{label}: train_refs={len(train_refs):,} capacity={cap} "
              f"max_vpn={max_vpn}", flush=True)

        ctx, target = build_context_dataset(train_refs, vpn_pad)
        y = feat.build_labels(train_refs)
        rng = np.random.default_rng(0)
        sub = rng.choice(len(train_refs), size=min(TRAIN_SUBSAMPLE, len(train_refs)),
                          replace=False)

        torch.manual_seed(0)
        model = GlobalContextModel(vpn_pad)
        model = train(model, ctx[sub], target[sub], y[sub])

        tr_f, _ = simulate_policy(model, train_refs, cap, vpn_pad)
        ev_f, _ = simulate_policy(model, eval_refs, ev_cap, vpn_pad)
        print(f"  global_context_embed: train={tr_f:>8d} held_out={ev_f:>8d} "
              f"({time.time()-t1:.0f}s)", flush=True)
        results.append((label, cap, ev_cap, tr_f, ev_f))

        MODELS_DIR.mkdir(exist_ok=True)
        torch.save(model.state_dict(),
                    MODELS_DIR / f"{label}_embed_global_context.pt")
        (MODELS_DIR / f"{label}_embed_global_context.json").write_text(
            f'{{"workload": "{label}", "experiment": "embedding", '
            f'"model": "global_context_embed", "window": {W}, '
            f'"embed_dim": {EMBED_DIM}, "train_log": "{train_stem}", '
            f'"eval_log": "{eval_stem}", "capacity": {cap}, '
            f'"eval_capacity": {ev_cap}, "train_faults": {tr_f}, '
            f'"held_out_faults": {ev_f}}}')

    out = TRACES / "embedding_results.csv"
    with out.open("w") as f:
        f.write("workload,capacity,eval_capacity,train_faults,held_out_faults\n")
        for r in results:
            f.write(",".join(str(x) for x in r) + "\n")
    print(f"\nALL DONE in {time.time()-t0:.0f}s. Results: {out}", flush=True)


if __name__ == "__main__":
    main()
