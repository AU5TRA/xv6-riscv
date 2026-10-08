#!/usr/bin/env python3
"""Zoo vs the rest: faults / Clock (geo-mean, censored at 3x Clock) per scope and evaluation group,
on the cells every listed system has. Writes report/results2/zoo_summary.csv.

    python3 zoo_report.py
"""
import csv
import math

import numpy as np
from collections import defaultdict

import zoo_core as Z
import zoo_trees as T
import pagesim as ps

R = Z.R
GROUPS = {"test": lambda r: r["split"] == "test", "held-out": lambda r: r["split"] == "heldout" and not r["stem"].startswith(("pat", "kv-T", "redis", "sqlite", "app-")),
          "pat": lambda r: r["stem"].startswith("pat"), "kv-T": lambda r: r["stem"].startswith("kv-T"),
          "real": lambda r: r["stem"].startswith(("redis", "sqlite")),
          "app": lambda r: r["stem"].startswith("app-")}
NN = {"deep", "setctx", "cnnmlp", "lstmmlp", "agecnn", "setcnn"}


def gather():
    sysf = defaultdict(dict)      # (system, scope) -> {(stem, frac): faults}
    meta = {}                     # stem -> split
    for r in csv.DictReader(open(R / "classical.csv")):
        meta[r["stem"]] = r["split"]
        if r["policy"] in ("clock", "lru", "belady"):
            sysf[(r["policy"], "*")][(r["stem"], r["fraction"])] = int(r["faults"])
    for r in csv.DictReader(open(R / "baselines_ext.csv")):
        if r["policy"] in ("arc", "s3fifo", "lhd"):
            sysf[(r["policy"], "*")][(r["stem"], r["fraction"])] = int(r["faults"])
    for f in ("transfer.csv", "transfer_real.csv", "transfer_app.csv"):
        for r in csv.DictReader(open(R / f)):
            if r["model"] in ("clock", "lru", "belady", "arc", "s3fifo", "lhd"):
                sysf[(r["model"], "*")][(r["stem"], r["fraction"])] = int(r["faults"])
            elif r["model"].startswith("linear:"):
                sc, g = r["model"][7:].split("|")
                sysf[(f"lin-{g}", sc)][(r["stem"], r["fraction"])] = int(r["faults"])
    for r in csv.DictReader(open(R / "final_test.csv")):
        sysf[(f"lin-{r['group']}", r["scope"])][(r["stem"], r["fraction"])] = int(r["faults"])
    return sysf, meta


def main():
    sysf, meta = gather()
    cells = list(csv.DictReader(open(Z.CELLS)))
    split_of = {r["stem"]: r["split"] for r in cells}
    out = []
    for scope in T.SCOPES:
        systems = {k[0]: v for k, v in sysf.items() if k[1] in ("*", scope)}
        for cls, is_nn, kern in (("zoo-trees", False, False), ("zoo-nn", True, False),
                                 ("zooK-trees", False, True), ("zooK-nn", True, True), ("zooKF-nn", True, "kf"), ("zooS-trees", False, "small")):
            cand = sorted((v, nm) for fam, (v, nm, pa) in T.best(scope).items()
                          if (nm.split(".")[1] in NN) == is_nn
                          and (not kern or (nm.split(".")[2] == "K" and nm.split(".")[1] in ("deep", "setctx", "agecnn") if kern == "kf"
                                            else nm.split(".")[2] in ("K", "Kr") and nm.split(".")[3].startswith(("trees4-", "trees8-", "trees16-"))
                                            if kern == "small" else nm.split(".")[2] in ("K", "Kr"))))
            if cand:
                nm = cand[0][1]
                systems[f"{cls}:{nm.split('.', 1)[1]}"] = {(r["stem"], r["fraction"]): int(r["faults"])
                                                           for r in cells if r["model"] == f"{nm}|pa2"}
        rows = {}
        for g, pred in GROUPS.items():
            ok = [(s, f) for (s, f) in systems["clock"]
                  if pred({"stem": s, "split": split_of.get(s, meta.get(s, "")) or meta.get(s, "")})]
            ok = [c for c in ok if c[0] in split_of or True]
            for name, d in systems.items():
                cs = [c for c in ok if c in d]
                if name.startswith("zoo") or name.startswith("lin"):
                    pass
                rows.setdefault(name, {})[g] = (cs, d)
        for g in GROUPS:
            zoo_names = [n for n in rows if n.startswith("zoo")]
            if not zoo_names or not rows[zoo_names[0]][g][0]:
                continue
            common = set(rows[zoo_names[0]][g][0])
            for n in rows:
                if n.startswith(("zoo", "lin-K+", "lin-any", "lru", "arc", "lhd", "s3fifo", "belady")) and rows[n][g][0]:
                    common &= set(rows[n][g][0])
            if not common:
                continue
            for n in rows:
                d = rows[n][g][1]
                if not all(c in d for c in common):
                    continue
                v = [min(d[c], 3 * systems["clock"][c]) / systems["clock"][c] for c in common]
                out.append([scope, g, n, round(math.exp(sum(math.log(max(x, 1e-9)) for x in v) / len(v)), 4), len(common)])
            ref = rows.get("lin-K+K+") or rows.get("lin-any")
            for n in zoo_names:       # paired stem-level bootstrap of the zoo model vs the best linear model
                refname = "lin-any" if ".FK" in n else "lin-K+K+"      # compare like with like: oracle features vs the best linear on any tier
                d, dl = rows[n][g][1], sysf[(refname, scope)]
                if not all(c in dl and c in d for c in common):
                    continue
                by = defaultdict(list)
                for c in common:
                    by[c[0]].append(math.log(max(min(d[c], 3 * systems["clock"][c]), 1) / max(min(dl[c], 3 * systems["clock"][c]), 1)))
                stems_ = list(by)
                rng = np.random.default_rng(1)
                bs = sorted(math.exp(np.mean([x for i in rng.integers(0, len(stems_), len(stems_)) for x in by[stems_[i]]]))
                            for _ in range(500))
                out.append([scope, g, n + " / " + refname, round(math.exp(np.mean([x for v_ in by.values() for x in v_])), 4),
                            f"CI95 {bs[12]:.3f}-{bs[487]:.3f}"])
    with open(R / "zoo_summary.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["scope", "group", "system", "geo_ratio_vs_clock", "cells"]); w.writerows(out)
    show = ["lru", "arc", "s3fifo", "lhd", "belady", "lin-K+K+", "lin-any", "lin-F"]
    for scope in T.SCOPES:
        sub = [r for r in out if r[0] == scope]
        if not sub:
            continue
        print(f"\n== {scope}")
        gs = [g for g in GROUPS if any(r[1] == g for r in sub)]
        print(f"{'system':44s}" + "".join(f"{g:>10s}" for g in gs))
        names = [n for n in dict.fromkeys(r[2] for r in sub) if n in show or n.startswith("zoo")]
        for r in sub:
            if "/ lin" in r[2]:
                print(f"  {r[1]:9s} {r[2][:52]:54s} ratio {r[3]:.3f}  {r[4]}")
        for n in names:
            if "/ lin" in n:
                continue
            print(f"{n[:43]:44s}" + "".join(f"{next((r[3] for r in sub if r[1] == g and r[2] == n), float('nan')):10.3f}" for g in gs))


if __name__ == "__main__":
    main()
