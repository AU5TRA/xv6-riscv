ROUND 6 (2026-10-13): items R1 and R2 of the paper handoff (GAWWY_HANDOFF_PAPER.md, "NEW 2026-10-13")
===========================================================================================================
Earlier rounds are in round1/ .. round5/ (never changed). Same kernel and build as rounds 4 and 5.

WHAT: at 10% memory, on every stream that does not have them yet:
  R1  the linear score scanning only 32 or 16 random candidates per eviction (global@32, global@16);
  R2  the five heavier models trained on all workloads (cnn-all, mlp-all, attention-all, trees-all, ranktrees-all).
Together 440 runs: 161 in the four notebooks, 279 on this PC. Purpose: the claims about sampling and about the heavier models then rest on all 74 streams, not 2 to 10.

ETA: the work is split so that the notebooks and this PC finish together. Each notebook about 3.1 hours of runs plus about 15 minutes of setup (allow up to 5 hours if a
Kaggle machine is slow). This PC about 3.1 hours (6 lanes). No GPU: Accelerator = None.

What to do (about 5 minutes):
  1. Upload round6/xv6_package.tar.gz as a NEW VERSION of the dataset "xv6-package" (Kaggle -> dataset -> New Version).
  2. In each of the 4 notebooks: delete the code cell, paste round6/notebook_N.py (N = 1..4), check the input shows the new dataset version,
     Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download kaggle_N_models.csv from each notebook's Output tab into /home/gawwy/Thesis/xv6-riscv/kaggle_results6/ and tell Claude.
The self test at the start must say "faults 10511, expected 10511". Runs are resumable: if a notebook stops, run it again.
This PC's share: bash kaggle_package/round6/local_run.sh  (results: report/results2/kernel_eval_models.csv; Claude starts it).
