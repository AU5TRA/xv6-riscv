#!/usr/bin/env python3
"""Run the workloads in xv6 itself under every policy, VM_POLICY_ML included.

Each run is the stream's own command (tools/streams_manifest.tsv) with the
memory margin set to a capacity from traces2/ML (the same frame count the
simulator used) and tracing off, launched as
    vmrun <policy> [model] <workload command>
The kernel's own counters (the workload's "[... workload]" delta line) are
recorded: swap faults, evictions, page writes, victim-selection ticks and
candidates scanned.

Runs execute in parallel lanes, each a private copy of the built tree under
/tmp (the swap area lives in fs.img, so lanes cannot share one).

    python3 kernel_eval.py [--lanes 6] [--fracs 0.1] [--splits test,heldout]
      -> report/results2/kernel_eval.csv (resumable)
"""
import argparse
import csv
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "report" / "results2" / "kernel_eval.csv"
INDEX = ROOT / "traces2" / "ML" / "index.json"
MANIFEST = ROOT / "tools" / "streams_manifest.tsv"
HEADER = ["stem", "split", "workload", "variant", "fraction", "frames", "policy",
          "model", "status", "swap_faults", "evictions", "page_writes", "select_ticks",
          "candidates_scanned", "zero_faults", "wall_s", "transcript"]
TRACE_BITS = 9      # trace | file-sink flag bits (tools/make_stream_manifest.py)


def policies(workload):
    return [("fifo", ""), ("clock", ""), ("aging", ""), ("lfu", ""),
            ("ml", "global"), ("ml", workload), ("ml", workload + "-k")]


def command(stem, frames):
    for line in open(MANIFEST):
        if line.startswith(stem + "\t"):
            cmd = line.rstrip("\n").split("\t")[3].split()
            cmd[2] = str(frames)                       # margin
            cmd[-1] = str(int(cmd[-1]) & ~TRACE_BITS)  # tracing off
            return cmd
    raise KeyError(stem)


LINE = re.compile(r"\[\w+ workload\] (.*)")


def parse(text):
    m = LINE.search(text)
    if not m:
        return None
    return {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", m.group(1))}


def make_lane(i):
    lane = Path(f"/tmp/xv6lane{i}")
    if lane.exists():
        shutil.rmtree(lane)
    subprocess.run(["rsync", "-a", "--exclude", "traces", "--exclude", "traces2",
                    "--exclude", "report", "--exclude", ".git", "--exclude", "test-logs",
                    f"{ROOT}/", f"{lane}/"], check=True)
    # Host-side only: xv6 does not negotiate virtio's flush feature, so QEMU
    # makes every guest write durable (a host fsync per swap write), ~0.1 s
    # each with several lanes on one virtual disk. cache=unsafe skips the host
    # syncs; the guest sees the same device and data, so every counter is
    # unchanged -- only wall time drops.
    mk = lane / "Makefile"
    text = mk.read_text()
    assert "format=raw,id=x0\n" in text
    mk.write_text(text.replace("format=raw,id=x0\n", "format=raw,id=x0,cache=unsafe\n"))
    return lane


def run_one(lane, job, timeout):
    stem, split, wl, variant, frac, frames, pol, model = job
    cmd = ["vmrun", pol] + ([model] if model else []) + command(stem, frames)
    t0 = time.time()
    p = subprocess.run(["python3", "tools/run_xv6_tests.py", "--cpus", "1", "--timeout",
                        str(timeout), " ".join(cmd)], cwd=lane, capture_output=True, text=True)
    wall = time.time() - t0
    out = p.stdout + p.stderr
    m = re.search(r"(/\S+\.log)", out)
    path = m.group(1) if m else ""
    text = open(path).read() if path and os.path.exists(path) else ""
    d = parse(text) or {}
    status = "ok" if p.returncode == 0 and d else ("timeout" if "timeout" in out else "fail")
    keep = ROOT / "test-logs" / "kernel_eval"
    keep.mkdir(parents=True, exist_ok=True)
    if path and os.path.exists(path):
        dst = keep / Path(path).name
        shutil.copy(path, dst)
        path = str(dst.relative_to(ROOT))
    return [stem, split, wl, variant, frac, frames, pol, model or "", status,
            d.get("swap_faults", ""), d.get("evictions", ""), d.get("page_writes", ""),
            d.get("select_ticks", ""), d.get("candidates_scanned", ""),
            d.get("zero_faults", ""), f"{wall:.0f}", path]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", type=int, default=6)
    ap.add_argument("--fracs", default="0.1")
    ap.add_argument("--splits", default="test,heldout")
    ap.add_argument("--only", default="", help="comma-separated stem prefixes")
    ap.add_argument("--timeout", type=int, default=10800)
    a = ap.parse_args()
    idx = json.load(open(INDEX))["streams"]
    done = set()
    if OUT.exists():
        with open(OUT) as f:
            done = {(r["stem"], r["fraction"], r["policy"], r["model"])
                    for r in csv.DictReader(f) if r["status"] == "ok"}
    jobs = []
    for e in idx:
        if e["split"] not in a.splits.split(","):
            continue
        if a.only and not any(e["stem"].startswith(p) for p in a.only.split(",")):
            continue
        for frac in a.fracs.split(","):
            frames = e["capacities"][frac]
            for pol, model in policies(e["workload"]):
                if (e["stem"], frac, pol, model) in done:
                    continue
                jobs.append((e["stem"], e["split"], e["workload"], e["variant"], frac,
                             frames, pol, model))
    refs = {e["stem"]: e["refs"] for e in idx}
    jobs.sort(key=lambda j: -refs[j[0]])
    print(f"{len(jobs)} kernel runs on {a.lanes} lanes", flush=True)
    q = queue.Queue()
    for j in jobs:
        q.put(j)
    lock = threading.Lock()
    new = not OUT.exists()
    f = open(OUT, "a", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(HEADER)
        f.flush()
    count = [0]

    def worker(i):
        lane = make_lane(i)
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                return
            row = run_one(lane, job, a.timeout)
            with lock:
                w.writerow(row)
                f.flush()
                count[0] += 1
                print(f"  [{count[0]}/{len(jobs)}] {row[0]:<20} {row[4]:<4} {row[6]:<5} "
                      f"{row[7]:<9} {row[8]:<7} faults={row[9]} writes={row[11]} "
                      f"({row[15]}s)", flush=True)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(a.lanes)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    f.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
