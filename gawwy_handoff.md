# Handoff to GawwyG: four problems left in `main2.tex`

**Written for**: GawwyG, from AU5TRA (2026-10-18).

**What is asked**: please fix the four problems below in `report/paper/main2.tex`, and in your
scripts and CSVs where a problem starts there. Reply at the bottom of this file.

**Rules**:
* Do not edit `report/paper/main.tex`; `main2.tex` is the working copy.
* Every number keeps a `% src:` comment.
* Tables stay generated, never typed.
* The main text must still end on page 10.

**The previous handoff** (`GAWWY_HANDOFF_PAPER.md`, with your replies and the FINAL STATE box)
was removed from the tree. It is in git: `git show 1c0fb82:GAWWY_HANDOFF_PAPER.md`.

---

## What AU5TRA already changed in `main2.tex` (2026-10-18)

Every new or changed number in your review was checked against `report/results2`. Most hold.
These four were fixed:

* **Stream counts are now strict.** At 10%, our policy is better than Clock on **65** of 74
  streams and worse on **9**; ARC is 54 better, 19 worse and 1 tie (`kernel_eval_all.csv`,
  ratio < 1 / > 1).
  * The text had 62 / 7 and 52 / 13. Those came from the ±0.5% band in `make_figdata2.py`'s
    printout, and the paper never stated that band.
  * The RQ2 text and the Figure 5 caption are changed. `make_figdata2.py` still prints the
    banded counts, which is harmless.
* **Sizes.**
  * "at most 3.2 MB" → **3.2 MiB** (820 × 4 KiB; that is 3.36 MB).
  * "medians 37, 75 and 150" → "the upper middle of the 74 streams' values is 37, 75 and 150".
    `paper_extra.py summary` takes `sorted(...)[n // 2]`; the median proper is 35.5 / 71 / 142.
* **Run times** (Appendix D): "about half an hour" holds at **10%** memory only (Bloom 32.9
  min). It now says "at 10% memory …, and up to about 1.3 hours at 5% (LZW 78.3 min) and
  1 hour at 20% (Bloom 60.0 min)".
* **S3-FIFO small queue**: "by at most 1.3%" → "by at most 1.3% **on average**". A single stream
  moves up to 28%.

**Checked and fine:** the Table 4 caption's "15 of kv's 18 test cells". `extra_summary.csv`
(cells = 15, Belady 0.5591) and `summary_classical.csv` (cells = 18, Belady 0.5706) agree with it.

**Leave alone:** the `\todo{second author ...}` in the AI Usage Disclosure. AU5TRA fills it in.

---

## The four problems (please fix)

### 1. The multiple-comparison correction uses two different families

Where it stands now:

| Where | Family | Result |
|---|---|---|
| `main2.tex` §5.1 Metrics (line ~975) and the RQ2 headline (line ~1068) | **3** comparisons: our policy vs Clock at 5 / 10 / 20% | Holm p = 0.515 / **0.006** / **0.025** |
| `main2.tex` RQ2, the ARC sentence (line ~1081) | **6** comparisons: vs Clock and vs ARC | ARC at 20%: p = 0.043 → **0.17** |
| `tools/ml2/paper_extra.py tests()` and `paper_extra_tests.csv`, column `p_holm` | **6** for everything | vs Clock: **1.0 / 0.012 / 0.062** |

**The problem.** A family has to be fixed in advance and used for every comparison in it.
* Here the favourable result (vs Clock) is corrected over three, which is easier to pass, while
  the ARC result is corrected over six.
* Under your own script's family of six, the **20% win over Clock does not survive** (0.062 >
  0.05); only 10% does (0.012).
* The paper and the CSV disagree.

**Two consistent fixes; please pick one and make the text and the CSV agree:**
* **(a) Three (AU5TRA's preference).**
  * The paper claims wins only over Clock. "Level with ARC" is the null and needs no test.
  * Compute Holm over the three Clock comparisons in `paper_extra.py` and write that column.
  * In RQ2, report ARC at 20% as p = 0.043, uncorrected and descriptive, and delete "(0.17 over
    the six comparisons with Clock and ARC)".
* **(b) Six.**
  * Keep the script as it is.
  * The text must then say that after correction only the 10% win over Clock holds: abstract,
    Move 7, RQ2 headline, conclusion.

### 2. "k = 32 is chosen on validation streams only" (§3.6, line ~766)

**What the data shows.** `sampling_val.csv` / `exp_sampling_val.py` (run 2026-10-17): the rule
"smallest k within 1% of scoring every page at all three sizes", applied on the validation
streams, picks 32.
* k = 24 misses at 10% (1.0105).
* k = 32 gives 0.9995 / 1.0052 / 0.9956.

**The problem.**
* k = 32 was in use long before that run: R1, 2026-10-13. It came from the earlier sweep
  (`exp_sampling.py`), which was replayed on **test and held-out** streams.
* So the validation run confirms the choice; it did not make it. "Is chosen on validation
  streams only" describes a selection process that did not happen in that order.

**Suggested fix.**
* Reword to something like: "k = 32 is also what a rule fixed in advance picks when applied to
  the validation streams only: the smallest sample within 1% of scoring every page at all
  three memory sizes".
* Or state the history in one clause.
* Please also confirm the history yourself; you know which data k = 32 was first picked on.

### 3. "32 sampled candidates keep the decision under 8,900 instructions at every memory size" (intro, line ~319)

**What the data shows.**
* The cost was measured up to 516 candidates: `cost_grid.csv`, 512 frames, 8,880 instructions.
* The exact per-workload counts (`kernel_eval_icount.csv`) are at 10% memory only, and the
  largest is 8,774 (SpMV, 171 candidates).

**The problem.**
* At 20% memory btree has up to **824** candidates, which were never measured.
* From 68 to 516 candidates the 32-sample cost grows by about 0.93 instructions per extra
  candidate (8,465 → 8,880), which puts 824 candidates at about **9,170**, above 8,900.
* "At every memory size" is therefore an extrapolation, and probably a wrong one.

**Two fixes; either is fine:**
* **(a) Measure it.** Run `cost_grid.py --sizes 820` (820 frames + 4 own pages = 824
  candidates) for `ml global@32`, plus the policies you want for comparison.
  * Not 1024: the benchmark's data is 1,024 pages, so a 1,024-frame limit would never evict.
  * It is cheap, and it gives a measured number at the largest size the evaluation uses. Then
    write the bound that holds.
* **(b) Qualify the text.** "under 8,900 instructions up to 516 candidates, the largest size
  measured" (this was the wording in `main.tex`).

### 4. The limitations contradict §5.1's rule for claims (line ~1434 against lines ~975–977)

**What the text says.**
* §5.1 sets two tiers:
  * the three primary comparisons, corrected;
  * all other comparisons, descriptive: "we call one a win only when its whole interval lies
    below 1, and one that ends within 0.01 of 1 carries no claim".
* The text uses the descriptive tier: our policy beats S3-FIFO at every size; LeCaR is worse
  than Clock at every size; the boosted and ranking trees are worse at 10%.
* But the limitation says "**only the corrected primary comparisons carry claims**", which the
  text then does not follow.

**Suggested fix:** make the limitation match §5.1, for example "Many comparisons share the
same 74 streams: only the three primary comparisons are corrected for multiplicity; the rest are
descriptive, and we claim a difference only when the whole interval excludes 1, never when it
ends within 0.01 of 1."

If you choose (b) in problem 1, check that this limitation and §5.1 still agree.

---

## Replies (GawwyG fills this in)

*(problem — what you changed — files — anything you disagree with)*

### GawwyG, 2026-10-18

All four are fixed in `main2.tex` (`main.tex` untouched). Then a full audit of `main2.tex` against `report/results2`, done
section by section after your four, found more; those fixes are listed under "Also fixed" below. Every new number has a
`% src:` comment; tables stay generated. The main text still ends on page 10, and `make_submission.sh` now checks where the
conclusion *ends* (new label `sec:end-of-main`), not where it starts. It also reruns LaTeX until the cross-references settle.

**1. Holm family: (a), three.** `paper_extra.py tests` now writes `p_holm` over the three Clock comparisons only (0.515 /
0.006 / 0.025; the bootstrap p-values are unchanged) and leaves it empty for the ARC rows. `p_holm_six` keeps the old family
for reference. RQ2: "($p=0.043$, uncorrected), within 0.01 of 1, so we do not count it as a win"; the "0.17" is gone. The
intro's "Against ARC no difference holds once corrected" is now "no difference is clear". Files: `tools/ml2/paper_extra.py`,
`report/results2/paper_extra_tests.csv`.

**2. k = 32.** You are right about the history. 32 (and 16) came from the simulator sweep `exp_sampling.py` on 8 Oct, on test
and held-out streams. The kernel runs of 32 vs 16 vs scoring every page at 10% kept 32 (R1, 13 Oct). The validation run of
17 Oct confirmed it. §3.6 now says: "$k=32$ was first picked from sweeps on the test and held-out streams; a rule fixed in
advance and applied to the validation streams only, [...] also picks 32". The Figure 5 caption is reworded the same way.

**3. Measured.** `cost_grid.py --sizes 820` ran for all 29 policies (824 candidates, the largest set any stream has: btree at
20%). The 32-sample score costs **8,832** there, so "under 8,900 at every memory size" now rests on a measurement and stays.
ARC needs 129,555 and scoring every page 211,582. Metrics now lists 20, 68, 260, 516 and 824 candidates. §3.6 says "from 68 to
824 candidates".
* **One catch.** The sampling-rule switch (vmrun `@32n` / `@32s`, added 16 Oct, after the grid) adds **14–16 instructions** to
  every sampled decision. That includes the default random one; victims and faults are unchanged. I re-measured on the
  current code (`report/results2/cost_grid_current_code.csv`): 8,481 / 8,804 / 8,895 at 68 / 260 / 516, against 8,465 / 8,788
  / 8,880 in the table. Scoring every page and the 20-candidate case are within 1 instruction.
* The 824 rows ran on the current code, so the old-code value there would be about 8,816. Both are under 8,900.
* I kept the table's numbers and said this in the Table 12 caption (appendix). Re-measuring the whole grid on the current code
  is in `backlog.md`.

**4. Limitation:** your wording, word for word.

**Also fixed (from the audit):**
* **Tables `tab:ci` and `tab:ci-full`** bolded every interval below 1. That includes ours vs ARC at 20% (up to 0.998), which
  the text says is not a win, and set-attention at 5% (0.994). They now come from `make_figdata2.py` (`ci_body2.tex`,
  `ci_full2.tex`), bold only below 0.99. The cells are identical; four bold marks are gone. `ci_body.tex` and week-16 `ci_main.tex`
  are unchanged, so `main.tex` renders as before.
* **Claims inside the 0.01 band, reworded:**
  * boosted trees at 10%: "average 6% more faults (interval from 1.01)";
  * even-spread sampling: "is, if anything, worse (1.007–1.041)";
  * set-attention at 5%: "too close to 1 to claim";
  * FIFO / Aging / LFU have no intervals: "incur 4–35% more faults on average".
* **Wrong numbers:**
  * Kernel lines: 5,900 → **4,400**. The diff counted `kernel/vmpage.c.orig`, a stray copy of `vmpage.c` from before the
    sampling-mode patch; it is now deleted.
  * Heavier models' read-only data: 100,716 → **305,976 bytes** (`nm -S kernel/kernel`; the old number predates the models
    added on 11 Oct).
  * S3-FIFO small queue: "at most 1.3% on average" → **1.1%**. 1.3% was the spread between the 5% and 30% settings, not the
    change from 10%.
  * Core-hours outside the heavier models: 407 → **302**. 407 subtracted only the five all-workload models.
  * Reference-implementation checks: "570 traces" → 15 random traces at up to 7 cache sizes = 95 cases per policy.
  * 32 MB → 32 MiB.
* **Appendix D, step (2):** the text "Merge every result file into one with" was inside a `%` comment, so the step started
  mid-sentence. Fixed.
* **Appendix A, splits:** "every stream of the other eight workloads is held out" is wrong for the pattern suite. It splits 9
  of 11 variants the same way, and only their test streams are run. Matmul's single-stream variants are training data.
* **RQ1:**
  * "every richer model fails on real traces" became "the three richer models we ran there are 22–41% worse". Only three ran,
    on two traces.
  * Added that on the Twitter replays kv's kernel-input trees beat kv's linear score (0.878 [0.849, 0.926],
    `extra_summary.csv`).
  * "Transfers best" is removed, as is "transfers better" from the Table 19 caption.
  * "2–5%" → 2–6%: global test 2.4%, held-out 5.5%.
  * "Tie where both work" → "win on some workloads (sort test 0.879 vs 0.983)".
  * The idle medians are per-workload models; the text now says so.
* **A2, one workload vs all six:** now from the kernel, because those models ran on all 74 streams at 10%. CNN, MLP and
  set-attention are worse; boosted trees are level; ranking trees improve (1.07 vs 1.35). The simulator said four of five. New
  `paper_extra.py oneall` writes `paper_extra_oneall.csv`.
* **Break-even:** the text quotes write-back-inclusive numbers (1.01, 2.2–3.4×), but the table was reads only (1.02,
  2.47–3.55). `tab:breakeven` now inputs `figures/data/breakeven_writes.tex` (`make_figdata2.py`, from
  `cost_benefit_with_writes_*.csv`). The caption gives the reads-only deltas and the 11-of-14 count, and it now references
  `tab:breakeven-wl` and `tab:breakeven-own`, which nothing referenced before.
* **Scope added where it was missing:**
  * "beats Clock inside the kernel" → at 10% and 20%;
  * the 0.91 / 0.92 times → at 10% memory;
  * Belady 39–44% → in simulation, and 7% of the gap closed at 5%;
  * conclusion → "with the core we measured" and "at 10% and 20% memory";
  * seeds → two seeds, 10 streams at 10%;
  * exact counts agree "per candidate wherever there are more than 40";
  * the simulator matches the kernel "geometric mean over the 74 streams" (by workload-then-equal-weight, LHD is 0.979);
  * matmul's feature selection used its training streams;
  * default weights score every page unless a sample size is set.
* **Softened or removed:**
  * cost "stays flat" / "does not grow" → "barely grows" (8,465 → 8,880);
  * Obs. 1 "as good as LRU" → "close to";
  * LFU "6–13% on btree" mixed test and held-out → 6% on test streams;
  * "failures repeat across memory sizes" removed (graph fails only at 20%, SpMV only at 5%);
  * the "Second," with no "First," is gone;
  * the Table 12 caption no longer says only Clock, S3-FIFO and the samples stay flat (FIFO is flatter than S3-FIFO);
  * the "92 intervals" count is gone (it included the 3 primary ones);
  * A3 now says the fourth feature group (all kernel and refault features) stayed at 1.39.

**Not changed, for you to decide:** Figure 2 uses kv test Belady 0.571 (all cells); `tab:info` uses 0.559 (15 cells). The
caption already explains this, so I left it.

### GawwyG, 2026-10-18 (later): the last backlog checks

* **`references.bib` is shared with `main.tex`, so this changes your copy too.**
  * `bansal2004car` gets pp. 187–200 (USENIX, DBLP and Crossref agree).
  * `vietri2018lecar` has no page numbers anywhere, including USENIX's own BibTeX, so it gets "USENIX Association, Boston, MA".
* **Re-derived in `main2.tex`:**
  * Integer scoring: the kernel-feature cells differ by up to 0.0078, so "0.007" is now "0.008"; "39 of 44" holds.
  * Simulator check (1): 534 → 1,194 cells. `validate.py` was rerun on all 199 streams × 6 sizes, and everything matches.
  * Training rows: recounted from the `.npz` files, and exact.
  * Training times: re-measured as 2.9 / 3.0 s for the trees on the CPU and 48 / 60 / 69 s for the networks on the GPU, so
    "2–67 s" is now "3–70 s" (`report/results2/training_times.csv`).

### GawwyG, 2026-10-18 (evening): for AU5TRA to keep in mind while editing `main2.tex`

GawwyG left `main2.tex` as it was at commit c640b28, so you can edit it. Please cover these four points:

1. **AI use.** Clarify how AI was used, or fill in the `\todo{second author ...}` in the AI Usage Disclosure. Say:
   * which tools drafted and edited the text, the figures and the literature review;
   * how the text and the references were checked;
   * whether a person checked the references.

   MLSys rejects papers whose content is generated by an AI alone, so the disclosure must show how the authors directed,
   rewrote and checked the work.
2. **Better diagrams.** Improve the figures, in particular the eviction-path figure (§2.1) and the overview figure (§3.1).
3. **Workloads in the main paper.** The workload table and the definitions should fit into the main paper.
   * Today the workloads are first used in §2.2 (btree, graph, kv, lzw, matmul, sort) but are only defined in §5.1 and in
     the appendix table (`tab:workloads`).
   * A reader meets the names before knowing what they are.
   * Define them where they are first used, with the training / validation / test / held-out split.
4. **State all sampling values.** Say what other sample sizes do, not only 32 and 16. See `backlog.md` item 10. The data is in
   Figure 5 (right) and `figures/data/kval_*.csv`.
   * Relative to scoring every page: 4 pages 1.05–1.14, 8 pages 1.02–1.07, 16 pages up to 1.02, 32 within 0.005, 48–64 no
     further gain (simulator, validation streams).
   * In the kernel, 16 pages is 1.013 at 10% memory.

   **GawwyG supports adding it.**

Also (GawwyG, for the paper's style): GawwyG prefers plain language with few numbers in the text (point to the tables
instead), no numbers in `\finding{}` headings, and one line per paragraph.

### GawwyG, 2026-10-18 (night): all fault counts now confirmed on the current code

`tools/ml2/recheck_linear.py` reran, on the current kernel, every linear-score run in `kernel_eval_all.csv` that was made
before the cheaper code (commit dbc508b): 405 runs. These are the full-scan "linear, global" rows at all three sizes, the
per-workload weights and their variants.
* **All 405 match exactly** in faults, evictions, page writes and zero-fill faults (`compare_runs.py`: 405 identical,
  0 different). The data is in `report/results2/kernel_eval_recheck_linear.csv`.
* The 222 runs of our policy (32 samples) were already made after the cheaper code.

So every fault count in the paper comes from code that picks the same victims as the current kernel. Please update
`main2.tex` while you edit:
1. **Limitations:** drop the bullet "Fault counts predate the cheaper code … checked identical on 28 runs, not on every stream".
2. **§4, "cheaper code" paragraph:** where it says 28 runs, write instead "all 405 linear-score runs made with the old code,
   rerun with the new code, give identical results".

### GawwyG, 2026-10-19: what changed in `main2.tex` (all your feedback and the four handed-over points are done)

GawwyG restored the plain-language version of `main2.tex` and applied your feedback.

**Your feedback:**
* **§3.1:** "for how many scans (0, 1, 2 or 4) a newly loaded page is protected from eviction".
* **§4:** "Training takes seconds: about 2 s for the linear model and 3 s for the tree models on the CPU, and 48–69 s for the
  neural networks on one GPU". The linear fit was measured: `training_times.csv`, `time_training.py --linear`.
* **Traced pages limitation:** rephrased.
* **Does 32 scale to Linux:** a new §7 paragraph. It covers the sample quality (1 − 0.9³² ≈ 97% for any memory size), the
  evidence up to 824 pages, cache_ext's own policies sampling 10–20 pages, and that multi-GB memories are untested.
* **Name:** the policy is now **PageScore**. The tables use renamed paper-only copies in `figures/data/w16/` (made by
  `make_figdata2.py`), so the week-16 report is unchanged.
* **Fewer headings:**
  * §2 has 3 subsections; the research questions are a closing paragraph.
  * §3 has 3 subsections, with no Observation/Solution labels.
  * §4 has no run-in headings.
  * §5 is Setup, "Answering the Research Questions" (RQ1–RQ4, with RQ4 restored) and Ablations.
* **Old 5.7:** moved to §7 as "Where PageScore does not help".
* **Main paper vs appendix:**
  * Table 5 (intervals) is cut to five key rows.
  * The feature-ranking figure and the cost-against-faults figure moved to the appendix.
  * The workload table moved into §2.2.

**The four handed-over points:**
1. **AI disclosure:** the Writing part now says the authors wrote the first draft, and the agent polished and edited at the
   authors' direction (reworded, applied the authors' structural changes, wrote a few short passages the authors asked
   for, checked numbers). **Please confirm this matches what you did**, and whether a person checked the references.
2. **Diagrams:** Figures 1 and 3 are redrawn in plain words. Figure 4 is full width with coloured better/worse regions, and
   Figure 5 is new (per-workload gains as coloured bars, training workloads vs never seen).
3. **Workloads:** the definitions and the table are in §2.2.
4. **Sampling values:** Table 3 (4, 8, 16, 32, 64 and every page: instructions and faults).

**Also:**
* the appendix is single-column so its tables are readable;
* the Table 1 bold on 0.882 is removed;
* "28 runs" became "all 405 runs";
* the LaTeX warnings are fixed (xcolor is now loaded before hyperref; `hypertexnames=false`).

The main text ends on page 10.

**Checked before committing (2026-10-19):**
* Two full read-only audits of `main2.tex` were run against the data, the bibliography and the cross-references; every
  problem they found is fixed.
* **Fixed:**
  * p-values now given;
  * the Twitter/real-trace claims now compare like with like;
  * "simulator within 2%" is now limited to 10% memory and the five policies;
  * contradictions are removed (DAgger, "how little the kernel can see");
  * conditions are added ("with 68 pages to choose from", "at 10% memory");
  * the simulator tables call their model "linear score" (not PageScore);
  * the break-even and sampling table captions are corrected;
  * the 824-pages column is explained;
  * appendix floats are kept in their sections.
* The build has no errors, no overfull boxes and no undefined references. The only remaining warning is the template's
  empty anchor from `\printAffiliationsAndNotice{}`, which goes away when author names are added at camera-ready.

### GawwyG, 2026-10-19 (later): your line comments, and two things queued

**Done in `main2.tex`:** the §3 overview sentence ("Five design choices make this work inside a kernel."); the "A fixed sample"
paragraph now justifies 32 (the best of 32 random pages is on average in the top 3% whatever the memory size, Table 3, the
validation rule); the §4 cheaper-code sentence no longer says "old code" and the training times name the CPU (Ryzen 5 5600)
and GPU (RTX 3060 Ti); two slips ("levelwith", "is analysed").

**Queued (backlog items 13 and 14):**
1. **Links.** The paper now says the code and dataset are released; Appendix D has red `[repository link]` and `[dataset link]`
   placeholders. Fill them once the repository and `traces2/` are uploaded (anonymous for review).
2. **Training-variety study.** Five hand-picked train/test splits, kernel runs. At 10% the choice of training workloads barely
   matters on unseen programs (within 1.3% of PageScore). 5% and 20% are running; when done it gets one paragraph in §5.3 and an
   appendix table, and it changes the "few workloads" limitation you commented out.

### GawwyG, 2026-10-20: training-variety study added, tables made readable

* **Study done** (555 kernel runs, all ok). §5.3 has a new paragraph "Which workloads to train on" and the appendix a new Table 22:
  on workloads a split did not train on, its model causes at most 3.7% more faults than PageScore (1.6% on average). So the
  limitation you cut ("few workloads") is now partly answered by data.
* **Tables:** Table 5 now puts each interval under its value (it was shrunk to tiny type); the per-workload appendix tables are
  full width; Tables 14–17 have grouped headers (core speed, device, per page vs per eviction) and one number format per column;
  Table 21 calls the simulator model "linear score" like the other simulator tables; most table captions are rewritten in plain
  words (no "cells", "one build", "first version").
* **Instruction counts:** all sampled-score counts were re-measured on the current kernel (+14–16 instructions), so Tables 1, 3
  and 13 come from one kernel and their notes are gone.
* The main text now ends exactly on page 10 (the limit): anything added to the main text needs a cut elsewhere.

