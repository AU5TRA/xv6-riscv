#!/usr/bin/env python3
"""Rerun, on the current kernel, every linear-score run in kernel_eval_all.csv that was made before the cheaper linear code
(commit dbc508b, 2026-10-15 13:28): the full-scan "linear, global" rows, the per-workload weights and their variants. The
cheaper code must keep every victim, so faults, evictions and page writes must match the stored rows exactly.

    python3 recheck_linear.py [--lanes 6]   -> report/results2/kernel_eval_recheck_linear.csv (resumable)
    python3 compare_runs.py report/results2/kernel_eval_recheck_linear.csv
"""
import argparse
import csv
import os
import queue
import re
import threading

os.environ.setdefault("KERNEL_EVAL_LANES", "/tmp/xv6recheck")
import kernel_eval as ke

R = ke.ROOT / "report" / "results2"
OUT = R / "kernel_eval_recheck_linear.csv"
CHEAPER_CODE = "20261015132821"
HEAVY = {"cnn-all", "mlp-all", "attention-all", "trees-all", "ranktrees-all"}
LINEAR = {"btree", "graph", "kv", "lzw", "matmul", "sort", "own"}


def linear(model):
    base = model.split("@")[0]
    return base not in HEAVY and (base.startswith("global") or base in LINEAR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", type=int, default=6)
    a = ap.parse_args()
    rows = []
    for r in csv.DictReader(open(R / "kernel_eval_all.csv")):
        ts = re.search(r"(\d{8})-(\d{6})", r["transcript"] or "")
        if r["policy"] == "ml" and linear(r["model"]) and ts and ts.group(1) + ts.group(2) < CHEAPER_CODE:
            rows.append(r)
    done = set()
    if OUT.exists():
        done = {(r["stem"], r["fraction"], r["model"]) for r in csv.DictReader(open(OUT)) if r["status"] == "ok"}
    todo = [r for r in rows if (r["stem"], r["fraction"], r["model"]) not in done]
    todo.sort(key=lambda r: -float(r["wall_s"] or 0))
    print(f"{len(rows)} runs to recheck, {len(todo)} left, on {a.lanes} lanes", flush=True)
    q = queue.Queue()
    for r in todo:
        q.put(r)
    new = not OUT.exists()
    f = open(OUT, "a", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(ke.HEADER)
    lock = threading.Lock()
    count = [len(done)]

    def worker(i):
        lane = ke.make_lane(i)
        while True:
            try:
                r = q.get_nowait()
            except queue.Empty:
                return
            job = (r["stem"], r["split"], r["workload"], r["variant"], r["fraction"], int(r["frames"]), r["policy"], r["model"])
            row = ke.run_one(lane, job, 10800, int(r["accesses"]) if r["accesses"] else 0)
            same = row[8] == "ok" and (str(row[9]), str(row[10]), str(row[11]), str(row[14])) == \
                (r["swap_faults"], r["evictions"], r["page_writes"], r["zero_faults"])
            with lock:
                w.writerow(row)
                f.flush()
                count[0] += 1
                print(f"[{count[0]}/{len(rows)}] {r['stem']:<22} {r['fraction']:<4} {r['model']:<10} {row[8]} "
                      f"{'SAME' if same else 'DIFFERENT'} faults {row[9]} (stored {r['swap_faults']}) {row[15]}s", flush=True)

    ts_ = [threading.Thread(target=worker, args=(i,)) for i in range(a.lanes)]
    [t.start() for t in ts_]
    [t.join() for t in ts_]
    f.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
