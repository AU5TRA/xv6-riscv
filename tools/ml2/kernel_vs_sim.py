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

    python3 kernel_vs_sim.py   -> report/results2/kernel_vs_sim.csv
"""
import csv
from multiprocessing import Pool

import numpy as np

import models as M
import pagesim as ps

R = ps.ROOT / "report" / "results2"
SIMPOL = {"fifo": "fifo", "clock": "clock", "aging": "aging", "lfu": "lfu_kernel"}


def final_models():
    out = {}
    for k, spec in M.load_models("final_linear").items():
        sc, g = k.split("|")
        if g in ("K", "K+K+"):
            out[sc + ("" if g == "K+K+" else "-k")] = spec
    return out


FM = final_models()


def job(args):
    stem, rows = args
    s = ps.load_stream(stem)
    out = []
    for r in rows:
        frames = int(r["frames"])
        if r["policy"] == "ml":
            spec = FM[r["model"]]
            sm = ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"],
                                std=spec["std"],
                                layers=[(np.asarray(L["W"], np.float32),
                                         np.asarray(L["b"], np.float32))
                                        for L in spec["layers"]],
                                quant_w=8, protect_age=spec.get("protect_age", 0))
            sim = ps.run(s, frames, "learned", sm)
        else:
            sim = ps.run(s, frames, SIMPOL[r["policy"]])
        kern = int(r["swap_faults"]) + int(r["zero_faults"])
        out.append([stem, r["split"], r["workload"], r["fraction"], frames, r["policy"],
                    r["model"], kern, sim["faults"], f"{kern / sim['faults']:.4f}",
                    r["page_writes"], sim["writebacks"]])
    return out


def main():
    rows = [r for r in csv.DictReader(open(R / "kernel_eval.csv")) if r["status"] == "ok"]
    by = {}
    for r in rows:
        by.setdefault(r["stem"], []).append(r)
    with Pool(6) as pool, open(R / "kernel_vs_sim.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stem", "split", "workload", "fraction", "frames", "policy", "model",
                    "kernel_faults", "sim_faults", "kernel_over_sim", "kernel_writes",
                    "sim_writes"])
        for out in pool.imap_unordered(job, by.items()):
            w.writerows(out)
    print("written", R / "kernel_vs_sim.csv")


if __name__ == "__main__":
    main()
