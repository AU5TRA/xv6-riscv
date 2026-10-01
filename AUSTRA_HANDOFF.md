# Handoff to AU5TRA: everything done on the ML side (as of 2026-10-01)

**Written for**: AU5TRA, picking up after GawwyG's work of 2026-09-28 to
2026-10-01. This file covers what was built, where every result lives, what
changed in the kernel and user programs you work in, what was tested, and
what is still open. The full write-up is `report/ML_REPORT.md` (also as
LaTeX/PDF). This file is the map to it.

**The short version.** On your `traces2` streams, a learned linear score
over 4–5 kernel-observable features beats Clock on all five workloads, on
unseen seeds and on unseen variants. It now runs inside xv6 as
`VM_POLICY_ML`, integer-only, and beats Clock there too. Its per-workload
weights give 3–46% fewer faults and up to 96% fewer page writes. The old
`traces/` study is superseded (Appendix A summarises it); two of its
headline results came from broken traces and must not be cited.

**Read first**:
* `report/ML_REPORT.md` — Summary, then §8b (in-kernel results).
* `report/slides/ml_results.pdf` — the 39-page deck. The kernel section is
  slides 24–29.

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
plan only (report §9.1). The open items are in §8.

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
| `94c503d` | GawwyG | LaTeX/PDF version of the report (`tools/ml2/md2tex.py`) |

All of this is on `riscv`. If `origin/riscv` doesn't have these commits
yet, GawwyG still has to push them.

## 2. Where everything is stored

| Path | What | In git? |
|---|---|---|
| `report/ML_REPORT.md` | **the report**: method, every result table, failures, kernel work, Linux plan | yes |
| `report/ML_REPORT.tex`, `report/ML_REPORT.pdf` | the same report as LaTeX/PDF (28 pp.), generated from the `.md` | yes |
| `report/slides/ml_results.tex`, `.pdf` | the presentation (39 slides); `slides/tables/*.tex` are generated tables | yes |
| `report/results2/` | **every raw result** as CSV, plus summaries and `tables.md` (every table in the report) | yes |
| `report/models2/` | every trained model: `linear_<scope>.json` (300 feature sets per scope), `final_linear.json` (**the selected models**), `nn/` (84 neural/ranking models), `linear_dagger.json`, `v1/` (first version) | yes |
| `report/figures2/` | figures, PNG and PDF | yes |
| `tools/ml2/` | all the code (§7 lists each script) | yes |
| `kernel/mlfeat.h`, `mlfeat_table.h`, `mlfeat_mant.h` | the integer feature code, shared by kernel and simulator | yes |
| `kernel/mlweights.h`, `user/mlmodels.h` | generated weights: the kernel default, and all 12 named models for `vmrun` | yes |
| `traces2/` (3.7 GB) | your streams; `traces2/ML/` is the dataset made from them; `traces2/ml2_cache/` holds the training sets | **no**: regenerate (§7) |
| `test-logs/kernel_eval/` | the 231 in-kernel transcripts, referenced from `kernel_eval.csv` | **no**: only on GawwyG's machine |
| `report/ML_TESTING_REPORT.md`, `report/models/`, `report/*.csv` | the earlier `traces/` study | yes, **superseded** |

Report §12 lists every CSV in `report/results2/`.

## 3. The `traces2` study (details: report §2–7)

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
  protected for *p* scans). Report §7.
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

## 5. In-kernel evaluation (details: report §8b)

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
| btree | −18% | −15% |
| graph | −39% | −46% |
| kv | −13% | −13% |
| sort | −4% | −7% |
| matmul | — | −3% |

* **Page writes**: graph −95% / −86%, matmul −96%.
* **Global model**: it beats Clock except on matmul (+12% faults).
* **The simulator predicts the kernel.** Median kernel/simulator ratio is
  0.94–1.07, with two exceptions:
  * **FIFO** is worse in the kernel. It probably evicts the hot code and
    stack pages that the traces don't contain; not verified.
  * **One PageRank stream sits on a capacity cliff.** The kernel gives it
    about 2 extra frames (`kernel_cliff.csv`).
* **Cost.** ML takes about 400–450 timer ticks per eviction vs Clock's 35,
  because it scores all ~106 pages. That's the main weakness.
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
python3 analyze.py && python3 tables.py && python3 figures.py && python3 fill_report.py
python3 md2tex.py --pdf                              # report/ML_REPORT.tex and .pdf
cd ../../report/slides && pdflatex ml_results.tex && pdflatex ml_results.tex
```

**Never hand-edit numbers in the report.** `analyze.py` → `tables.py` →
`fill_report.py` regenerate every table at its `<!-- T:name -->` marker.

## 8. What is still open (suggested next steps)

1. **Cheaper selection.** Score a sample or batch of candidates, as MGLRU
   does with generations, instead of all ~106 per eviction. This is the
   biggest gap between the current kernel version and a deployable one.
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
6. **Linux port**: a plan only, in report §9.1. It maps `idle`, `sfreq`,
   `dirty`, `refaults` and `rdist` to MGLRU, DAMON and `mm/workingset.c`
   signals.
7. **Not covered**:
   * lzw (its trace exceeds xv6's maximum file size);
   * kvbench's TTL mode;
   * the real Redis/SQLite traces in `traces/old/`.

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
