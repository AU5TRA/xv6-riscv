#!/usr/bin/env python3
"""What does choosing a victim cost, for every policy, as the number of candidates grows?

patbench `uniform` over 1024 pages with a memory limit of n frames makes every eviction choose among n
candidates, whatever the policy does (every access is a uniform random page, so the same stream for every
policy). QEMU runs in instruction-count mode (QEMU_ICOUNT=1: 1 timer tick = 100 instructions), so the kernel's
per-eviction counters are exact and do not depend on how busy the host is. Several runs go in parallel (private
copies of the tree); each is independent.

Counters per eviction: collect (building the candidate list), select (scanning + choosing: the policy),
path (the whole eviction except waiting for the swap-out write).

    python3 cost_grid.py [--sizes 16,64,256,512] [--accesses 20000] [--lanes 6]   -> report/results2/cost_grid.csv
"""
import argparse
import csv
import os
import queue
import re
import subprocess
import threading

import kernel_eval as ke

ROOT = ke.ROOT
OUT = ROOT / "report" / "results2" / "cost_grid.csv"
POLICIES = [("fifo", ""), ("clock", ""), ("aging", ""), ("lfu", ""), ("ml", "global"), ("ml", "global@64"), ("ml", "global@32"), ("ml", "global@16"), ("ml", "global@8"), ("ml", "global@4"),
            ("ml", "cnn-kv"), ("ml", "mlp-kv"), ("ml", "trees-kv"), ("ml", "attention-graph"), ("ml", "ranktrees-graph"),
            ("arck", ""), ("s3fifo", ""), ("lhd", ""), ("lecar", ""), ("ml", "cnn-all"), ("ml", "mlp-all"), ("ml", "trees-all"), ("ml", "attention-all"),
            ("ml", "ranktrees-all"), ("ml", "cnn-kv@32"), ("ml", "mlp-kv@32"), ("ml", "trees-kv@32"), ("ml", "attention-graph@32"), ("ml", "ranktrees-graph@32")]
HEADER = ["frames", "policy", "model", "evictions", "candidates_per_eviction", "collect_ticks_per_eviction",
          "select_ticks_per_eviction", "path_ticks_per_eviction", "select_instructions_per_eviction",
          "path_instructions_per_eviction", "faults"]


def one(lane, n, pol, model, accesses):
    cmd = ["vmrun", pol] + ([model] if model else []) + ["patbench", "1024", str(n), str(accesses), "1", "uniform", "0"]
    env = dict(os.environ, QEMU_ICOUNT="1")
    p = subprocess.run(["python3", "tools/run_xv6_tests.py", "--cpus", "1", "--timeout", "7200", " ".join(cmd)],
                       cwd=lane, env=env, capture_output=True, text=True)
    m = re.search(r"(/\S+\.log)", p.stdout + p.stderr)
    d = ke.parse(open(m.group(1)).read()) if m else None
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="16,64,256,512")
    ap.add_argument("--accesses", type=int, default=20000)
    ap.add_argument("--lanes", type=int, default=6)
    a = ap.parse_args()
    done = set()
    if OUT.exists():
        done = {(int(r["frames"]), r["policy"], r["model"]) for r in csv.DictReader(open(OUT))}
    jobs = [(int(n), p, m) for n in a.sizes.split(",") for p, m in POLICIES if (int(n), p, m) not in done]
    print(len(jobs), "runs", flush=True)
    q = queue.Queue()
    for j in jobs:
        q.put(j)
    lock = threading.Lock()
    new = not OUT.exists()
    f = open(OUT, "a", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(HEADER)
    os.environ.setdefault("KERNEL_EVAL_LANES", "/tmp/xv6cost")

    def worker(i):
        lane = ke.make_lane(i)
        while True:
            try:
                n, pol, model = q.get_nowait()
            except queue.Empty:
                return
            d = one(lane, n, pol, model, a.accesses)
            if not d:
                print("FAILED", n, pol, model, flush=True)
                continue
            ev = max(d["evictions"], 1)
            row = [n, pol, model, d["evictions"], round(d["candidates_scanned"] / ev, 1), round(d["collect_ticks"] / ev, 2),
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
