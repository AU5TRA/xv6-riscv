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
