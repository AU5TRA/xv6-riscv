# main2.tex — what changed against main.tex, and why (GawwyG's review, 2026-10-17)

`main.tex` was not edited. `main2.tex` is the reviewed copy; merge what you accept. It builds (pdfLaTeX + BibTeX), has no undefined
references, and the main text still ends on page 10. Every new number has a `% src:` comment. Still open: `backlog.md`,
section "PAPER — still to do" (anonymous link, template year, stripping comments, the separate appendix upload, camera-ready items).

## Placeholders
* The three `\todo{anonymized code link}` removed (abstract, Availability, Conclusion); the link is a backlog item.

## Incorrect or inconsistent values
* **Belady on kv test**: Figure 2 / §2.2 use all test cells (0.571); Table `tab:info` uses the cells every model ran (15 of 18; 0.559).
  Both are right; the `tab:info` caption now says so.
* **Reproduction times** (Appendix D) were wrong ("graph 2–25 min, others ≤3"). Now: a Clock run takes seconds to ~half an hour, a heavier
  model up to ~4 h; all 4,489 runs ≈ 715 core-hours (`paper_extra.py summary`).
* Teaser: FIFO / Aging / LFU now to 3 decimals like the other rows (1.228/1.253/1.345, 1.043/1.066/1.166, 1.068/1.130/1.270).
* Stale comment "Framing and claim: PENDING decision D2" fixed.

## Substantive changes
1. **Framing.** Abstract and intro say plainly that the policy does not beat ARC/LHD: it matches them at lower, flat cost; Move 4 adds
   "learning matches the best hand-written rule at a lower cost ... and leaves most of the gap to Belady open".
2. **Gap to Belady (new data).** Belady on the kernel's own streams and memory sizes (simulator): 0.614 / 0.590 / 0.563 of Clock. The
   policy closes 7% / 21% / 22% of the Clock–Belady gap, ARC 14% / 14% / 4%, LHD ≤12% (`paper_extra_headroom.csv`). New paragraph
   "Far from optimal" in RQ2; one sentence in the intro and the conclusion.
3. **k = 32 chosen on validation data (new data).** Rule fixed before running: smallest k within 1% of scoring every page at every size,
   on the streams the global model was selected on. k = 32 is that k (1.000 / 1.005 / 0.996; 24 misses at 10%: 1.010)
   (`sampling_val.csv`, `exp_sampling_val.py`). §3.6 says so; Figure 5 (right) shows the curve.
4. **Write-backs in the time model (new data).** Measured write latency (SSD 22 µs, disk 2.6 ms) added (`cost_benefit.py
   --ssd-write-us/--hdd-write-us`): the policy's time ratios move by ≤0.01, no policy crosses 1 (`cost_benefit_with_writes_*.csv`).
   RQ3 and the "Faults, not writes" limitation updated; the policy's headline time numbers are now the with-writes ones
   (SSD 0.92, faster on 11/14; slow core 1.01, 8/14).
5. **Untuned baselines stated, with a check (new data).** Setup says the classical policies use published settings; S3-FIFO's small queue
   at 5/20/30% instead of 10% moves its faults by ≤1.3% (simulator, `paper_extra_s3.csv`; `pagesim.c` got `set_s3_small_pct`).
6. **Statistics.** Primary comparisons = the policy vs Clock at three sizes, with bootstrap p-values Holm-corrected over the three:
   0.515 / **0.006** / **0.025** (`paper_extra_tests.csv`). Everything else descriptive. The ARC 20% interval (p = 0.043) is reported
   as not surviving correction (0.17 over six). Replaces the ad-hoc "0.01 rule" as the main safeguard (kept for the descriptive rows).
7. **"Never used in training" made precise.** Their streams were never used in training or selection; kv-T reuses the trained kv
   program; pat and app are synthetic. Redis/SQLite: "one trace each, simulator only".
8. **Instruction-to-time conversion explained.** 0.047 ns = native x86 time / RISC-V instruction count, a conversion factor, not a
   clock rate; 1 ns justified as a 1 GHz in-order core at ~1 instruction per cycle.
9. **Absolute sizes.** Resident limits 2–205 / 4–410 / 8–820 pages (≤3.2 MB; medians 37 / 75 / 150).

## Readability ("how it could be better")
* **Learned weights shown** (§3.4): per-SD weights idle +1.29, age −1.01, dirty +0.15, refaults −1.63, rdist +0.88, in words.
* **New Figure 5**: per-stream distribution at 10% (ours better than Clock on 62/74 streams, worse on 7; ARC 52/13) and the validation
  k-curve. Data: `make_figdata2.py` → `figures/data/cdf_*.csv`, `kval_*.csv`.
* **Fewer numbers per sentence**: intro Move 5 and Move 7, contributions, RQ1 (LeCaR), RQ2 (wins), RQ3 (break-even, integer scoring),
  A5, §4, Discussion. Related work condensed (same citations).
* **To keep 10 pages**: the feature table moved to the appendix (the Discussion lists each feature's Linux analogue in prose);
  "The simulator predicts the kernel" shortened to one sentence (details in Appendix B).
* One name for our policy in prose ("our policy"); the tables keep "linear, 32 sampled", defined in the teaser caption.

## MLSys 2027 compliance (added 2026-10-17, after checking the official call and style archive)
* Template: the 2027 call prescribes `mlsys2025style.zip`; our style files are identical. 10-pt Times, Type-1 fonts only (checked).
* Page limit: main text ends on page 10 (references excluded).
* **AI Usage Disclosure added** after the references (mandatory; not counted in the page limit). Draft: the second author fills in
  the red writing part; both authors check every sentence (inaccurate disclosure risks desk rejection).
* Abstract shortened to 6 sentences (template: "roughly 4–6"); four citation groups put in chronological order (template rule).
* **Submission build: `bash make_submission.sh main2`.** Building with `\withappendixfalse` (main.tex's instruction) left 8 appendix
  references as "??"; the script builds once and splits into `submission/main2_paper.pdf` (14 pages: text, references, disclosure)
  and `submission/main2_appendix.pdf` (5 pages).
