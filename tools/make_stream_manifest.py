#!/usr/bin/env python3
"""Write the manifest of reference streams to collect: one line per
(workload, variant, seed), each collected once at a generous margin.

A reference string does not depend on how much memory the run is given
(verified: every capacity of a workload in traces/sweep produced a
byte-identical trace), so a new seed or variant needs one traced run, not a
capacity sweep. The margin is chosen above every footprint, so the run pages
barely at all and costs close to its compute time.

Stems are <workload>-<variant>-s<seed>. Phases:
  pilot    seed 1 of every variant, plus a "-rep" repeat of it: the repeat
           must be byte-identical (determinism), and every pilot run must
           pass and stay inside the file-size budget before the rest runs.
  dataset  the remaining seeds.

Deliberately absent:
  * kvbench TTL -- expiry reads uptime(), so a TTL run's reference string
    depends on timing and would not reproduce.
  * matmulbench seeds -- the seed only fills in matrix values; the access
    pattern is fixed by the loops, so every seed gives the same string.

Usage:  python3 tools/make_stream_manifest.py > tools/streams_manifest.tsv
"""

MARGIN = 8000          # above every footprint below; resident_limit_max 16384
SEEDS5 = [1, 2, 3, 4, 5]
SEEDS3 = [1, 2, 3]
SEEDS6 = [0, 1, 2, 3, 4, 5]   # lzwbench: seed 0 is the original text
FILE = 9               # trace bit | file-sink bit

# (stem prefix, estimated seconds per run incl. fs.img rebuild, seeds,
#  command template with {m} margin and {s} seed)
VARIANTS = [
    # kvbench <footprint> <margin> <ops> <seed> <mode> <flags>
    ("kv-A",       60, SEEDS5, "kvbench 2000 {m} 20000 {s} A %d" % FILE),
    ("kv-B",       60, SEEDS5, "kvbench 2000 {m} 20000 {s} B %d" % FILE),
    ("kv-C",       60, SEEDS5, "kvbench 2000 {m} 20000 {s} C %d" % FILE),
    ("kv-D",       60, SEEDS5, "kvbench 2000 {m} 20000 {s} D %d" % FILE),
    ("kv-F",       60, SEEDS5, "kvbench 2000 {m} 20000 {s} F %d" % FILE),
    ("kv-Arehash", 60, SEEDS5, "kvbench 2000 {m} 20000 {s} A %d" % (FILE | 2)),
    ("kv-Avsize",  60, SEEDS5, "kvbench 2000 {m} 20000 {s} A %d" % (FILE | 4)),
    # btreebench <footprint> <margin> <ops> <seed> <mix> <flags>
    ("btree-mixed",    50, SEEDS5, "btreebench 5000 {m} 45000 {s} mixed %d" % FILE),
    ("btree-lookup",   50, SEEDS5, "btreebench 5000 {m} 45000 {s} lookup %d" % FILE),
    ("btree-scan",     50, SEEDS5, "btreebench 5000 {m} 45000 {s} scan %d" % FILE),
    ("btree-insert",   50, SEEDS5, "btreebench 5000 {m} 45000 {s} insert %d" % FILE),
    ("btree-mixedwal", 50, SEEDS5, "btreebench 5000 {m} 45000 {s} mixed %d" % (FILE | 2)),
    # graphbench <footprint> <margin> <pr_iters> <seed> <bfs|pagerank|both>
    # ~6.2M refs / ~41 MB each except bfs (~3.2M). 1000 pages x 3 iterations
    # is the variant where PageRank revisits the same hubs across iterations.
    ("graph-both2000x1", 660, SEEDS5, "graphbench 2000 {m} 1 {s} both %d" % FILE),
    ("graph-both1000x3", 660, SEEDS3, "graphbench 1000 {m} 3 {s} both %d" % FILE),
    ("graph-bfs2000",    350, SEEDS3, "graphbench 2000 {m} 1 {s} bfs %d" % FILE),
    ("graph-pr2000x2",   660, SEEDS3, "graphbench 2000 {m} 2 {s} pagerank %d" % FILE),
    # sortbench <footprint> <margin> <n> <seed>
    ("sort-n20000", 90,  SEEDS3, "sortbench 2000 {m} 20000 {s} %d" % FILE),
    ("sort-n40000", 160, SEEDS3, "sortbench 2000 {m} 40000 {s} %d" % FILE),
    ("sort-n60000", 240, SEEDS3, "sortbench 2000 {m} 60000 {s} %d" % FILE),
    # matmulbench <footprint> <margin> <n> <naive|blocked> -- no seed
    ("matmul-naive64",    60,  [1], "matmulbench 2000 {m} 64 naive %d" % FILE),
    ("matmul-naive96",    155, [1], "matmulbench 2000 {m} 96 naive %d" % FILE),
    ("matmul-naive128",   330, [1], "matmulbench 2000 {m} 128 naive %d" % FILE),
    ("matmul-blocked64",  60,  [1], "matmulbench 2000 {m} 64 blocked %d" % FILE),
    ("matmul-blocked96",  155, [1], "matmulbench 2000 {m} 96 blocked %d" % FILE),
    ("matmul-blocked128", 330, [1], "matmulbench 2000 {m} 128 blocked %d" % FILE),
    # lzwbench <margin> <repeat_count> <flags> <seed> -- the seed picks the
    # text: 0 is corpus.txt (the GPL), 1-5 are public-domain books of the
    # same size (user/lzwbench.c). With the GPL, 20 fills the dictionary and
    # freezes it (~4.0M refs); 30 also drives one CLEAR (~6.1M refs).
    ("lzw-r20", 570, SEEDS6, "lzwbench {m} 20 %d {s}" % FILE),
    ("lzw-r30", 850, SEEDS6, "lzwbench {m} 30 %d {s}" % FILE),
]

# Graph repeats cost ~11 min each; one graph repeat covers the code path the
# other graph variants share.
GRAPH_REPEAT = {"graph-both1000x3"}

print("# stem\test_s\tphase\tcommand")
for prefix, est, seeds, cmd in VARIANTS:
    for s in seeds:
        phase = "pilot" if s == seeds[0] else "dataset"
        print("%s-s%d\t%d\t%s\t%s" % (prefix, s, est, phase,
                                      cmd.format(m=MARGIN, s=s)))
    if not prefix.startswith("graph-") or prefix in GRAPH_REPEAT:
        print("%s-s%d-rep\t%d\tpilot\t%s" % (prefix, seeds[0], est,
                                             cmd.format(m=MARGIN, s=seeds[0])))
