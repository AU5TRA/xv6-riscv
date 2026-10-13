"""Write the data files the paper's plots read (pgfplots in main.tex).

    python make_figdata.py

Every plotted number comes from report/results2/*.csv; nothing is typed by hand.
Output: figures/data/*.csv and figures/data/tradeoff_labels.tex (re-run after the
result CSVs change; the files are small and committed with the paper).

  headroom.csv      Fig. 2: Belady and the classical policies against Clock, simulator,
                    geometric mean over 5/10/20% memory (summary_classical.csv; test
                    streams, matmul held-out because it has no test split).
  diagnostics.csv   Fig. 3: within-decision Spearman correlation of each feature with
                    the next-use label, per workload, plus the mean over the six
                    (feature_diagnostics.csv).
  tradeoff_*.csv    Fig. 7: instructions per decision against faults relative to Clock
                    at 10% memory (tradeoff.csv), one file per marker group.
  marginal.csv      Appendix figure: median change in faults when a kernel feature is
                    added to a subset that lacks it (summary_marginal.csv; per-workload
                    models, test streams, matmul held-out), as a percentage.
"""
import csv
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
RES = HERE.parent / "results2"
OUT = HERE / "figures" / "data"
OUT.mkdir(parents=True, exist_ok=True)

WORKLOADS = ["btree", "graph", "kv", "lzw", "matmul", "sort"]


def split_for(w):
    return "heldout" if w == "matmul" else "test"


def read(name):
    with open(RES / name, newline="") as f:
        return list(csv.DictReader(f))


def write(name, header, rows):
    with open(OUT / name, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


# ---- Fig. 2: headroom -------------------------------------------------------------
CLASSICAL = ["fifo", "aging", "lfu_kernel", "lru", "lfu_exact"]
XMAX = 1.5                       # axis limit; larger values are drawn at the edge
cls = {(r["policy"], r["workload"], r["split"]): float(r["geo_ratio_vs_clock"])
       for r in read("summary_classical.csv") if r["fraction"] == "all"}
rows_b, rows_c = [], []
for i, w in enumerate(WORKLOADS):
    s = split_for(w)
    b = cls[("belady", w, s)]
    best = min(cls[(p, w, s)] for p in CLASSICAL)
    # gap: from Belady to the best classical policy (the headroom no heuristic claims)
    rows_b.append([i, w, f"{b:.3f}", f"{best - b:.3f}", f"{b:.2f}"])
    for p in CLASSICAL:
        v = cls[(p, w, s)]
        rows_c.append([i, w, p, f"{min(v, XMAX):.3f}", int(v > XMAX), f"{v:.3f}"])
write("headroom_belady.csv", ["row", "workload", "ratio", "gap", "label"], rows_b)
hdr = ["row", "workload", "policy", "ratio", "clipped", "true_ratio"]
write("headroom_classical.csv", hdr, [r for r in rows_c if not r[4]])
write("headroom_clipped.csv", hdr, [r for r in rows_c if r[4]])     # drawn at the axis edge

# ---- Fig. 3: within-decision correlations ------------------------------------------
FEATURES = ["rec", "freq", "sd", "wr", "ref", "aging", "sfreq", "idle", "age", "dirty",
            "refaults", "rdist"]
rho = {(r["workload"], r["feature"]): float(r["within_decision_spearman"])
       for r in read("feature_diagnostics.csv")}
rows = []
for i, w in enumerate(WORKLOADS + ["mean"]):
    for j, f in enumerate(FEATURES):
        v = (sum(rho[(x, f)] for x in WORKLOADS) / len(WORKLOADS) if w == "mean"
             else rho[(w, f)])
        # mean row labelled, without the leading zero so 12 labels fit one column width
        lab = (f"{v:.2f}".replace("0.", ".", 1) if w == "mean" and abs(v) >= 0.1 else "")
        rows.append([j, i, f"{v:.3f}", f"${lab}$" if lab else ""])
write("diagnostics.csv", ["col", "row", "rho", "label"], rows)

# ---- Fig. 7: trade-off --------------------------------------------------------------
# group, short label, label anchor and offset in pt (layout only; chosen by eye so labels
# clear their markers and each other)
GROUPS = {
    "FIFO": ("classic", "FIFO", "west", 3, 0),
    "Clock": ("classic", "Clock", "north west", 1, -1),
    "Aging": ("classic", "Aging", "east", -3, 0),
    "LFU": ("classic", "LFU", "east", -3, 0),
    "S3-FIFO (adapted)": ("adapted", "S3-FIFO", "south", 0, 2),
    "ARC (adapted)": ("adapted", "ARC", "south east", -1, 2),
    "LHD (adapted)": ("adapted", "LHD", "south west", 1, 2),
    "linear score, global, all candidates": ("linear", "linear", "west", 3, 0),
    "linear score, global, 32 sampled candidates": ("sampled", "$k{=}32$", "north", 0, -2),
    "linear score, global, 16 sampled candidates": ("sampled", "$k{=}16$", "east", -3, 0),
    "boosted trees": ("heavy", "trees", "south", 0, 2),
    "ranking trees": ("heavy", "ranking trees", "west", 3, 0),
    "set-attention": ("heavy", "set-attn.", "south", 0, 2),
    "CNN": ("heavy", "CNN", "east", -3, 0),
    "deeper MLP": ("heavy", "MLP", "north", 0, -2),
}
groups = {}
for r in read("tradeoff.csv"):
    g, lab, anc, dx, dy = GROUPS[r["policy"]]
    groups.setdefault(g, []).append([r["instructions_per_decision_68_candidates"],
                                     r["faults_over_clock_10pct"], lab, anc, dx, dy,
                                     r["workloads_covered"]])
for g, rows in groups.items():
    write(f"tradeoff_{g}.csv", ["instr", "faults", "label", "anchor", "dx", "dy", "workloads"],
          rows)

# ---- Appendix: marginal value of each kernel feature -----------------------------------
KFEAT = ["ref", "aging", "sfreq", "idle", "age", "dirty", "refaults", "rdist"]
marg = {(r["scope"], r["workload"], r["split"], r["feature"]): float(r["median_delta_log_ratio"])
        for r in read("summary_marginal.csv")}
rows = []
for i, w in enumerate(WORKLOADS):
    for j, f in enumerate(KFEAT):
        pct = 100.0 * (math.exp(marg[(w, w, split_for(w), f)]) - 1.0)
        # label only the cells that matter (|change| >= 10%); the rest stay unlabelled
        rows.append([j, i, f"{pct:.1f}", f"${pct:.0f}$" if abs(pct) >= 10 else ""])
write("marginal.csv", ["col", "row", "pct", "label"], rows)

print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))
