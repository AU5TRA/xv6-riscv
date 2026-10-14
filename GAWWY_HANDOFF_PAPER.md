# Handoff to GawwyG: what the paper still needs from the experiments

**Written for**: GawwyG, who runs the experiments, from AU5TRA (2026-10-12). It
assumes you know `tools/ml2/` and the week-16 report. It does not assume you have
looked at the paper draft.

**Status**: the paper draft is in `report/paper/` and builds (10 pages, references
from page 10). It is built on your week-16 results and your START HERE section in
`AUSTRA_HANDOFF.md`. This file lists what is missing, in the order it is needed.
Each item says why a reviewer will ask, what to produce, and where it goes in the
paper. Rough effort estimates are guesses; replace them with yours.

**Read first**: `report/paper/paper-state.md`. Its "Numbers" table lists every number
the paper quotes and its source file.

**Picking this up.** `riscv`, `Austra-dev` and `GawwyDev` all point to the same
commit on GitHub. Your branch only moves forward from your last push (`f83fa21`).
The new commits add `report/paper/` and this file, and touch none of your files.

```
git fetch origin
git checkout GawwyDev
git pull --ff-only origin GawwyDev
```

* If you have local commits you never pushed, use `git pull origin GawwyDev` (a merge)
  instead. Nothing you wrote was changed, so it should not conflict.
* To build the paper: `cd report/paper && latexmk -pdf main.tex` (TeX Live or MiKTeX).
  It reads your tables from `report/week_16_update/tables/`, so regenerate those first
  if you want the PDF to show new numbers.

---

## NEW 2026-10-15: R8, runs for the 32-sample version (AU5TRA; read this first)

**Decision.** The paper's learned policy becomes the linear score that scores 32 randomly
sampled candidates (`ml global@32`). Scoring every candidate (`ml global`, "the full scan")
becomes a variant. I will update the paper myself once your data is in; please don't edit
`main.tex`.

**Why.** It costs half as much and makes the same faults:
* 11,293 instructions per eviction at 68 candidates, against 22,803 (`cost_grid.csv`).
* The cost stops growing with memory: 11,813 and 11,907 at 260 and 516 candidates, against
  91,720 and 183,311.
* At 10% memory it makes 0.998 of the full scan's faults, interval 0.975–1.017
  (`kernel_ci_classic.csv`).

**Already there, nothing to run:**
* faults and writes at 10% on all 74 streams (R1);
* cost at all four sizes (`cost_grid.csv`);
* native timing at 68 candidates: 856 ns, 892 ns with the page-table walk, 1,447 ns with cold
  caches (`native_timing*.csv`);
* the `tradeoff.csv` row.

**Missing:** the 5% and 20% memory sizes. Today the paper can only show the full scan there.

### Runs (cut-off 25 Oct as agreed)

**R8a (must). `global@32` at 5% and 20% on all 74 streams: 148 runs.**
* Flags as in R1, with the sizes changed: `--fracs 0.05,0.2 --models global@32 --splits
  test,heldout`. The pattern and application streams take `--accesses 50000`, as in every
  other round.
* Package it the way you did rounds 6 and 7. If the output is not a `kaggle_*.csv` file (those
  are merged automatically), add it to `SOURCES` in `merge_kernel_results.py`.
* Cost: about the same as the full-scan linear runs at those sizes, since sampling makes each
  decision cheaper.
* **A free check.** The kernel samples only when a process has more than 32 candidates
  (`kernel/vmpage.c:313`). At 5% several workloads have very little memory: matmul 2 frames,
  sort 2–6, lzw 17–23, kv / kv-T / bloom 25–37 (`kernel_eval_all.csv`). Any stream that never
  has more than 32 candidates must give exactly the faults of `ml:global` on the same stream.
  Please run those streams anyway, so every table covers all 74.

**R8b (must, small). A correctness check of the sampled path.**
* `vmtest data-invariance` runs every policy at a limit of the baseline + 8 frames
  (`user/vmtest.c:1135`), so the learned policy never samples there. The check (checksum
  `AB0C8578`, 0 fallbacks) therefore covers only the full scan.
* Please run the same workload under `ml global@32` at a limit with more than 32 candidates,
  with prefetch both sync and async. Report the checksum and the fallback count. How you set
  it up (a vmtest option or a vmrun wrapper) is your call.

**R8c (should). Graph's own weights with 32 samples at 10%: `--models graph@32 --only graph`,
the 6 graph streams.** The paper's sentence "graph's own weights reach 0.60 at 10%" is a
full-scan number.
* **Please also check that number.** It comes from your START HERE section. But
  `kernel_eval_all.csv` (`ml:graph` against `clock` at 10%, geometric mean over the 6 graph
  streams) gives 0.578. If 0.60 came from an older build or different streams, say which
  value the paper should use.

**R8d (optional).** LeCaR at 5% and 20%: Kaggle round 7 is already packaged and was not run.
It could ride along with R8a, so that LeCaR's rows cover every size. `global@16` at 5% and 20%
is not needed.

### Tables from your scripts (no runs; so the paper can `\input` them)

**G1. Intervals (`kernel_ci_classic.py`, faults and writes).**
* New comparisons: `ml:global@32` against `clock`, `arck`, `lhd`, `s3fifo`, `lecar` and
  `ml:global`, and the five heavier models against `ml:global@32`.
* **Caution:** the loop runs "for each memory size, for each pair" with one random generator
  (seed 7). Adding pairs to `PAIRS` therefore shifts the random draws of every later memory
  size, and would change intervals that are already published. Please compute the new pairs
  in a second loop after the existing one, with its own `default_rng(7)`, so the existing rows
  stay identical.

**G2. `ci_main.tex` (`report_w16.py`, `ci_table`):** the same new rows.

**G3. Per-workload tables (`report_w15.py`, `kernel_main`, list `A`):** add
`("ml:global@32", "linear, 32 sampled")` for faults and writes.
* Do this **after R8a**. The function keeps only the streams every listed policy ran, and at a
  memory size where one policy has no runs it writes no table at all, so the old file would
  stay in place unnoticed (`report_w15.py:371-374`).

**G4. Break-even at each policy's own measured speed (`cost_benefit.py`).**
* Today every policy is charged the same time per instruction. `cost_benefit_measured_all.csv`
  uses 0.0592 ns, which is 1,350 ns / 22,803; I checked that it reproduces exactly.
* The 32-sample score is slower per instruction natively: 856 / 11,293 = 0.076 ns, 0.079 ns
  with the walk, and 0.128 ns with cold caches. So its `breakeven_summary.tex` row understates
  its time.
* Please add a per-policy native time, or at least rows for the 32-sample score at 0.079 and
  0.128 ns.
* Check values: I ran `cost_benefit.py --ssd-us 63 --hdd-us 8921 --ns-per-instr 0.1281` into a
  scratch file (not committed). Time vs Clock was 0.931 on the SSD (faster on 10 of 14
  workloads) and 0.913 on the hard disk. At 0.079 ns it was 0.924 and 0.912.

**G5. `breakeven_by_workload.tex`:** add the 32-sample score's columns.

**Reply below** with item, result, files, and anything that failed. I'll fold it into the
paper.

---

## NEW 2026-10-14: R1–R6 are in the paper (AU5TRA)

Thanks. Every R1–R6 number is now in `report/paper/main.tex`. Each was recomputed from
`report/results2/*.csv` and your generated tables: 58 checks, all pass. No new runs were
needed for R1–R6 (R8, above, asks for new ones). R7 (the Limits bullet) was already done on
your side.

**Paper changes that touch your files:**
* Table 6 in the body shows the 12 rows of `ci_main.tex` the text cites. They are written by
  `report/paper/make_figdata.py` into `figures/data/ci_body.tex`, in the same format. The
  full `ci_main.tex` is in the appendix.
* `breakeven_summary.tex` and `breakeven_by_workload.tex` are in the appendix (C).
* `tradeoff.csv` now covers 14 workloads for every row, so Fig. 5 uses filled markers
  throughout.
* In `week_16_update_report.tex` I changed one sentence. The LeCaR appendix paragraph still
  ended "We did not run it in the kernel"; it now points to the kernel result in Section
  `sec:main`. The PDF is rebuilt.

**Typed numbers that moved, so you can check them:**
* break-even median at 1 ns: 250 → 260 µs (`cost_benefit_measured_devices.csv`, 259.4);
* btree on the SSD at 1 ns: 1.96 → 1.90;
* linear time vs Clock on the SSD at 0.059 ns: 0.95 → 0.94; on the hard disk: 0.92 → 0.91.

**Two numbers rest only on your R4 text, with no CSV behind them:**
* LeCaR kernel/simulator over 59 streams. I could recheck it on the 40 streams in
  `baselines_ext.csv`: 0.999, median 1.004, range 0.81–1.048.
* LeCaR's data-invariance pass.

If you have the 59-stream file, add it to `report/results2/`.

---

## NEW 2026-10-13: what the paper still needs from you (read this first)

The paper (`report/paper/main.tex`, commit `b321b8e` or later) now uses every result you
handed back: D2, N1 (74 streams at every size, 2,743 runs), S1/S2 (measured device latency
and native timing), S3 (LeCaR, §5.2 and appendix table `lecar.tex`), the Twitter licence
statement. The guard is gone everywhere. All six figures are drawn; their data comes from
`report/paper/make_figdata.py`, which reads `report/results2/*.csv`. The body is 10 pages.
`git pull --ff-only` is enough: all three branches point to the same commit.

**Rules that still hold:** same frozen evaluation build as `kernel_eval_all.csv` (never
compare across builds); runs stop on **25 Oct**; tables are regenerated, never typed. After
any new run: add its output file to `SOURCES` in `tools/ml2/merge_kernel_results.py` (the
list is fixed; an unlisted file is silently ignored), then
`python3 merge_kernel_results.py && python3 kernel_ci_classic.py && python3 report_w15.py && python3 report_w16.py && python3 tradeoff.py`,
then `cd report/paper && python3 make_figdata.py && latexmk -pdf main.tex`. Reply below
with: item, result, files, and which typed numbers in the paper moved.

### R1 (high). Sampled linear score on all 74 streams at 10%
* *Why:* the abstract, §3.6, §5.6 and Fig. 5 say "sampling 32 candidates halves the cost
  for at most one point of faults". Today that rests on 3 workloads (32 candidates) and 2
  (16), and §5.6's numbers (LZW 0.837 → 0.842 → 0.858; Twitter 0.876 → 0.875 → 0.884)
  use **per-workload** weights, not the global ones the paper headlines.
* *Run:* `cd tools/ml2 && KERNEL_EVAL_OUT=kernel_eval_sampled.csv python -u kernel_eval.py --lanes 6 --fracs 0.1 --models global@32,global@16`
  (pattern and application streams with `--accesses 50000` as before, via `--only`).
  5% and 20% only if time allows.
* *Produce:* the rows in `kernel_eval_all.csv`; in `kernel_ci_classic.py` add the
  comparisons `ml:global@32` and `ml:global@16` against `clock` and against `ml:global`
  (faults and writes); a row per sample size in `tradeoff.csv` covering 14 workloads.
* *Paper:* abstract, §1 Move 7, §3.6, §5.4, §5.6 (A5), Fig. 5 (the open blue markers
  become filled).
* *Cost:* the same as the linear runs at 10% (sampling makes each decision cheaper).

### R2 (medium). The five heavier models on all 74 streams, at least at 10%
* *Why:* "level with the linear score at 20–150× the cost" (abstract, §1, §5.6, Fig. 5)
  rests on 10 streams; their intervals are the widest in Table `ci_main`.
* *Run:* `KERNEL_EVAL_OUT=kernel_eval_nets74.csv python -u kernel_eval.py --lanes 6 --fracs 0.1 --models cnn-all,mlp-all,attention-all,trees-all,ranktrees-all`
  (names from `user/mlnet_names.h`). These are slow (CNN about 2.0M instructions and MLP
  3.4M per decision, against 22.8K for the linear score): estimate the time from
  `kernel_eval_w16*.csv` before starting, and if it does not fit before 25 Oct, run
  CNN and MLP only (the two the text names), or skip and keep "ten streams" in the text.
* *Produce:* `kmain_B_*` and the `ci_main` rows recomputed on the larger set; `tradeoff.csv`
  coverage updated.
* *Paper:* abstract, §1, §5.6, Fig. 5, appendix table of the heavier models.

### R3 (medium). The two first-version results, rerun or relabel
* *Why:* §2.4 (the naive learned policy fails: almost every linear model ≥ 3× Clock on
  PageRank with uniformly sampled candidates, 97% of its victims loaded at the previous
  fault, needed again a median of 16 references later; Belady's choice last used about
  300 references earlier; 167 resident pages; three DAgger rounds did not help) and
  §5.6 ("one round of DAgger did not help") come from the first version of the study
  (`ML_REPORT` 7.1, 7.3), before the deterministic-seed refit.
* *Run:* rebuild the v1-style data (no recency stratum: `N_RECENT = 0` in
  `build_datasets.py`, separate `ML2_CACHE`), refit, replay `graph-pr2000x2-s2`
  (validation) and recount the victim ages; and `python3 extras.py dagger` on the current
  datasets.
* *Produce:* the five §2.4 numbers and the DAgger table in `tables.md`.
* *Paper:* §2.4, §5.6. *If not done:* tell AU5TRA and the text will say "first version of
  the study" in both places.

### Optional (only if R1–R3 are done)
* **R4.** LeCaR in the kernel (today simulator only; its accessed-bit form is 1.116 of
  Clock there, so a kernel run mainly confirms a loss).
* **R5.** Native timing that includes the accessed-bit page-table walk
  (`native_timing.c` leaves it out, so 1.35 µs is a lower bound).
* **R6.** A generated table of the measured break-even per workload
  (`cost_benefit_measured_all.csv` and `_devices.csv`) for the appendix, written by
  `report_w16.py` like the other tables.
* **R7.** Fix the Limits bullet of the week-16 report ("the fault cost is assumed"),
  which S1/S2 made stale.

### Not runs, but yours
* Legal names, affiliations, e-mails of both authors; the supervisor decision (before
  **19 Oct**, when submissions open); the author-quota check.
* The full 74-step regression matrix is still not needed: the paper cites only the
  data-invariance check.

---

## State of everything (2026-10-12, evening): read this first

* **`cache_ext_notes.md` is now in git** (project root), for your related-work search.

* **All experiments are finished and frozen** (build unchanged; 2,743 kernel runs in `report/results2/kernel_eval_all.csv`; all three memory sizes cover the same 74 streams; the five heavier models cover ten streams). Tables and intervals are regenerated: `report/week_16_update/tables/`, `report/week_16_update/week_16_update_report.pdf`. **No new runs.** Your cut-off of 25 Oct is agreed.
* **Done from your list:** M1, M2, M3, M4, M5 (with the limits stated in the replies), S1, S2, S3, S4, N1. **Dropped by GawwyG:** N2 and the guard everywhere. **S3 (LeCaR):** done at GawwyG's request later on 2026-10-12 (LeCaR, see the reply below).
* **Numbers that moved since your draft was built on the week-16 report** (please re-check what you typed): the 5% and 20% results (round 5 added streams), the cost section (exact instruction counts, measured device latency and native speed replace the assumed 100 us / 8 ms / 1 ns), the page-writes result (the older "96.5% fewer writes" does not hold as an average), the global-scope rows of `model_comparison.tex` (M1), the within-decision correlations and the catastrophic-subset count (M4). Everything is listed with its file in the replies below.
* **Decisions (D2), made by GawwyG (done by Claude at GawwyG's request on 2026-10-12): see "D2 decided" below.**
* **Twitter trace licence: checked, see "Twitter licence" below.**
* **The replies below were written by Claude at GawwyG's request; GawwyG has read the arrangement and accepts them as the answers. GawwyG's OpenReview profile already exists.**
* **Still open, and only GawwyG can do these:** the author quota check, GawwyG's legal name and affiliation for the author block (to be sent to you), the supervisor question, and pushing the commits to GitHub (nothing is pushed until GawwyG does it).
* **Still open on your side (not experiments):** the rewrite in your own words, figures 1 and 4 and the re-plotted classical-vs-Belady figure, related work, the `% VERIFY` references, the `yang2020twitter` author fix, re-checking the typed 5% / 20% numbers, and removing the guard from the paper.
* **Your new request, the full 74-step regression matrix on the final build: NOT done.** `tools/phase2_gate.sh` is hard-wired to an old machine's paths (`/mnt/d/thesis/...`) and does a clean debug build and a clean release build; running it would need a scratch copy of the repository and several hours, and it would not touch the frozen evaluation build. What exists on the final build instead: `vmtest` (the standard run), `prefetchtest`, and `vmtest data-invariance` under all 8 policies and under the five heavier models (checksum `AB0C8578`, zero fallbacks; see M5). Cite only data invariance unless GawwyG asks for the full matrix; if so it is a separate job of its own.

---

## 1. Dates (official; checked 2026-10-12)

Source: https://mlsys.org/Conferences/2027/CallForResearchPapers and `/Dates`.

| When | What |
|---|---|
| **~16 Oct** | **Every author has a complete OpenReview profile** (affiliation, conflicts, publication history). The call says "at least two weeks in advance". Author list cannot change after the deadline. |
| 19 Oct | Submissions open (OpenReview). |
| **30 Oct** | **Paper deadline.** The call says 20:00 UTC, the dates page 12:00 PDT (= 19:00 UTC). We use **19:00 UTC** (31 Oct, 01:00 in Bangladesh). The appendix is a separate file, due at the same time. |
| 18–21 Jan | Reviews out; responses due (three days). |

**Proposed cut-off (please confirm):** no new runs after **25 Oct**. Tables
regenerated from frozen CSVs on 25 Oct; 26–29 Oct is for writing only.

Two rules from the call that affect us:
* **AI-written text.** "Papers where the content is generated by LLMs … alone are prohibited."
  The draft was written with an AI assistant from our reports, so we rewrite it in our
  own words before submission. This also applies to text copied from reports
  written with an assistant.
* **Author quota.** New for 2027: a per-author limit on submissions. Check the author
  list with https://mlsys.org/Conferences/2027/AuthorQuotaChecker.

## 2. Decisions only you can make (your D2), needed by 14 Oct

1. **The claim.** The draft uses the one you proposed, marked "pending D2". It says the
   linear score beats Clock at 10% (0.914 [0.85, 0.98]) and is level with ARC, and that
   heavier models are not clearly better at 20–150× the cost. The draft never says
   "beats ARC". Confirm the claim or change it.
2. **Title and the system name.** The draft's working title is "Glimpse: Learned Page
   Replacement from What the Kernel Already Sees". Your language rule says no invented
   terms, so we can drop "Glimpse" if you prefer. It is one macro (`\sys`) near the
   top of `report/paper/main.tex`.
3. **Venue.** MLSys 2027, research track. Confirm.
4. **Authors and credits** (the platform, the programs, the Kaggle runs), and the
   **Twitter trace licence** before any derived streams are released.

## 3. How the paper uses your results (please keep this working)

* The kernel tables are `\input` **directly** from `report/week_16_update/tables/`:
  `kmain_A_005/01/02`, `kmain_B_01`, `ci_main`, `cost`, `trainedall`. When you rerun
  `report_w15.py` and `report_w16.py`, the paper updates by itself.
  * **Do not rename these files or change their column layout without telling me.**
  * If you start a `week_17_update/`, either keep writing these files where they are,
    or tell me and I change one macro (`\wsixteen` near the top of
    `report/paper/main.tex`). The paper is a single file now; your tables are its only
    `\input`s.
* Numbers quoted in the text are typed, each with a `% src:` comment, and listed in
  `paper-state.md` → "Numbers". If a rerun changes one of them, tell me which.
* `\best{}` in `ci_main.tex` is defined in the paper as bold. Keep using it.
* Keep names out of table files. The submission is double-blind, so no names, handles
  or machine names.

## 4. What to do, in order

### Must have: checks and small reruns (no new experiments)

**M1. Check the "global, held-out" row of `model_comparison.tex`.**
* *Why:* in `report/results2/extra_summary.csv` the `global,held-out` group has 15 cells.
  Its LRU, ARC, S3-FIFO, LHD and Belady values are exactly kv held-out's (0.9816,
  0.9816, 1.0131, 0.9006, 0.5772). It looks as if only kv's held-out streams were
  scored for the global scope. `global,test` has 27 cells: please confirm which
  streams those are too.
* *Produce:* a fixed `extra_summary.csv` and `model_comparison.tex`, or one line
  explaining why this is right.
* *Paper:* Table 4 (§5.2) leaves out both global rows until this is settled.
* *Effort:* small once the cause is found.

**M2. Say which ARC/LHD/S3-FIFO the simulator columns are.**
* In `model_comparison.tex` and `transfer.tex`, are "ARC" and "LHD" the per-hit
  simulator versions or the kernel forms (`arck`)?
* *Paper:* §5.2 currently quotes neither column. It will quote them if they are the
  kernel forms.

**M3. Page writes for the final build.**
* *Why:* earlier builds cut writes by up to 96.5%, a strong result for a paging
  system, but the final runs do not report writes. A reviewer will ask why faults
  are reported and writes are not.
* *Produce:* a table in the layout of `kmain_A_*` with `page_writes` relative to Clock,
  from `kernel_eval_all.csv`, for 5/10/20%. Also the interval for "linear, global
  against Clock" in writes at each size (same method as `ci_main`).
  * Note: on kv-F almost every victim is dirty, so writes track faults there. That is
    not a bug.
* *Paper:* §5.3, possibly the page-1 table.
* *Effort:* small; script only.

**M4. Regenerate the numbers that predate the week-15 refit.** The paper quotes these
from the old `ML_REPORT.md`:
* within-decision feature correlations (`feature_diagnostics.csv`; §2.3: sfreq −0.45
  vs freq −0.52, rdist +0.45);
* marginal value of each feature (`summary_marginal.csv`; §5.2 and appendix figure:
  idle −71% graph, −29% btree, −20% kv);
* the v1-vs-v2 training-data and probation tables (§5.6);
* the 8-bit integer check, "within ±0.002 of float" (§5.4), on the current selected
  models;
* the number of catastrophic subsets (graph: 98 of 255).

*Produce:* the regenerated CSVs, or a note on which ones are too costly. Those we
label "first version of the study" in the text.

**M5. Small facts the text needs.** Each one is a single number.
* QEMU version, host CPU and OS (§5.1).
* Training rows and decisions for the current six-workload datasets (§3.3; the old
  figure was 4.73M rows over 357K decisions).
* Training time of the final models (§4).
* Bytes per resident page and per swap slot added for the learned policy, and the size
  of one model's weights in bytes (§4).
* `policy_fallbacks` summed over the final runs; we expect 0 (§3.5). If `vmbench` does
  not print it, one run of `vmtest policies-correctness` under each of the 8 policies
  is enough.
* `vmtest data-invariance` on the final build with all policies, including ARC/LHD/
  S3-FIFO and the heavier models: the same checksum everywhere (§4).

### Should have: answers to the questions reviewers ask most

**S1. Replace the assumed fault cost with measured device numbers.**
* *Why:* the break-even rests on 8 ms (disk) and 100 µs (flash) per fault, both
  assumed. Your handoff lists this as the first thing not done.
* *Cheapest version:* measure 4 KB random read and write latency of the thesis PC's
  SSD (and a hard disk if one is available) with `fio`, then rerun `cost_benefit.py`
  with those values. It is still not an xv6 fault, but it is a measured device.
* *Paper:* §5.4, §7.
* *Effort:* half a day.

**S2. Turn instruction counts into time on a real CPU.**
* *Why:* "one instruction = 1 ns" is the other assumption.
* *Cheapest version:* compile the scoring loop (`kernel/mlfeat.h` plus the dot product)
  natively and time it per candidate on the PC. That gives ns per decision for 68
  candidates and for 32 sampled.
* *Paper:* §5.4.
* *Effort:* half a day.

**S3. One learned-cache baseline from the literature, or a reason to leave it out.**
* *Why:* reviewers expect the closest prior learned method run on the same data.
* *Candidate:* LeCaR (online regret-weighted mix of two policies). In the simulator
  only, with what a kernel sees: Clock in place of LRU, the decayed LFU in place of
  exact LFU.
* *Produce:* one row in Table 4 or the kernel table, or one sentence on why not.
* *Effort:* about one day in the simulator.

**S4. Data for the trade-off figure.**
* *Produce:* one CSV with policy, instructions per decision (68 candidates), and faults
  relative to Clock at 10% (mean over the 14 workloads). Also add the linear score
  with 16 and 32 sampled candidates if those runs exist at 10%.
* I will plot it (Fig 7) in the paper's style.
* *Effort:* small.

### Nice to have, only if time is left before 25 Oct

* **N1. More streams at 5% and 20% memory** (51 → all 74). This would tighten the
  intervals, which are the main reason most comparisons read "level". It is another
  Kaggle round; check the ETA against the cut-off.
* **N2. The guard in the kernel**, with its window counted in evictions or faults, not
  accesses. You called it optional. If it is not done, the paper says the kernel runs
  have no guard (it already does).

## 5. What the paper side is doing meanwhile

* Rewriting the draft in our own words (the AI-content rule).
* Drawing Fig 1 (eviction path) and Fig 4 (overview), and re-plotting the
  classical-vs-Belady figure.
* Searching related work: in-kernel learned eviction and eBPF page-cache policies.
  Your `cache_ext_notes.md` is not in git; please commit it or send it.
* Checking every reference marked `% VERIFY` in `report/paper/references.bib`.

## 6. How to hand results back

* Commit to `GawwyDev` as usual. The three branches (`riscv`, `Austra-dev`, `GawwyDev`)
  were all at the same commit on 2026-10-12.
* For each item, add one line to the "Issues to raise with the collaborator" section
  of `report/paper/paper-state.md`, or reply in this file below with: item, result,
  file.
* Never compare runs across builds (your rule). If the build changes again, say so and
  I will recheck every quoted number.

## Replies (GawwyG fills this in)

**AU5TRA, 2026-10-12: M1–M5 and S4 are folded into the paper.** Where they went:
* Table 4 now has the "all six" rows.
* §5.3 says writes do not fall on average; the writes table is in the appendix.
* The regenerated correlations, marginal values, catastrophic counts, integer check and
  probation numbers are in.
* Your facts are in §3–§5.

The page-writes result is reported as a negative result in the intro, §5.3, §5.7 and §7.
Still open from your side: S1, S2, S3, N1, N2, and D2. Also, if you can, run the full
regression matrix on the final build; otherwise the paper cites only data invariance.

*(Added by GawwyG's side after merging the paragraph above: its "still open" list was written before the work below. Now: S1, S2, S3 and N1 are done, N2 is dropped, D2 is decided. The full-regression-matrix request is answered at the end of this section.)*

*(item — result — file)*  Worked through on 2026-10-12. S1, S2 and S3 done (below). N2 dropped (below). **N1 is DONE (2026-10-12): 23 more streams at 5% and 20% memory, eight policies each (FIFO, Clock, Aging, LFU, ARC, LHD, S3-FIFO, linear global); 368 runs, all ok (256 on this PC, 112 on Kaggle, self tests matched). All three memory sizes now cover the same 74 streams; `kernel_eval_all.csv` has 2,743 runs and every table and interval was regenerated. The five heavier models were not rerun, so their tables keep the ten streams. What changed in the quoted numbers (equal-weight over 14 workloads, 95% interval): ARC against Clock 0.947 [0.92, 0.98] at 5% (was 0.946) and 0.984 [0.95, 1.02] at 20% (was 0.986); LHD 1.005 and 0.949 [0.87, 1.01]; S3-FIFO 1.086 and 1.086 [0.98, 1.20]; linear against Clock 0.976 [0.90, 1.09] and 0.882 [0.77, 1.00] (upper end 1.001, so "includes 1" only just); linear against ARC 1.031 [0.97, 1.13] and 0.896 [0.77, 1.02]; linear against LHD 0.972 and 0.929 [0.79, 1.08]. Conclusions unchanged; graph with the global weights at 20% is now 1.40 (was 1.60); sort at 5% 1.03 (was 1.06). Please re-check every number you typed for 5% and 20%.**

**DROPPED by GawwyG, in full: N2 (the guard in the kernel) and the guard everywhere else.** It is not needed for the research question. Please remove it from the paper and do not work on it: it appears in `report/paper/outline.md` (rows 3 and 5.5), `paper-state.md` (lines about C4, the ablation and fallback rows, the guard numbers 1.86 to 1.36, step 6), `sections/1-introduction.tex` (line 104), `2-background.tex` (line 125), `3-design.tex` (the "fallback guard" item and its plan and todo, lines 168-180), `5-evaluation.tex` (line 275 and the robustness text) and `7-discussion.tex` (the "No guard in the kernel" item). Keep the plain statement that the learned policy can be worse than Clock and where. Anything else GawwyG marks "not required" is dropped the same way.

**D2 decided (2026-10-12).**
1. **The claim.** Use this, and do not write "beats ARC": *A small linear score over signals a kernel can already see, computed with whole numbers, makes fewer page faults than Clock in xv6 (0.914 [0.85, 0.98] of Clock's faults at 10% memory; 0.976 and 0.882 at 5% and 20%, where the intervals include 1) and is level with, or better than, ARC, the best classical policy we could run in the kernel (1.031, 0.970 and 0.896 of ARC's faults at 5, 10 and 20%; no interval excludes 1). Bigger models (CNN, deeper MLP, set-attention, trees) are level with the linear score and cost 20 to 150 times more per decision. Whether a saving in faults pays for the extra work depends on the device and the core: with the device and core we measured, the linear score pays on a hard disk and, with a fast core, on an SSD; the bigger models pay on neither an SSD nor a slow core.* ARC and S3-FIFO and LHD are the accessed-bit forms; say so wherever they are named.
2. **Title and system name.** Drop "Glimpse" (the language rule: no invented terms). Title: "Learned Page Replacement from What the Kernel Already Sees". Do not name the system; say "the learned policy" or "the linear score". Change the `\sys` macro near the top of `report/paper/main.tex` accordingly.
3. **Venue.** MLSys 2027, research track, deadline 30 Oct 2026, 19:00 UTC (the stricter of the two times on the site).
4. **Authors and credits.** Two authors, GawwyG and AU5TRA, with an equal-contribution note; GawwyG supplies the legal names, affiliations and emails for OpenReview (the handles in this repository are not legal names, and Claude does not know them). Whether the supervisor is also an author is GawwyG's call and has not been made; the author list cannot change after the deadline, so settle it before 19 Oct. In the acknowledgments: the authors of cache_ext (for the archive of Twitter traces), the Twitter trace release (below), and Kaggle for compute. Programs by AU5TRA (LZW, pointer chase, hash join, Bloom filter, sparse matrix-vector, heap churn) are credited as hers in the text. An AI assistant is not an author; disclose its use as the venue requires.
5. **Cut-off.** No new runs after 25 Oct: agreed.

**Twitter licence (verified 2026-10-12).** The Twitter cache traces are released under **CC BY 4.0**: the data and the trace documentation "are made available under the CC-BY license. By downloading it or using them, you agree to the terms of this license" (README of github.com/twitter/cache-trace, last section "License"; the LICENSE file is the CC BY 4.0 legal text). CC BY allows sharing and adapting, including derived data, if the work is credited, a link to the licence is given and changes are indicated. The README names the source paper (Yang, Yue, Rashmi Vinayak, "A large scale analysis of hundreds of in-memory cache clusters at Twitter", OSDI 2020) and asks that papers using the traces be added to its trace bibliography; that is a request, not a condition. What we use: the cache_ext project's processed archive (`twitter-traces.tar.zst` in its public bucket), from which `tools/twitter_extract.py` keeps the first requests of each cluster as numbered key ids and read/write flags (no key text), and `tools/gen_tw_keys.py` then samples about 1,000 keys per cluster (by key hash, keeping each kept key's whole request sequence) and cuts the stream to 4,751 to 40,000 requests (`user/twk*.bin`); our key-value store replays them and the page references it makes are the `kv-T*` streams. The cache_ext repository states no licence of its own for that archive, so the licence that applies is the original CC BY 4.0.
*What this means for the paper:* (a) cite Yang et al. (OSDI 2020) and the cache_ext paper; the entry `yang2020twitter` in `references.bib` is marked VERIFY, and the author list there ("Rashmi, K. V.") should be "Rashmi Vinayak" to match the trace page, please check against the OSDI page; (b) say in the text that the replays use clusters 4, 17, 18, 24, 35 and 52, spatially sampled to about 1,000 keys and 4,751 to 40,000 requests each, key ids and write flags only, that is, a changed form of the data; (c) if derived streams are released with the artifact, release them under CC BY 4.0 with that attribution and the same change note, and do not redistribute the original archive (point to the original source); the scripts that make the streams can be released under the paper's code licence; (d) the real Redis and SQLite page traces were collected by us on Linux from the stock programs (`tools/collect_linux_trace.sh`, valgrind lackey) and the other workloads are ours or AU5TRA's, so no third-party data licence applies; the programs' own licences (SQLite public domain, Redis BSD) were not separately checked and do not restrict our measurements.

**M1 — global, held-out row.** Cause found and fixed; it was not a scoring bug. The neural nets are not run on the longest streams (`NN_MAX_REFS` in `extra_trees.py`, numpy callbacks are slow), so in the global scope the
net `extraKF-nn:deep` covers only 15 of the held-out cells (kv-F, five streams); `extra_report.py` took the intersection of cells over *all* systems, so every other column was cut to those streams too. Now, for the global scope, the main rows use the cells all non-net systems have
(global test: 75 cells = 25 streams; global held-out: 72 cells = 24 streams) and the net columns show "--" there; the nets' numbers on their own cells are in extra rows named "test (short streams)" / "held-out (short streams)".
Other scopes are unchanged apart from the third decimal of some bootstrap interval ends (the bootstrap now iterates the streams in sorted order, so it no longer depends on Python's hash order). New global rows: test LRU .992, ARC .948, S3F .978, LHD .926, linear K .877, trees K .897, trees FK .856, Belady .591; held-out LRU .979, ARC .968, S3F 1.020, LHD .926, linear K .896, trees K .894, trees FK .854, Belady .558.
Files: `report/results2/extra_summary.csv`, `report/week_16_update/tables/model_comparison.tex`, `tools/ml2/extra_report.py`. Table 4 can now include the global rows (net columns "--").

**M2 — which ARC/LHD/S3-FIFO the simulator columns are.** In `model_comparison.tex` and `transfer.tex`: **ARC and S3-FIFO are the per-hit versions** (every access updates the lists; `P_ARC`, `P_S3FIFO` in `pagesim.c`); **LHD is the accessed-bit form** (time counted in evictions, a "hit" is a page found accessed at an eviction; `P_LHD`), i.e. the same form as the kernel's. The kernel-form ARC (`arck`) and S3-FIFO (`s3scan`) are separate simulator policies, used only for the kernel-vs-simulator check (`kernel_vs_sim_classic.csv`). So the simulator columns for ARC and S3-FIFO are *not* the kernel forms and should not be set beside the kernel rows without saying so; LHD may be.

**M3 — page writes.** Tables `report/week_16_update/tables/kmain_WA_005/01/02.tex` (same layout as `kmain_A_*`; page writes to swap relative to Clock, geometric mean per workload) and intervals in `report/results2/kernel_ci_writes.csv` (`python3 tools/ml2/kernel_ci_classic.py writes`). **The earlier "up to 96.5% fewer writes" does not carry over to the final runs as an average.** Linear (global) against Clock in writes, equal weight per workload, after round 5 (74 streams at every size): 1.215 [0.85, 2.05] at 5%, 1.120 [0.84, 1.74] at 10%, 0.984 [0.72, 1.51] at 20% (no interval excludes 1); the mean is pulled up by matmul (4.75 times Clock's writes at 10%) and SpMV (4.22); on btree 0.95, kv 0.78, heap 0.72, chase 0.73 it writes less. ARC writes less than Clock at 5 and 10% (0.901 [0.81, 0.99], 0.883 [0.76, 0.98]) and about the same at 20% (1.036 [0.94, 1.23]); LHD 0.971 [0.93, 1.01], 0.887 [0.72, 1.00], 0.936 [0.85, 1.00]; S3-FIFO more (1.37, 1.16, 1.46). FIFO writes a lot more (mean 1.69 at 10%).

**M4 — numbers that predate the refit.** The CSVs were already regenerated on 2026-10-08 with the deterministic seeds; the paper's quoted values come from the old report. Current values:
* Within-decision Spearman correlation with the label, mean over the six workloads (`feature_diagnostics.csv`): freq (exact count, oracle) −0.239, sfreq (kernel) −0.269, rdist +0.324, age −0.367, idle +0.195, aging −0.073. Per workload sfreq / freq: btree −0.53/−0.59, graph −0.33/−0.34, kv −0.47/−0.54, lzw −0.20/−0.16, matmul −0.40/−0.12, sort +0.31/+0.32. The old "−0.45 vs −0.52, +0.45" does not hold; the new picture is that the kernel's sampled count is about as informative as the exact one on average and rdist is the strongest of the three.
* Marginal value of the idle feature (`summary_marginal.csv`, median change of log faults when it is added, test): graph −71% (−1.232), btree −30% (−0.353), kv −19% (−0.215), lzw −1%. Matches the old "−71%, −29%, −20%".
* Catastrophic feature sets (at least 3 times Clock) per-workload models, 10%: graph 113 of 300 (test), 114 of 300 (val); kv 52 and 55 of 300; btree, matmul, sort 0 of 300 (v2). The old "98 of 255" is the first version; v1 on the same 300 sets: graph 110.
* 8-bit integer against float, selected linear models (`report/results2/tables.md`, "Integer-only scoring"): within 0.002 on 39 of 44 cells, within 0.005 on 42; the largest differences are lzw 0.013 (test, oracle+kernel; not deployable), lzw held-out kernel-only 0.007, matmul 0.005.
* v1 against v2 data and probation tables: regenerated in `tables.md` (`python3 tools/ml2/tables.py`); the slides' tables were not touched.

**M5 — small facts.**
* QEMU 8.2.2 (Debian 1:8.2.2+ds-0ubuntu1.18), `-machine virt -smp 1 -m 128M`; host AMD Ryzen 5 5600 (6 cores, 12 threads), Ubuntu 24.04 under WSL2 (kernel 6.18.33.2), 8 GB RAM, RTX 3060 Ti for training; riscv64-linux-gnu-gcc 13.3.0; Python 3.12.3. Kaggle notebooks: 4 CPU cores, QEMU 8.2.2, about 3.1 times slower than this PC, identical counts on 180 repeated runs.
* Training data (six original workloads, train + validation splits): 6,129,272 rows over 419,359 decisions (train 5,216,668 rows / 376,706 decisions; validation 912,604 / 42,653) (`dataset_summary.csv`, `traces2/ml2_cache`).
* Training time of the final models on the global scope, measured on the RTX 3060 Ti with the training code and not saved: MLP 48 s, CNN over the aging bits 48 s, set-attention 67 s; boosted trees 1.8 s, ranking trees 2.7 s (100 trees, 16 leaves, CPU).
* Space: `struct vm_page` is 160 bytes, 40 of them (120 → 160) for the learned policy's bookkeeping, per resident page; 12 bytes per swap slot (the eviction time and the refault count); the linear weights are an 80-byte structure per process; all ten built-in models (five kinds, two sets) are 100,716 bytes of read-only data in the kernel (about 50 KB per set of five). The three new classical policies keep one machine-wide state of about 0.95 MB (lists over frames and swap slots, per-page counters, LHD histograms).
* `policy_fallbacks`: 0 in every data-invariance configuration (all 8 policies, with and without asynchronous prefetch, 16 runs) on the final build, and again for each of the five heavier models (6 runs of 16 lines, 96 lines in all). The evaluation transcripts do not record this counter, so there is no sum over the final evaluation runs; adding it would change the programs' output (and so the build), which we did not do.
* `vmtest data-invariance` on the final build: checksum `AB0C8578` on every line for all 8 policies (FIFO, Clock, Aging, LFU, linear, ARC, S3-FIFO, LHD), with and without prefetch, and under each of CNN, MLP, set-attention, boosted trees, ranking trees (`vmrun ml <model> vmtest data-invariance`), all PASS. (The test harness prints "FAIL: without PASS marker" for the `vmrun ... vmtest` form because of how it looks for its marker; vmtest itself printed PASS each time.)

**S1 — measured device latency (no `fio` here, so a Windows-side tester that does the same thing).** `tools/io_latency.ps1`: 4 KB random reads and writes, one request at a time, no file cache (NO_BUFFERING; writes also WRITE_THROUGH), 1 GB test file, deleted afterwards. Results (`report/results2/device_latency.csv`, microseconds): Samsung 980 500 GB NVMe SSD: read median 63, mean 67, p99 134 (20,000 reads); write median 22, p99 56. WD Blue 1 TB SATA hard disk: read median 8,921, mean 9,526, p99 24,541 (1,500 reads); write median 2,609, p99 8,074 (the drive's write cache absorbs writes, so treat the write numbers as a floor). Note the thesis PC's WSL disk file sits on the hard disk. The measured read latencies replace the assumed 100 us and 8 ms. These are a device, not an xv6 fault: the rest of the fault path is not included. The hard-disk figure is for reads spread over a 1 GB file; xv6's swap area is only 32 MB, which would see shorter seeks, so 8.9 ms is a pessimistic hard-disk value. (A 32 MB test file gave 81 us on the hard disk because it fits in the drive's own cache, so it measures the cache, not the disk; it was discarded.)

**S2 — native speed of the scoring code.** `tools/ml2/native_timing.c` compiles the kernel's own headers (`mlfeat.h`, `mlnet.h`, `mlnets.h`) for the host and times one decision (features, scores, selection; sampled variants include the draw; no page-table walk): `report/results2/native_timing.csv`, median of 25 batches, one pinned core of the Ryzen 5 5600, two runs agree within 3%. Per decision at 68 candidates: linear score 1,350 ns (20 ns per candidate); with 32 sampled 856 ns, 16 sampled 431 ns; boosted trees 32,520; ranking trees 30,115; set-attention 105,770; CNN 106,945; deeper MLP 206,188 ns. At 256 candidates the linear score is 5.3 us, the nets scale linearly. Against the kernel's instruction counts (`cost_grid.csv`) that is 0.054 to 0.070 ns per instruction, median 0.06: the "1 ns per instruction" assumption is about 17 times too slow for this desktop core, and about right only for a slow in-order core. It is a lower bound (no accessed-bit scan).
**Break-even redone** (`tools/ml2/cost_benefit.py --ssd-us 63 --hdd-us 8921 --ns-per-instr <x> --out ...`; files `cost_benefit_measured_devices.csv` (measured devices, 1 ns), `cost_benefit_native_speed.csv` (assumed devices, 0.06 ns), `cost_benefit_measured_all.csv` (both measured)). Time spent on faults and on choosing victims against Clock, geometric mean over workloads: linear score (14 workloads) 1.34 on the SSD and 0.92 on the hard disk at 1 ns per instruction; 0.945 (faster on 9 of 14 workloads) and 0.917 (11 of 14) at 0.06 ns. CNN: 24.5 / 1.18 at 1 ns, 2.67 / 0.95 at 0.06 ns; deeper MLP 40.9 / 1.33 and 3.77 / 0.96; set-attention 23.0 / 1.18 and 2.58 / 0.97; boosted trees 7.4 / 1.07 and 1.50 / 1.01 (SSD / hard disk). Median break-even fault cost for the linear score: 250 us at 1 ns, 15 us at 0.06 ns. So: the linear score pays on a hard disk with either core and on an SSD with a fast core; the heavier models pay on neither an SSD nor a slow core. This replaces the assumed numbers in §5.4 and §7; the week-15 `cost_benefit.csv` (assumed values) is kept for comparison.

**S3 — one learned-cache baseline from the literature: LeCaR, in the simulator (done 2026-10-12).** Two versions in `tools/ml2/pagesim.c` (`lecar_exact` and `lecar`), each checked against an independent Python reference in `test_baselines.py` (95 traces, identical faults and evictions; `validate.py`, `validate_kernel.py` and `test_extra.py` still pass). Original parameters: learning rate 0.45, discount 0.005^(1/N), history of half the cache per expert, the two experts picked at random in proportion to their weights, no learning when both experts pick the same page.
* **`lecar_exact` (as published; needs every access, so a reference only):** experts exact LRU and exact LFU (frequency since the start of the stream, ties to the least recent), time = request index.
* **`lecar` (the form a kernel can run):** experts Clock and the kernel's decayed frequency count, both on the same accessed-bit snapshot at each eviction, time = evictions, N = cache size in pages. Your suggested substitution (Clock for LRU, decayed LFU for LFU).
Results, faults relative to Clock in the simulator, same cells as Table 4 (`report/week_16_update/tables/lecar.tex`; data `baselines_ext.csv`, `extra_summary.csv`): as published: btree 0.906 / 0.910 (test / held-out), graph 0.981 / 0.968, kv 0.904 / 0.918, lzw 1.043 / 1.042, matmul 0.851, sort 0.980 / 1.012, global held-out 0.958; kernel form: 1.122 / 1.065, 1.327 / 1.321, 1.127 / 1.149, 1.056 / 1.190, 0.882, 1.016 / 1.000, 1.116. For comparison, linear K: 0.835 / 0.875, 0.847 / 0.798, 0.897 / 0.903, 0.821 / 0.813, 0.671, 0.983 / 0.933, 0.896; ARC 0.950 / 0.975, 0.991 / 0.993, 0.986 / 0.982. So LeCaR as published beats ARC and LRU on btree and kv, ties them on graph, and the linear score on kernel signals beats it on btree, graph, kv and lzw (sort is level); the kernel-form LeCaR is worse than Clock on most scopes. On the two streams I examined (kv-A-s5, graph-pr2000x2-s3 at 10%) the two experts were penalised about equally often (2,270 against 2,238 and 49,304 against 49,279 regret events), so the weights drift (final weights Clock/frequency 0.49/0.51 and 0.17/0.83) instead of settling on Clock; the frequency expert evicts nearly as badly as the kernel's frequency policy (1.17 and 1.84 times Clock on those streams), and the kernel-form LeCaR ends close to it (1.15 and 1.87). That explanation rests on those two streams only. It was not run in the kernel. Table 4's layout is unchanged; the LeCaR columns are in the separate table `lecar.tex`, and the week-16 report has a paragraph on it in the simulator appendix.

**S4 — trade-off figure data.** `report/results2/tradeoff.csv` (`python3 tools/ml2/tradeoff.py`): policy, instructions to choose one victim (68 candidates, exact), faults relative to Clock at 10% (mean over workloads), number of workloads covered, and the global linear score on the same workloads. Sampled linear scores exist at 10% on only 3 workloads (32 candidates: 0.900 against 0.905 for all candidates, 11,293 instructions) and 2 (16 candidates: 0.931 against 0.936, 5,656 instructions); the heavier models cover ten workloads (linear on those: 0.927).

---

## R1, R2, R3 done (2026-10-13/14) — read this before the paper numbers above

All three are merged and committed on `riscv` (round 6 = commit 6739f76; the R3 files follow). Nothing failed: 440 kernel runs (161 on four Kaggle notebooks, 279 on the PC), all `ok`.

**R1 — sampled linear scores, 74 streams at 10%** (`ml:global@32`, `ml:global@16` in `kernel_eval_all.csv`, `kernel_ci_classic.csv`, `kernel_ci_writes.csv`, `tradeoff.csv`).
Against Clock: 0.912 [0.856, 0.965] (32 candidates), 0.926 [0.880, 0.975] (16). Against the full linear score: 0.998 [0.975, 1.017], 1.013 [0.983, 1.043]. Cost per eviction at 68 candidates: 11,293 and 5,656 instructions against 22,803. So the sampling claim holds: 32 candidates are level with all of them at half the cost, and 16 are about 1% worse at a quarter of the cost. Writes against Clock are not distinguishable (1.048 and 1.054, intervals include 1). Filled markers in Fig. 5 are now allowed (point = tradeoff.csv row, 14 workloads).

**R2 — the five heavier models, 74 streams at 10%** (5% and 20% stay on ten streams; do not say 74 there).
Against Clock: CNN 0.914 [0.837, 0.972], MLP 0.912 [0.840, 0.973] (both better than Clock). Against the linear score: CNN 1.000 [0.939, 1.063], MLP 0.998 [0.939, 1.060], set-attention 0.992 [0.929, 1.047] (level); boosted trees 1.061 [1.009, 1.124] (worse); ranking trees 1.476 [1.050, 2.421] (worse, graph 10.5x Clock, SpMV 5.8x). Against ARC: CNN 0.969 [0.901, 1.020], MLP 0.968 [0.900, 1.019], set-attention 0.962 [0.884, 1.025], boosted trees 1.029 [0.975, 1.088]; all include 1. So the sentence "level with the linear score at 20 to 150 times the cost" now rests on 74 streams for CNN, MLP and set-attention at 10%; it does not hold for boosted and ranking trees (worse).
**Numbers that moved from what you may have typed:** CNN / MLP against ARC at 10% 0.987 / 0.985 → 0.969 / 0.968; CNN / MLP against linear at 10% 1.003 / 1.000 → 1.000 / 0.998; boosted trees against ARC at 10% is now 1.029 [0.975, 1.088] on 74 streams (check your typed value); "ranking trees 1.40 at 10%" → 1.35 against Clock (74 streams). New in the main text: CNN and MLP beat Clock at 10% with intervals below 1; the week-16 report (`report/week_16_update/`) already has all of this.

**R3 — the first-version failure, rerun** (`tools/ml2/r3_first_version.py`; results `report/results2/r3_first_version.md` and `.csv`). First-version data (no recent-use candidates, no probation, current deterministic seeds), all 300 linear feature sets on graph, replay of `graph-pr2000x2-s2` at 10% (167 frames, 6.1M references, Clock 53,782 faults):
* 203 of 300 models make at least 3x Clock's faults (run stopped at 3x); median model 3.00x; the best 0.762x. **"Almost every" should read "two thirds (203 of 300)".**
* For a failing model (the median one and the all-features one): 85.7% / 87.3% of victims were loaded at the previous fault (**not 97%**), median references until needed again 15 / 16, Belady's choice last used a median 270 / 234 references earlier (**not about 300**), 167 resident pages.
* The best of the 300 does not do this (0.9% of victims loaded at the previous fault).
* DAgger: the three-round result was not rerun. The current-data DAgger table (one round, `tables.md`, from `extras.py dagger`, commit 8228ea7) shows no consistent gain. Keep "first version of the study" on the three-round sentence in §2.4 and §5.6, or say "one round, on the current data".

**Still open for you (not runs):** the supervisor decision, legal names and affiliations, author quota, and the push.

---

## R4, R5, R6 done (2026-10-14)

Committed on `riscv` (kernel d6f885f; results with the commit after this note). Nothing failed.

**R4 — LeCaR in the kernel** (`VM_POLICY_LECAR` = 8, `vmrun lecar`; `kernel/vmpage.c:choose_lecar`). Integers only: weights in 2^30 units, the regret factor from a 64-entry table; the two experts are Clock and the kernel's decayed frequency count, the histories are ghost lists as in ARC. 74 streams at 10% (`kernel_eval_lecar.csv`, merged into `kernel_eval_all.csv`): **1.113 of Clock's faults [1.036, 1.232]**, 1.197 of its page writes [1.07, 1.40]; the global linear score against LeCaR **0.822 [0.728, 0.913]** (writes 0.936 [0.70, 1.41]). Per workload: graph 1.60, SpMV 1.47, kv and kv-T 1.15 to 1.16, pattern programs 1.14, btree 1.09, heap 0.95, Bloom, matmul and sort 1.00. Kernel against simulator (59 streams of full length): geometric mean 1.000, median 1.004, range 0.81 to 1.05 (graph-pr2000x2-s3 is the 0.81). Cost: 8,155 instructions per eviction at 68 candidates (0.36 of the linear score; `cost_grid.csv`); time against Clock on this PC's core 1.12 (SSD) and 1.11 (disk), faster on 1 of 14 workloads. `vmtest data-invariance` passes for it (checksum `AB0C8578`, 0 fallbacks, both async settings), so **the kernel now has 9 policies; the "8 policies" sentences above describe the earlier build**. Clock re-run in the new build is identical to the old Clock runs (all 74 streams: ratio exactly 1.0), so comparing LeCaR with the merged Clock numbers is fine (`kernel_eval_lecar_clock.csv` keeps the rerun, not merged). Only 10% memory was run. 5% and 20% are prepared as Kaggle round 7 (`kaggle_package/round7/`, 4 notebooks, about 1.3 h each) but are NOT run: the 10% result already shows a loss. Paper: where LeCaR is "simulator only" it can now say "also in the kernel at 10%: 1.11 of Clock".

**R5 — native timing with the page-table walk** (`tools/ml2/native_timing.c`; `native_timing_walk.csv`, `native_timing_cold.csv`). The three-level walk and the per-page counter updates are now done for each candidate. Linear score at 68 candidates: 1.25 µs without the walk (the old 1.35 µs row stays in `native_timing.csv`), 1.52 µs with it, 2.11 µs with the caches flushed between evictions (0.093 ns per instruction); the heavier models change by under 10%. With 0.093 ns for every policy the linear score is still faster than Clock on the SSD (0.96, 9 of 14 workloads) and the CNN, MLP and boosted trees are not (3.9, 5.8, 1.8) (`cost_benefit_cold_bound.csv`). Still left out: the TLB flush after the scan and the locks, so it stays a lower bound.

**R6 — break-even tables** are generated by `report_w16.py` (`tables/breakeven_summary.tex`, `tables/breakeven_by_workload.tex`; the summary replaces the hand-typed time table in the week-16 report, the per-workload one is its Appendix A). `cost_benefit.py` now reads `kernel_eval_all.csv`, so the heavier models are on all 74 streams there. The numbers moved by at most 0.01 to 2 (the 1 ns SSD column of the heavier models: CNN 29.9, MLP 50.6, attention 27.3, trees 8.5, ranking trees 11.5; linear 1.34). Everything else in the report text on cost is unchanged.
