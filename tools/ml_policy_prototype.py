#!/usr/bin/env python3
"""First ML page-replacement policy prototype (step 5 of the ML-model
work this whole project has been groundwork for).

Deliberately the simplest model that could plausibly work: linear
regression predicting each resident page's next-reuse-distance from
three cheap running features (recency, access frequency, previous
inter-access interval), trained on Belady's own ground truth (the true
next-reuse-distance every reference has -- see sim.py's
belady_faults_evictions()). At eviction time, evict whichever resident
page has the LARGEST predicted distance -- i.e., approximate Belady
using a learned predictor instead of oracle lookahead.

Chosen deliberately over LSTM/GRU (the other candidates from the
project's own early notes) for this first pass: a linear model is
trivially portable to fixed-point kernel arithmetic (a handful of
multiply-adds), which any in-kernel inference eventually needs given
xv6 has no floating point anywhere. Whether a heavier model is worth
the added complexity is a question for once this simple baseline's
ceiling is known.

Usage:
    python3 tools/ml_policy_prototype.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trace_decode import decode_split
from sim import run_policy, CAPACITY_FIELD

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "traces"

# graphbench: the workload step 3's sweep found the real gap in --
# FIFO/Clock/Aging/LRU all land within 0.1% of each other (none of them
# capture its pointer-chasing structure at all), with Belady needing
# ~40% fewer faults. If a learned policy can't beat the classical pack
# here, it isn't going to beat them anywhere easier.
FOLDER = TRACES / "graphbench"
TRAIN_LOG = FOLDER / "graph-p15-c200.log"
EVAL_LOG = FOLDER / "graph-p20-c267.log"   # held-out capacity, same trace
TRACE_FILE = FOLDER / "graphbench.trace"

NEVER_AGAIN_CAP = 1 << 20  # finite stand-in for "no future use"


def features_and_labels(refs):
    """One training example per reference: (recency, frequency,
    prev_interval) -> true forward distance to next reuse of this page.
    """
    n = len(refs)
    last_pos = {}
    freq = {}
    prev_interval = {}
    X, y = [], []
    for i, vpn in enumerate(refs):
        recency = i - last_pos.get(vpn, i)  # 0 on first touch
        f = freq.get(vpn, 0)
        pi = prev_interval.get(vpn, 0)
        X.append((recency, f, pi))
        # true label filled in on the NEXT occurrence, via a second pass
        if vpn in last_pos:
            prev_interval[vpn] = i - last_pos[vpn]
        last_pos[vpn] = i
        freq[vpn] = f + 1
        y.append(None)  # placeholder, filled below
    # second pass: true forward distance to next reuse
    next_pos = {}
    for i in range(n - 1, -1, -1):
        vpn = refs[i]
        y[i] = next_pos.get(vpn, NEVER_AGAIN_CAP) - i if vpn in next_pos \
            else NEVER_AGAIN_CAP
        next_pos[vpn] = i
    return np.array(X, dtype=np.float64), np.array(y, dtype=np.float64)


def train_linear(X, y):
    """Closed-form least squares, capping the label so a handful of
    'never again' outliers (distance ~10^6) don't dominate the fit --
    what matters for eviction ranking is getting the ORDER of near-term
    reuse right, not the exact magnitude of a page nobody revisits."""
    y_capped = np.minimum(y, 50_000)
    Xb = np.hstack([X, np.ones((len(X), 1))])
    w, *_ = np.linalg.lstsq(Xb, y_capped, rcond=None)
    return w  # [w_recency, w_freq, w_prev_interval, bias]


class MLPolicy:
    name = "ml"

    def __init__(self, capacity, weights):
        self.capacity = capacity
        # Plain Python floats, not a numpy array: this prediction runs
        # once per resident candidate on every eviction (tens of
        # millions of calls at this trace's scale), and numpy's
        # per-call array-construction overhead dominates at vector size
        # 4 -- plain scalar arithmetic is far faster here.
        self.w_recency, self.w_freq, self.w_pi, self.w_bias = \
            (float(v) for v in weights)
        self.resident = {}       # vpn -> last_access_time
        self.freq = {}           # vpn -> access count
        self.prev_interval = {}  # vpn -> gap before the last access
        self.t = 0
        self.faults = 0
        self.evictions = 0

    def _predict(self, vpn):
        recency = self.t - self.resident[vpn]
        f = self.freq.get(vpn, 0)
        pi = self.prev_interval.get(vpn, 0)
        return (self.w_recency * recency + self.w_freq * f +
                self.w_pi * pi + self.w_bias)

    def access(self, vpn):
        if vpn in self.resident:
            if vpn in self.freq:
                self.prev_interval[vpn] = self.t - self.resident[vpn]
            self.resident[vpn] = self.t
            self.freq[vpn] = self.freq.get(vpn, 0) + 1
            self.t += 1
            return
        self.faults += 1
        if len(self.resident) >= self.capacity:
            victim = max(self.resident, key=self._predict)
            del self.resident[victim]
            self.evictions += 1
        self.resident[vpn] = self.t
        self.freq[vpn] = self.freq.get(vpn, 0) + 1
        self.t += 1


def run_ml_policy(refs, capacity, weights):
    sim = MLPolicy(capacity, weights)
    for vpn in refs:
        sim.access(vpn)
    return {"faults": sim.faults, "evictions": sim.evictions}


def main():
    print(f"training on {TRAIN_LOG.name} ...")
    train_header, train_refs = decode_split(TRAIN_LOG, TRACE_FILE)
    X, y = features_and_labels(train_refs)
    weights = train_linear(X, y)
    print(f"learned weights (recency, freq, prev_interval, bias): "
          f"{weights.round(3).tolist()}")

    for label, log in (("train (in-sample)", TRAIN_LOG),
                        ("held-out capacity", EVAL_LOG)):
        header, refs = decode_split(log, TRACE_FILE)
        capacity = int(header[CAPACITY_FIELD])
        ml = run_ml_policy(refs, capacity, weights)
        classical = {name: run_policy(name, refs, capacity)
                     for name in ("fifo", "clock", "aging", "lru", "belady")}
        print(f"\n{label}: {log.name} (capacity={capacity})")
        for name, r in list(classical.items())[:4]:
            print(f"  {name:>6s}: faults={r['faults']:>7d}")
        print(f"  {'ml':>6s}: faults={ml['faults']:>7d}   <-- this prototype")
        print(f"  {'belady':>6s}: faults={classical['belady']['faults']:>7d}"
              f"   (oracle)")
        best_classical = min(classical[n]["faults"]
                              for n in ("fifo", "clock", "aging", "lru"))
        verdict = ("beats" if ml["faults"] < best_classical else
                    "ties" if ml["faults"] == best_classical else "loses to")
        print(f"  -> {verdict} the best classical policy "
              f"({best_classical} faults)")


if __name__ == "__main__":
    main()
