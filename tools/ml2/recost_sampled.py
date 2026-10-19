#!/usr/bin/env python3
"""Re-measure the sampled scores (global@4..@64) in cost_grid.csv on the current kernel, so every
instruction count in the paper comes from one kernel. Same benchmark and counting as cost_grid.py.

    python3 recost_sampled.py [--lanes 2]   -> report/results2/cost_grid_sampled_current.csv
"""
import argparse
import csv
import os
import queue
import threading

import cost_grid as cg
import kernel_eval as ke

OUT = cg.ROOT / "report" / "results2" / "cost_grid_sampled_current.csv"
MODELS = ["global@4", "global@8", "global@16", "global@32", "global@64"]
SIZES = [16, 64, 256, 512]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", type=int, default=2)
    a = ap.parse_args()
    done = set()
    if OUT.exists():
        done = {(int(r["frames"]), r["model"]) for r in csv.DictReader(open(OUT))}
    q = queue.Queue()
    for n in SIZES:
        for m in MODELS:
            if (n, m) not in done:
                q.put((n, m))
    print(q.qsize(), "runs", flush=True)
    new = not OUT.exists()
    f = open(OUT, "a", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(cg.HEADER)
    lock = threading.Lock()
    os.environ.setdefault("KERNEL_EVAL_LANES", "/tmp/xv6recost")

    def worker(i):
        lane = ke.make_lane(i)
        while True:
            try:
                n, m = q.get_nowait()
            except queue.Empty:
                return
            d = cg.one(lane, n, "ml", m, 20000)
            if not d:
                print("FAILED", n, m, flush=True)
                continue
            ev = max(d["evictions"], 1)
            row = [n, "ml", m, d["evictions"], round(d["candidates_scanned"] / ev, 1), round(d["collect_ticks"] / ev, 2),
                   round(d["select_ticks"] / ev, 2), round(d["path_ticks"] / ev, 2), round(100 * d["select_ticks"] / ev),
                   round(100 * d["path_ticks"] / ev), d["swap_faults"] + d["zero_faults"]]
            with lock:
                w.writerow(row)
                f.flush()
                print(row, flush=True)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(a.lanes)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    f.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
