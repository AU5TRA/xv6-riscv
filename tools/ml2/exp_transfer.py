#!/usr/bin/env python3
"""Transfer test on streams no model was trained on: the patbench modes
(seeds 1 and 5) and the six Twitter-driven kvbench streams. Trained models are
the final selected linear scorers (global scope; kv scope for the Twitter
streams); policies are the classical and literature baselines plus Belady.

    python3 exp_transfer.py run [--jobs 6]   -> report/results2/transfer.csv
    python3 exp_transfer.py report           -> faults / Clock per stream and capacity
"""
import argparse
import csv
import math
import time
from multiprocessing import Pool

import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
OUT = R / "transfer.csv"
OUT_REAL = R / "transfer_real.csv"
OUT_APP = R / "transfer_app.csv"
OUT_T3 = R / "transfer_traces3.csv"
T3 = ([f"{w}-s1" for w in ("heap-small", "heap-mixed", "heap-churn", "join-r4", "join-uni", "join-zipf", "spmv-band", "spmv-rand")]
      + [f"patb-{m}-s1" for m in ("loop", "scanhot", "scanhotlo", "zipf060", "zipf099", "zipf120", "uniform", "phase", "phaseshort", "switch")])
NETS = ["cnn-kv", "attention-graph", "mlp-kv", "ranktrees-graph", "trees-kv"]
APP = [f"app-{m}-s{k}" for m in ("chase", "spmv", "hashjoin", "bloom") for k in (1, 3)]
FRACS = ("0.05", "0.1", "0.2")
CLASSIC = ["fifo", "lru", "clock", "belady", "mru", "arc", "s3fifo", "s3scan", "mglru", "lhd"]
HEADER = ["model", "stem", "workload", "fraction", "frames", "faults", "writebacks", "aborted"]
MODES = ["loop", "scanhot", "scanhotlo", "zipf060", "zipf080", "zipf099", "zipf120",
         "uniform", "phase", "phaseshort", "switch"]
TW = [4, 17, 18, 24, 35, 52]


REAL = ["redis-real-s1", "sqlite-real-s1"]


def stems():
    return [f"pat-{m}-s{s}" for m in MODES for s in (1, 5)] + [f"kv-T{c}-s1" for c in TW]


def specs():
    final = M.load_models("final_linear")
    return {k: v for k, v in final.items() if k.startswith("global|") or k.startswith("kv|")}


def job(args):
    stem, frac = args
    s = ps.load_stream(stem)
    cap = s.capacities[frac]
    rows = []
    clock = ps.run(s, cap, "clock")["faults"]
    for pol in CLASSIC:
        r = ps.run(s, cap, pol)
        rows.append([pol, stem, s.workload, frac, cap, r["faults"], r["writebacks"], 0])
    for name, spec in specs().items():
        scope = name.split("|")[0]
        if (scope == "kv") != stem.startswith("kv-T"):
            continue
        r = ps.run(s, cap, "learned", M.to_scored(spec, protect_age=spec.get("protect_age")), max_faults=3 * clock)
        rows.append(["linear:" + name, stem, s.workload, frac, cap, r["faults"], r["writebacks"], int(r["aborted"])])
    if stem in T3:       # the five extra models (integer versions, as in the kernel), probation 2
        import extra_core as Z
        import kernel_vs_sim as kvs
        import netint
        for nm in NETS:
            r = ps.run(s, cap, "learned", netint.scored(Z.load_spec(kvs.NETS[nm]), 2), max_faults=3 * clock)
            rows.append(["net:" + nm, stem, s.workload, frac, cap, r["faults"], r["writebacks"], int(r["aborted"])])
    return rows


def run(jobs, which="main"):
    out = {"main": OUT, "real": OUT_REAL, "app": OUT_APP, "t3": OUT_T3}[which]
    tasks = [(st, fr) for st in {"main": stems(), "real": REAL, "app": APP, "t3": T3}[which] for fr in FRACS]
    t0 = time.time()
    with Pool(jobs) as pool, open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(HEADER)
        for i, rows in enumerate(pool.imap_unordered(job, tasks), 1):
            w.writerows(rows); f.flush()
            if i % 10 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} cells, {time.time() - t0:.0f}s", flush=True)


def report():
    rows = [r for p in (OUT, OUT_REAL, OUT_APP, OUT_T3) if p.exists() for r in csv.DictReader(open(p))]
    f = {(r["model"], r["stem"], r["fraction"]): int(r["faults"]) for r in rows}
    models = sorted({r["model"] for r in rows}, key=lambda m: (not m in CLASSIC, CLASSIC.index(m) if m in CLASSIC else 0, m))
    print("faults / Clock, geo-mean over the 3 capacities and the seeds of a mode")
    names = sorted({r["stem"].rsplit("-s", 1)[0] for r in rows})
    print(f"{'':12s}" + "".join(f"{m[:9]:>10s}" for m in models))
    for n in names:
        sts = sorted({r["stem"] for r in rows if r["stem"].rsplit("-s", 1)[0] == n})
        line = f"{n[:12]:12s}"
        for m in models:
            v = [f[(m, st, fr)] / f[("clock", st, fr)] for st in sts for fr in FRACS if (m, st, fr) in f]
            line += f"{math.exp(sum(math.log(max(x, 1e-9)) for x in v) / len(v)):10.3f}" if v else f"{'-':>10s}"
        print(line)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("--jobs", type=int, default=6); ap.add_argument("--set", default="main", choices=["main", "real", "app", "t3"])
    a = ap.parse_args()
    run(a.jobs, a.set) if a.cmd == "run" else report()
