#!/usr/bin/env python3
"""Does the simulator predict the kernel? For every in-kernel run
(report/results2/kernel_eval.csv) replay the same stream in pagesim at the
same frame count, with the same policy -- VM_POLICY_ML with the same integer
weights and probation (the simulator's integer mode uses kernel/mlfeat.h,
so both score a page identically) -- and compare total faults (the kernel's
zero-fill + swap faults; the simulator starts from empty memory too).

The kernel's resident limit also holds the process's code and stack pages
(3-9 frames, not in the trace), so small differences are expected; what
matters is whether the two agree on how policies compare.

    python3 kernel_vs_sim.py   -> report/results2/kernel_vs_sim.csv, kernel_cliff.csv
"""
import csv
from multiprocessing import Pool

import numpy as np

import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
SIMPOL = {"fifo": "fifo", "clock": "clock", "aging": "aging", "lfu": "lfu_kernel",
          "arck": "arck", "s3fifo": "s3scan", "lhd": "lhd"}


def final_models():
    out = {}
    for k, spec in M.load_models("final_linear").items():
        sc, g = k.split("|")
        if g in ("K", "K+K+"):
            out[sc + ("" if g == "K+K+" else "-k")] = spec
    return out


FM = final_models()
import extra_core as Z
import export_nets
import netint
NETS = {name: src for name, src in export_nets.MODELS}


WARM = False     # --warm: put one populate sweep in front of the stream, as the kernel's benchmarks have


def simulate(s, frames, r):
    if WARM:
        import warm_start
        r2 = dict(r)
        global_warm, globals()["WARM"] = True, False
        try:
            cold = simulate(s, frames, r)
            t = warm_start.warm(s)
            full = simulate(t, frames, r)
            import copy
            u = copy.copy(t)
            u.n = t.prefix
            pre = simulate(u, frames, r)
        finally:
            globals()["WARM"] = global_warm
        return {"faults": full["faults"] - pre["faults"], "writebacks": full["writebacks"] - pre["writebacks"]}
    if r["policy"] == "ml" and r["model"].split("@")[0] in NETS:
        return ps.run(s, frames, "learned", netint.scored(Z.load_spec(NETS[r["model"].split("@")[0]]), 2))
    if r["policy"] == "ml":
        spec = FM[r["model"]]
        sm = ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"],
                            std=spec["std"],
                            layers=[(np.asarray(L["W"], np.float32),
                                     np.asarray(L["b"], np.float32))
                                    for L in spec["layers"]],
                            quant_w=8, protect_age=spec.get("protect_age", 0))
        return ps.run(s, frames, "learned", sm)
    return ps.run(s, frames, SIMPOL[r["policy"]])


def prefix(s, n):
    """The first n references of a stream: patbench / appbench kernel runs use fewer accesses than
    the stored 1M-reference stream, whose first n references are exactly what they ran."""
    import copy
    t = copy.copy(s)
    t.n = n
    return t


def job(args):
    stem, rows = args
    s = ps.load_stream(stem)
    out = []
    for r in rows:
        frames = int(r["frames"])
        sim = simulate(prefix(s, int(r["accesses"])) if r.get("accesses") else s, frames, r)
        kern = int(r["swap_faults"]) + int(r["zero_faults"])
        out.append([stem, r["split"], r["workload"], r["fraction"], frames, r["policy"],
                    r["model"], kern, sim["faults"], f"{kern / sim['faults']:.4f}",
                    r["page_writes"], sim["writebacks"]])
    return out


CLIFF = range(5)    # extra frames tried for the stream the kernel disagrees on most


def cliff(args):
    stem, rows = args
    s = ps.load_stream(stem)
    return [[stem, r["policy"], r["model"], r["frames"],
             int(r["swap_faults"]) + int(r["zero_faults"])]
            + [simulate(s, int(r["frames"]) + d, r)["faults"] for d in CLIFF] for r in rows]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated stem prefixes")
    ap.add_argument("--tag", default="", help="suffix of the output files")
    ap.add_argument("--warm", action="store_true", help="start the simulator from a populated memory, as the kernel does")
    ap.add_argument("--input", default="kernel_eval.csv", help="in-kernel results file in report/results2")
    a = ap.parse_args()
    globals()["WARM"] = a.warm
    pre = tuple(a.only.split(",")) if a.only else ()
    rows = [r for r in csv.DictReader(open(R / a.input)) if r["status"] == "ok"
            and (not pre or r["stem"].startswith(pre))]
    by = {}
    for r in rows:
        by.setdefault(r["stem"], []).append(r)
    with Pool(6) as pool, open(R / f"kernel_vs_sim{a.tag}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stem", "split", "workload", "fraction", "frames", "policy", "model",
                    "kernel_faults", "sim_faults", "kernel_over_sim", "kernel_writes",
                    "sim_writes"])
        for out in pool.imap_unordered(job, by.items()):
            w.writerows(out)
    print("written", R / f"kernel_vs_sim{a.tag}.csv")
    # The stream the kernel disagrees on most: is it sitting on a capacity cliff,
    # where the frame or two of difference in the kernel's limit dominates?
    res = list(csv.DictReader(open(R / f"kernel_vs_sim{a.tag}.csv")))
    worst = min(res, key=lambda r: float(r["kernel_over_sim"]))["stem"]
    with Pool(6) as pool, open(R / f"kernel_cliff{a.tag}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stem", "policy", "model", "frames", "kernel_faults"]
                    + [f"sim_plus{d}" for d in CLIFF])
        for out in pool.imap_unordered(cliff, [(worst, [r]) for r in by[worst]]):
            w.writerows(out)
    print("written", R / f"kernel_cliff{a.tag}.csv", "for", worst)


if __name__ == "__main__":
    main()
