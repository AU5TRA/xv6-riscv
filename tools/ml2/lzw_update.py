#!/usr/bin/env python3
"""Bring the whole traces2 study up to date after lzw joined the workloads,
with identity gates so nothing old silently changes.

  1 classical.py          gate: rows of the 89 old streams unchanged (vs git HEAD)
  2 build_datasets.py     gate: two rebuilds are bit-identical (deterministic)
  3 sweep_linear.py       all rows dropped and recomputed (new training draws, lzw in global); informational: drift of refit models
  4 train_all_nn.sh       all scopes
  5 run_phase_b.sh        selection, test, neural eval, extras, analysis

    python3 lzw_update.py [--from N]
"""
import csv, hashlib, io, json, subprocess, sys, time
from pathlib import Path

import pagesim as ps

PY = str(Path.home() / ".venvs/xv6ml/bin/python")
HERE = Path(__file__).resolve().parent
R = ps.ROOT / "report" / "results2"
CACHE = ps.ROOT / "traces2" / "ml2_cache"
T0 = time.time()


def say(msg):
    print(f"[{time.time() - T0:6.0f}s] {msg}", flush=True)


def run(*cmd):
    say("run " + " ".join(str(c) for c in cmd)[:100])
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-1500:], r.stderr[-1500:])
        sys.exit(f"FAILED: {cmd}")
    return r.stdout


def git_show(path):
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ps.ROOT, capture_output=True,
                          text=True, check=True).stdout


def old_stems():
    return {e["stem"] for e in json.load(open(ps.ROOT / "traces2/ML_old89/index.json"))["streams"]}


def gate_classical():
    old = list(csv.DictReader(io.StringIO(git_show("report/results2/classical.csv"))))
    new = {(r["stem"], r["fraction"], r["policy"]): r for r in csv.DictReader(open(R / "classical.csv"))}
    bad = sum(1 for r in old if new.get((r["stem"], r["fraction"], r["policy"])) != r)
    n_lzw = sum(1 for k in new if k[0].startswith("lzw"))
    say(f"gate classical: {len(old)} old rows, {bad} changed; {n_lzw} lzw rows")
    assert bad == 0 and n_lzw > 0


def hashes():
    return {l.split()[1]: l.split()[0] for l in
            subprocess.run("sha256sum *.npz", shell=True, cwd=CACHE, capture_output=True,
                           text=True).stdout.splitlines()}


def gate_deterministic(first):
    second = hashes()
    changed = [f for f in first if second.get(f) != first[f]]
    say(f"gate datasets: rebuild is deterministic -> {len(first)} caches, {len(changed)} differ")
    assert not changed and "train_lzw.npz" in second


def report_model_drift():
    """Informational: how far the refit per-workload models moved (the old
    caches came from an unrecorded random draw and cannot be regenerated)."""
    import numpy as np
    for sc in ("btree", "graph", "kv", "matmul", "sort"):
        old = json.loads(git_show(f"report/models2/linear_{sc}.json"))
        new = json.load(open(ps.ROOT / f"report/models2/linear_{sc}.json"))
        d = [np.max(np.abs(np.array(old[k]["layers"][0]["W"]) - np.array(new[k]["layers"][0]["W"])))
             for k in old if k in new]
        say(f"drift {sc}: max |dW| over {len(d)} feature sets = {max(d):.4f} (median {np.median(d):.4f})")


def main():
    start = int(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 1
    if start <= 1:
        run(PY, "-u", "classical.py", "--jobs", "6")
        gate_classical()
    if start <= 2:
        run(PY, "-u", "build_datasets.py", "--jobs", "6")
        first = hashes()
        run(PY, "-u", "build_datasets.py", "--jobs", "6")
        gate_deterministic(first)
    if start <= 3:
        sweep = R / "linear_sweep.csv"
        rows = list(csv.reader(open(sweep)))
        # every training set is a new (now reproducible) draw and global gained lzw,
        # so no old sweep row is valid: recompute them all
        keep = [rows[0]]
        say(f"sweep: dropping all {len(rows) - 1} rows (backup .pre_lzw)")
        sweep.rename(R / "linear_sweep.pre_lzw.csv")
        csv.writer(open(sweep, "w", newline="")).writerows(keep)
        run(PY, "-u", "sweep_linear.py", "--fracs", "0.1", "--jobs", "6")
        report_model_drift()
        n = sum(1 for _ in open(sweep)) - 1
        say(f"sweep rows now {n}")
    if start <= 4:
        subprocess.run(["bash", "train_all_nn.sh"], cwd=HERE, check=True, capture_output=True)
        say("neural models trained for all scopes")
    if start <= 5:
        run("bash", "run_phase_b.sh")
    say("LZW-UPDATE-DONE")


if __name__ == "__main__":
    main()
