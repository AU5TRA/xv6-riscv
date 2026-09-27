#!/usr/bin/env python3
"""Comprehensive sweep: every model tried so far (7 architectures on
interval-history features, plus linear/MLP on 6 feature sets) run on
EVERY workload in the traces/ sweep archive, not just graphbench.

Saves every trained model's weights + a metadata sidecar under
models/, and writes one combined results table to
traces/ml_comprehensive_results.csv, so both the numbers and the exact
trained models behind them are reproducible without retraining.

Usage (needs the venv with torch installed):
    /tmp/.../scratchpad/mlvenv/bin/python3 tools/ml_comprehensive.py
"""
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ml_arch_experiments as arch
import ml_feature_experiments as feat
from trace_decode import decode_split
from sim import run_policy, CAPACITY_FIELD

ROOT = Path(__file__).resolve().parents[1]
TRACES = ROOT / "traces"
REPORT = ROOT / "report"
MODELS_DIR = REPORT / "models"
RESULTS_CSV = REPORT / "ml_comprehensive_results.csv"

# (workload label, folder name, train log stem, eval log stem, trace-file stem)
WORKLOADS = [
    ("btreebench", "btreebench", "btree-p15-c266", "btree-p20-c355", "btreebench"),
    ("kvbench", "kvbench", "kv-p15-c79", "kv-p20-c106", "kvbench"),
    ("sortbench", "sortbench", "sort-p15-c12", "sort-p20-c16", "sortbench"),
    ("graphbench", "graphbench", "graph-p15-c200", "graph-p20-c267", "graphbench"),
    ("lzwbench", "lzwbench", "lzw-p15-c8", "lzw-p20-c10", "lzwbench"),
    ("matmulbench-naive", "matmulbench", "matmulN-c4", "matmulN-c8", "matmulbench-naive"),
    ("matmulbench-blocked", "matmulbench", "matmulB-c4", "matmulB-c8", "matmulbench-blocked"),
]


def save_model(model, name: str, meta: dict):
    MODELS_DIR.mkdir(exist_ok=True)
    torch.save(model.state_dict(), MODELS_DIR / f"{name}.pt")
    (MODELS_DIR / f"{name}.json").write_text(json.dumps(meta, indent=2))


def run_workload(label, folder, train_stem, eval_stem, trace_stem, writer, csvfile):
    t0 = time.time()
    d = TRACES / folder
    train_log = d / f"{train_stem}.log"
    eval_log = d / f"{eval_stem}.log"
    trace_file = d / f"{trace_stem}.trace"
    print(f"\n{'='*70}\n{label}\n{'='*70}", flush=True)

    train_header, train_refs = decode_split(train_log, trace_file)
    eval_header, eval_refs = decode_split(eval_log, trace_file)
    cap = int(train_header[CAPACITY_FIELD])
    ev_cap = int(eval_header[CAPACITY_FIELD])
    arena_pages = int(train_header["arena_pages"])
    print(f"train_refs={len(train_refs):,} capacity={cap}  "
          f"eval_refs={len(eval_refs):,} capacity={ev_cap}", flush=True)

    def emit(experiment, name, tr_f, ev_f, extra=""):
        writer.writerow([label, experiment, name, cap, ev_cap,
                          len(train_refs), tr_f, ev_f])
        csvfile.flush()
        print(f"  [{experiment:>9s}] {name:<20s} train={tr_f:>8d} "
              f"held_out={ev_f:>8d} {extra}", flush=True)

    # classical policies, once per workload
    for name in ("fifo", "clock", "aging", "lru", "lfu", "stackdist", "belady"):
        tr = run_policy(name, train_refs, cap)["faults"]
        ev = run_policy(name, eval_refs, ev_cap)["faults"]
        emit("classical", name, tr, ev)

    # --- architecture experiment (interval-history features) ---
    X, y = arch.build_dataset(train_refs)
    rng = np.random.default_rng(0)
    sub = rng.choice(len(X), size=min(arch.TRAIN_SUBSAMPLE, len(X)), replace=False)
    Xs, ys = X[sub], y[sub]
    for name, ctor in arch.MODELS.items():
        t1 = time.time()
        torch.manual_seed(0)
        model = arch.train(ctor(), Xs, ys)
        tr_f, _ = arch.simulate_policy(model, train_refs, cap)
        ev_f, _ = arch.simulate_policy(model, eval_refs, ev_cap)
        emit("arch", name, tr_f, ev_f, f"({time.time()-t1:.0f}s)")
        save_model(model, f"{label}_arch_{name}",
                   {"workload": label, "experiment": "arch", "model": name,
                    "input": "interval_history_k8", "train_log": train_stem,
                    "eval_log": eval_stem, "capacity": cap,
                    "eval_capacity": ev_cap, "train_faults": tr_f,
                    "held_out_faults": ev_f})

    # --- feature-set experiment ---
    feats = feat.build_features(train_refs, arena_pages)
    ylab = feat.build_labels(train_refs)
    corr = {n: float(np.corrcoef(v, ylab)[0, 1]) for n, v in feats.items()}
    print(f"  feature correlations: {corr}", flush=True)
    sub2 = rng.choice(len(train_refs),
                       size=min(feat.TRAIN_SUBSAMPLE, len(train_refs)),
                       replace=False)
    for fs_name, names in feat.FEATURE_SETS.items():
        Xf = np.stack([feats[n] for n in names], axis=1).astype(np.float32)
        Xfs, yfs = Xf[sub2], ylab[sub2]
        for model_name, ctor in (("linear", lambda ni: feat.Linear(ni)),
                                  ("mlp", lambda ni: feat.MLP(ni))):
            t1 = time.time()
            torch.manual_seed(0)
            model = feat.train(ctor(Xf.shape[1]), Xfs, yfs)
            tr_f, _ = feat.simulate_policy(model, train_refs, cap, names, arena_pages)
            ev_f, _ = feat.simulate_policy(model, eval_refs, ev_cap, names, arena_pages)
            full_name = f"{fs_name}/{model_name}"
            emit("feature", full_name, tr_f, ev_f, f"({time.time()-t1:.0f}s)")
            save_model(model, f"{label}_feat_{fs_name}_{model_name}",
                       {"workload": label, "experiment": "feature",
                        "feature_set": fs_name, "features": names,
                        "model": model_name, "train_log": train_stem,
                        "eval_log": eval_stem, "capacity": cap,
                        "eval_capacity": ev_cap, "correlations": corr,
                        "train_faults": tr_f, "held_out_faults": ev_f})

    print(f"-- {label} done in {time.time()-t0:.0f}s --", flush=True)


def main():
    RESULTS_CSV.parent.mkdir(exist_ok=True)
    with RESULTS_CSV.open("w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["workload", "experiment", "model", "capacity",
                          "eval_capacity", "train_refs", "train_faults",
                          "held_out_faults"])
        csvfile.flush()
        t0 = time.time()
        for args in WORKLOADS:
            run_workload(*args, writer=writer, csvfile=csvfile)
        print(f"\nALL DONE in {time.time()-t0:.0f}s. "
              f"Results: {RESULTS_CSV}, models: {MODELS_DIR}", flush=True)


if __name__ == "__main__":
    main()
