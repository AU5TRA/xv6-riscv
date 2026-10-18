#!/usr/bin/env python3
"""Figure data for the review revision (main2.tex), from report/results2; complements make_figdata.py (not changed).

  figures/data/cdf_<policy>.csv   per-stream faults / Clock at 10% memory, sorted, with the cumulative share of streams (Figure fig:dist)
  figures/data/kval_<size>.csv    validation streams: faults with k sampled pages / faults scoring every page (Figure fig:dist, right)
  figures/data/ci_body2.tex       Table tab:ci and figures/data/ci_full2.tex Table tab:ci-full: the rows of make_figdata.py's ci_body.tex
                                  and report_w16.py's ci_main.tex, bold only under the paper's claim rule (whole interval below 0.99)
  figures/data/breakeven_writes.tex  Table tab:breakeven: report_w16.py's breakeven_summary.tex counting write-backs too
                                  (cost_benefit_with_writes_*.csv instead of the reads-only files)

    python3 make_figdata2.py
"""
import csv
import math
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
R = HERE.parents[1] / "report" / "results2"
OUT = HERE / "figures" / "data"


def gm(xs):
    xs = list(xs)
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def cdf():
    d = defaultdict(list)
    for r in csv.DictReader(open(R / "paper_extra_cdf.csv")):
        if r["fraction"] == "0.1":
            d[r["policy"]].append(float(r["ratio"]))
    for pol, name in (("ml:global@32", "policy"), ("arck", "arc"), ("lhd", "lhd")):
        v = sorted(d[pol])
        with open(OUT / f"cdf_{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ratio", "share"])
            w.writerow([round(min(v[0], 0.5), 4), 0])
            for i, x in enumerate(v, 1):
                w.writerow([round(min(x, 2.0), 4), round(i / len(v), 4)])     # clipped at 2 for the axis
        print(name, len(v), "streams; worse than Clock on", sum(x > 1.005 for x in v), "; better on", sum(x < 0.995 for x in v))


def kval():
    rows = list(csv.DictReader(open(R / "sampling_val.csv")))
    full = {(r["stem"], r["fraction"]): int(r["faults"]) for r in rows if r["variant"] == "full"}
    res = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["variant"] == "random":
            res[(int(r["k"]), r["fraction"])][r["stem"]].append(int(r["faults"]) / full[(r["stem"], r["fraction"])])
    for fr, name in (("0.05", "05"), ("0.1", "10"), ("0.2", "20")):
        with open(OUT / f"kval_{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["k", "ratio"])
            for k in sorted({k for k, f2 in res if f2 == fr}):
                by = defaultdict(list)
                for s, v in res[(k, fr)].items():
                    by[s.split("-")[0]].append(gm(v))
                w.writerow([k, round(gm(gm(v) for v in by.values()), 4)])


NAME = {"arck": "ARC", "lhd": "LHD", "s3fifo": "S3-FIFO", "clock": "Clock", "lecar": "LeCaR", "ml:global": "linear, global",
        "ml:global@32": "linear, 32 sampled", "ml:global@16": "linear, 16 sampled", "ml:cnn-all": "CNN", "ml:mlp-all": "deeper MLP",
        "ml:attention-all": "set-attention", "ml:trees-all": "boosted trees", "ml:ranktrees-all": "ranking trees"}
BODY_PAIRS = [("ml:global@32", "clock"), ("ml:global@32", "arck"), ("ml:global@32", "lecar"), ("ml:global@32", "ml:global"),
              ("ml:global", "clock"), ("ml:global", "arck"), ("arck", "clock"), ("lecar", "clock"),
              ("ml:cnn-all", "ml:global@32"), ("ml:mlp-all", "ml:global@32"), ("ml:attention-all", "ml:global@32"),
              ("ml:trees-all", "ml:global@32"), ("ml:ranktrees-all", "ml:global@32")]           # = make_figdata.py PAIRS
FULL_PAIRS = [("arck", "clock"), ("lhd", "clock"), ("s3fifo", "clock"), ("ml:global", "clock"), ("ml:global", "arck"), ("ml:global", "lhd"),
              ("lecar", "clock"), ("ml:global", "lecar"), ("ml:global@32", "clock"), ("ml:global@16", "clock"), ("ml:global@32", "ml:global"),
              ("ml:global@16", "ml:global"), ("ml:global@32", "arck"), ("ml:global@32", "lhd"), ("ml:global@32", "s3fifo"),
              ("ml:global@32", "lecar"), ("ml:cnn-all", "clock"), ("ml:mlp-all", "clock"), ("ml:cnn-all", "arck"), ("ml:mlp-all", "arck"),
              ("ml:attention-all", "arck"), ("ml:trees-all", "arck"), ("ml:cnn-all", "ml:global"), ("ml:mlp-all", "ml:global"),
              ("ml:attention-all", "ml:global"), ("ml:trees-all", "ml:global"), ("ml:ranktrees-all", "ml:global"),
              ("ml:cnn-all", "ml:global@32"), ("ml:mlp-all", "ml:global@32"), ("ml:attention-all", "ml:global@32"),
              ("ml:trees-all", "ml:global@32"), ("ml:ranktrees-all", "ml:global@32")]           # = report_w16.py ci_table pairs


def table(head, body):
    s = ["\\begin{tabular}{l" + "r" * (len(head) - 1) + "}", "\\toprule", " & ".join(head) + " \\\\", "\\midrule"]
    s += [" & ".join(r) + " \\\\" for r in body]
    return "\n".join(s + ["\\bottomrule", "\\end{tabular}", ""])


def ci_tables():
    """Interval tables with the claim rule of Setup/Metrics: a cell is bold only when its whole interval lies below 0.99
    (an interval that ends within 0.01 of 1 carries no claim)."""
    ci = {(r["policy"], r["against"], r["fraction"]): r for r in csv.DictReader(open(R / "kernel_ci_classic.csv"))}
    for pairs, name in ((BODY_PAIRS, "ci_body2.tex"), (FULL_PAIRS, "ci_full2.tex")):
        body, n_bold = [], 0
        for a, b in pairs:
            line = [f"{NAME[a]} against {NAME[b]}"]
            for fr in ("0.05", "0.1", "0.2"):
                r = ci.get((a, b, fr))
                if not r:
                    line.append("--")
                    continue
                cell = f"{float(r['faults_ratio']):.3f} [{float(r['ci95_low']):.2f}, {float(r['ci95_high']):.2f}]"
                bold = float(r["ci95_high"]) < 0.99
                n_bold += bold
                line.append(f"\\best{{{cell}}}" if bold else cell)
            body.append(line)
        (OUT / name).write_text(table(["comparison", "5\\% memory", "10\\% memory", "20\\% memory"], body), encoding="utf-8")
        print(name, len(body), "rows,", n_bold, "bold cells")


def breakeven_writes():
    """report_w16.py breakeven_summary.tex with write-backs charged too (SSD 22 us, disk 2,609 us per write)."""
    one = list(csv.DictReader(open(R / "cost_benefit_with_writes_1.0.csv")))
    own = list(csv.DictReader(open(R / "cost_benefit_with_writes_0.0472.csv")))
    body = []
    for pol, n in [("ml:global", "linear score, all candidates"), ("ml:global@32", "linear score, 32 sampled"),
                   ("ml:global@16", "linear score, 16 sampled"), ("arck", "ARC"), ("lhd", "LHD"), ("lecar", "LeCaR"), ("s3fifo", "S3-FIFO"),
                   ("ml:cnn-all", "CNN"), ("ml:mlp-all", "deeper MLP"), ("ml:attention-all", "set-attention"),
                   ("ml:trees-all", "boosted trees"), ("ml:ranktrees-all", "ranking trees")]:
        a = [r for r in one if r["policy"] == pol]
        b = [r for r in own if r["policy"] == pol]
        assert len(a) == 14 and len(b) == 14, pol
        cells = [gm(float(r[k]) for r in rs) for rs, k in ((a, "time_vs_clock_ssd"), (a, "time_vs_clock_hdd"),
                                                          (b, "time_vs_clock_ssd"), (b, "time_vs_clock_hdd"))]
        body.append([n, f"{gm(float(r['faults_over_clock']) for r in a):.3f}"] +
                    [f"\\best{{{c:.2f}}}" if c < 0.995 else f"{c:.2f}" for c in cells])
    (OUT / "breakeven_writes.tex").write_text(table(["policy", "faults / Clock", "SSD, 1 ns", "disk, 1 ns", "SSD, 0.047 ns",
                                                      "disk, 0.047 ns"], body), encoding="utf-8")
    print("breakeven_writes.tex", len(body), "rows")


if __name__ == "__main__":
    cdf()
    kval()
    ci_tables()
    breakeven_writes()
