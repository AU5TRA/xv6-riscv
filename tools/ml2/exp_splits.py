#!/usr/bin/env python3
"""Training-variety ablation: does PageScore improve when it is trained on different workloads?

PageScore's features (idle, age, dirty, refaults, rdist), probation (4 scans) and sample size (32) stay fixed; only the
weights are refitted on each split's training workloads, then each model runs in the kernel on the split's unseen
workloads. kv and kv-T (the same program) always stay on the same side.

    python3 exp_splits.py build                 training data for the new workloads -> traces2/ml2_splits/<workload>.npz
    python3 exp_splits.py fit                   weights for each split -> report/results2/split_models.json, user/mlmodels.h
    python3 exp_splits.py run [--fracs 0.1]     kernel runs -> report/results2/kernel_eval_splits.csv (resumable)
    python3 exp_splits.py report [--fracs 0.1]  each split's model against Clock and against PageScore on its unseen streams
"""
import argparse
import csv
import json
import os
import queue
import re
import threading
from collections import defaultdict
from multiprocessing import Pool

import numpy as np

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
R = ROOT / "report" / "results2"
CACHE = ROOT / "traces2" / "ml2_splits"
OUT = R / "kernel_eval_splits.csv"
FEATURES = ["idle", "age", "dirty", "refaults", "rdist"]
KFEAT = ["ref", "aging", "sfreq", "idle", "age", "dirty", "refaults", "rdist"]
PROTECT = 4
OLD = ["btree", "graph", "kv", "lzw", "matmul", "sort"]
NEW = ["kv-T", "heap", "join", "spmv", "chase", "bloom", "pat", "app"]
ALL = OLD + NEW
# training workloads of each split; the unseen (test) workloads are the rest. kv and kv-T always together.
SPLITS = {
    "s1": ["heap", "join", "spmv", "chase", "bloom", "pat", "app"],                    # reverse: train on the new programs
    "s2": ["graph", "kv", "kv-T", "chase", "spmv", "join", "heap"],                     # irregular access
    "s3": ["btree", "lzw", "matmul", "sort", "bloom", "pat", "app"],                    # regular access
    "s4": ["btree", "kv", "kv-T", "lzw", "sort", "join", "chase", "bloom", "pat", "app"],  # broad training; test the hard cases
    "s5": ["graph", "kv", "sort"],                                                      # very little variety
}


def group(stem):
    return "kv-T" if stem.startswith("kv-T") else stem.split("-")[0]


def build_job(a):
    os.environ["ML2_CACHE"] = str(CACHE / "tmp")
    import build_datasets as B
    d = B.job(a)
    return group(a[0]), {k: d[k] for k in ("feat", "label", "group")}


def build():
    import pagesim as ps
    CACHE.mkdir(parents=True, exist_ok=True)
    stems = [e["stem"] for e in ps.index()["streams"] if group(e["stem"]) in NEW]
    jobs = [(s, fr, "train") for s in stems for fr in ("0.05", "0.1", "0.2")]
    parts = defaultdict(list)
    with Pool(6) as pool:
        for g, d in pool.imap_unordered(build_job, jobs):
            parts[g].append(d)
    for g, ds in parts.items():
        off, gr = 0, []
        for d in ds:                       # decision ids unique within the workload
            gr.append(d["group"] + off); off += int(d["group"].max()) + 1
        np.savez(CACHE / f"{g}.npz", feat=np.concatenate([d["feat"] for d in ds]), label=np.concatenate([d["label"] for d in ds]),
                 group=np.concatenate(gr))
        print(f"{g}: {len(ds)} stream x size jobs, {sum(len(d['label']) for d in ds)} rows", flush=True)


def load(g):
    import models as M
    if g in OLD:
        return M.load_part("train", g)     # the same training data the current PageScore used
    z = np.load(CACHE / f"{g}.npz")
    return {k: z[k] for k in ("feat", "label", "group")}


def fit():
    import models as M
    out = {}
    for name, train in SPLITS.items():
        parts = [(g, load(g)) for g in train]
        data = {k: np.concatenate([p[k] for _, p in parts]) for k in ("feat", "label")}
        w = np.concatenate([np.full(len(p["label"]), 1.0 / len(p["label"])) for _, p in parts])   # each workload counts equally
        data["weight"] = w * len(w) / w.sum()
        spec = M.LinearFitter(data).fit(FEATURES)
        qa = [int(round(x / s * 256)) for x, s in zip(spec["layers"][0]["W"][0], spec["std"])]
        out[name] = {"train": train, "test": [g for g in ALL if g not in train], "features": FEATURES, "qa": qa, "protect_age": PROTECT,
                     "rows": int(len(w))}
        print(name, "train", train, "qa", qa, flush=True)
    (R / "split_models.json").write_text(json.dumps(out, indent=1))
    h = ROOT / "user" / "mlmodels.h"
    text = re.sub(r'  \{ "split-s\d".*\n', "", h.read_text())
    idx = [KFEAT.index(f) for f in FEATURES]
    lines = "".join('  { "split-%s", { %d, { %s }, { %s }, %d } },  // training-variety ablation (exp_splits.py)\n'
                    % (n, len(idx), ", ".join(str(i) for i in idx + [0] * (8 - len(idx))), ", ".join(str(q) for q in m["qa"] + [0] * (8 - len(idx))), PROTECT)
                    for n, m in out.items())
    h.write_text(text.replace("};\n#define ML_NMODELS", lines + "};\n#define ML_NMODELS"))
    print("user/mlmodels.h updated")


def jobs_for(fracs):
    models = json.loads((R / "split_models.json").read_text())
    rows = [r for r in csv.DictReader(open(R / "kernel_eval_all.csv")) if r["policy"] == "ml" and r["model"] == "global@32" and r["fraction"] in fracs]
    jobs = []
    for name, m in models.items():
        for r in rows:
            if group(r["stem"]) in m["test"]:
                jobs.append((r, f"split-{name}@32"))
    return jobs


def run(fracs, lanes):
    os.environ.setdefault("KERNEL_EVAL_LANES", "/tmp/xv6splits")
    import kernel_eval as ke
    done = set()
    if OUT.exists():
        done = {(r["stem"], r["fraction"], r["model"]) for r in csv.DictReader(open(OUT)) if r["status"] == "ok"}
    todo = [(r, m) for r, m in jobs_for(fracs) if (r["stem"], r["fraction"], m) not in done]
    todo.sort(key=lambda j: -float(j[0]["wall_s"] or 0))
    print(f"{len(todo)} runs left on {lanes} lanes", flush=True)
    q = queue.Queue()
    for j in todo:
        q.put(j)
    new = not OUT.exists()
    f = open(OUT, "a", newline=""); w = csv.writer(f)
    if new:
        w.writerow(ke.HEADER)
    lock = threading.Lock(); count = [0]

    def worker(i):
        lane = ke.make_lane(i)
        while True:
            try:
                r, m = q.get_nowait()
            except queue.Empty:
                return
            job = (r["stem"], r["split"], r["workload"], r["variant"], r["fraction"], int(r["frames"]), "ml", m)
            row = ke.run_one(lane, job, 10800, int(r["accesses"]) if r["accesses"] else 0)
            with lock:
                w.writerow(row); f.flush(); count[0] += 1
                print(f"[{count[0]}/{len(todo)}] {r['stem']:<22} {r['fraction']} {m:<14} {row[8]} faults {row[9]} (PageScore {r['swap_faults']}) {row[15]}s", flush=True)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(lanes)]
    [t.start() for t in ts]; [t.join() for t in ts]
    f.close(); print("done", flush=True)


def report(fracs):
    import paper_extra as pe
    models = json.loads((R / "split_models.json").read_text())
    allr = {(r["stem"], r["fraction"], r["policy"] + ":" + r["model"] if r["model"] else r["policy"]): r
            for r in csv.DictReader(open(R / "kernel_eval_all.csv")) if r["status"] == "ok"}
    sp = {(r["stem"], r["fraction"], r["model"]): r for r in csv.DictReader(open(OUT)) if r["status"] == "ok"}
    faults = lambda r: max(int(r["swap_faults"]) + int(r["zero_faults"] or 0), 1)
    with open(R / "splits_summary.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["split", "fraction", "train", "test", "streams", "split_vs_clock", "pagescore_vs_clock", "split_vs_pagescore"])
        for name, m in models.items():
            for fr in fracs:
                a, b, c = {}, {}, {}
                for (stem, f2, mod), r in sp.items():
                    if f2 != fr or mod != f"split-{name}@32":
                        continue
                    cl, ps_ = allr.get((stem, fr, "clock")), allr.get((stem, fr, "ml:global@32"))
                    if cl and ps_:
                        a[stem] = faults(r) / faults(cl); b[stem] = faults(ps_) / faults(cl); c[stem] = faults(r) / faults(ps_)
                if not a:
                    continue
                ra, rb, rc = pe.wmean(a)[0], pe.wmean(b)[0], pe.wmean(c)[0]
                w.writerow([name, fr, "+".join(m["train"]), "+".join(m["test"]), len(a), round(ra, 3), round(rb, 3), round(rc, 3)])
                print(f"{name} {fr}: {len(a)} unseen streams  split model {ra:.3f} of Clock, PageScore {rb:.3f}, split/PageScore {rc:.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("--fracs", default="0.1"); ap.add_argument("--lanes", type=int, default=6)
    a = ap.parse_args(); fr = a.fracs.split(",")
    {"build": build, "fit": fit, "run": lambda: run(fr, a.lanes), "report": lambda: report(fr)}[a.cmd]()
