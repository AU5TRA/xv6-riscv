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
