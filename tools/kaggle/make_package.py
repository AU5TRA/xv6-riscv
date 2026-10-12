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
_argv = __import__("sys").argv
if "--round" in _argv:
    PK = ROOT / "kaggle_package" / f"round{_argv[_argv.index('--round') + 1]}"
    if (PK / "xv6_package.tar.gz").exists():
        raise SystemExit(f"{PK} already holds a package; use a new --round number (older rounds are never overwritten)")
    PK.mkdir(parents=True, exist_ok=True)
    if not (PK / "plan.json").exists():          # the self-test expectation, from the newest earlier round
        shutil.copy(sorted((ROOT / "kaggle_package").glob("round*/plan.json"))[-1], PK / "plan.json")
R = ROOT / "report" / "results2"
NETS = "cnn-kv,attention-graph,mlp-kv,ranktrees-graph,trees-kv"
NETS_REPS = "btree-mixed-s5,kv-A-s5,kv-T17-s1,sort-n40000-s3,matmul-blocked128-s1,heap-small-s1,join-zipf-s1,spmv-band-s1,chase-tree-s1,bloom-k7-s1".split(",")
PATAPP = "pat-zipf099-s5,pat-phase-s5,pat-scanhot-s5,pat-loop-s5,pat-uniform-s5,app-chase-s1,app-spmv-s1,app-hashjoin-s1,app-bloom-s1".split(",")
LANES = {"local": 6, "k1": 4, "k2": 4, "k3": 4, "k4": 4}
NETS_ALL = "cnn-all,attention-all,mlp-all,ranktrees-all,trees-all"
OLD_NAME = {"cnn-all": "cnn-kv", "attention-all": "attention-graph", "mlp-all": "mlp-kv", "ranktrees-all": "ranktrees-graph", "trees-all": "trees-kv"}


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


KAGGLE_SLOWDOWN = 3.1    # measured: 180 runs repeated here vs on Kaggle, median Kaggle wall / local wall (quartiles 2.9-3.2)


def costs_nets_all(skip=()):
    """5% / 20% runs of the five all-workloads models on the ten streams of the per-workload models (minus `skip`). Cost of one
    (stream, memory size) item = the five runs, at Kaggle speed: the wall time of the corresponding per-workload model measured on Kaggle,
    else this machine's wall time times KAGGLE_SLOWDOWN, else 3 hours (it timed out on Kaggle)."""
    kag, loc = {}, {}
    for f in R.glob("kaggle_*.csv"):
        for r in csv.DictReader(open(f)):
            if r["status"] == "ok" and r["wall_s"] and r["model"] in OLD_NAME.values():
                kag[(r["stem"], r["fraction"], r["model"])] = float(r["wall_s"])
    for f in [R / "kernel_eval_all.csv"] + sorted(R.glob("kernel_eval_w16*.csv")):
        for r in csv.DictReader(open(f)):
            if r["status"] == "ok" and r["wall_s"] and r["model"] in OLD_NAME.values():
                loc.setdefault((r["stem"], r["fraction"], r["model"]), float(r["wall_s"]))
    done = set()
    for f in R.glob("kaggle_*_netsall.csv"):
        done |= {(r["stem"], r["fraction"], r["model"]) for r in csv.DictReader(open(f)) if r["status"] == "ok"}
    items = {}
    for st in NETS_REPS:
        if st in skip:
            continue
        for fr in ("0.05", "0.2"):          # one item per (stream, memory size) so the notebooks balance
            if f"{st}@{fr}" in skip:        # "stream@fraction" skips just that size (it runs on the thesis PC instead)
                continue
            h = 0.0
            for new, old in OLD_NAME.items():
                if (st, fr, new) in done:
                    continue
                k = (st, fr, old)
                if k in kag and not (k in loc and abs(loc[k] - kag[k]) < 1e-9):
                    w = kag[k]
                elif k in loc:
                    w = loc[k] * KAGGLE_SLOWDOWN
                else:
                    w = 3 * 3600.0
                h += w / 3600
            if h:
                items[("netsall", (st, fr))] = h
    return items


def main_nets_all():
    skip = ()
    if "--skip" in __import__("sys").argv:
        skip = tuple(__import__("sys").argv[__import__("sys").argv.index("--skip") + 1].split(","))
    items = costs_nets_all(skip)
    bins = {n: {"lanes": 4, "work": 0.0, "netsall": []} for n in ("k1", "k2", "k3", "k4")}
    for (kind, st), h in sorted(items.items(), key=lambda kv: -kv[1]):
        b = min(bins.values(), key=lambda b: b["work"] / b["lanes"])
        b["work"] += h
        b["netsall"].append(st)
    for n, b in bins.items():
        print(f"{n} {b['lanes']} lanes, {b['work']:5.1f} lane-h at Kaggle speed -> at least {b['work'] / b['lanes']:.1f} h; {len(b['netsall'])} items")
    PK.mkdir(exist_ok=True)
    out = PK / "xv6_package.tar.gz"
    skip_ext = {".o", ".d", ".asm", ".sym", ".img", ".pyc"}
    def keep(ti):
        n = ti.name
        if "__pycache__" in n or Path(n).suffix in skip_ext or n.endswith("/kernel/kernel") or "/user/_" in n or n.endswith("fs.img") or n.endswith("/mkfs/mkfs"):
            return None
        return ti
    with tarfile.open(out, "w:gz") as t:
        for p in ("Makefile", "kernel", "user", "mkfs", "tools/ml2/kernel_eval.py", "tools/run_xv6_tests.py", "tools/extract_file.py",
                  "tools/streams_manifest.tsv", "README", "corpus.txt", "corpus1.txt", "corpus2.txt", "corpus3.txt", "corpus4.txt", "corpus5.txt"):
            if (ROOT / p).exists():
                t.add(ROOT / p, arcname=f"xv6/{p}", filter=keep)
        t.add(ROOT / "traces2/ML/index.json", arcname="xv6/traces2/ML/index.json")
    exp = json.load(open(PK / "plan.json"))["selftest"]
    tpl = (Path(__file__).parent / "notebook_template.py").read_text()
    for i in (1, 2, 3, 4):
        cfg = json.dumps({"id": i, "standard": [], "nets": [], "patapp": False, "netsall": [list(x) for x in bins[f"k{i}"]["netsall"]], "selftest": exp}, indent=1)
        (PK / f"notebook_{i}.py").write_text(tpl.replace("__CONFIG__", cfg))
    print("package", out, round(out.stat().st_size / 1e6, 1), "MB; notebooks rewritten for the all-workloads models")


def costs_classic(skip=()):
    """5% / 20% runs of ARC, S3-FIFO and LHD (round 3). One item = one (stream, memory size) = three runs, each costed like the Clock run of the
    same cell: Kaggle's own wall time if it ran there, else this machine's times KAGGLE_SLOWDOWN."""
    kag, loc, short = {}, {}, set()
    for f in R.glob("kaggle_*.csv"):
        for r in csv.DictReader(open(f)):
            if r["status"] == "ok" and r["wall_s"] and r["policy"] == "clock":
                kag[(r["stem"], r["fraction"])] = float(r["wall_s"])
    for f in [R / "kernel_eval_all.csv"] + sorted(R.glob("kernel_eval_w16*.csv")):
        for r in csv.DictReader(open(f)):
            if r["status"] == "ok" and r["wall_s"] and r["policy"] == "clock":
                loc.setdefault((r["stem"], r["fraction"]), float(r["wall_s"]))
                if r["accesses"]:
                    short.add(r["stem"])
    done = set()
    for f in R.glob("kaggle_*_classic.csv"):
        done |= {(r["stem"], r["fraction"], r["policy"]) for r in csv.DictReader(open(f)) if r["status"] == "ok"}
    items = {}
    for (st, fr), w in loc.items():
        if fr not in ("0.05", "0.2") or f"{st}@{fr}" in skip or st in skip:
            continue
        w = kag.get((st, fr), w * KAGGLE_SLOWDOWN)
        n = sum((st, fr, p) not in done for p in ("arck", "s3fifo", "lhd"))
        if n:
            items[("classic", (st, fr))] = (w * n / 3600, w / 3600)
    return items, short


def main_classic():
    argv = __import__("sys").argv
    skip = tuple(argv[argv.index("--skip") + 1].split(",")) if "--skip" in argv else ()
    items, short = costs_classic(skip)
    bins = {n: {"lanes": 4, "work": 0.0, "classic": []} for n in ("k1", "k2", "k3", "k4")}
    for (kind, st), (h, one) in sorted(items.items(), key=lambda kv: -kv[1][0]):
        b = min(bins.values(), key=lambda b: b["work"] / b["lanes"])
        b["work"] += h
        b["classic"].append(st)
    for n, b in bins.items():
        print(f"{n} {b['lanes']} lanes, {b['work']:5.1f} lane-h at Kaggle speed -> at least {b['work'] / b['lanes']:.1f} h; {len(b['classic'])} items")
    print("longest single runs (h, Kaggle speed):", sorted(((round(o, 1), k[1]) for k, (h, o) in items.items()), reverse=True)[:6])
    PK.mkdir(exist_ok=True)
    out = PK / "xv6_package.tar.gz"
    skip_ext = {".o", ".d", ".asm", ".sym", ".img", ".pyc"}
    def keep(ti):
        n = ti.name
        if "__pycache__" in n or Path(n).suffix in skip_ext or n.endswith("/kernel/kernel") or "/user/_" in n or n.endswith("fs.img") or n.endswith("/mkfs/mkfs"):
            return None
        return ti
    with tarfile.open(out, "w:gz") as t:
        for p in ("Makefile", "kernel", "user", "mkfs", "tools/ml2/kernel_eval.py", "tools/run_xv6_tests.py", "tools/extract_file.py",
                  "tools/streams_manifest.tsv", "README", "corpus.txt", "corpus1.txt", "corpus2.txt", "corpus3.txt", "corpus4.txt", "corpus5.txt"):
            if (ROOT / p).exists():
                t.add(ROOT / p, arcname=f"xv6/{p}", filter=keep)
        t.add(ROOT / "traces2/ML/index.json", arcname="xv6/traces2/ML/index.json")
    exp = json.load(open(PK / "plan.json"))["selftest"]
    tpl = (Path(__file__).parent / "notebook_template.py").read_text()
    for i in (1, 2, 3, 4):
        cfg = json.dumps({"id": i, "standard": [], "nets": [], "patapp": False, "classic": [list(x) for x in bins[f"k{i}"]["classic"]],
                          "short": sorted(short), "selftest": exp}, indent=1)
        (PK / f"notebook_{i}.py").write_text(tpl.replace("__CONFIG__", cfg))
    print("package", out, round(out.stat().st_size / 1e6, 1), "MB; notebooks rewritten for ARC / S3-FIFO / LHD")


MORE_NONML = "fifo,clock,aging,lfu,arck,s3fifo,lhd"
MORE_POLICIES = MORE_NONML.split(",") + ["ml:global"]


def costs_more(skip=()):
    """Streams that ran at 10% memory but not at 5% or 20% (51 of 74 streams were run at 5% and 20%): the eight policies (the seven
    without a model and the global linear score) on each missing (stream, memory size). Cost of one item = eight runs, each costed like the Clock run of the
    same stream at 10% (this machine's wall time times KAGGLE_SLOWDOWN, times 1.5 for 5% memory, which evicts more)."""
    loc, short, have = {}, set(), set()
    for f in [R / "kernel_eval_all.csv"]:
        for r in csv.DictReader(open(f)):
            if r["status"] != "ok":
                continue
            if r["policy"] == "clock":
                have.add((r["stem"], r["fraction"]))
                if r["fraction"] == "0.1" and r["wall_s"]:
                    loc[r["stem"]] = float(r["wall_s"])
                if r["accesses"]:
                    short.add(r["stem"])
    done = set()
    for f in R.glob("kaggle_*_more.csv"):
        done |= {(r["stem"], r["fraction"], r["policy"] + (":" + r["model"] if r["model"] else "")) for r in csv.DictReader(open(f)) if r["status"] == "ok"}
    items = {}
    for st, w in loc.items():
        for fr in ("0.05", "0.2"):
            if (st, fr) in have or f"{st}@{fr}" in skip or st in skip:
                continue
            n = sum((st, fr, p) not in done for p in MORE_POLICIES)
            if n:
                one = w * KAGGLE_SLOWDOWN * (1.5 if fr == "0.05" else 1.0)
                items[("more", (st, fr))] = (one * n / 3600, one / 3600)
    return items, short


def main_more():
    argv = __import__("sys").argv
    skip = tuple(argv[argv.index("--skip") + 1].split(",")) if "--skip" in argv else ()
    items, short = costs_more(skip)
    # the thesis PC runs part of it: 6 lanes, each worth KAGGLE_SLOWDOWN Kaggle lanes (work is counted at Kaggle speed)
    bins = {n: {"lanes": 4, "work": 0.0, "more": []} for n in ("k1", "k2", "k3", "k4")}
    bins["local"] = {"lanes": 6 * KAGGLE_SLOWDOWN, "work": 0.0, "more": []}
    for (kind, st), (h, one) in sorted(items.items(), key=lambda kv: -kv[1][0]):
        b = min(bins.values(), key=lambda b: b["work"] / b["lanes"])
        b["work"] += h
        b["more"].append(st)
    for n, b in bins.items():
        print(f"{n} {b['lanes']:.1f} lanes, {b['work']:5.1f} lane-h at Kaggle speed -> at least {b['work'] / b['lanes']:.1f} h; {len(b['more'])} items")
    sh = ["#!/bin/bash", "# the thesis PC's share of this round (resumable); results in report/results2/kernel_eval_more.csv", "cd \"$(dirname \"$0\")/../../tools/ml2\"",
          "export KERNEL_EVAL_OUT=kernel_eval_more.csv KERNEL_EVAL_LANES=/tmp/xv6more", "PY=${PY:-python3}"]
    for fr in ("0.05", "0.2"):
        for is_short in (False, True):
            sts = [st + "$" for st, f in bins["local"]["more"] if f == fr and (st in short) == is_short]
            if sts:
                sh.append(f'$PY -u kernel_eval.py --lanes 6 --fracs {fr} {"--accesses 50000 " if is_short else ""}--only "{",".join(sts)}" --splits test,heldout --nonml {MORE_NONML} --models global --timeout 40000')
    (PK / "local_run.sh").write_text("\n".join(sh) + "\n")
    print("items", len(items), "runs", sum(8 for _ in items), "longest single run (h):", sorted(((round(o, 1), k[1]) for k, (h, o) in items.items()), reverse=True)[:5])
    out = PK / "xv6_package.tar.gz"
    skip_ext = {".o", ".d", ".asm", ".sym", ".img", ".pyc"}
    def keep(ti):
        n = ti.name
        if "__pycache__" in n or Path(n).suffix in skip_ext or n.endswith("/kernel/kernel") or "/user/_" in n or n.endswith("fs.img") or n.endswith("/mkfs/mkfs"):
            return None
        return ti
    with tarfile.open(out, "w:gz") as t:
        for p in ("Makefile", "kernel", "user", "mkfs", "tools/ml2/kernel_eval.py", "tools/run_xv6_tests.py", "tools/extract_file.py",
                  "tools/streams_manifest.tsv", "README", "corpus.txt", "corpus1.txt", "corpus2.txt", "corpus3.txt", "corpus4.txt", "corpus5.txt"):
            if (ROOT / p).exists():
                t.add(ROOT / p, arcname=f"xv6/{p}", filter=keep)
        t.add(ROOT / "traces2/ML/index.json", arcname="xv6/traces2/ML/index.json")
    exp = json.load(open(PK / "plan.json"))["selftest"]
    tpl = (Path(__file__).parent / "notebook_template.py").read_text()
    for i in (1, 2, 3, 4):
        cfg = json.dumps({"id": i, "standard": [], "nets": [], "patapp": False, "more": [list(x) for x in bins[f"k{i}"]["more"]],
                          "short": sorted(short), "selftest": exp}, indent=1)
        (PK / f"notebook_{i}.py").write_text(tpl.replace("__CONFIG__", cfg))
    print("package", out, round(out.stat().st_size / 1e6, 1), "MB; notebooks rewritten for the extra 5% / 20% streams")


def main():
    if "--more-streams" in __import__("sys").argv:
        return main_more()
    if "--classic" in __import__("sys").argv:
        return main_classic()
    if "--nets-all" in __import__("sys").argv:
        return main_nets_all()
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
        if "__pycache__" in n or Path(n).suffix in skip_ext or n.endswith("/kernel/kernel") or "/user/_" in n or n.endswith("fs.img") or n.endswith("/mkfs/mkfs"):
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
