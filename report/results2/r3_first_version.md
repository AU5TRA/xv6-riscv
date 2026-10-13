# R3: the first-version failure on PageRank, rerun 2026-10-13 (tools/ml2/r3_first_version.py)

Data as in the first version of the study: candidates sampled uniformly (N_RECENT = 0, no "most recently used" slots), no probation
(protect_age 0), built with the current deterministic seeds into a separate cache (ML2_CACHE=/tmp/ml2_v1; the committed data are untouched).
All 300 linear feature sets fitted on graph's training rows, replayed on graph-pr2000x2-s2 at 10% (167 frames, 6,143,976 references,
Clock 53,782 faults). Per-model results: report/results2/r3_first_version.csv.

* 203 of the 300 linear models make at least 3x Clock's faults (the run is stopped at 3x); median of the 300 is 3.00x; the best is 0.762x Clock.
  So "almost every" in the old text becomes "two thirds (203 of 300)"; some models do fine, but two thirds of the 300 feature sets fail.
* Victims of a failing model (the median model, aging+sfreq+idle+age+dirty+refaults+rdist; and the all-features model):
  85.7% and 87.3% of victims had been loaded at the previous fault (old text: 97%);
  median references until a victim is needed again: 15 and 16 (old text: 16);
  Belady's choice was last used a median of 270 and 234 references earlier (old text: about 300);
  167 resident pages.
* The best of the 300 (rec+freq+ref+aging+sfreq+idle+age+dirty+refaults+rdist) does not do this: 0.9% of its victims were loaded at the previous fault.
* DAgger: not rerun on the first-version data. The DAgger table in tables.md (one round, per-workload linear models) was produced with
  extras.py dagger on the current datasets (commit 8228ea7, deterministic seeds); it shows no consistent gain (e.g. btree held-out kernel tier
  0.875 -> 0.904, graph test 0.872 -> 0.898). The "three rounds on the first version" statement stays labelled "first version of the study".
