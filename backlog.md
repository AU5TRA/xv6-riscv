# Backlog: work deferred for later

**For AU5TRA's agent (2026-10-17): read the section "PAPER — still to do" first.** This file is now in git (it was local only);
older sections below are history and many items in them are done. Remove items as they are done.

## PAPER — still to do (2026-10-17)

`report/paper/main2.tex` is a reviewed copy of `main.tex` (GawwyG's review, 2026-10-17; `main.tex` itself was not edited, as asked).
Diff it against `main.tex` and merge what you accept. What is still open:

0. **MLSys 2027 rules, checked 2026-10-17 against https://mlsys.org/Conferences/2027/CallForResearchPapers and the official style
   archive.** The style files in `report/paper/` are byte-identical to `mlsys2025style.zip`, which the 2027 call prescribes ("same
   submission format as 2025"): the template is correct. Limits: 10 pages excluding references (main2 ends on page 10), appendix
   unlimited but **a separate upload** due at the paper deadline, 10-pt Times, Type-1 fonts only (checked: all Type 1), table captions
   above / figure captions below, abstract "roughly 4–6 sentences" (main2: 6), multiple citations in chronological order (fixed in
   main2), every reference lists all authors (checked). Dates: submissions open **19 Oct 20:00 UTC**, deadline **30 Oct 20:00 UTC**
   (OpenReview, https://openreview.net/group?id=MLSys.org/2027/Conference); author lists cannot change after the deadline.
   * **AI Usage Disclosure — mandatory, missing from main.tex.** "placed after the references section; it does not count toward the
     page limit"; must describe tools, which parts, to what extent; "Undisclosed or inaccurately disclosed AI use ... may result in
     desk rejection". main2.tex has a draft after the references: the second author must fill in the red writing part, and BOTH
     authors must check every sentence.
   * **Build for submission with `bash report/paper/make_submission.sh main2`** (one build, split into paper and appendix PDFs).
     main.tex's own instruction (\withappendixfalse) leaves 8 appendix references as "??" in the paper PDF.
   * **OpenReview:** every author needs a complete, active profile ("at least two weeks in advance", i.e. by 16 Oct): check the
     second author's (and the supervisor's, if added); register all conflicts on the submission site.
   * ~~Page numbers for two references~~ — done 2026-10-18: bansal2004car pp. 187–200 (USENIX, DBLP, Crossref agree);
     vietri2018lecar has no page numbers (USENIX's own BibTeX has none; HotStorage papers are separate PDFs), so it gets
     publisher and address instead. The MLSys proceedings entries have none, which is allowed ("whenever possible").
1. **Anonymized code and data link.** The three `\todo{anonymized code link}` marks were removed from `main2.tex` (abstract,
   Availability, Conclusion). Before submission: create an anonymous mirror (e.g. anonymous.4open.science or an anonymized zip), make
   sure its history and paths do not identify the authors, and add the link once (Availability paragraph, §4) — not in the abstract.
2. ~~Template year~~ — checked: the 2027 call prescribes the 2025 style files, and ours are identical (item 0).
3. **Strip comments before any source upload** (arXiv, OpenReview supplementary, the anonymous repository): the `.tex` comments name
   both authors and the handoff files. The PDF itself is clean (checked: no names in text or metadata).
   `python3 tools/strip_tex_comments.py report/paper/main2.tex out.tex` writes a comment-free copy.
4. **Appendix upload.** Use `make_submission.sh` (item 0), then read the paper PDF once without the appendix and check every
   "Appendix" reference still reads well (reviewers need not read the appendix).
5. **Camera-ready only:** legal names, affiliations, the supervisor decision (by 19 Oct), equal-contribution marks, acknowledgements,
   the credit for the lzw/chase/join/bloom/spmv/heap programs.
7. **Cost grid on one code version (2026-10-18).** cost_grid.csv rows at 16-512 frames predate the sampling-rule switch (16 Oct);
   the 820-frame rows ran after it. The switch adds 14-16 instructions to a sampled decision (cost_grid_current_code.csv). The
   paper states this in the Table 12 caption. Optional: re-measure the sampled rows (or the whole grid) on the current code and
   regenerate cost_sizes.tex, the teaser and the break-even CSVs (about 0.2% on the sampled scores; nothing changes sides).
8. **Week-16 report tables (2026-10-18).** report_w16.py ci_main.tex still bolds every interval below 1 (including 0.998 / 0.994);
   main2 uses make_figdata2.py's ci_full2.tex (below 0.99). Align report_w16.py if the week-16 report is rebuilt.
6. ~~Older numbers not re-derived~~ — done 2026-10-18: "39 of 44" holds (but "within 0.007" was 0.0078 → now 0.008); "534 cells"
   was stale (89 streams of week 14) → validate.py rerun on all 1,194 cells, all match; 5.22M / 377K / 0.91M / 43K recounted from
   the .npz files, exact; training times re-measured (training_times.csv): 2.9–69.3 s → "3–70 s". "22–41% worse" was checked
   in the 2026-10-18 audit (extra_summary.csv global,real).


## Recommended next (from the ML study, 2026-10-01)

1. **Cheaper victim selection for `VM_POLICY_ML`.** It scores every
   resident page on every eviction, about 4 timer ticks per page: 88 ticks
   (9 µs) on sort with ~10 pages, ~1,000 ticks (100 µs) on btree with ~250
   pages, i.e. 2.5–32× Clock and ~2× Aging. Try scoring a sample or batch, as
   MGLRU does with generations. This is the biggest gap to a deployable
   policy. (week-14 report §4.5)
2. **Evaluate the selected models at 15%, 25% and 30% memory (simulator).**
   Training and evaluation used 5/10/20% only, for cost, but the dataset has
   six sizes, and the headroom does not shrink at larger memory (Belady vs
   Clock: 0.615, 0.584, 0.618, 0.585, 0.550, 0.518 at 5–30%). Replaying the
   selected linear models on the 33 test/held-out traces at the three unseen
   sizes is ~100 runs and checks whether they generalise to memory sizes they
   were never trained on. (2026-10-01)
2b. **In-kernel runs at 5% and 20% memory.**
   `python3 tools/ml2/kernel_eval.py --fracs 0.05,0.2` needs no code
   changes, just several hours of QEMU time. It would show the kernel
   result isn't specific to the 10% setting. Then rerun
   `kernel_vs_sim.py`, `analyze.py`, `tables.py` and `report_figs.py`,
   and update the week-14 report.
3. **Pick ML weights automatically per program or phase.** The
   per-process weights and `vmrun` already exist. The case to beat is the
   global model losing to Clock on matmul (+11.5% faults, 3.9× writes).
4. **Linux prototype** (plan only; nothing was run):
   * **Features from state Linux already keeps.** `idle` → the folio's MGLRU
     generation relative to the youngest (generations age by page-table
     walks, as xv6's scans do); `sfreq` → MGLRU's per-folio reference tier;
     `dirty` → `PG_dirty`; `refaults`, `rdist` → the eviction timestamp that
     `mm/workingset.c` stores in a shadow entry and the refault distance it
     computes on refault (a full per-page refault *count* would need a few
     spare bits in the shadow entry; Linux keeps only the `PG_workingset`
     flag). All are integers already.
   * **Where to score.** MGLRU evicts folios in batches from the oldest
     generation; the learned score ranks the folios of a batch with the same
     integer dot product and probation rule, falling back to the stock order
     when no weights are loaded.
   * **Training data.** A reference string per workload (PEBS/IBS sampling or
     binary instrumentation), replayed in the same simulator with
     Linux-faithful aging.
   * **Evaluation.** Against stock MGLRU and the classic active/inactive LRU
     under the same memory-cgroup limits: refaults, writeback, and reclaim
     CPU time. (Also in `AUSTRA_HANDOFF.md` §8, item 6.)
5. **Measure total run time.** Do the fewer faults and saved disk reads
   outweigh the slower eviction decisions? Re-run a subset of the in-kernel
   cases one at a time (no parallel lanes, so timings are comparable) and
   compare whole-program run time per policy. Listed as "not yet measured"
   in the week-14 report's Summary.

## NEXT-PHASE PLAN (drafted 2026-10-08, awaiting the user's go-ahead; details in cache_ext_notes.md)

Facts that shape it: lzw was fixed by AU5TRA (on `origin/Austra-dev`, merge is
conflict-free per dry run; 12 traces + 2 repeats already in `traces2/lzw/`; not
yet in `traces2/ML`; split: lzw-r20 seeds 0-3 train, 4 val, 5 test; lzw-r30 held
out). AU5TRA's `GAWWY_HANDOFF_NEW_BENCHMARKS.md` plans 11 workloads (patbench
x6 modes, spmv, chase, join, bloom, heap), nothing implemented, 4 open decisions.
Real Redis/SQLite page traces exist in `traces/old/real/` (70 + 50 MB, no R/W
marks) and were never used in the ML study. No tree, forest, boosting or logistic
model has ever been run in ml2 (roadmap Phase 6 named logistic regression and a
shallow decision tree first); CNN/attention/LSTM were only tried on the old traces.
- A. Data: merge Austra-dev; lzw into the pipeline; patbench (+ `uniform` leak
  control); Twitter key traces driving kvbench; real-trace transfer test; then
  chase/join/bloom/heap.
- B. Baselines in the simulator: MGLRU-style, S3-FIFO, LHD, ARC, exact MRU
  (oracle reference), sampled LFU, LearnedCache-style ml_protect.
- C. Wider model comparison: logistic, trees/forest/GBDT, binned and table models, candidate-
  relative features, set-attention, CNN/LSTM/attention and mixed models, deeper
  MLPs, ensembles and gated mixtures, distillation into kernel-feasible form.
- D. Kernel: sampled scoring port, tree/table scorer, no-op arm, full-eviction
  timer, serialized run-time measurement, in-kernel runs for lzw/patbench.
- E. Report: week-15 report with the new baselines and E1/E2 caveats.

## Related work found 2026-10-07: cite and position against before publishing

- **LearnedCache** (Zejia Qi, arXiv:2605.26168v2, Jul 2026): an ML eviction
  policy (single perceptron over 9 kernel-observable timing/EMA features,
  quantized weights) running live in real Linux's page cache via
  `cache_ext`/eBPF, trained per workload, evaluated on real hardware with
  YCSB/LevelDB and production Twitter traces. Up to 44% throughput gain over
  MGLRU/LRU on some workloads; mixed/loses on others; oversampled ranking
  policy "wholly infeasible" under extreme cache pressure due to decision
  overhead. Must be cited in any write-up of the Linux port plan
  (`AUSTRA_HANDOFF.md` §8 item 6) — it already did "ML policy live inside a
  real kernel," just for the file-backed page cache, not anonymous memory.
  Also cites closely related prior work to read: ML-CLOCK (Cho & Kang 2021),
  Yang et al. 2023 (arXiv:2301.11886), HALP (Song et al., NSDI'23).
  - **Action before publishing anything:** position our contribution against
    it explicitly — we do an oracle-vs-kernel-observable feature ablation and
    a validation-selected feature-subset sweep they don't; they measure
    real-hardware application throughput, which is exactly our own "not yet
    measured" gap (see "Measure total run time" below). Closing that gap
    becomes higher priority given this paper exists.

## Ideas from cache_ext / LearnedCache (repo: /home/gawwy/Thesis/cache_ext, 2026-10-08)

- **[Simulator part DONE 2026-10-08, E2] Sampled scoring.** Results in
  `cache_ext_notes.md` and `report/results2/sampling_sweep.csv`. K=32 random
  candidates keep 96% (scan all, score 32) or 93% (scan and score 32) of the
  fault gain over Clock while touching ~5x fewer pages; K=16 keeps 89% / 83%.
  Graph is most sensitive; page writes degrade faster than faults. Still open:
  - **Port to the kernel**: add a sample size to `choose_ml` (a per-process knob
    via `vmctl`, default all), draw K random candidates, scan and score only
    those, then measure ticks per eviction and faults in xv6 (does the
    projected ~168 ticks hold?). Keep the O(N) candidate-list walk in mind (next item).
  - **Time the whole eviction path**, not just `choose_policy_victim`:
    `select_ticks` starts after `reclaim_frame` walks the owner's full page list
    (kernel/vmpage.c:370-375), a cost common to all policies that no reported
    number includes. Add a timer around the whole path for every policy before
    publishing decision-cost ratios.
  - **Retrain on sampled features** to see whether the scan-sample loss shrinks.
- **[DONE 2026-10-08, E1] Clean-first hand-written baseline.** Result
  (`cache_ext_notes.md`, `report/results2/handwritten_vs_ml.csv`): hard
  "never evict dirty" is worse than Clock on faults in all 9 workload/split
  groups (4 censored at 3x Clock). A soft rule (idle, dirty counted ~7x less
  idle) matches the learned model on graph (0.851 / 0.856 vs 0.845 / 0.799
  faults; writes 0.430 / 0.388 vs 0.418 / 0.338) but fails on btree, kv,
  matmul and sort (1.056, 0.981, 1.136, 1.174). The fitted `idle+dirty` model
  agrees. Follow-ups still open:
  - **Add a "hand-written baselines" paragraph and table to the report**
    (`tools/ml2/report_tables.py` + week_14 report), stating that graph's gain
    is largely dirty-awareness while btree/kv/matmul/sort need the other
    features. Needs the user's go-ahead because it changes the framing.
  - **Reword "idle is the most valuable feature"** in the report: it is a
    marginal statistic; alone, idle is LRU-like and about Clock (0.985-1.011 in
    8 of 9 groups).
  - **Tune the soft-dirty weight on validation** (one parameter) for a fairer
    hand-written baseline than the a-priori -2.
- **Binned (piecewise-constant) linear features.** LearnedCache bins each
  feature into <=10 quantile bins and one-hot encodes it, so a perceptron
  gets per-feature non-linearity at one table lookup plus one add per
  feature. Try this in the simulator: it might recover the 2-4% the MLP
  gained on kv/btree/held-out graph at nearly linear cost.
- **Neighbour / region features.** LearnedCache uses file-level (inode)
  access deltas and EMA plus distance from the last access within the file.
  Our features are all per-page. Try the idle time of adjacent VPNs and the
  VPN distance from the most recently accessed page, aimed at sequential
  patterns (sort, btree-scan) where our gain is small.
- **Scan-based ports of S3-FIFO and LHD into `pagesim.c`.** First needs a
  design decision: in a kernel that only sees accessed bits at scans, a "hit"
  is "found accessed at a scan" and ages are measured in scans. MRU was run in
  E1 as an idle weight of -1 and failed (censored in 8 of 9 groups).
- **Read PageFlex** (Yelam et al., USENIX ATC'25): eBPF delegation of Linux
  swapping and prefetching policies for mmap'd memory, the closest Linux
  analogue of our anonymous-memory setting; and LRB (Song et al., NSDI'20), a
  learned and sampled eviction policy.
- **More baselines, with reference code.** `policies/` has eBPF LHD, S3-FIFO
  and MGLRU (plus FIFO, MRU, LFU sampling) to port into `pagesim.c`. LHD
  and LFU were the strongest heuristics in LearnedCache's results, tying or
  edging out its ML policy. Extends "More classical baselines" below.
- **Measure framework cost with a no-op policy.** cache_ext measures its CPU
  overhead with a policy that keeps all the bookkeeping but defers to the
  default eviction. For our run-time measurement, add an "ML bookkeeping +
  scan, Clock's decision" arm, so scoring cost, bookkeeping cost and fewer
  faults can be separated.
- **Linux port plan, two corrections.** (1) cache_ext covers the file page
  cache only (swapcache is a TODO in its lib header), so it cannot host an
  anonymous-memory policy like ours; a port either targets file caching, as
  LearnedCache does, or needs a kernel patch. (2) An eBPF policy cannot read
  workingset shadow entries; cache_ext's MGLRU keeps its own LRU-hash ghost
  map (400k entries) keyed by (inode, offset), so our `refaults` / `rdist`
  would need a bounded ghost map and lose history when it overflows. This
  qualifies the item-4 plan above.
- **Standard workloads and metrics.** Twitter production traces
  (`bench/bench_twitter_trace.py`, cgroup = 10% of DB size) and YCSB on
  LevelDB; LearnedCache reports throughput, and cache_ext also reports
  P99 latency. Datasets are ~75 GB compressed
  (`cache-ext-artifact-data` GCS bucket). The traces are key-value
  requests, not page traces, so using them means driving `kvbench` with
  real keys.
- **Per-cgroup policies** in cache_ext correspond to our per-process
  weights; its evict-candidate validation plus fallback to the default
  policy is already matched by `choose_policy_victim`'s validity check and
  fallback.

## Limitations to address before claiming ML beats classical policies in general

From the week-14 report (2026-10-01). Each one stands between "better on our
benchmarks" and a general claim.

- **Run time.** ML's decisions are 2.4–32.4× slower than Clock's; whether
  programs actually finish faster is unmeasured. (See "Measure total run
  time" above.)
- **Workloads.** Five synthetic benchmarks, not real applications, and some
  test sets are small (matmul has 2 held-out traces). (See "More trace
  variety" below.)
- **Memory sizes.** In-kernel runs only at 10%. (See "In-kernel runs at 5%
  and 20%" above.)
- **Baselines.** No comparison yet with modern algorithms (ARC, LIRS,
  CLOCK-Pro, Linux's MGLRU). (See "More classical baselines" below.)
- **One model for everything.** The realistic single global model loses to
  Clock on matmul (+11.5%); the best results need a model per program. (See
  "Pick ML weights automatically" above.)
- **Environment.** One emulated CPU in QEMU, not real hardware. Run on real
  RISC-V hardware (or at least measure on more than one core) to confirm the
  fault and timing results.
- **Distance from optimal.** Belady still has 42.9–54.4% fewer faults than
  Clock on btree, kv and graph, so there is a lot of room left. Look for the
  signals the current models miss (e.g. per-program access structure).

## ML study, other open items

- **Test CNN and attention models on `traces2`** (for publication: show the
  model families were covered). Both were tried only in the earlier study, on
  the old traces, where all architectures landed within 0.2% of each other.
  Add a 1-D CNN and a small attention model over a page's access history to
  `tools/ml2/train_nn.py` and evaluate them like the GRU. (requested 2026-10-01)
- **Shrink the ML per-page bookkeeping.** It is 33 bytes per physical page
  (~1 MB for 32,768 frames): three 8-byte scan counters, two 4-byte counts and a
  flag in `struct vm_page`. Scan counts fit in 4 bytes and `rdist` can be capped
  to 2, so about 16 bytes would do. (2026-10-01)
- **Confidence intervals and per-trace win counts in the report.** Results are
  geometric means without error bars; some groups have only 2–3 traces
  (matmul held-out 2, sort test 2, graph 3). Add bootstrap confidence
  intervals over traces, and per-trace win counts (today: ML per-workload beats
  Clock in 32 of 33 kernel traces, 96 of 99 simulated trace × memory cases; the
  one kernel loss is matmul-blocked128, +0.7%). (2026-10-01)
- **Check model weights for zero-weight edges (skip connections).** Look for
  connections whose weights are zero or near zero (e.g. the graph model's
  `sfreq` weight is −2 against `idle`'s 159 and `dirty`'s −347; dead units or
  near-zero edges in the MLPs). They add work in the kernel without changing
  decisions, and pruning them could simplify the models. (requested 2026-10-01)
- **Test ensembles of models**: e.g. average the scores of the per-workload
  linear models, or of linear + MLP, or let several models vote on the victim.
  Check whether an ensemble beats the single selected model, and whether a
  cheap ensemble of linear models can replace per-program weights (the global
  model's matmul loss). (requested 2026-10-01)
- **More classical baselines**: ARC, LIRS, 2Q, CLOCK-Pro, and an MGLRU-style
  generations policy, in `tools/ml2/pagesim.c`. These are the standard
  baselines reviewers expect; CLOCK-Pro and MGLRU are what Linux actually
  uses. (2026-10-01)
- **More trace variety, rather than more seeds**: new variants or workloads
  (larger matmul and sort, another graph shape, lzw split into chunks that
  fit xv6's maximum file size). There are only 5 held-out variants today, and
  sort/matmul touch just 12–118 pages. (2026-10-01)

- **Capacity-aware graph models.** Graph's simulated gain is
  concentrated at 10%; at 5% and 20% it is small. (`results2/tables.md`, table `bycap_KpKp`)
- **Explain the FIFO kernel/simulator gap.** FIFO is 10–41% worse in the
  kernel on kv, sort and matmul. The hypothesis is that it evicts
  non-arena code and stack pages; it's unverified. Count per-VPN faults
  for non-arena pages to check. (week-14 report §4.5)
- **Explain the global model on `graph-pr2000x2-s3`.** That stream sits
  on a capacity cliff. The global model gets 65,576 faults in the kernel
  vs 20,121 in the simulator at the matching +2 frames, and the cause
  isn't established. (`kernel_cliff.csv`)
- **Why the kernel gives the arena about 2 extra frames** compared with
  the nominal limit. The guess is arena pages already resident when
  `vmbench` measures the baseline. Not checked.
- **Workloads not covered:**
  - lzw: its trace exceeds xv6's maximum file size;
  - kvbench's TTL mode: its reference string depends on timing;
  - the real Redis/SQLite traces in `traces/old/`.
- **Re-run the full `tools/phase2_gate.sh` matrix** (debug build, 10-seed
  soak, bigfile, grind) on the current kernel. Only a subset was run on
  2026-10-01. The script also hard-codes AU5TRA's paths (`/mnt/d/thesis`,
  `/home/ashfaq/xv6env.sh`).
- **`tools/run_xv6_tests.py` misreports `vmrun …` commands as FAIL.**
  `pass_marker()` keys on the first word of the command. Teach it to skip
  a `vmrun <policy> [model]` prefix.
- **`traces2/` (3.7 GB) and `test-logs/kernel_eval/` aren't in git.**
  Decide how to share or archive them with AU5TRA and the supervisor.

## Older deferred items (from `HANDOFF_TO_CLAUDE.md` §7–9)

- **Kernel: the narrow `sleep_prepare`/`sleep` lost-wakeup window.** It
  predates this project and was deliberately left open.
- **Kernel: the demand-reserve margin.** Also pre-existing and left open.
- **kvbench calibration margin.** It is ~12.7% closer to real Redis than
  the control (btreebench: 44%). Not yet tried: the fixed 60% initial load
  factor, SET-then-GET op ordering, and the value-size distribution shape.
  Each needs new `kvbench.c` knobs.
- **Extend the calibration grid** or try other distance-metric weightings
  (`tools/calibrate.py`).
- **Matched-margin, matched-op-count Redis-vs-SQLite replay comparison.**
  The current one is qualitative only. The filesystem has ~550 KB of
  headroom left, so trim chunks first.
- **In-kernel timing for quantised models** (WORK_PROMPT3). This is now
  partly answered by the `select_ticks` stats, but only in emulated
  ticks, not on real hardware.

## Deliberately out of scope (don't start without asking)

- Floating-point support in xv6.
- Vendoring real Redis/SQLite source into xv6.
- Changes to the core paging mechanism without flagging them first.

## Reporting rule (user, 2026-10-08)
After ALL work is done: verify everything, update handoffs, write new report in report/week_15_update/, commit. "Do them automatically" = commit each verified step.

## Transfer results (exp_transfer.py, faults/Clock geo-mean, unseen streams; 2026-10-08)
pat (11 modes, seeds 1,5): lru .991, arc .886, s3fifo .875, lhd .933, belady .643; linear global F .918, F+K 1.012 (phase modes blow up 2.6x), K .942, K+K+ .837, any .837; uniform all 1.000 (no leak).
kv-T (6 Twitter clusters): lru .983, arc .983, s3fifo 1.028, lhd .916, belady .611; linear kv|F .861, F+K .845, K .890, K+K+ .980. cluster35 (flat popularity) ~1.0 for all.
Open: F+K global fails on phase shifts -> candidate for extra-model robustness check.
Real host-collected traces (redis-real 12.3M refs, sqlite-real 8.6M; T-marks, no R/W): lru .929/.908, arc .967/.947, lhd .973/.927, belady .667/.567, linear global F .988/.925, F+K 3.0(censored)/1.318, K .906/.880, K+K+ 1.106/.934. F+K again fragile out of distribution. Imported via tools/import_real_traces.py (HELD_OUT redis-real, sqlite-real).
appbench (chase/spmv/hashjoin/bloom, held out; faults/Clock, seeds 1,3; CORRECTED column mapping): all online policies ~1.0 (belady .54-.73). Global linear K+K+ (all kernel signals) HURTS spmv 1.239 and hashjoin 1.138, ~1.02 chase, HELPS bloom .930; global F+K (oracle) is safe: spmv .995, hashjoin 1.017, bloom .926. GBDT K (extra) .965 overall on app vs linear K+K+ 1.076. => scan + random-structure workloads are where the kernel-signal linear model can lose.

## State at the PC restart (2026-10-10 ~12:00)
Done: stage 1 (kernel runs of the five models + standard policies on all workloads and AU5TRA's programs at 10%, sim tests on traces3 streams,
program-vs-host-model checks for heap/join/bloom/chase/spmv all exact), merge of origin/Austra-dev (dc792cc), traces3 import.
Stage 2 in progress (resumable): `bash tools/ml2/resume_stage2.sh` -> 504 standard-policy runs (kernel_eval_w16e.csv, 39 done) and 100 five-model runs
(kernel_eval_w16f.csv, 35 done) at 5% and 20%. Then: pat/app (and patb) at 5%/20% with --accesses 50000, `python3 tools/ml2/cost_grid.py` (cost vs candidates),
break-even analysis, merge the w16*.csv files in report_w15.py, report + handoff update. ETA when stopped: ~8 h.

## State 2026-10-10 evening (before closing VS Code)
All local runs finished (stage 2 local share 168+10 runs, cost grid 68 runs). Cost analysis done: tools/ml2/cost_benefit.py -> report/results2/cost_benefit.csv
(linear scorer pays off above ~26-530 us per fault; CNN/MLP/attention never; trees only on HDD).
WAITING ON: four Kaggle notebooks (kaggle_N_standard/nets/patapp csv files) -> copy to report/results2/.
NEXT (after the files arrive): 1) merge kaggle_*.csv + w16e/f into the analysis (report_w15.py reads kernel_eval_w16*.csv; add kaggle_*),
2) tables/figures for 5% and 20% memory, 3) report sections: AU5TRA's programs (merge dc792cc), populate-start finding, state sensitivity,
full tests of the five models, cost vs candidates + break-even, 4) update AUSTRA_HANDOFF.md addendum, 5) rerun all checks, commit, copy PDF.

## Paper and submission backlog (2026-10-11) -- "B" items, deferred
7. Decide the claim and the venue/format (thesis chapter vs conference/workshop paper). GawwyG decides.
8. Related work: a real literature search on learned caching / page replacement (only notes in cache_ext_notes.md exist). Every citation must be checked.
9. Paper-quality figures and tables in the venue's style (the report ones are drafts).
10. Artifact and licences: traces are ~4 GB (ignored by git); check the terms of the Twitter data (cache_ext authors) before releasing derived streams;
    one clean README (the repo has many handoff files).
11. Authors, AU5TRA's credit (programs, Kaggle work), supervisor review.

## Evidence gaps ("A" items) not finished, with where they can run
A1 Train each of the five model kinds on ALL workloads (incl. new programs) and test in the kernel.
   - training: GPU, ~1 h total (small nets) -> Kaggle GPU notebook (two at a time, 2xT4 each) or the local RTX 3060 Ti; needs ml2_cache uploaded as a dataset
   - simulator selection/test of the new models: CPU, ~2-3 h -> Kaggle CPU notebooks (up to 10)
   - kernel tests: CPU, ~5 h on 6 lanes -> 4 Kaggle CPU notebooks ~1.7 h (kaggle_package already does this; add the model files)
   - PARTIAL: simulator comparison exp_trained_on_all.py, 14 of 24 cells (resume: see AUSTRA_HANDOFF.md section 6). First result: CNN 0.89, MLP 0.90 vs linear 0.94.
A2 Error bars: kernel intervals across streams are DONE (kernel_ci.py). More seeds for 5%/20% (one stream per variant now): CPU kernel runs -> Kaggle CPU.
A3 Real fault cost: needs real hardware (not Kaggle, not QEMU). Proxy: measure page-in/page-out service time on Linux with fio; then plug into cost_benefit.py.
A4 LHD in the kernel: ~1 day development (local), evaluation on Kaggle CPU.
A5 Safety guard (fall back to Clock when worse): 1-2 days development (local); evaluation on Kaggle CPU.
A6 Missing runs: 3 Bloom 20% runs (CNN, MLP, set-attention): rerun with --timeout 43200 (CPU; Kaggle sessions allow 12 h). lzw sampled-scoring reruns: 6 of 21 done.
Other: chase-tree / bloom-k7 omitted from exp_trained_on_all.py (33 CPU-h, nothing helps there anyway).

## State at the end of the session (2026-10-11 ~00:40)
All jobs stopped (nothing running). Unfinished, all resumable (commands: AUSTRA_HANDOFF.md section 6): lzw sampled-scoring reruns (kernel_eval_w16g.csv),
trained-on-all simulation (trained_on_all.csv), three Bloom 20% runs (kernel_eval_w16j.csv, written but may be empty).
Last commit: 737a268 (GawwyDev, pushed). Uncommitted: the partial result files above only.
After they finish: merge_kernel_results.py (add w16j to SOURCES), kernel_ci.py, report_w15.py, replace the PLACEHOLDER rows in the START HERE table, commit.

## Decision needed from GawwyG (collected while working; everything else was done without waiting)
D1. [DROPPED 2026-10-11: not needed for the research question] Safety guard in the kernel. The guard is an optional extra (simulator prototype, report section "A safety guard"); the research question is which learned policy works best against Clock and other classical algorithms, and a policy losing on some workloads is a result, not a limitation.
D2. Venue / claim wording / authors (B items 7, 11).
D3. [BACKLOG, to do later, GawwyG's call 2026-10-11] Port LHD into the kernel (~1 day). Reason: the in-kernel comparison only has Clock, Aging and LFU; the strongest classical baselines (LHD 0.90-0.95 of Clock, ARC, S3-FIFO) exist only in the simulator, which matters for "learned vs classical". Then ARC and S3-FIFO if time allows.
D4. [DEFERRED 2026-10-11, not worth doing now] More seeds / streams for the 5%/20% memory sizes (error bars). Revisit only if a reviewer asks.

## State 2026-10-11 ~06:00 (all non-blocking work finished; nothing running)
Last commit a6c7644 (not pushed). Done: lzw sampled reruns (21/21), Bloom 20% reruns (3/3), 5%/20% tables complete, kernel runs of the five all-workloads models at 10%
(50 runs; CNN/MLP level with linear), guard prototype (simulator), cost + break-even incl. sampled variants, kernel intervals, report 15 pages, handoff START HERE updated.
WAITING ON GawwyG: (1) Kaggle round 2 (kaggle_package/README.txt: upload new xv6_package.tar.gz, paste notebook_1..4.py, run; download kaggle_N_netsall.csv into report/results2/;
then: python3 tools/ml2/merge_kernel_results.py && python3 tools/ml2/report_w15.py, add the 5%/20% rows for the all-workloads models to the report), (2) decisions D1-D4 above,
(3) permission to push / merge to riscv (github.md has the commands).

- Report restructure (user 2026-10-11): kernel results main tables; simulator results subsidiary (main text if space, else appendix); headline = all-workloads models vs classical. Do after round 2 results arrive and user allows report edits.

- Classical policies in the kernel (ARCK, S3-FIFO scan form, LHD scan form; VM_POLICY_ARCK/S3FIFO/LHD = 5/6/7, vmrun names arck/s3fifo/lhd) are INTEGRATED and smoke-tested (one tiny patbench run each: PASS; vmtest, prefetchtest PASS). Their evaluation runs are NOT done (user 2026-10-11: after round 2). To run: kernel_eval.py --nonml arck,s3fifo,lhd (plus clock for reference) at 0.05,0.1,0.2 on all streams; then compare with simulator via kernel_vs_sim.py (SIMPOL has the mapping); add to report/handoff (kernel tables first).

- 2026-10-11 (late): week 16 report written (report/week_16_update, kernel results first, simulator in appendix) and AUSTRA_HANDOFF.md START HERE rewritten. Kernel runs of ARC/S3-FIFO/LHD done at 5/10/20%. Open: D2 (claim/venue/authors), push/merge approval, A3 real fault cost, related work, paper figures, Twitter licence check, one clean README. Optional: per-workload CIs for heavier models need more streams (only ten at present).

- 2026-10-12: GawwyG dropped the safety guard completely (no work, no text). Removed from week 16 report and AUSTRA_HANDOFF; her handoff and START HERE list the places in report/paper to remove. exp_guard.py and the week 15 report section stay as history only.

- 2026-10-15 QUEUED (user): round 9 = five heavier models at 5% and 20% on all 74 streams (kaggle_package/round9, 6 notebooks + PC share local_run.sh, ~109 core-hours). Order: LeCaR 5% (running) -> round 8 PC share (apply kaggle_package/round8/kernel_sampling.patch to the repo first, commit) -> round 9 PC share.
- 2026-10-15 open, not done: (1) cheaper scoring code (cache the log features, straight-line code, cache PTE pointers; est. 30-40% of the scoring part); (2) kernel-side seeds for the sampler (vmrun option) + multi-seed kernel runs; (3) real page-fault time (needs real hardware); (4) = round 9.
- 2026-10-15 queued: cost grid on other patbench patterns (loop, zipf, hotscan, phase) at 64 frames for linear, ARC, LHD, LeCaR, Aging, Clock (~25 runs); maybe one real program if it can run at a fixed limit.
- 2026-10-15 native timing of the new code was measured WHILE the PC queue ran (6 busy lanes, noise +-25%): linear 947 ns new vs 1495 old at 68 candidates (ratio 0.63). Re-measure on an idle PC after the queue finishes (taskset -c 3 /tmp/native_timing, also 'walk' and 'cold' modes; gcc -O2 -I . -I kernel tools/ml2/native_timing.c); then cost_benefit.py x = new ns / new instructions (teammate A step 4/5), report_w16.py, tradeoff.py.
