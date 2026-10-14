ROUND 9 (2026-10-15): the five heavier models at 5% and 20% memory on all 74 streams (item 4 of the "open, not done" list; queued AFTER round 8)
==========================================================================================================================================
Earlier rounds are in round1/ .. round8/ (never changed). The kernel is the one in the repository at the time of building (with LeCaR, without the
sampling patch of round 8). Builds differ by about 1% between rounds; the heavier models at 10% came from the round-6 build.

WHAT: cnn-all, mlp-all, attention-all, trees-all, ranktrees-all at 5% and at 20% memory on every stream that does not have them yet:
640 runs minus the 100 that exist = 540 runs: 175 in the six notebooks, 365 on the thesis PC (bash round9/local_run.sh, started by Claude).
Purpose: the intervals of the heavier models at 5% and 20% then rest on 74 streams instead of ten.

ETA (estimate, about 109 core-hours at this PC's speed in total): each notebook about 8 hours of runs at Kaggle speed on 4 cores plus 15 minutes of setup.
My estimates for the heavy models were about 2x too low before, so a notebook may hit Kaggle's 12-hour limit. Runs are resumable: if a notebook stops,
run it again. This PC: about 8 hours (6 lanes). No GPU: Accelerator = None.

What to do (about 10 minutes):
  1. Upload round9/xv6_package.tar.gz as a NEW VERSION of the dataset "xv6-package".
  2. In each of the 6 notebooks: delete the code cell, paste round9/notebook_N.py (N = 1..6), check the input shows the new dataset version,
     Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download kaggle_N_sizes.csv from each notebook's Output tab into /home/gawwy/Thesis/xv6-riscv/kaggle_results9/ and tell Claude.
The self test at the start must say "faults 10511, expected 10511".
