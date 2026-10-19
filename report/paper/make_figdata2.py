#!/usr/bin/env python3
"""Figure data for the review revision (main2.tex), from report/results2; complements make_figdata.py (not changed).

  figures/data/cdf_<policy>.csv   per-stream faults / Clock at 10% memory, sorted, with the cumulative share of streams (Figure fig:dist)
  figures/data/kval_<size>.csv    validation streams: faults with k sampled pages / faults scoring every page (Figure fig:dist, right)
  figures/data/ci_body2.tex       Table tab:ci and figures/data/ci_full2.tex Table tab:ci-full: the rows of make_figdata.py's ci_body.tex
                                  and report_w16.py's ci_main.tex, bold only under the paper's claim rule (whole interval below 0.99)
  figures/data/breakeven_writes.tex  Table tab:breakeven: report_w16.py's breakeven_summary.tex counting write-backs too
  figures/data/sample_sizes.tex   Table tab:samples: instructions (cost_grid.csv) and faults relative to scoring every page
                                  (validation streams, simulator; sampling_val.csv via kval) for each sample size
  figures/data/w16/*.tex          the week-15/16 tables main2.tex inputs, with the policy's row labels renamed to PageScore
  figures/data/gains.csv          per-workload percent fewer faults than Clock at 10% (PageScore, ARC, LHD) for Figure fig:gains
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
                w.writerow([k, round(gm(gm(v) for v in by.values()), 6)])


NAME = {"arck": "ARC", "lhd": "LHD", "s3fifo": "S3-FIFO", "clock": "Clock", "lecar": "LeCaR", "ml:global": "PageScore, every page",
        "ml:global@32": "PageScore", "ml:global@16": "PageScore, 16 pages", "ml:cnn-all": "CNN", "ml:mlp-all": "deeper MLP",
        "ml:attention-all": "set-attention", "ml:trees-all": "boosted trees", "ml:ranktrees-all": "ranking trees"}
BODY_PAIRS = [("ml:global@32", "clock"), ("ml:global@32", "arck"), ("ml:global@32", "lhd"), ("ml:global@32", "ml:global"),
              ("arck", "clock")]           # the main comparisons only; every other row is in ci_full2.tex (appendix)
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
            line = [f"{NAME[a]} vs.\\ " + ("every page" if b == "ml:global" else NAME[b])] if name == "ci_body2.tex" else [f"{NAME[a]} against " + ("scoring every page" if b == "ml:global" else NAME[b])]
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
    for pol, n in [("ml:global", "PageScore, every page"), ("ml:global@32", "PageScore"),
                   ("ml:global@16", "PageScore, 16 pages"), ("arck", "ARC"), ("lhd", "LHD"), ("lecar", "LeCaR"), ("s3fifo", "S3-FIFO"),
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


RENAME = [("linear score, 32 sampled", "PageScore"), ("linear score, 16 sampled", "PageScore, 16 pages"),
          ("linear score, all pages", "PageScore, every page"), ("linear score, all candidates", "PageScore, every page"),
          ("linear, 32 sampled", "PageScore"), ("linear, 16 sampled", "PageScore, 16 pages"), ("linear, global", "PageScore, every page"),
          ("linear score faults", "PageScore (every page) faults"), ("linear score break-even", "PageScore (every page) break-even"),
          ("linear kv K+", "linear score, kv weights"), ("linear F+K", "linear score, F+K"), ("linear K+", "linear score"),
          ("linear K", "linear score"),     # simulator tables: the linear score over every page, not PageScore's 32 samples
          ("CNN on aging bits", "CNN"), ("trained on all workloads", "trained on all six"), ("none (what every run used)", "none (the old code)"),
          ("& linear &", "& PageScore, every page &"), ("& 32 sampled & 16 sampled", "& PageScore & PageScore, 16 pages")]


def renamed_tables():
    """Copies of the generated week-15/16 tables main2.tex inputs, with the policy called PageScore."""
    W16 = HERE.parents[0] / "week_16_update" / "tables"
    W15 = HERE.parents[0] / "week_15_update" / "tables"
    dst = OUT / "w16"; dst.mkdir(exist_ok=True)
    names = sorted(set(__import__("re").findall(r"\\wsixteen/([A-Za-z0-9_]+)", (HERE / "main2.tex").read_text())))
    for n in names:
        src = W16 / f"{n}.tex"
        text = src.read_text()
        for a, b in RENAME:
            text = text.replace(a, b)
        (dst / f"{n}.tex").write_text(text)
    print("renamed copies:", ", ".join(names))


def sample_sizes():
    """Cost and faults of each sample size: instructions from cost_grid.csv, faults from the validation k-curve."""
    cost = {}
    for r in csv.DictReader(open(R / "cost_grid.csv")):
        if r["policy"] == "ml" and r["model"].startswith("global") and "-" not in r["model"]:
            cost[(r["model"], int(r["frames"]))] = int(r["select_instructions_per_eviction"])
    kv = {}
    for fr, name in (("0.05", "05"), ("0.1", "10"), ("0.2", "20")):
        for row in csv.DictReader(open(OUT / f"kval_{name}.csv")):
            kv[(int(row["k"]), fr)] = float(row["ratio"])
    body = []
    for k in (4, 8, 16, 32, 64, None):
        m = f"global@{k}" if k else "global"
        cells = [f"{cost[(m, n)]:,}".replace(",", "\\,") for n in (64, 512, 820)]
        f = [f"{kv[(k, fr)]:.3f}" if k else "1" for fr in ("0.05", "0.1", "0.2")]
        body.append([str(k) if k else "every page"] + cells + f)
    head = ["\\begin{tabular}{lrrrrrr}", "\\toprule",
            " & \\multicolumn{3}{c}{instructions} & \\multicolumn{3}{c}{faults vs.\\ every page} \\\\",
            "\\cmidrule(lr){2-4}\\cmidrule(l){5-7}",
            "pages scored & 68 & 516 & 824 & 5\\% & 10\\% & 20\\% \\\\", "\\midrule"]
    lines = head + [" & ".join(r) + " \\\\" for r in body] + ["\\bottomrule", "\\end{tabular}", ""]
    (OUT / "sample_sizes.tex").write_text("\n".join(lines), encoding="utf-8")
    print("sample_sizes.tex", len(body), "rows")


def workload_gains():
    """Per-workload gain over Clock at 10% memory (percent fewer faults), PageScore against ARC and LHD, from the renamed
    kmain_A_01 table, for the coloured bar diagram (figures/data/gains.csv)."""
    rows = {}
    head = None
    for line in (OUT / "w16" / "kmain_A_01.tex").read_text().split("\n"):
        cells = [c.strip().rstrip("\\").strip() for c in line.split("&")]
        if cells[0] == "policy":
            head = cells
        elif head and len(cells) == len(head):
            rows[cells[0]] = dict(zip(head, cells))
    trained = ["btree", "graph", "kv", "lzw", "matmul", "sort"]
    unseen = ["kv-T", "heap", "join", "spmv", "chase", "bloom", "pat", "app"]
    with open(OUT / "gains.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pos", "workload", "group", "ours", "ours_pos", "ours_neg", "arc", "lhd"])
        pos = 0
        for group, names in (("trained", trained), ("unseen", unseen)):
            for n in names:
                g = round(100 * (1 - float(rows["PageScore"][n])), 1)
                w.writerow([pos, n, group, g, max(g, 0), min(g, 0), round(100 * (1 - float(rows["ARC"][n])), 1),
                            round(100 * (1 - float(rows["LHD"][n])), 1)])
                pos += 1
            pos += 0.6     # a gap between the two groups
    print("gains.csv written")


def sampling_kernel_table():
    """report_w16.py's sampling_kernel.tex with three-decimal intervals (two decimals put 0.999 outside [1.00, 1.00]) and the
    paper's bold rule (whole interval below 0.99); written over the renamed copy in figures/data/w16/."""
    d = {(r["fraction"], r["policy"], r["against"]): r for r in csv.DictReader(open(R / "kernel_ci_classic.csv"))}

    def cell(a, b):
        r = d.get(("0.1", a, b))
        if not r:
            return "--"
        lo, hi = float(r["ci95_low"]), float(r["ci95_high"])
        c = f"{float(r['faults_ratio']):.3f} [{lo:.3f}, {hi:.3f}]"
        return f"\\best{{{c}}}" if hi < 0.99 else c
    body = []
    for k in ("32", "16"):
        for suf, name in (("", "random"), ("n", "the quarter newest, rest random"), ("s", "evenly spread over the load order")):
            m = f"ml:global@{k}{suf}"
            body.append([f"{k} pages, {name}", cell(m, "ml:global"), cell(m, "clock"), cell(m, f"ml:global@{k}") if suf else "--"])
    (OUT / "w16" / "sampling_kernel.tex").write_text(table(["which pages", "vs every page", "vs Clock", "vs random, same number"], body), encoding="utf-8")
    print("sampling_kernel.tex (three-decimal intervals)")


def tradeoff_labels():
    """Figure fig:tradeoff reads the policy's point from tradeoff_linear.csv (make_figdata.py, label "linear"); main2.tex
    uses this copy with the label PageScore, so main.tex is unchanged."""
    src = (OUT / "tradeoff_linear.csv").read_text().split("\n")
    out = [src[0]] + [l.replace(",linear,", ",PageScore,") for l in src[1:]]
    (OUT / "tradeoff_linear2.csv").write_text("\n".join(out))
    heavy = (OUT / "tradeoff_heavy.csv").read_text()      # CNN and set-attention sit almost on top of each other: label CNN below
    heavy = heavy.replace("1936230,0.914,CNN,east,-3,0,14", "1936230,0.914,CNN,north,0,-3,14").replace("1801153,0.907,set-attn.,south,0,3,14", "1801153,0.907,set-attention,south,0,3,14")
    (OUT / "tradeoff_heavy2.csv").write_text(heavy)


if __name__ == "__main__":
    cdf()
    kval()
    ci_tables()
    breakeven_writes()
    sample_sizes()
    renamed_tables()
    workload_gains()
    sampling_kernel_table()
    tradeoff_labels()
