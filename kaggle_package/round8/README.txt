ROUND 8 (2026-10-15): other ways of choosing the sampled pages, in the kernel (follow-up to R1)
================================================================================================
THIS ROUND NEEDS THE KERNEL IN THIS PACKAGE (it adds "model@32n" and "model@32s" to vmrun; the patch is kernel_sampling.patch).
Earlier rounds are in round1/ .. round7/ (never changed).

WHAT: the global linear score scanning only k pages per eviction, at 10% memory, on all 74 streams, six variants, ALL rerun in this one build
(so they can be compared with each other without build differences):
  global@32  global@16     k random pages (what round 6 ran)
  global@32n global@16n    the k/4 newest loaded pages + random rest
  global@32s global@16s    evenly spread over the load order (every (count/k)-th page, the start moves on)
444 runs: 126 in the four notebooks, 318 on the thesis PC (bash round8/local_run.sh, started by Claude after the LeCaR run ends).
Results go to files named sampling_kaggle_N.csv (NOT kaggle_N_*.csv, so they never mix with the earlier results).

ETA: each notebook about 2.3 to 2.7 hours of runs at Kaggle speed plus 15 minutes of setup; my estimates for the heavy models were about 2x too low
before, so allow up to 6 hours. This PC: about 2.5 hours after the LeCaR run ends. No GPU: Accelerator = None.

What to do (about 5 minutes):
  1. Upload round8/xv6_package.tar.gz as a NEW VERSION of the dataset "xv6-package".
  2. In each of the 4 notebooks: delete the code cell, paste round8/notebook_N.py (N = 1..4), check the input shows the new dataset version,
     Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download sampling_kaggle_N.csv from each notebook's Output tab into /home/gawwy/Thesis/xv6-riscv/kaggle_results8/ and tell Claude.
The self test at the start must say "faults 10511, expected 10511". Runs are resumable: if a notebook stops, run it again.
