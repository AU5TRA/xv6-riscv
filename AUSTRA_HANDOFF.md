# Handoff to AU5TRA: everything done on the ML side (as of 2026-10-11; START HERE section first, week-15 addendum below)

**Written for**: AU5TRA, picking up after GawwyG's work of 2026-09-28 to
2026-10-01. This file covers what was built, where every result lives, what
changed in the kernel and user programs you work in, what was tested, and
what is still open. The final report is `report/week_14_update_report.pdf`;
every generated table behind it is in `report/results2/tables.md`. This file
is the map to them.

**The short version.** On your `traces2` streams, a learned linear score
over 4–5 kernel-observable features beats Clock on all five workloads, on
unseen seeds and on unseen variants. It now runs inside xv6 as
`VM_POLICY_ML`, integer-only, and beats Clock there too. Its per-workload
weights give 2.7–45.9% fewer faults and up to 96.5% fewer page writes. The old
`traces/` study is superseded (Appendix A summarises it); two of its
headline results came from broken traces and must not be cited.

**Read first**:
* `report/week_14_update_report.pdf` — the final report (11 pages): Summary,
  then §4.5 (in-kernel results).
* `report/slides/ml_results.pdf` — the 20-page deck. The kernel section is
  slides 14–18.

---

## START HERE: handoff for writing the paper (2026-10-11)

**For**: your agent (or you), to start writing the paper from the current state. Every result below is tagged:
* **FINAL**: measured and checked; will not change unless a bug is found. Safe to write.
* **PLACEHOLDER**: a number exists, but a run is unfinished or a check is pending. Write it into the text, mark it (for example "[PLACEHOLDER]"), and
  update it when the files named below change.
* **WIP**: not done. Write the section skeleton only.

Language rule from GawwyG: plain words, no jargon, no invented terms. Say what a thing is, not what it is called.

### 1. What the paper can claim (proposal; GawwyG decides the final claim and venue)
A small linear score over signals an operating-system kernel can already see (accessed bit, dirty bit, how long a page was idle, how often it was
evicted and came back), computed with whole numbers, makes fewer page faults than Clock in xv6 and is cheap enough to run. Bigger models (deeper networks,
convolutional and attention models, boosted trees) cost 20 to 145 times more per eviction and gain at most about 3% in the kernel on the workloads they were
trained for; whether they gain more when trained on everything is **WIP** (see section 3). Sampling a few candidates per eviction removes the growth of the cost
with memory size. Method lessons (worth a paragraph): every benchmark has an exact model of its reference string; the kernel starts from filled memory, so a
simulator that starts empty misjudges some models; one model (set-attention) changes by up to 14 times with the starting memory state.

### 2. Results table (numbers are faults relative to Clock; below 1 is better; xv6 on QEMU unless it says simulator)
| Result | Status | Where |
|---|---|---|
| Linear score, nine workloads, kernel: 0.94 / 0.92 / 0.79 at 5 / 10 / 20% memory; FIFO 1.28/1.27/1.34, Aging 1.10/1.05/1.19, LFU 1.13/1.11/1.24 | FINAL | report section "All three memory sizes"; `report/results2/kernel_eval_all.csv` |
| Linear score per workload at 10% with 95% intervals (btree 0.84, graph 0.58 own-model, kv 0.87, lzw 0.84, heap 0.74 global, sort 0.94) | FINAL | `kernel_ci.csv`, table in the report |
| Linear score fails on: matmul at 5% (1.48), SpMV (1.12 to 1.14), global model on graph at 20% (1.60) | FINAL | report, three-size tables |
| CNN and MLP vs linear model on kv: 2.9% and 2.7% fewer faults, clear over 11 streams; worse than linear on btree, lzw, sort, graph | FINAL for models trained on one workload | `kernel_ci_paired.csv` |
| Same comparison with each model trained on all workloads | **PLACEHOLDER / WIP**: first partial result (14 of 24 cells, 5 streams, simulator): CNN 0.89, MLP 0.90, trees 1.01, set-attention 0.92, ranking trees 1.37 against 0.94 for the global linear model. This may overturn "richer models do not beat linear"; do not write that sentence as final | `trained_on_all.csv` (partial) |
| Cost of choosing a victim against number of candidates (linear 360 instructions per candidate, trees 7,300, set-attention 27,000, CNN 30,000, MLP 51,000; Clock under 1,100 up to 512 candidates) | FINAL | `cost_grid.csv`; report section "What choosing a victim costs" |
| Break-even: linear model of its own workload pays on a hard disk (8 ms per fault) everywhere it has one (time 0.58 to 0.94 of Clock); about breaks even on fast flash (100 us); CNN and MLP never pay | FINAL given two assumptions: 1 instruction = 1 ns, and the two fault costs (**the fault cost was never measured**) | `cost_benefit.csv` |
| Sampling 32 candidates: linear cost stops growing with memory (11,800 instructions at 256 and at 512 candidates against 91,700 and 183,300) | FINAL | `cost_grid.csv` |
| Sampling 32 / 16 candidates, faults vs full scan in the kernel (about 0 to 1% / 1 to 2.5% more) | **PLACEHOLDER**: lzw rows were rerun on the current build, 6 of 21 done | `kernel_eval_w16g.csv`; report table "kernelruns" |
| Kernel against simulator agree within about 4% except two gaps, both explained (filled memory at start; set-attention instability) | FINAL | report section "Why the kernel and the simulator disagree" |
| Kaggle results equal this machine's results exactly (261 of 261 runs done on both) | FINAL | report |
| Literature baselines in the simulator (ARC, S3-FIFO, an MGLRU analogue, LHD, MRU); LHD best untrained at 0.90 to 0.95 | FINAL (simulator only; none are in the kernel) | `baselines_ext.csv`, `transfer*.csv` |
| Your programs (chase, join, Bloom, SpMV, heap) reproduce your host models byte for byte in our kernel; simulator and kernel results on them | FINAL | report section "Programs from AU5TRA" |
| Noise from the choice of training rows: at most 0.0005 (kernel signals) | FINAL | `noise_floor.csv` |
| Bloom filter at 20%: CNN, MLP, set-attention (3 runs timed out after 3 h on Kaggle) | **PLACEHOLDER** (missing; all policies score 1.00 on Bloom elsewhere) | |

### 3. What is not done (WIP; write skeletons, no claims)
* Train each of the five model kinds on all workloads and test them in the kernel (about 5 hours of kernel time; see "Resuming" below). The simulator part is half done.
* A safety guard that falls back to Clock when the learned policy does worse (the linear model loses on matmul at 5%, SpMV, graph at 20%). Not started.
* A port of LHD (the best untrained baseline) into the kernel. Not started.
* The cost of a real page fault (reading a page from disk and writing one back). Needs real hardware; xv6 on QEMU cannot give it.
* More than one stream per variant at 5% and 20% memory; more seeds for error bars.
* Related work (a proper literature search; nothing is written beyond notes in `cache_ext_notes.md`), paper-quality figures, the choice of venue and format,
  licence check of the Twitter data before releasing derived streams, author list. These are in `backlog.md` (not in git) and are summarised here.

### 4. Suggested outline and where each part's material is
1. Introduction and claim (section 1 above). 2. Background: xv6 demand paging, the policies (FIFO, Clock, Aging, LFU), what a kernel can observe: report sections "Models and features" of week 14 (`report/week_14_update_report.pdf`).
3. The workloads: 6 original programs, lzw (yours), patbench (11 patterns with known answers; a control called uniform where nothing can be learned), Twitter replays, real Redis and SQLite traces, appbench, and your five programs:
   report "New workloads" and "Programs from AU5TRA". 4. Models and how they run in the kernel (whole-number arithmetic, `kernel/mlfeat.h`, `kernel/mlnet.h`, sampling).
5. Method: validation-only selection, streams held out, error bars, the filled-memory pitfall. 6. Results: sections 2 above. 7. Cost and break-even. 8. Limits. 9. Related work. 10. Conclusion.
The week-15 report (`report/week_15_update/week_15_update_report.pdf`, 14 pages, source `.tex` and generated `tables/`) already has text for most of 3 to 8.

### 5. How to read the numbers (traps)
* **One file for kernel results**: `report/results2/kernel_eval_all.csv`, built by `tools/ml2/merge_kernel_results.py` from all the `kernel_eval*.csv` and `kaggle_*.csv`. Never read the others directly.
* **Two builds**: runs from the week-14 build and from the current build differ by about 1% for every policy. The merge keeps only current-build rows where both exist. Never compare across builds.
* **Memory sizes**: 5%, 10%, 20% of a program's pages. 10% covers every stream; 5% and 20% cover one stream per variant (42 streams). The five extra models at 5% and 20% cover one stream per workload.
* **Streams**: patbench and appbench kernel runs use 50,000 accesses, not the full strings. Her programs: only seed 1 was handed over (`traces3/`); other seeds and repeats are "external" in the manifest.
* **The extra models were trained on one workload each** (kv for CNN, MLP, boosted trees; graph for set-attention and ranking trees); outside that workload they show transfer, not their best.
* **Time** is counted in instructions with QEMU in instruction-count mode (`QEMU_ICOUNT=1`), so it repeats; it is not wall-clock time.
* **Simulator** starts from empty memory unless `--warm` / `warm_start.py` is used; the kernel starts from filled memory.
* Data not in git: `traces2/` (4 GB), `traces/streams`. The result files in `report/results2/` are in git, so tables and figures regenerate from them with `python3 tools/ml2/report_w15.py` (a few tables also read the dataset index and need the traces).

### 6. Resuming the unfinished runs (everything is resumable; finished runs are skipped)
```
cd tools/ml2     # python is ~/.venvs/xv6ml/bin/python on GawwyG's machine
# lzw sampled-scoring reruns on the current build (6 of 21 done) -> kernel_eval_w16g.csv
KERNEL_EVAL_OUT=kernel_eval_w16g.csv KERNEL_EVAL_LANES=/tmp/xv6G python -u kernel_eval.py --lanes 6 --fracs 0.1 \
  --only lzw-r20-s5,lzw-r30-s0,lzw-r30-s1,lzw-r30-s2,lzw-r30-s3,lzw-r30-s4,lzw-r30-s5 --splits test,heldout --models lzw@16,lzw@32,lzw@64
# trained-on-all comparison in the simulator (14 of 24 cells done) -> trained_on_all.csv (about 8 CPU-hours in total)
python -u exp_trained_on_all.py --jobs 4 --only btree-mixed-s5,kv-A-s5,kv-T17-s1,sort-n40000-s3,matmul-blocked128-s1,heap-small-s1,join-zipf-s1,spmv-band-s1
# the three missing Bloom runs (give them 12 hours)
KERNEL_EVAL_OUT=kernel_eval_w16j.csv python -u kernel_eval.py --lanes 3 --fracs 0.2 --only bloom-k7-s1 --models cnn-kv,mlp-kv,attention-graph --timeout 43200
# then, in this order:
python merge_kernel_results.py && python kernel_ci.py && python report_w15.py     # add the new file name to SOURCES in merge_kernel_results.py first
```
Kaggle: `kaggle_package/` (built by `tools/kaggle/make_package.py`) runs kernel tests on CPU-only notebooks (about 1.7 hours each for 4 notebooks, no GPU needed); GawwyG
can run two GPU notebooks (two T4 each) at a time, which only helps for training models. Results that came back are in `kaggle_results/` and `report/results2/kaggle_*.csv`.

### 7. Files added since the last handoff (all in git)
`tools/ml2/`: `merge_kernel_results.py`, `kernel_ci.py`, `cost_grid.py`, `cost_benefit.py`, `state_sensitivity.py`, `warm_start.py`, `victims_cmp.py`, `exp_trained_on_all.py`,
`netint.py`, `export_nets.py`, `extra_*.py` (tree and neural models), `report_w15.py`, `timing_runs.py`. `tools/kaggle/`. `report/week_15_update/`. `report/results2/` new CSVs
(`kernel_eval_all.csv`, `kernel_ci*.csv`, `cost_grid.csv`, `cost_benefit.csv`, `state_sensitivity.csv`, `trained_on_all.csv`, `transfer_*.csv`, `extra_*.csv`, `noise_floor.csv`).
Kernel: `kernel/mlnet.h`, `mlnets.h` (five extra models in whole-number form), sampled scoring (`vmrun ml <model>@<k>`), new timing counters, `vmrun -v` victim log.

---

## Week 15 addendum (2026-10-09): what changed since the sections below were written

Report: `report/week_15_update/week_15_update_report.pdf` (tables/figures from `tools/ml2/report_w15.py`).
All work is on branch `GawwyDev`, one commit per step (`git log --oneline` from `c2cff42`).

**Read this first: results of earlier sections that moved.**
* Python's `hash()` was seeding the training samples, so datasets were not reproducible. Fixed
  (`build_datasets.py`: CRC32 seed, optional `BUILD_SEED_SALT`). All models were refit; classical results are
  unchanged (4272 rows). Numbers in the week-14 report therefore differ slightly from a fresh run; the
  global default kernel model changed (`kernel/mlweights.h`, now 5 features).
* lzw (your fixed benchmark) is in the full pipeline (`tools/ml2/lzw_update.py` drove the gated update).

**New workloads (all held out; they only test).** Each has a host model and, where marked, host-generated streams:
| workload | program | model / generator | streams |
|---|---|---|---|
| patbench (11 synthetic modes) | `user/patbench.c` | `tools/patbench_model.py`, `tools/pat_hostgen.py` | `traces2/pat/` (9 kernel-collected, rest host-generated, HOSTGEN line in log) |
| Twitter replays `kv-T<cluster>` | `kvbench ... T<cluster>`, keys in `user/twk<N>.bin` | `tools/twitter_extract.py` (needs `~/.venvs/twx`), `tools/gen_tw_keys.py` | `traces2/kv/kv-T*` (kernel-collected) |
| real Redis/SQLite | host recordings, `T <page>` lines, no R/W | `tools/import_real_traces.py` | `traces2/redis`, `traces2/sqlite` |
| appbench (chase, spmv, hashjoin, bloom) | `user/appbench.c` | `tools/appbench_model.py`, `tools/app_hostgen.py` | `traces2/app/` (host-generated; kernel runs checked equal for 30k refs/mode) |
Dataset: `python3 tools/stream_dataset.py prepare` (176 streams in `traces2/ML`; `traces2/ml` is a symlink to it).

**Simulator additions** (`tools/ml2/pagesim.c/.py`): MRU, ARC, S3-FIFO (two forms), MGLRU-anon, LHD
(tests: `test_baselines.py`, 475/475 vs independent references); scorer kinds `trees` (C, with candidate-set rank
features) and `callback` (Python, for set/sequence nets). Checks that must pass after any change:
`validate.py`, `validate_kernel.py`, `test_baselines.py`, `test_extra.py`, `test_extra_nn.py`.

**Experiments and where results live** (`report/results2/`): `baselines_ext.csv` (E1 literature baselines),
`transfer*.csv` (`exp_transfer.py`), `extra_cells.csv` + `extra_summary.csv` (`extra_trees.py`/`extra_nn.py`/`extra_report.py`;
models in `report/models2/extra/*.pkl`), `kernel_eval.csv` + `kernel_vs_sim_w15.csv`, `noise_floor.csv`
(`exp_noise.py`). Headline: with kernel-observable inputs no richer model beats the linear scorer by the 2%/2x-cost
bar overall; oracle-input models gain up to 6% in distribution and fail on the real Redis/SQLite traces.

**Kernel**: `VM_POLICY_ML` has sampled scoring: `struct vm_ml_weights.sample_k`, `vmrun ml <model>@<k>`
(`ml_sample()` in `kernel/vmpage.c`). In xv6 at 10%: lzw `ml lzw` 0.84 of Clock, kv-T `ml global` 0.85,
patbench `ml global` 0.85, appbench 1.00; `@32` costs 0-1% more faults at 40-80% of the selection ticks, `@16`
30-55% of the ticks for 1-2.5%. **The two earlier discrepancies are explained** (report section "Why the kernel and the simulator disagree"): the kernel's benchmarks populate
memory before the traced part, the simulator started empty (`tools/ml2/warm_start.py`, `kernel_vs_sim.py --warm`: kv-scope linear model on the Twitter
replays goes from kernel/sim 0.90 to 1.00); and set-attention is unstable (`state_sensitivity.py`: median spread 2x over five starting states, up to 14x;
Clock, linear, CNN, MLP, trees change by 1-5%). `vmrun -v` logs every victim (`victims_cmp.py` compares kernel and simulator victim by victim).

**Five extra models in the kernel** (week 15, later): `kernel/mlnet.h` (integer evaluation, shared with `pagesim.c`),
`kernel/mlnets.h` + `user/mlnet_names.h` (generated by `tools/ml2/export_nets.py` from `report/models2/extra/*.pkl`),
`tools/ml2/netint.py` (float model -> integer layout; `test_netint.py` checks it). Choose with `vmrun ml <name>[@k]`, names:
`cnn-kv attention-graph mlp-kv ranktrees-graph trees-kv`. `struct vm_ml_weights.model_id` selects them.
Time delay: kernel counters `collect_ticks`, `select_ticks`, `path_ticks` (whole eviction minus the swap-out wait);
`QEMU_ICOUNT=1 make qemu` runs QEMU with `-icount shift=0,sleep=off` so 1 tick = 100 instructions and counts repeat to <0.3%;
`tools/ml2/timing_runs.py` runs every policy one at a time -> `report/results2/timing.csv`. In-kernel results of the five:
`report/results2/kernel_eval_w16.csv` (+ `kernel_vs_sim_w16.csv`). Outcome: CNN/MLP ~2.5% fewer faults than linear on kv at
85x/148x the instructions; trees tie at 21x; on graph linear wins; set-attention is worse than Clock on graph test in the kernel
(unexplained, sim says 0.84).

**Reproduce**: see the last section of the week-15 report. Long runs (use a monitor, not a sleep loop):
`extra_trees.py select/test` (~1-2 h each), `kernel_eval.py` (lzw runs take ~16 min each per lane).

**Later in week 15 (2026-10-10)**
* **AU5TRA's branch is merged** (commit `dc792cc`): chasebench, joinbench, bloombench, spmvbench, heapbench, her host models (`tools/hostmodel/`),
  her manifest rows. Her patbench has the same name and arguments as mine but different strings: hers is `user/patbench2.c` (stems `patb-*`),
  mine stays `patbench` (stems `pat-*`). All five new programs reproduce her host models byte for byte in our kernel (short runs).
  `tools/import_traces3.py` imports the new strings from `traces3/` (heap, join, spmv); chase and bloom streams are generated with her models.
  traces3 had 116 traces but 26 distinct strings; everything for btree, graph, kv, lzw, matmul, sort duplicates ours (`tools/traces3_inventory.py`).
* **All memory sizes, Kaggle**: 5% and 20% memory runs (42 streams) were split over this machine and four Kaggle notebooks
  (`tools/kaggle/make_package.py` builds `kaggle_package/`; `kaggle_results/` holds what came back). All 261 runs done on both machines are
  identical. `tools/ml2/merge_kernel_results.py` -> `report/results2/kernel_eval_all.csv` (the single file the report reads).
  **Build caveat**: runs from the week-14 build (`kernel_eval.csv`) and from the current build differ by ~1% for every policy; the merge drops
  old-build rows from groups that have current-build rows. Never compare across builds.
* **Cost**: `tools/ml2/cost_grid.py` (cost of choosing a victim against the number of candidates, all policies, repeatable clock) and
  `cost_benefit.py` (break-even fault cost; time vs Clock for SSD and disk). Result: linear model of its own workload pays on a disk everywhere it has one,
  about breaks even on flash; CNN/MLP/set-attention never pay; boosted trees pay only on a disk on kv.
* **Known gaps**: the five extra models were trained on one workload each (kv or graph) and are only transferred elsewhere; 3 runs missing (Bloom 20%
  with CNN, MLP, set-attention timed out after 3 h on Kaggle); 5%/20% use one stream per variant.

**New gotchas**
* `pkill -f <pattern>` kills the shell that runs it if the pattern appears in the command line; use PIDs.
* `grep -i error` matches the `-Werror` flag in every compile line; grep for `error:`.
* A large embedded table in a user program breaks `vmbench_burn` (the FIFO burn evicts the oldest pages, i.e. the
  table, before reaching the arena): read data from a file after setup instead (as `kvbench T` does).
* Set `OMP_NUM_THREADS=1` (the extra_* modules do) before numpy loads when running several simulator workers: BLAS threads
  made the numpy callbacks 10x slower.
* `check_streams.py` requires different seeds to give different strings; deterministic replays (kv-T) have one seed.
* The neural extra models are not run on streams longer than 400k references (callback cost); only trees are.
* Quick appbench/patbench kernel runs use `--accesses 50000` in `kernel_eval.py`; `kernel_vs_sim.py` replays the prefix.

---

## 0. For the agent reading this (Claude, Codex, …): do this first

**Before you start any task from this file, check with AU5TRA that she and
GawwyG agree on what the research project is.** Summarise §0.1 to her in a
few sentences, ask her the questions in §0.2, and wait for her answers.
Where her view differs from §0.1, don't resolve it yourself. Tell her it
should be settled with GawwyG, and note the difference at the end of this
file under "AU5TRA's answers". Don't treat §0.1 as decided until she has
confirmed it.

### 0.1 The project as GawwyG sees it

* **Research question.** Can a learned model replace the classical
  page-replacement policy of an operating system?
* **What a model may use.** The model is trained offline on reference
  traces from real workloads. At run time it may use **only signals a
  kernel can actually observe**: accessed/dirty-bit scans and refault
  bookkeeping, never per-access information.
* **Where it runs.** Inside the kernel, frozen (no in-kernel training),
  with integer arithmetic only.
* **Order of work.** Show it in xv6-riscv first, then carry the same
  feature set and policy to **Linux**, using the signals MGLRU, DAMON and
  `mm/workingset.c` already keep.
* **Success.** Fewer faults and fewer page writes than Clock (xv6's best
  built-in policy) on unseen seeds and unseen workload variants. Model
  selection uses validation only, and results are measured in the real
  kernel, not just in simulation. The eviction-time cost must be
  acceptable.
* **Deliverable.** A thesis that is supervisor-ready and, ideally,
  publishable.
* **Division of work so far.** AU5TRA built the paging/swap platform, the
  workloads and the trace collection (`traces2/`). GawwyG did the
  verification and test infrastructure, the ML study, `VM_POLICY_ML`, and
  the in-kernel evaluation.

Status against this plan: the xv6 part is done (§3–6). Linux is a written
plan only (§8, item 6). The open items are in §8.

### 0.2 Questions to ask AU5TRA

1. Is §0.1 the project you have in mind? Is the thesis about learned page
   replacement, with the paging platform as its foundation? Or do you see
   the platform and traces as the main contribution, with ML as one part?
2. **Linux.** Is the goal a working Linux implementation (for example a
   kernel patch or module on MGLRU/DAMON signals)? Or Linux traces and
   analysis only? Or is Linux future work outside the thesis?
3. Do you agree on the evaluation criteria in §0.1? That means:
   * Clock as the baseline;
   * memory at 5/10/20% of each workload's pages;
   * kernel-observable features only;
   * unseen seeds and variants as the test.
4. **Kernel review needed.** `VM_POLICY_ML` and the LFU fix touch the
   paging core you built (§4). They add to `reclaim_frame`, `setup_page`
   and `vm_frame_set_backing` in `kernel/vmpage.c`, and they change the
   `vmbench` burn phase. Will you review these changes?
5. Which open items (§8) do you want to take, and what does the
   supervisor expect next, and by when?
6. Are the earlier constraints still in force?
   * no floating point in xv6;
   * no Redis/SQLite source vendored into xv6;
   * no changes to the paging core without flagging them.

## 1. What happened, in order

| Commit | Who | What |
|---|---|---|
| `9d36525`, `2d89a64`, `791ad45`, `e6bfafe` | you | read/write-marked traces, the 89-stream seed/variant set (`traces2/`), the ML dataset (`traces2/ML`), `make_summary` |
| `39ccb65`, `2f9c025` | GawwyG | `tools/ml2/`: a compiled simulator (`pagesim.c`), validated against your baselines and the kernel's own logic |
| `ed7854b` | GawwyG | decision-point training sets, per-feature diagnostics |
| `f14407c` | GawwyG | training/evaluation pipeline, classical baselines, neural models |
| `8520ad0` | GawwyG | v2 study: all 300 feature sets × 6 scopes, failure analysis (§3), report draft |
| `86c3439` | GawwyG | final selection, neural/sequence/embedding models, integer-only scoring, report and slides |
| `160e238` | GawwyG | **kernel: LFU livelock fixed** (decayed frequency, cherry-picked from GawwyDev `d1d247f`), debug probe removed |
| `a60faaa` | GawwyG | **kernel: `VM_POLICY_ML`**, the learned policy, integers only |
| `4f3761a`, `f02ead3` | GawwyG | in-kernel evaluation (231 runs), comparison with the simulator, report §8b, slides |
| `94c503d` | GawwyG | LaTeX/PDF version of the long report (since replaced by `report/week_14_update_report.pdf`) |

All of this is on `riscv`. If `origin/riscv` doesn't have these commits
yet, GawwyG still has to push them.

## 2. Where everything is stored

| Path | What | In git? |
|---|---|---|
| `report/week_14_update_report.pdf` | **the final report** (11 pages) | yes |
| `report/week_14_update/` | its LaTeX source and figures (`figs/`, made by `tools/ml2/report_figs.py`) | yes |
| `report/slides/ml_results.tex`, `.pdf` | the presentation (20 slides); `slides/tables/*.tex` are generated tables | yes |
| `report/results2/` | **every raw result** as CSV, plus summaries and `tables.md`: every generated table, including ones the report leaves out (probation ablation, DAgger, v1 vs v2 data, all feature subsets) | yes |
| `report/models2/` | every trained model: `linear_<scope>.json` (300 feature sets per scope), `final_linear.json` (**the selected models**), `nn/` (84 neural/ranking models), `linear_dagger.json`, `v1/` (first version) | yes |
| `report/figures2/` | figures, PNG and PDF | yes |
| `tools/ml2/` | all the code (§7 lists each script) | yes |
| `kernel/mlfeat.h`, `mlfeat_table.h`, `mlfeat_mant.h` | the integer feature code, shared by kernel and simulator | yes |
| `kernel/mlweights.h`, `user/mlmodels.h` | generated weights: the kernel default, and all 12 named models for `vmrun` | yes |
| `traces2/` (3.7 GB) | your streams; `traces2/ML/` is the dataset made from them; `traces2/ml2_cache/` holds the training sets | **no**: regenerate (§7) |
| `test-logs/kernel_eval/` | the 231 in-kernel transcripts, referenced from `kernel_eval.csv` | **no**: only on GawwyG's machine |
| `report/ML_TESTING_REPORT.md`, `report/models/`, `report/*.csv` | the earlier `traces/` study | yes, **superseded** |

The main CSVs in `report/results2/`: `classical.csv` (classical policies),
`linear_sweep.csv` (the 28,800 linear runs), `final_val.csv`/`final_test.csv`
(selected models), `nn_eval.csv` (neural models), `extras.csv` (DAgger,
quantisation, probation), `kernel_eval.csv` (231 in-kernel runs),
`kernel_vs_sim.csv`, `kernel_cliff.csv`, and the `summary_*.csv` aggregates.

## 3. The `traces2` study (details: week-14 report §1–4)

* **Data.** Your 89 streams (123M R/W-marked references). Splits come
  from your `SPLITS.tsv`: held-out means unseen variants; test and
  validation are unseen seeds. Capacities are 5/10/20% of each stream's
  distinct pages. **All tuning used validation only.**
* **Simulator** (`tools/ml2/pagesim.c`). It is validated:
  * it equals your `baselines.tsv` on all 534 cells;
  * it matches the kernel's Clock, Aging and LFU logic in faults and
    writebacks;
  * `PTE_A`/`PTE_D` are set at fault-in, as in `kernel/vm.c`. The old
    `sim.py` didn't do this.
* **Features**, in three tiers:
  * **F, oracle**: `rec`, `freq`, `sd`, `wr`;
  * **K, kernel-observable** from A/D scans: `ref`, `aging`, `sfreq`,
    `idle`, `age`, `dirty`;
  * **K+, refault bookkeeping** (Linux workingset): `refaults`, `rdist`.
* **Models.** Linear models over every feature combination (28,800 full
  replays), MLPs, a ranking loss, a GRU, and a cross-page embedding
  (kept as an ablation). The training data is 4.73M eviction-decision rows
  recorded under LRU, with the label `log1p(next-use distance)`.
* **Bug found and fixed.** The v1 training data never showed a "just
  touched" page, so the models evicted the page being streamed. On
  PageRank, 97% of their victims had been loaded at the previous fault.
  Fixed by recency-stratified recording plus probation (new pages are
  protected for *p* scans). Tables `v1v2` and `protect` in `results2/tables.md`.
* **Results** (simulated; selected kernel+refault model vs Clock; test /
  held-out):

  | Workload | Test | Held-out |
  |---|---|---|
  | btree | −17% | −14% |
  | graph | −15% | −20% |
  | kv | −10% | −10% |
  | matmul | — | −32% |
  | sort | −2% | −7% |

  * Up to 66% fewer page writes.
  * Oracle features buy almost nothing; `idle` matters most.
  * Bigger models don't pay.
  * 8-bit integer scoring is within ±0.002 of the float result.
* **Corrections to the old study** are in Appendix A. Don't cite its
  graph or lzw numbers.

## 4. Kernel and user-program changes you need to know about

These affect anything you run in xv6, the benchmarks included:

* **LFU (`VM_POLICY_LFU`) livelock fixed** (`160e238`). LFU now uses the
  decayed counter from GawwyDev `d1d247f`: at each scan,
  `freq = (freq >> 1) + accessed`. A fresh page counts its fault-in touch.
  The `LFU_DEBUG` printk is gone. `data-invariance` passes under LFU.
* **New policy `VM_POLICY_ML` = 4** (`a60faaa`), so `VM_POLICY_COUNT` is now
  5:
  * **Selection**: `choose_ml()` in `kernel/vmpage.c` scans every candidate
    (reads and clears `PTE_A`, like Aging), computes an integer score
    Σ qa[j]·X_j and evicts the highest, oldest load first on a tie.
    Probation is applied.
  * **Features** come from `kernel/mlfeat.h` (Q8 fixed point, table
    `log1p`, no floating point, no libgcc).
  * **Bookkeeping**: new `struct vm_page` fields `ml_load_scan`,
    `ml_last_seen`, `ml_rdist`, `ml_sfreq`, `ml_refaults`, `ml_seen`. The
    kernel also keeps a per-swap-slot record of the eviction scan and
    refault count, and a per-process scan counter `vm.ml_scans`.
* **ABI changes** in `kernel/vmstats.h`:
  * `VMSTATS_VERSION` is now **3**.
  * New `vmctl` op `VM_SET_ML_WEIGHTS` (11), taking a
    `struct vm_ml_weights` (`n`, `feat[8]`, `qa[8]`, `protect_age`).
  * Weights are per process, inherited on fork and kept across exec. The
    default is the global model in `kernel/mlweights.h`.
  * New stats fields `select_ticks` (timer ticks spent choosing a victim)
    and `candidates_scanned` (eligible list size), counted for every
    policy.
  * Anything that parses `struct vmstats` must be rebuilt.
* **New `user/vmrun`**: `vmrun <fifo|clock|aging|lfu|ml> [model] <prog>
  args…`. It runs a program under a policy, optionally with one of the 12
  named models in `user/mlmodels.h`: `global`, `global-k`, and
  `<workload>`/`<workload>-k` for btree, graph, kv, matmul and sort.
  `vmtest`, `prefetchtest` and `policydemo` accept `ml`/`lfu` as policy
  names.
* **`user/sh.c`: `MAXARGS` 10 → 16**, so long `vmrun` command lines fit.
* **Benchmark fairness fix in `user/vmbench.c`, which changes numbers.**
  Each process's baseline is sized by the burn phase, and
  `vmbench_burn()` now always runs it under **FIFO**, then restores the
  process's policy. Before, the burn settled differently per policy: for
  the same matmul run, Clock 13 resident pages, Aging 9, ML 28. So each
  policy effectively got a different memory size, and ML looked impossibly
  good, below Belady. Your trace collections ran under FIFO and are
  unaffected. Any **non-FIFO benchmark numbers measured before this fix**
  are not comparable to new ones.

## 5. In-kernel evaluation (details: week-14 report §2.4, §4.5)

**Setup.** All 33 test and held-out streams were run in xv6 at 10%
memory, under 7 policies:

* FIFO, Clock, Aging and LFU;
* ML with the global weights;
* ML with the workload's own weights;
* ML with the workload's kernel-only weights.

That is 231 runs, all of which completed, measured with the kernel's own
counters. The run tool is `tools/ml2/kernel_eval.py`, which uses 6 lanes
and is resumable.

**Results with per-workload weights**, faults vs Clock (test / held-out):

| Workload | Test | Held-out |
|---|---|---|
| btree | −17.7% | −14.6% |
| graph | −38.6% | −45.9% |
| kv | −12.9% | −12.5% |
| sort | −4.0% | −6.7% |
| matmul | — | −2.7% |

* **Page writes**: graph −95.5% / −86.2%, matmul −96.5%.
* **Global model**: it beats Clock except on matmul (+11.5% faults).
* **The simulator predicts the kernel.** Median kernel/simulator ratio is
  0.94–1.07, with two exceptions:
  * **FIFO** is worse in the kernel. It probably evicts the hot code and
    stack pages that the traces don't contain; not verified.
  * **One PageRank stream sits on a capacity cliff.** The kernel gives it
    about 2 extra frames (`kernel_cliff.csv`).
* **Cost.** ML takes about 4 timer ticks per page in memory, because every resident page is scored: 88 ticks (9 µs) on sort with ~10 pages up to ~1,000 ticks (100 µs) on btree with ~250 pages, i.e. 2.5–32× Clock and ~2× Aging. That's the main weakness.
* **Lanes run QEMU disks with `cache=unsafe`.** This is host-side only:
  counters are identical and runs are about 1.5× faster. The real
  `Makefile` is untouched.

## 6. Test status of the current kernel

Run 2026-10-01 against `94c503d` (CPUS=1):

| Test | Result |
|---|---|
| `vmtest all` | PASS |
| `vmtest all-policy ml` | PASS |
| `vmtest all-policy lfu` | PASS |
| `prefetchtest all ml` | PASS |
| `prefetchtest all lfu` | PASS |
| `vmtest data-invariance` | PASS (all 5 policies give checksum `AB0C8578`) |
| `vmrun ml vmtest random 1 100000` | PASS |
| `vmrun ml vmtest random 17 100000` | PASS |
| `usertests -q` | PASS (ALL TESTS PASSED, 346 s) |

The full `tools/phase2_gate.sh` matrix (debug build, the 10-seed soak and
the rest) was **not** re-run. It also still has your paths
(`/mnt/d/thesis`, `/home/ashfaq`) hard-coded.

`run_xv6_tests.py` picks the PASS marker from the first word of the
command, so a `vmrun …` command is reported as FAIL even when the program
printed `vmtest: random: PASS`. Read the transcript, or teach
`pass_marker()` to skip a `vmrun <policy> [model]` prefix.

## 7. How to reproduce

Run everything from `tools/ml2/`. You need Python 3.12, NumPy, PyTorch
(CUDA only matters for neural training) and gcc. GawwyG's venv is
`~/.venvs/xv6ml` (NumPy 2.5, torch 2.6+cu124).

```
python3 tools/stream_dataset.py prepare   # (your tool, repo root) traces2/ -> traces2/ML
cd tools/ml2
python3 validate.py && python3 validate_kernel.py   # simulator checks
python3 classical.py                                 # classical baselines
python3 build_datasets.py                            # training sets  (~3 min)
python3 sweep_linear.py --fracs 0.1                  # all 300 feature sets (~75 min, 6 threads)
./train_all_nn.sh                                    # neural/ranking models (~25 min, GPU)
./run_phase_b.sh                                     # selection, test, extras (~1.5 h)
python3 export_kernel.py                             # kernel/mlweights.h, user/mlmodels.h
python3 kernel_eval.py --lanes 6 --fracs 0.1         # in-kernel runs (resumable; 5.5 h lane time)
python3 kernel_vs_sim.py                             # same runs in the simulator + cliff check
python3 analyze.py && python3 tables.py && python3 figures.py   # summaries, tables.md, slide tables
python3 report_figs.py && python3 report_tables.py   # final report: figures, tables, quoted numbers
cd ../../report/week_14_update && pdflatex week_14_update_report.tex && pdflatex week_14_update_report.tex
cp week_14_update_report.pdf ../week_14_update_report.pdf
cd ../slides && pdflatex ml_results.tex && pdflatex ml_results.tex
```

**Numbers are never typed by hand.** `analyze.py` → `tables.py` regenerate
`results2/tables.md` and the slide tables. For the final report,
`report_figs.py` makes the figures and `report_tables.py` makes every results
table plus `tables/numbers.tex`, which holds every number the text quotes
(used as `\val{key}`). Percentages and times carry one decimal, computed from
the 4-decimal summaries.

## 8. What is still open (suggested next steps)

1. **Cheaper selection.** *Done in week 15 (sampled scoring, `vmrun ml model@k`); remaining: a full-eviction-path
   timer and a no-op policy arm to calibrate the selection-tick counter.*
2. **In-kernel runs at 5% and 20%**:
   `python3 kernel_eval.py --fracs 0.05,0.2`. It needs no changes, just
   hours of QEMU time, and would show the kernel result isn't specific to
   10%.
3. **Pick weights automatically** per program or phase. The mechanism
   (per-process weights, `vmrun`) exists. The global model losing on matmul
   is the case to beat.
4. **Capacity-aware graph models** (the simulated gain is concentrated at
   10%).
5. **Explain the two kernel/simulator gaps**:
   * FIFO: count per-VPN faults for non-arena pages.
   * The global model on the PageRank cliff stream.
6. **Linux port** (a plan only; nothing was run):
   * **Features from state Linux already keeps.** `idle` → the folio's MGLRU
     generation relative to the youngest (generations age by page-table
     walks, as xv6's scans do); `sfreq` → MGLRU's per-folio reference tier;
     `dirty` → `PG_dirty`; `refaults`, `rdist` → the eviction timestamp that
     `mm/workingset.c` stores in a shadow entry and the refault distance it
     computes on refault. All are integers already.
   * **Where to score.** MGLRU evicts folios in batches from the oldest
     generation; the learned score would rank the folios of a batch with the
     same integer dot product and probation rule, falling back to the stock
     order when no weights are loaded.
   * **Training data.** A reference string per workload (PEBS/IBS sampling
     or binary instrumentation), replayed in the same simulator with
     Linux-faithful aging.
   * **Evaluation.** Against stock MGLRU and the classic active/inactive LRU
     under the same memory-cgroup limits: refaults, writeback, and reclaim
     CPU time.
7. **Not covered**:
   * lzw: covered since week 15 (see the addendum);
   * kvbench's TTL mode;
   * the real Redis/SQLite traces: covered in the simulator since week 15 (not in the kernel).

## 9. Gotchas hit along the way

* **Stale `fs.img`**: after changing a user program, make sure `fs.img` is
  rebuilt, or you run the old binary.
* **Lanes need their own `fs.img`**: the swap area lives in it, so lanes
  can't share one. `kernel_eval.py` rsyncs a private copy of the tree per
  lane.
* **`pkill -f`/`pgrep -f` match their own shell**: a pattern like `qemu`
  kills the command running it. Use `[q]emu`.
* **Runtime**: graph streams take 2–25 min each in the kernel. The other
  workloads take at most about 3 min.

---

# Appendix A: the earlier `traces/` study, compressed (superseded)

Before `traces2`, GawwyG ran a study on the old `traces/` captures
(2026-09-25 to 09-27). Its scripts were `tools/ml_*.py`,
`handwritten_policy_sweep.py` and `sim.py`. Its results are in
`report/ML_TESTING_REPORT.md`, `report/*.csv` and `report/models/`.

* **It was superseded.** Its splits used the same stream at two
  capacities, not unseen runs. And two of its seven traces were broken:
  graph recorded only the edge array, and lzw was truncated.
* **Do not cite:** "global_frequency beats Clock by 4.3% on graph",
  "hand-written LFU −24% on lzw", or its "stack distance" feature, which
  counted first-ever touches.
* **What carried over** into the current study:
  * A feature only helps if it varies **across the candidates of one
    eviction decision**. `position` correlated with the label but changed
    nothing.
  * Static per-page preferences, and LFU-like scores, can be catastrophic
    on small cyclic working sets (sort, matmul).
  * Model capacity mattered far less than features.
  * Evaluate with one batched scoring call per eviction.

The full original text is in git:
`git show fb1ab93:AUSTRA_HANDOFF.md`.

## AU5TRA's answers (to §0.2)

*(Her agent fills this in.)*
