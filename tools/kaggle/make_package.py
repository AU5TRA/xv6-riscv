#!/usr/bin/env python3
"""Split the remaining kernel runs of stage 2 over this machine and four Kaggle notebooks, and build the package.

    python3 tools/kaggle/make_package.py   -> kaggle_package/ (tarball, notebook_1..4.py, README.txt, local_resume.sh)

Work items are streams ("standard": 4 policies + global + own linear model, "nets": the five extra models) at 5% and
20% memory, plus a group of short patbench/appbench runs. Each item's cost is the measured run time of the same
runs at 10% memory. Items are placed greedily on the bin with the least work per lane. Runs that are already done
(report/results2/kernel_eval_w16e.csv / w16f.csv) are not counted and are copied into each notebook's output file,
so nothing is repeated. The cost measurements stay on this machine (their instruction counts depend on the
compiler version).
"""
import csv
import collections
import json
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PK = ROOT / "kaggle_package"
R = ROOT / "report" / "results2"
NETS = "cnn-kv,attention-graph,mlp-kv,ranktrees-graph,trees-kv"
NETS_REPS = "btree-mixed-s5,kv-A-s5,kv-T17-s1,sort-n40000-s3,matmul-blocked128-s1,heap-small-s1,join-zipf-s1,spmv-band-s1,chase-tree-s1,bloom-k7-s1".split(",")
PATAPP = "pat-zipf099-s5,pat-phase-s5,pat-scanhot-s5,pat-loop-s5,pat-uniform-s5,app-chase-s1,app-spmv-s1,app-hashjoin-s1,app-bloom-s1".split(",")
LANES = {"local": 6, "k1": 4, "k2": 4, "k3": 4, "k4": 4}


def costs():
    wall = {}
    for f in ("kernel_eval.csv", "kernel_eval_w16.csv", "kernel_eval_w16b.csv", "kernel_eval_w16c.csv", "kernel_eval_w16d.csv"):
        for r in csv.DictReader(open(R / f)):
            if r["status"] == "ok" and r["fraction"] == "0.1" and r["wall_s"]:
                wall[(r["stem"], r["policy"], r["model"])] = float(r["wall_s"])
    done = set()
    for f in ("kernel_eval_w16e.csv", "kernel_eval_w16f.csv"):
        for r in csv.DictReader(open(R / f)):
            if r["status"] == "ok":
                done.add((r["stem"], r["fraction"], r["policy"], r["model"]))
    reps = (R / "stage2_streams.txt").read_text().strip().split(",")
    items = {}
    for s in reps:
        own = "kv" if s.startswith("kv-T") else s.split("-")[0]
        h = 0.0
        for fr in ("0.05", "0.2"):
            for p, m in [("fifo", ""), ("clock", ""), ("aging", ""), ("lfu", ""), ("ml", "global"), ("ml", own)]:
                if (s, fr, p, m) not in done and (s, p, m) in wall:
                    h += wall[(s, p, m)] / 3600 / 1.4
        if h:
            items[("standard", s)] = h
    for s in NETS_REPS:
        h = 0.0
        for fr in ("0.05", "0.2"):
            for m in NETS.split(","):
                if (s, fr, "ml", m) not in done and (s, "ml", m) in wall:
                    h += wall[(s, "ml", m)] / 3600 / 1.4
        if h:
            items[("nets", s)] = h
    return items


def main():
    items = costs()
    patapp_h = 6.6   # 9 short streams x 11 policies x 2 sizes, about 2 minutes each (measured at 10%)
    bins = {n: {"lanes": l, "work": 0.0, "standard": [], "nets": [], "patapp": False} for n, l in LANES.items()}
    bins["k4"]["work"] += patapp_h
    bins["k4"]["patapp"] = True
    bins["local"]["work"] += 6.0       # the cost measurements run here
    for (kind, s), h in sorted(items.items(), key=lambda kv: -kv[1]):
        b = min(bins.values(), key=lambda b: b["work"] / b["lanes"])
        b["work"] += h
        b[kind].append(s)
    for n, b in bins.items():
        print(f"{n:6s} {b['lanes']} lanes, {b['work']:5.1f} lane-h -> about {b['work'] / b['lanes']:.1f} h; standard {len(b['standard'])} streams, nets {len(b['nets'])}, pat/app {b['patapp']}")
    PK.mkdir(exist_ok=True)
    # tarball: sources only
    out = PK / "xv6_package.tar.gz"
    skip_ext = {".o", ".d", ".asm", ".sym", ".img", ".pyc"}
    def keep(ti):
        n = ti.name
        if "__pycache__" in n or Path(n).suffix in skip_ext or n.endswith("/kernel/kernel") or "/user/_" in n or n.endswith("fs.img"):
            return None
        return ti
    with tarfile.open(out, "w:gz") as t:
        for p in ("Makefile", "kernel", "user", "mkfs", "tools/ml2/kernel_eval.py", "tools/run_xv6_tests.py", "tools/extract_file.py",
                  "tools/streams_manifest.tsv", "README", "corpus.txt", "corpus1.txt", "corpus2.txt", "corpus3.txt", "corpus4.txt", "corpus5.txt"):
            if (ROOT / p).exists():
                t.add(ROOT / p, arcname=f"xv6/{p}", filter=keep)
        t.add(ROOT / "traces2/ML/index.json", arcname="xv6/traces2/ML/index.json")
        for f in ("kernel_eval_w16e.csv", "kernel_eval_w16f.csv"):
            t.add(R / f, arcname=f"xv6/start_{f}")
    print("package", out, round(out.stat().st_size / 1e6, 1), "MB")
    # expected value for the self test
    exp = None
    for r in csv.DictReader(open(R / "kernel_eval_w16.csv")):
        if r["stem"] == "kv-A-s5" and r["fraction"] == "0.1" and r["policy"] == "clock" and r["status"] == "ok":
            exp = {"stem": "kv-A-s5", "faults": int(r["swap_faults"]) + int(r["zero_faults"]), "frames": int(r["frames"])}
    json.dump({"selftest": exp, "bins": {n: {k: v for k, v in b.items() if k in ("standard", "nets", "patapp")} for n, b in bins.items()}},
              open(PK / "plan.json", "w"), indent=1)
    tpl = (Path(__file__).parent / "notebook_template.py").read_text()
    for i in (1, 2, 3, 4):
        b = bins[f"k{i}"]
        cfg = json.dumps({"id": i, "standard": b["standard"], "nets": b["nets"], "patapp": b["patapp"], "selftest": exp}, indent=1)
        (PK / f"notebook_{i}.py").write_text(tpl.replace("__CONFIG__", cfg))
    loc = bins["local"]
    sh = ["#!/bin/bash", "# restart the local jobs on this machine's share only (finished runs are skipped)",
          "cd /home/gawwy/Thesis/xv6-riscv/tools/ml2 || exit 1", "PY=~/.venvs/xv6ml/bin/python", "LOG=${LOG:-/tmp}"]
    if loc["standard"]:
        sh.append(f'KERNEL_EVAL_OUT=kernel_eval_w16e.csv KERNEL_EVAL_LANES=/tmp/xv6E nohup $PY -u kernel_eval.py --lanes 3 --fracs 0.05,0.2 --only "{",".join(loc["standard"])}" --splits test,heldout --nonml fifo,clock,aging,lfu --models global,own > $LOG/local_standard.log 2>&1 &')
    if loc["nets"]:
        sh.append(f'KERNEL_EVAL_OUT=kernel_eval_w16f.csv KERNEL_EVAL_LANES=/tmp/xv6F nohup $PY -u kernel_eval.py --lanes 3 --fracs 0.05,0.2 --only "{",".join(loc["nets"])}" --splits test,heldout --models {NETS} > $LOG/local_nets.log 2>&1 &')
    (PK / "local_resume.sh").write_text("\n".join(sh) + "\n")


if __name__ == "__main__":
    main()
