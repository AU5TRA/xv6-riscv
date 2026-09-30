#!/usr/bin/env python3
"""Follow-up experiments on the linear sweep, all -> report/results2/extras.csv

  matmul_train  every linear subset of the matmul and global scopes on
                matmul's training streams: matmul has no validation split,
                so this is where its subsets are selected (never on held-out).
  quant         the validation-selected linear models scored in integer
                arithmetic only (Q8 features, weights rounded after folding in
                the standardisation) -- what a kernel without floating point
                would compute -- next to their float results.
  dagger        one DAgger round for the validation-selected linear models:
                the training decisions were recorded while LRU chose victims,
                but a deployed model meets the states its own choices create.
                Record again under the model itself, add those rows, refit.

    python3 extras.py matmul_train|quant|dagger [--jobs 6]
"""
import argparse
import csv
import time
from multiprocessing import Pool

import numpy as np

import analyze
import build_datasets as B
import models as M
import pagesim as ps

OUT = ps.ROOT / "report" / "results2" / "extras.csv"
HEADER = ["kind", "scope", "features", "stem", "split", "workload", "variant",
          "fraction", "frames", "faults", "writebacks", "aborted"]
EVAL_FRACS = ("0.05", "0.1", "0.2")


def run_models(args):
    """(stem, frac, [(kind, scope, key, spec, quant_w)]) -> rows"""
    stem, frac, jobs = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    limit = 5 * ps.baselines()[(stem, frac)]["fifo"]
    rows = []
    for kind, scope, key, spec, q in jobs:
        sm = M.to_scored(spec) if not q else ps.ScoredModel(
            "mlp", features=spec["features"], mean=spec["mean"], std=spec["std"],
            layers=[(np.asarray(L["W"], np.float32), np.asarray(L["b"], np.float32))
                    for L in spec["layers"]], quant_w=q)
        r = ps.run(s, cap, "learned", sm, max_faults=limit)
        rows.append([kind, scope, key, stem, s.split, s.workload, s.variant, frac, cap,
                     r["faults"], r["writebacks"], int(r["aborted"])])
    return rows


def dispatch(tasks, jobs):
    new = not OUT.exists()
    with open(OUT, "a", newline="") as f, Pool(jobs) as pool:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(run_models, tasks), 1):
            w.writerows(rows)
            f.flush()
            print(f"  [{i}/{len(tasks)}]", flush=True)


def matmul_train(jobs):
    specs = {sc: M.load_models(f"linear_{sc}") for sc in ("matmul", "global")}
    tasks = []
    for stem in ps.stems("train", "matmul"):
        for frac in EVAL_FRACS:
            tasks.append((stem, frac, [("matmul_train", sc, k, sp, 0)
                                       for sc in specs for k, sp in specs[sc].items()]))
    dispatch(tasks, jobs)


def selected():
    chosen = analyze.main()
    return {(sc, g): f for (sc, g), f in chosen.items() if g in ("F", "K", "K+K+", "any")}


def quant(jobs):
    chosen = selected()
    specs = {sc: M.load_models(f"linear_{sc}") for sc in M.WORKLOADS + ["global"]}
    tasks = []
    for stem in ps.stems(("test", "heldout")):
        wl = ps.index_entry(stem)["workload"]
        todo = []
        for (sc, g), key in chosen.items():
            if sc not in (wl, "global"):
                continue
            for q in (4, 8, 12):
                todo.append((f"quant{q}", sc, key, specs[sc][key], q))
        for frac in EVAL_FRACS:
            tasks.append((stem, frac, todo))
    dispatch(tasks, jobs)


def dagger_record(args):
    stem, frac, spec = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    evictions = max(ps.baselines()[(stem, frac)]["lru"] - cap, 1)
    per = min(B.MAX_CAND, cap)
    p = min(1.0, B.ROWS["train"] / (evictions * per))
    r = ps.record(s, cap, "learned", p=p, max_rows=int(B.ROWS["train"] * 3) + 4 * per,
                  seed=7, model=M.to_scored(spec), max_cand=B.MAX_CAND)
    return r["feat"], r["label"]


def dagger(jobs):
    chosen = selected()
    new_specs = {}
    for (sc, g), key in sorted(chosen.items()):
        if sc == "global":
            continue
        spec = M.load_models(f"linear_{sc}")[key]
        args = [(stem, frac, spec) for stem in ps.stems("train", sc) for frac in B.TRAIN_FRACS]
        with Pool(jobs) as pool:
            parts = pool.map(dagger_record, args)
        base = M.load_scope("train", sc)
        feat = np.concatenate([base["feat"]] + [p[0] for p in parts])
        label = np.concatenate([base["label"]] + [p[1] for p in parts])
        fitter = M.LinearFitter({"feat": feat, "label": label,
                                 "weight": np.ones(len(label))})
        new_specs[(sc, key)] = fitter.fit(key.split("+"))
        print(f"  dagger {sc} {g}: {key} +{sum(len(p[1]) for p in parts):,} rows", flush=True)
    M.save_models("linear_dagger", {f"{sc}|{k}": v for (sc, k), v in new_specs.items()})
    tasks = []
    for stem in ps.stems(("val", "test", "heldout")):
        wl = ps.index_entry(stem)["workload"]
        todo = [("dagger", sc, k, v, 0) for (sc, k), v in new_specs.items() if sc == wl]
        if todo:
            for frac in EVAL_FRACS:
                tasks.append((stem, frac, todo))
    dispatch(tasks, jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["matmul_train", "quant", "dagger"])
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    {"matmul_train": matmul_train, "quant": quant, "dagger": dagger}[a.what](a.jobs)
    print(f"{a.what} done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
