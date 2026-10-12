ROUND 5 (2026-10-12): more streams at 5% and 20% memory (item N1 of the paper handoff)
=========================================================================================
Earlier rounds are in round1/ .. round4/ (never changed). Same kernel as round 4; the build fix from round 4 (no compiled tool in the package) is kept.

WHAT: 23 streams ran at 10% memory but not at 5% or 20%. This round runs them at both sizes (46 stream-and-size pairs), with eight policies each:
FIFO, Clock, Aging, LFU, ARC, LHD, S3-FIFO (the adapted kernel forms) and the global linear score. 368 runs. The five heavier models are not run (they were only ever run on ten streams).
Purpose: the intervals at 5% and 20% become as wide as at 10% (74 streams instead of 51 at each size).

ETA: the work is split so that this PC and the four notebooks finish at about the same time. Each notebook: about 2.6 to 3.1 hours of runs plus about 15 minutes of
setup (allow up to 4.5 hours if a Kaggle machine is slow). This PC: about 2.6 hours (6 lanes). No GPU: Accelerator = None.

What to do (about 5 minutes):
  1. Upload round5/xv6_package.tar.gz as a NEW VERSION of the dataset "xv6-package" (Kaggle -> dataset -> New Version).
  2. In each of the 4 notebooks: delete the code cell, paste round5/notebook_N.py (N = 1..4), check the input shows the new dataset version,
     Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download kaggle_N_more.csv from each notebook's Output tab into /home/gawwy/Thesis/xv6-riscv/kaggle_results5/ and tell Claude.
The self test at the start must say "faults 10511, expected 10511". Runs are resumable: if a notebook stops, run it again.
This PC's share: bash kaggle_package/round5/local_run.sh  (results: report/results2/kernel_eval_more.csv; Claude starts it).
