# cache_ext / LearnedCache: analysis, plan, results log

Local only (excluded via `.git/info/exclude`). Written 2026-10-08 on branch
`GawwyDev`. Repo analysed: `/home/gawwy/Thesis/cache_ext` (framework repo;
LearnedCache's own code is not in it). Papers: LearnedCache (arXiv
2605.26168v2) and `cache_ext_paper.pdf`.

## 1. What was read (nothing skipped)

All of `policies/*.bpf.c` and `*.bpf.h` (FIFO, MRU, LFU-by-sampling, LHD,
S3-FIFO, GET-SCAN, MGLRU, dir_watcher, lib), the loaders' options and map
sizing (`policies/*.c`), `eval/twitter` and `bench/bench_twitter_trace.py`,
`download_dbs.sh`, and the relevant sections of the cache_ext paper (scope,
API, safety, overhead, floating point, related work).
NOT available locally: the four submodules (custom Linux 6.6.8 kernel, leveldb,
rocksdb, My-YCSB), so the C code of `bpf_cache_ext_list_sample` and the
kernel hooks is unread; LearnedCache's own repo is unlocated.

## 2. The policies

| Policy | State kept | Rule | Candidates examined | Dirty handling |
|---|---|---|---|---|
| FIFO | one list | evict from head | iterate until enough | skip dirty/writeback |
| MRU | one list, move-to-head on access | evict most recent | iterate (skip non-uptodate/non-LRU for first 200) | **not checked** |
| LFU (sampling) | per-folio access count | lowest count | sample 20 | never evicted (INT64_MAX) |
| LHD | per-folio last access time, last two hit ages; 256 classes x 16384 age buckets of hit/eviction counts (EWMA 0.9) | lowest hit density | sample 16 | never evicted |
| S3-FIFO | small list (~1/15 of cache) + main list + ghost LRU-hash (size = cache pages); freq capped at 3 | small: promote if freq>1 else evict; main: 4 passes decrementing freq | iterate lists | skipped |
| GET-SCAN | two lists (general, scan-tagged by PID), access count, +100000 for a file's last page | lowest count | sample 5, scan list first when >=5000 pages | **not checked** |
| MGLRU | 4 generation lists, per-folio {accesses, gen}, tiers = log2(accesses), per-tier evicted/refaulted counters, PID-style controller, ghost map of 400k (inode, offset) -> tier | evict from oldest gen unless tier above controller threshold (then promote) | iterate | dirty/locked/writeback promoted to the next generation |

Cross-cutting facts:
- Sampled scoring is the norm: 5 to 20 candidates per eviction (our policy
  scores all ~106 on average, up to ~250).
- 5 of 8 policies refuse to evict dirty folios; MGLRU defers them. Two (MRU,
  GET-SCAN) ignore dirtiness.
- LHD is an online learner: counts adapt continuously; a heavy
  `reconfigure` (loops over 256 x 16384 buckets) runs outside the hot path,
  triggered every 2^20 events via a ring buffer + `BPF_PROG_RUN` from userspace.
- Fixed point: LHD scales by 2^20 because "eBPF does not support
  floating-point operations" (paper section 5). Same constraint and same fix
  as our Q8 integers.
- Memory cost: cache_ext's registry is 0.4 to 1.2% of the cgroup's memory;
  our per-frame bookkeeping is 33 B / 4096 B = 0.8%. Comparable.
- CPU cost: a no-op cache_ext policy costs at most 1.7% CPU per I/O.
- Safety: kernel validates every proposed candidate (valid-folio registry) and
  falls back to the default policy if a policy proposes too few. We have the
  same in `choose_policy_victim`.
- Scope: file-backed page cache only. Paper: "While anonymous memory pages are
  managed similarly to file-backed memory, in this paper we focus specifically
  on file-backed memory." Swapcache is a TODO in `cache_ext_lib.bpf.h`.
- MGLRU in eBPF deliberately skips swap-backed folios and PTE-based promotion:
  only `folio_mark_accessed` (the fd path) reaches policies, never PTE
  accessed-bit scans. Our K features are built from PTE scans, so they have no
  cache_ext equivalent.
- Related work to read: PageFlex (Yelam et al., USENIX ATC'25), eBPF
  delegation of Linux *paging* (swap, prefetch) policies for mmap'd memory:
  the closest Linux analogue of our anonymous-memory setting. LRB (Song et al.,
  NSDI'20, learned relaxed Belady) is cited as a sampled learned policy.

## 3. What we can adopt, and what each tests

| # | Idea | Source | Tests | Cost |
|---|---|---|---|---|
| E1 | Hand-written baselines (idle, clean-first, soft dirty, MRU) | LFU/LHD/S3-FIFO never evict dirty | Is the learned model better than a trivial rule? Where do the write savings come from? | no C change |
| E2 | Sampled scoring, sweep K | `bpf_cache_ext_list_sample` | Can decision cost drop 5-10x at equal quality? | small C change |
| E3 | More baselines: S3-FIFO, LHD (scan-based), MGLRU-style | policies/ | Does learned beat strong adaptive heuristics? | new C code per policy |
| E4 | Binned (one-hot quantile) linear | LearnedCache | MLP-like gain at linear cost? | new scorer + training |
| E5 | Neighbour/region features | LearnedCache inode features | Gain on sequential patterns? | new features + retrain |
| E6 | No-op arm + serialized run-time | cache_ext overhead method | Is the policy a net win in run time? | kernel runs, hours |

## 4. Plan (status)

- [x] 0. Switch to GawwyDev and merge riscv (commit e8b8e84; tree identical to riscv).
- [x] 1. Read every cache_ext policy, loader, eval script and the relevant paper sections.
- [x] 2. E1 in the simulator (99 cells). Decision rule: if clean-first is within 1%
      of the learned policy on faults AND writes for graph and matmul, the report's
      write-savings claim must be re-attributed to dirty avoidance.
- [x] 3a. E2 in the simulator (done); [ ] 3b. port to `choose_ml` and measure ticks. E2: add `sample_k` to the simulator (score-only and scan+score variants),
      sweep K in {4, 8, 16, 32, 64, all}; pick the smallest K within 1% of full scoring;
      then port to `choose_ml` and re-measure ticks per eviction.
- [ ] 4. E3: port S3-FIFO and a scan-based LHD into `pagesim.c`; MRU already in E1.
- [ ] 5. E4 and E5, only if 2-4 leave a gap worth closing.
- [ ] 6. E6 in the kernel for any winner; then update the week-14 report, handoff
      and backlog with the new baselines, flagging anything that weakens a claim.

## 5. Results log

(appended below as experiments finish)

### E1: hand-written rules vs the learned models (done 2026-10-08)

Code: `tools/ml2/exp_handwritten.py`, `exp_handwritten_report.py`. Output:
`report/results2/handwritten_vs_ml.csv`, `summary_handwritten.csv`. 693 runs,
99 test/held-out cells (33 streams x 5/10/20%), 42 s. Hand weights were set a
priori and never fitted. All use the kernel-observable `idle` / `dirty`
features, 8-bit integer scorer, same tie-break. `ml_*` are the selected K+K+
linear models in the same 8-bit arithmetic.

Faults / Clock (geo-mean over streams x 5/10/20%; * = censored at 3x Clock):

| group | idle | clean-first | soft-dirty | ML global | ML per-workload |
|---|---|---|---|---|---|
| btree test | 0.995 | 1.151 | 1.056 | 0.864 | **0.833** |
| graph test | 0.991 | 2.476* | **0.851** | 0.874 | 0.845 |
| graph held-out | 0.992 | 1.165 | 0.856 | **0.791** | 0.799 |
| kv test | 0.990 | 1.136 | 0.981 | 0.908 | **0.905** |
| matmul held-out | 0.931 | 3.000* | 1.136 | 0.967 | **0.681** |
| sort test | 1.011 | 2.432* | 1.174 | 1.005 | **0.983** |

Page writes / Clock: graph test 0.328* (clean) / 0.430 (soft) / 0.418 (ML);
graph held-out 0.223 / 0.388 / 0.338; matmul held-out 0.007* / 0.142 / 0.658.

Per-cell wins (99 cells): ML per-workload < Clock 97; < clean-first 98;
< clean+p4 97; < soft-dirty 92. `idle` alone < Clock in 77 (it is LRU-like).

Reading:
1. Hard "never evict dirty" is a bad rule here: worse than Clock on faults in
   all 9 groups (kv held-out is level, 1.004), 4 of them censored at 3x Clock.
   Likely reason cache_ext can afford it (reasoning, not measured): dirty file
   pages are flushed by background writeback anyway, whereas an evicted dirty
   anonymous page needs an immediate swap write and a hot dirty page is costly
   to lose.
2. **On graph, one hand-set number explains most of the learned gain.**
   Soft-dirty (idle, dirty counted ~7x less idle) gets 0.851 / 0.856 faults
   and 0.430 / 0.388 writes, against ML 0.845 / 0.799 and 0.418 / 0.338. The
   fitted two-feature model `idle+dirty` (existing sweep, 10%) agrees: graph
   0.660 / 0.592 vs selected 0.624 / 0.560.
3. On btree, kv, matmul, sort that rule does NOT work (1.056, 0.981, 1.136,
   1.174 faults) and `idle+dirty` stays at 0.97-1.00; the gain there comes from
   the other features (aging, age, refaults, rdist, sfreq) and per-workload
   weights: btree 0.997 -> 0.803, matmul 0.999 -> 0.913 (10%).
4. Implication for the write-savings claim: real, but on graph it is mostly
   dirty-awareness rather than learning; on matmul the learned model is the
   only variant that cuts both faults (0.681) and writes (0.658).
5. Wording risk in the report: "idle is the most valuable feature" is a
   marginal statistic (median change when added to subsets lacking it); on its
   own idle is LRU-like and ~Clock (0.985-1.011 in 8 of 9 groups; matmul 0.931).

### E2: sampled scoring (simulator part done 2026-10-08)

Code: `tools/ml2/pagesim.c` (new `sample_k`, `sample_scan`, `sample_seed`; counters
`scanned`/`scored`; `draw_sample`, `choose_sampled`, `scan_one`), `pagesim.py`,
`exp_sampling.py`, `exp_sampling_report.py`. Output
`report/results2/sampling_sweep.csv` (6,138 runs, 175 s), `summary_sampling.csv`.
Regression: with sampling off, 42/42 spot-checked runs are bit-identical to
before; `validate.py` (534 cells) and `validate_kernel.py` (11,792 evictions x
53 candidates, 0 mismatches) still pass.

Selected per-workload linear models (8-bit), 99 test/held-out cells, 3 seeds,
no retraining. Faults relative to FULL scoring on the same cell (paired):

| K | score-sample: faults | vs Clock | writes | scan-sample: faults | vs Clock | writes | pages touched / eviction |
|---|---|---|---|---|---|---|---|
| all | 1.000 | 0.866 | 1.000 | 1.000 | 0.866 | 1.000 | 131.2 |
| 64 | 1.002 | 0.867 | 1.007 | 1.003 | 0.869 | 1.010 | 47.3 |
| 32 | 1.007 | 0.871 | 1.025 | 1.011 | 0.875 | 1.037 | 26.7 |
| 16 | 1.018 | 0.881 | 1.063 | 1.027 | 0.889 | 1.084 | 14.4 |
| 8 | 1.042 | 0.902 | 1.153 | 1.062 | 0.919 | 1.210 | 7.6 |
| 4 | 1.092 | 0.945 | 1.293 | 1.128 | 0.976 | 1.362 | 3.9 |

(score-sample still scans all 131 pages; scan-sample touches only K.)

Per workload at K=32 (score / scan): btree +0.5% / +1.0%, graph +2.8% / +4.2%,
kv +0.0% / +0.1%; matmul and sort unaffected (2-24 frames, so K >= 16 never
samples). Graph is the most sensitive (K=16: +6.5% / +9.4%).

Reading:
1. K=32 keeps 96% (score) / 93% (scan) of the fault gain over Clock
   (gain 13.4% full vs 12.9% / 12.5%) while touching ~5x fewer pages.
   K=16 keeps 89% / 83%; K=8 73% / 59%.
2. Page writes degrade faster than faults (K=32: +2.5% / +3.7%; K=16:
   +6% / +8%): with few candidates there may be no clean page in the sample.
3. Scan-sampling (stale features) costs only ~0.4 to 1.5 points more than
   score-sampling at the same K, so the page-table walks can be sampled too.
4. No retraining was done; a model fitted on sampled features might recover some
   of the loss. Not tried.
5. Projected cost (extrapolation from the kernel fit ~43 + 3.9 ticks/page, NOT
   measured with sampling): K=32 would cost ~168 ticks (17 us) per eviction
   instead of ~1,010 (btree) / ~594 (graph), i.e. ~5x / ~3.5x Clock instead of
   32x / 11x.
6. CAVEAT on every cost number in the report: `select_ticks` starts AFTER
   `reclaim_frame` has walked the owner's whole page list to build
   `frame_table.candidates` (kernel/vmpage.c:370-375), a pointer walk done for
   every policy, Clock included. It is not in any reported decision time, and
   sampling inside `choose_ml` cannot remove it. The reported ratios to Clock
   are for `choose_policy_victim` only.

## STATE LOG (2026-10-08, authorised autonomous run; rules in CLAUDE.md)

Commits so far on GawwyDev: 7c97878 (E1/E2), merge of origin/Austra-dev (lzw).
Done and verified (uncommitted unless noted):
- lzw dataset: `traces/streams -> ../traces2` symlink (git-excluded); `stream_dataset.py prepare`
  wrote `traces2/ml` (101 streams) -> now `traces2/ML` (old copy `traces2/ML_old89`; the 89 old
  streams are bit-identical). lzw split: r20 seeds 0-3 train, 4 val, 5 test; r30 held out.
- BUG FOUND+FIXED: `build_datasets.py` seeded rows with `hash()` (per-process random), so the
  original training sets were an unrecorded random draw and cannot be regenerated. Now crc32
  (+ BUILD_SEED_SALT for noise experiments); two rebuilds are bit-identical. Consequence: all
  models are refit, results shift slightly vs week-14 (expected, to be noted in the report).
- `tools/ml2/lzw_update.py` (gated, resumable `--from N`) re-runs classical -> datasets ->
  sweep (all rows) -> NN (all scopes) -> run_phase_b.sh. Log in scratchpad lzw_update2.log.
  `sweep_linear.py` resume key is now (scope, stream, fraction).
- patbench: user/patbench.c, user/pat_zipf.h, tools/gen_pat_zipf.py, tools/patbench_model.py
  (host model; selftest passes), Makefile, manifest rows (11 variants x 5 seeds + reps, held-out
  pat-zipf120 and pat-switch). Smoke collection of 35 runs in progress.
- Sandbox simulator `pagesim_dev.c` (env PAGESIM_SRC/PAGESIM_LIB): new policies mru, arc, s3fifo,
  s3scan, mglru, lhd; `test_baselines.py` 475/475 identical to independent references; old-vs-dev
  regression 94/94 identical. NOT yet copied over pagesim.c (wait for pipeline to finish).
  `exp_baselines.py` results in report/results2/baselines_ext.csv (120 cells).
Baselines vs Clock (all 120 cells, faults geo-mean): LHD 0.924 (beats Clock in 103), ARC 0.973,
S3-FIFO 1.026, MGLRU-anon 0.999, MRU 2.47. LHD ties the learned model on graph/kv.
Next: patbench validation -> collect 66 traces (2 lanes) -> (after pipeline) integrate dev sim,
prepare dataset v2 with pat + twitter + real traces, install lightgbm/sklearn/zstandard, extra models.
