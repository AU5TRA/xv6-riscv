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
* DAgger, three rounds on the first-version data (tools/ml2/r3_dagger_v1.py; report/results2/r3_dagger_v1.csv; graph only, validation stream
  graph-pr2000x2-s2 at 10%, faults / Clock; each round records under the previous model, adds those rows to all earlier ones, refits):

  | model | round 0 | 1 | 2 | 3 |
  |---|---|---|---|---|
  | best of the 300 | 0.762 | 0.765 | 0.763 | 0.759 |
  | median of the 300 | 3.00 (stopped) | 2.01 | 2.49 | 3.00 (stopped) |
  | all 12 features | 3.00 (stopped) | 0.914 | 0.879 | 0.871 |

  So "DAgger did not help" is NOT reproduced as a general statement: the all-features model goes from failing to 0.87 of Clock, the best model
  does not change (already good), the median model moves around without settling. With the current deterministic seeds the honest wording is:
  DAgger helped some of the failing models and not others (first version of the study, graph only).
