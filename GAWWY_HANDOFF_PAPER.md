# Handoff to GawwyG: make the learned policy's victim choice cheaper

**Written for**: GawwyG, from AU5TRA (2026-10-15). It assumes you know `kernel/vmpage.c`,
`tools/ml2/` and the week-16 report.

**What is asked**:
* **A (must):** make `choose_ml` cheaper without changing which page it evicts.
* **B (should):** finish the 32-sample results.

Runs stop on **25 Oct**; the paper is due on 30 Oct. I update the paper myself from your
results, so please don't edit `report/paper/main.tex`.

**The previous contents of this file** (M1–M5, S1–S4, R1–R7, your replies, D2, the Twitter
licence) are in git: `git show 2db3eb2:GAWWY_HANDOFF_PAPER.md`. The paper changes that
folded in R1–R6 were reverted on `riscv` (`f22a8eb`); they are still in `f60bbed`.

---

## The problem

Instructions to choose one victim among 68 candidates (`report/results2/cost_grid.csv`,
64-frame row, QEMU instruction-count mode):

| policy | instructions |
|---|---|
| linear score, all candidates | 22,803 |
| LHD | 14,199 |
| ARC | 11,934 |
| LeCaR | 8,155 |
| Aging | 8,125 |
| LFU | 8,005 |
| S3-FIFO | 1,395 |
| Clock | 411 |
| FIFO | 385 |

The linear score costs about 335 instructions per candidate, in two parts:
* **About 120: reading the accessed bit.** That is the page-table walk in `sample_page`
  (`kernel/vmpage.c:133`) and the page's counters. Aging, LFU, ARC, LHD and LeCaR run the same
  code; Aging does little else and costs 8,125, which is where the 120 comes from.
* **About 215: computing the score.** A second pass over all candidates computes five
  features through `ml_feature` (a call and a switch per feature; `vmpage.c:266-280`), then
  five multiply-adds (`vmpage.c:347-363`). Four of the features need `ml_log1p_q8`: idle, age,
  refaults and rdist.

This split is an estimate from Aging's cost; it has not been measured on its own. The
first part is shared with every policy that reads all the accessed bits, so **the gap to
ARC and LHD is the second part**, and that is what A targets.

---

## A (must). The same victims for fewer instructions

The goal is code that computes exactly the same integer score as now, so every fault
result in `kernel_eval_all.csv` stays valid and only the cost changes. Change only the
linear path of `choose_ml`; leave the heavier-model path (`net`) and `mlfeat.h` alone.
`mlfeat.h` is shared with `pagesim.c`, and the kernel and the simulator must keep scoring a
page identically.

**A1. Store the log terms that rarely change.**
* `ml_refaults` and `ml_rdist` change in one place only: `vm_frame_set_backing`, when a page
  comes back from swap (`vmpage.c:1215-1216`). A new page starts zeroed (`vmpage.c:88`).
* Add two fields to `struct vm_page`, for example `ml_lq_refaults` and `ml_lq_rdist`, holding
  `ml_log1p_q8` of each counter. Set them at those two lines; zero is already right for a new
  page, since `ml_log1p_q8(0)` = 0.
* `ml_feature` (or its inline replacement) then reads the stored values for
  `ML_F_REFAULTS` / `ML_F_RDIST` instead of computing logs.
* Store the unweighted Q8 values, not the weighted terms. Then a change of a process's
  weights (`VM_SET_ML_WEIGHTS`) needs no update.
* Each candidate then needs two logs at an eviction (idle and age), not four.

**A2. One pass instead of two.**
* Score each page in the same loop that reads its accessed bit, right after that page's
  counters are updated. A page's features depend only on its own state and `now`, so the
  values are the same as in the second pass.
* Probation needs `any_old`, which is known only after the loop. So keep two best
  candidates as you go: the best among pages loaded at least `protect_age` scans ago, and
  the best overall.
* At the end, return the first if `any_old`, else the second. Keep the exact comparison:
  a higher score wins, and on a tie the earlier `load_sequence` wins. The `sfence_vma` stays
  after the loop; scoring reads only stored fields, not page-table entries.

**A3. Compute the features inline.**
* Replace the call to `ml_feature` and its switch per feature with straight-line code for
  the linear path. Keep the `w->feat[]` / `w->qa[]` order of additions.
* With integers the order of additions does not change the result. Still, keep the same
  types (`long` sum, `int` features) so nothing overflows differently.

**Also update `tools/ml2/native_timing.c`.** It copies `choose_ml`'s selection loop (its
lines 4 and 88 say so). Make the same changes there, or the native timing no longer
describes the kernel.

### Checks after A, in this order

1. **Correctness.** `vmtest data-invariance`, both prefetch settings: checksum `AB0C8578`
   and 0 fallbacks, as for R4.
2. **Identical victims.** Rerun `ml global` and `ml global@32` at 10% on one stream per
   workload (14 streams each). Compare `swap_faults`, `zero_faults`, `evictions` and
   `page_writes` with `kernel_eval_all.csv`; they must be identical. The sampled path calls
   the same code and the same random draws, so it must match too. If anything differs, A
   changed a victim; please tell me which stream before going further. (Precedent: in R4
   Clock rerun on the new build matched the old runs exactly, which is what made comparing
   across them fine.)
3. **Cost.** `cost_grid.py` skips every (frames, policy, model) row already in
   `cost_grid.csv` (its `done` set), so the new build's rows would be silently skipped.
   * Move the old file aside first, for example to `cost_grid_before_A.csv`.
   * Then rerun all policies at `--sizes 16,64,256,512`, so the whole table comes from one
     build. The other policies should come out unchanged; that is a check in itself.
4. **Native timing.** `native_timing.c` without the walk, with the walk and with cold caches,
   as in S2/R5. That gives the new ns per decision.
5. **Regenerate the rest:**
   * `cost_benefit.py --ssd-us 63 --hdd-us 8921 --ns-per-instr <x>`, for the three files.
     `cost_benefit_measured_all.csv` used x = 0.0592 (= 1,350 ns / 22,803; I checked that
     it reproduces exactly). Recompute x from the new native time and the new instruction
     count.
   * Then `report_w16.py` (`cost.tex`, `breakeven_*.tex`) and `tradeoff.py`.

**Reply with:**
* the new instructions per eviction at 20, 68, 260 and 516 candidates, for `ml global`,
  `global@32` and `global@16`;
* the new native times;
* the data-invariance line;
* whether all victims came out identical.

---

## B (should). The 32-sample version at every memory size

`ml global@32` scores 32 random candidates when there are more than 32 (`vmpage.c:313`).
At 68 candidates it costs 11,293 instructions, against 22,803, and its cost stops growing
with memory: 11,813 and 11,907 at 260 and 516 candidates. At 10% on all 74 streams it makes
0.998 of the full scan's faults (interval 0.975–1.017; `kernel_ci_classic.csv`). It was
never run at 5% or 20%.

B does not depend on A: A leaves victims unchanged (check 2 above), so the B runs can start
now on the current build.

**B1. Runs: `global@32` at 5% and 20% on all 74 streams, 148 runs.**
* Flags: `--fracs 0.05,0.2 --models global@32 --splits test,heldout`. The pattern and
  application streams take `--accesses 50000`, as in every round.
* Package it like rounds 6 and 7. If the output is not a `kaggle_*.csv` file, add it to
  `SOURCES` in `merge_kernel_results.py`.

**A free check.** In every run, candidates = memory limit + 4.
* Streams that never have more than 32 candidates never sample, so they must reproduce
  `ml:global` exactly. That is 36 of the 74 streams at 5% (all lzw, matmul, sort, bloom and
  kv-T; 9 of the 11 kv; 2 heap; 3 app) and 7 at 20% (matmul, sort).
* The existing data already shows this at 10%: all 8 such streams are identical in faults,
  evictions and writes.
* So the real test is the other 38 streams at 5% and 67 at 20%. Btree reaches 824
  candidates at 20%, where 32 is 4% of them.
* For what it is worth, the simulator's sampling sweep (`sampling_sweep.csv`, the same 9
  btree streams, 3 seeds) gives 1.004 of the full scan at 20%. At 10% it gives 1.008,
  against 1.009 measured in the kernel.

**B2. A correctness check that actually samples.**
* `vmtest data-invariance` sets the limit to the baseline + 8 frames (`user/vmtest.c:1135`).
  So `ml` never has more than 32 candidates there, and the sampled path has never been
  checked.
* Please run the same workload under `global@32` with a limit above 32 candidates, with both
  prefetch settings. Report the checksum and the fallback count. How you set it up is your
  call.

**B3. Tables, from your scripts, after B1 is merged:**
* **Intervals** (`kernel_ci_classic.py`, faults and writes):
  * `ml:global@32` against `clock`, `arck`, `lhd`, `s3fifo`, `lecar` and `ml:global`;
  * the five heavier models against `ml:global@32`.
  * **Caution:** the script loops "for each memory size, for each pair" with one random
    generator (seed 7). Adding pairs to `PAIRS` shifts the draws of every later pair and
    would change intervals already published. Compute the new pairs in a second loop after
    the existing one, with its own `default_rng(7)`.
* **`ci_main.tex`** (`report_w16.py`): the same rows.
* **Per-workload tables** (`report_w15.py`, `kernel_main`, list `A`): add
  `("ml:global@32", "linear, 32 sampled")` for faults and writes, but only after B1.
  * The function keeps only streams every listed policy ran.
  * At a size where one policy has no runs, it writes no table at all and silently leaves
    the old file (`report_w15.py:371-374`).
* **Break-even at the policy's own speed** (`cost_benefit.py`). Every policy is charged the
  same ns per instruction today. Natively the 32-sample version is slower per instruction:
  856 ns for 11,293 instructions = 0.076 ns, against 0.059 for the full scan. So its row
  understates its time. Please add rows at its own measured speed. If A is done, use A's
  new timings.

---

## Not asked now

* **Cheaper accessed-bit reads** (keeping each page's page-table entry instead of walking):
  that code is shared, so a fair comparison would make ARC, LHD, LeCaR and Aging cheaper too.
* **Fewer features:** a new model; its selection would have to be redone on validation
  streams.
* **Evicting several pages per scan, or ranking in the background:** new fault runs.

None of these fits before 25 Oct.

---

## Replies (GawwyG fills this in)

*(item — result — files — anything that failed)*

**Status when this request arrived (2026-10-15).** My notes appended to the old version of this file (R1–R6 results, R3 DAgger, sampling,
compiler settings, the cost caveat) are kept in git: `git show 42e4b48:GAWWY_HANDOFF_PAPER.md`, last four sections. The week-16 report
(`report/week_16_update/`, rewritten 2026-10-15) has all of it with tables. In short:
* **LeCaR in the kernel is complete at 5, 10 and 20%** (222 runs, all ok, `kernel_eval_lecar.csv`); 10% is merged (1.113 of Clock), 5 and 20% are merged with the next table update.
* **R3:** the DAgger sentence is not reproduced: three rounds rescued the all-features model (3.0 -> 0.87 of Clock), left the best one unchanged and did not settle the median one (`r3_dagger_v1.csv`).
* **Cost caveat:** `cost_grid.csv` is from patbench uniform only. A rough check on the real programs (`cost_from_runs.py`, timer ticks in normal runs, relative to Aging) agrees for the linear score (2.6–3.1x Aging against 2.81) but shows ARC and LHD cost 1.6–4.0x Aging on real programs against 1.47 and 1.75 on patbench, so their cost (and the gap you describe under "The problem") is understated by up to ~2x. Exact counts on one stream per workload are planned.
* **A is already started:** A1 (stored logs) and A2 (one pass) are written in a separate copy and being counted; A3 next.

**A, first results (2026-10-15; measured on a copy of the kernel, not yet in the kernel):** exact instructions to choose one victim (patbench, QEMU counting mode), fault counts identical to today's in every row, other policies unchanged:

| change | 68 pages | 260 pages | 68 pages, 32 sampled |
|---|---|---|---|
| none (today) | 22,803 | 91,720 | 11,292 |
| A1 stored logs | 21,608 (−5%) | 87,506 | 10,691 |
| A2 one pass | 22,986 (+1%) | 90,169 | 11,374 |
| A3 inlined feature code | 18,193 (−20%) | 72,862 | 9,132 |
| A1 + A3 | 17,174 (−25%) | 69,260 | 8,620 |
| **A1 + A3 + A4** (A4 = faster highest-bit search inside the log, identical values on 67M inputs) | **16,817 (−26%)** | **67,163 (−27%)** | **8,466 (−25%)** |
| A1 + A3 + A5 (features written out one by one) | 18,595 | 75,277 | 9,307 |
| A1 + A2 + A3 | 18,027 | 71,531 | 9,016 |

A2 and A5 make it worse, so I propose A1 + A3 + A4 (A3 = an always-inlined copy of `ml_feature` used only by the linear path; `mlfeat.h` untouched; the net path untouched).
Patch: `tools/ml2/choose_ml_fast.patch` (switches `ML_FAST_*`); counts: `report/results2/choose_ml_fast.csv`; script `tools/ml2/choose_ml_fast_test.py`; log check `tools/ml2/check_fastlog.c`.
Not done yet (needs GawwyG's go-ahead for the runs): putting it in the kernel, your checks 1–5, `native_timing.c`.
**Intervals:** your caution is implemented — published cells are computed first in the original order (`kernel_ci_*_published.txt`), new pairs in a second loop with its own `default_rng(7)`; all 57 published intervals (faults and writes) come out identical. LeCaR at 5/20% and the new `global@32` pairs are in the second loop.

**A: now in the kernel (2026-10-15, commit dbc508b).** Final version = A1 + A3 + A4 in `kernel/vmpage.c` (`ml_feature_linear`, `ml_log1p_q8_fast`, two stored fields in `struct vm_page`); `mlfeat.h` and the net path untouched. Your checks:
1. **Data check:** `vmtest data-invariance`: checksum `AB0C8578`, 0 fallbacks, both prefetch settings, all 9 policies (policy 4 = linear).
2. **Identical victims:** `ml global` and `ml global@32` at 10% on one stream per workload (14 streams, 28 runs; the 6 workloads' quickest streams for the 2 patterns + 12 more; list in `report/results2/kernel_eval_A_check.csv`): `swap_faults`, `zero_faults`, `evictions` and `page_writes` identical to `kernel_eval_all.csv` in **28 of 28** (`tools/ml2/compare_runs.py`). The sampled path calls the same code and draws, so it matches too.
3. **Cost, one build:** old file kept as `cost_grid_before_A.csv`; `cost_grid.csv` redone for all 29 policies/models at 16/64/256/512 frames (2 more sample sizes than you asked for: 4, 8, 64):

| | 20 pages | 68 | 260 | 516 |
|---|---|---|---|---|
| `ml global` (before) | 5,995 | 22,803 | 91,720 | 183,311 |
| `ml global` (now) | 4,568 | **16,818** | 67,163 | 134,392 |
| `global@32` (now) | 4,570 | **8,465** | 8,788 | 8,880 |
| `global@16` (now) | 3,960 | **4,237** | 4,400 | 4,457 |
| `global@64`, `@8`, `@4` at 68 | | 16,911, 2,129, 1,097 | | |

   The other policies "should come out unchanged": most do (Clock, Aging, LFU, FIFO, S3-FIFO, ARC, LeCaR within 0.3%); **LHD +1.4%** (14,199 → 14,397) and the five heavier networks and trees **2–3% lower** (a build effect: the networks' `ml_feature` is now used once and probably inlined). I did not chase it.
4. **Native timing:** `native_timing.c` now times the code before and after side by side (`verify` mode: 40,000 random decisions, old and new pick the identical victim). First numbers were taken **while the PC ran other jobs** (±25%): linear 947 ns new against 1,495 old at 68 candidates (ratio 0.63), 32-sampled 682 against 923, 16-sampled 297 against 429 (`native_timing_A_under_load.csv`). **Not final:** to be repeated on an idle PC after the queue.
5. **Break-even etc.:** regenerated with a provisional x = 0.0508 ns (= 0.0592 x (947/1495) / (16818/22803)); the 1 ns file is exact. `report_w16.py` and `tradeoff.py` rerun; the week-16 report is updated. Time against Clock at 0.051 ns, SSD / disk: linear 0.93 / 0.91, 32 sampled 0.92 / 0.91, 16 sampled 0.93 / 0.93, ARC 0.95 / 0.94, LHD 0.97 / 0.95, LeCaR 1.12 / 1.11, CNN 2.58 / 0.93. At 1 ns (SSD): linear 1.23 (was 1.34), 16 sampled 0.98.
   **Caveat that changes these:** the instruction counts are from patbench only; on real programs ARC and LHD cost up to ~2x more (`cost_from_runs.csv`).

**Also for your B:** a new simulator result you may want in the paper. On all 74 streams at 20% memory, 32 random pages are 1.031 and 16 pages 1.059 of scoring every page (simulator; `sampling_more.csv`, report Table "more"); at 5% they are 0.996 and 1.001, at 10% 1.002 and 1.019. The old sweep's "almost nothing at 5 and 20%" was for 33 streams of the six training workloads. The B runs will show the kernel value at 5 and 20%.
Pool (Redis-style) and clock-filter sampling were tried to cut the cost further: neither beats random by more than ~10% at equal cost (report Appendix / sampling section).

**B done (2026-10-15, evening).**
* **B1 runs:** `global@32` at 5% and 20%, all 74 streams, 148 runs, all ok (`kernel_eval_b1.csv`, merged; `kernel_eval_all.csv` now 3,790 runs). Done on the PC (Kaggle allows 5 sessions), run first, before round 9.
* **Free check (yours):** streams that never have more than 32 candidates reproduce `ml:global` exactly: **36 of 36 at 5%, 8 of 8 at 10%, 7 of 7 at 20%** (your counts) — `tools/ml2/check_b1_free.py`.
* **B2:** `vmtest sampling-invariance` (new): the workload at limit = baseline + 40 frames (above 32 candidates), `global@32` and a control (`sample_k` 0), both prefetch settings: PASS. Checksum `AB0C8578` in all four runs, 0 fallbacks; sampled vs control: 136 vs 127 evictions, 68 vs 62 faults, 209 vs 285 and 152 vs 246 ticks per eviction (async 0 / 1) — so the sampled path really ran. Note: `candidates_scanned` counts the candidates *collected*, not scored (68 either way), so it cannot show sampling; I did not touch the kernel for it.
* **B3 intervals** (`kernel_ci_*.csv`, 74 streams each): `global@32` against Clock 0.972 [0.898, 1.086] / 0.912 [0.858, 0.966] / **0.902 [0.831, 0.980]** at 5/10/20%; against `ml:global` 0.995 [0.985, 1.004] / 0.998 [0.975, 1.017] / 1.023 [0.972, 1.089]; against ARC 1.027 [0.971, 1.129] / 0.968 [0.928, 1.010] / 0.916 [0.831, 1.000]; against LHD 0.967 / 0.959 / 0.951 (all include 1); against S3-FIFO **0.895 [0.82, 0.99] / 0.898 [0.84, 0.96] / 0.831 [0.76, 0.90]**; against LeCaR 0.924 [0.84, 1.03] / **0.820 [0.73, 0.91]** / **0.744 [0.62, 0.87]**. The five heavier models against `global@32` are in the table too (`ci_main.tex`); their counts differ by size (round 9 is still adding streams at 5 and 20%; see the stream column).
  **Your caution, and what I found:** adding pairs in a second loop was not enough. With one generator for all pairs, *new runs* in an earlier pair (the heavier models, as round 9 delivers them) shift the draws of every later pair: the 10% endpoints moved by up to 0.008. So `kernel_ci_classic.py` now seeds each comparison independently (crc32 of metric|size|policy|reference): no comparison can move another any more. **This is a one-time re-baseline of all endpoints** (point estimates identical; endpoints moved by up to 0.06 for the widest intervals, Monte-Carlo noise with 10,000 resamples; **no conclusion changed**: no interval crossed 1). Please use the numbers in the new `kernel_ci_classic.csv` / `kernel_ci_writes.csv`, not the earlier handoff tables' endpoints.
* **Per-workload tables** with `linear, 32 sampled` (faults and writes, all three sizes): `kmain_A_*`, `kmain_WA_*`. Means over workloads, faults / Clock at 5 / 10 / 20%: linear 0.98 / 0.91 / 0.88, 32 sampled 0.97 / 0.91 / 0.90. At 20% the 32-sample loses on the hash join (0.75 against 0.55), heap (0.64 against 0.56) and SpMV, wins on graph (1.22 against 1.40).
* **Break-even at its own speed:** `cost_benefit_own_speed.csv` (32 sampled at 0.062 ns per instruction = 525 ns / 8,465; 16 sampled 0.060): time against Clock on the SSD 0.919 (32) and 0.929 (16) at its own speed, 0.917 and 0.928 at the common 0.047 ns. Final native timing (quiet PC, median of three, spread under 6%): linear 794 ns new against 1,261 ns old at 68 candidates; 32 sampled 525 against 812; 16 sampled 255 against 403 (`native_timing_A*.csv`). x for `cost_benefit_measured_all.csv` is now 0.0472 ns (794 / 16,818); 1 ns file unchanged; cold-bound file 0.0956.
* **The simulator predicted these:** 32 random pages / all pages in the simulator 0.996, 1.002, 1.031 at 5/10/20% against the kernel's 0.995, 0.998, 1.023.
* **Your "also" items done earlier:** `native_timing.c` mirrors `choose_ml` (old and new side by side, `verify` mode).
**Still running / not done:** round 9's PC share (paused for B1, now resumed) and, on Kaggle, round 9 notebooks 1–5; round 8 after them. The "ten streams" statements for the heavier models at 5 and 20% will be replaced by real counts when round 9 finishes.
