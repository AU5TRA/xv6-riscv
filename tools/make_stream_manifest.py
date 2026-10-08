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
PAT_S = 170            # patbench, any mode: 154s measured for 2M accesses

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
    # patbench <footprint> <margin> <accesses> <seed> <mode> -- six synthetic
    # patterns with known answers (user/patbench.c), 2,000,000 accesses over
    # 1024 pages, one reference each: 2.0M refs, ~13 MB, all 1024 pages
    # touched. The zipf modes and switch need exactly 1024 pages.
    ("pat-loop",       PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} loop %d" % FILE),
    ("pat-scanhot",    PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} scanhot %d" % FILE),
    ("pat-scanhotlo",  PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} scanhotlo %d" % FILE),
    ("pat-zipf060",    PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} zipf060 %d" % FILE),
    ("pat-zipf080",    PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} zipf080 %d" % FILE),
    ("pat-zipf099",    PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} zipf099 %d" % FILE),
    ("pat-zipf120",    PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} zipf120 %d" % FILE),
    ("pat-uniform",    PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} uniform %d" % FILE),
    ("pat-phase",      PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} phase %d" % FILE),
    ("pat-phaseshort", PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} phaseshort %d" % FILE),
    ("pat-switch",     PAT_S, SEEDS5, "patbench 1024 {m} 2000000 {s} switch %d" % FILE),
    # chasebench <footprint> <margin> <ops> <seed> <mode> -- pointer chasing
    # over 1024 pages of nodes (user/chasebench.c); ops sized for ~2.0M refs
    # (seed 1: list 2,041,652, tree 2,005,263, n256 2,001,911), all 1024
    # pages touched. chase-n256 is the tree with 256-byte nodes.
    ("chase-list", 170, SEEDS5, "chasebench 1024 {m} 4000 {s} list %d" % FILE),
    ("chase-tree", 170, SEEDS5, "chasebench 1024 {m} 160000 {s} tree %d" % FILE),
    ("chase-n256", 170, SEEDS5, "chasebench 1024 {m} 180000 {s} tree256 %d" % FILE),
    # joinbench <footprint> <margin> <r_tuples> <seed> <mode> -- hash join
    # (user/joinbench.c), |R| = 65536; footprint = the pages the layout needs,
    # all touched. Seed 1: uni 623,039 refs over 1280 pages, zipf 567,481
    # over 1280, r4 1,082,885 over 2048.
    ("join-uni",  60, SEEDS5, "joinbench 1280 {m} 65536 {s} uni %d" % FILE),
    ("join-zipf", 60, SEEDS5, "joinbench 1280 {m} 65536 {s} zipf %d" % FILE),
    ("join-r4",   90, SEEDS5, "joinbench 2048 {m} 65536 {s} r4 %d" % FILE),
    # bloombench <footprint> <margin> <n_keys> <seed> <mode> -- a 512-page
    # Bloom filter (user/bloombench.c), 131072 keys inserted and 4x as many
    # queries. Seed 1: k3 1,448,691 refs, k7 3,031,307; all 512 pages.
    ("bloom-k3", 130, SEEDS5, "bloombench 512 {m} 131072 {s} k3 %d" % FILE),
    ("bloom-k7", 250, SEEDS5, "bloombench 512 {m} 131072 {s} k7 %d" % FILE),
    # spmvbench <footprint> <margin> <iters> <seed> <mode> -- CSR SpMV
    # (user/spmvbench.c), 131072 rows, ~4 non-zeros a row, 2 iterations:
    # ~4.2M refs over ~1667 pages (the exact count varies with the seed's
    # non-zeros; 1680 covers them).
    ("spmv-rand", 340, SEEDS5, "spmvbench 1680 {m} 2 {s} rand %d" % FILE),
    ("spmv-band", 340, SEEDS5, "spmvbench 1680 {m} 2 {s} band %d" % FILE),
    # heapbench <footprint> <margin> <ops> <seed> <mode> -- K&R malloc/free
    # in the arena (user/heapbench.c), 24000 operations. Seed 1: small
    # 3,862,616 refs over 409 pages, mixed 3,585,728 over 1469, churn
    # 2,522,723 over 438; the break stays below the 2048-page arena.
    ("heap-small", 300, SEEDS5, "heapbench 2048 {m} 24000 {s} small %d" % FILE),
    ("heap-mixed", 280, SEEDS5, "heapbench 2048 {m} 24000 {s} mixed %d" % FILE),
    ("heap-churn", 200, SEEDS5, "heapbench 2048 {m} 24000 {s} churn %d" % FILE),
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
