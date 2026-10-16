import sys; sys.path.insert(0,'.')
import csv, math, collections
from multiprocessing import Pool
import pagesim as ps, kernel_vs_sim as kvs, exp_sampling_pct as P, exp_sampling_heur as H
cells = P.cells("0.2")
def job(a):
    stem, c = a
    s = ps.load_stream(stem)
    if c["accesses"]: s = kvs.prefix(s, c["accesses"])
    out = []
    for k in (48, 64):
        for seed in (1, 2):
            r = ps.run(s, c["frames"], "learned", H.model(sample_k=k, sample_scan=1, sample_seed=seed))
            out.append([stem, "0.2", k, seed, r["faults"], r["evictions"], r["scored"]])
    return out
with Pool(6) as pool, open("../../report/results2/sampling_pct_extra.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["stem", "fraction", "k", "seed", "faults", "evictions", "scored"])
    for rows in pool.imap_unordered(job, list(cells.items())): w.writerows(rows)
print("done")
