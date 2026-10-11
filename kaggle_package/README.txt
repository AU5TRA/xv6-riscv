ROUND 3 (2026-10-11): ARC, S3-FIFO and LHD in the kernel, at 5% and 20% memory
================================================================================
Earlier rounds are archived in round1/ and round2/ (their notebooks and packages, unchanged).

ETA: each of the 4 notebooks about 2.3 hours of runs plus about 15 minutes to install and build; allow up to 3.5 hours if the Kaggle machine is slow
(the estimate is each cell's Clock run time x 3.1 for Kaggle's slower machines, x 3 policies, balanced over the 4 notebooks; LHD may cost a little more
than Clock). No GPU: Accelerator = None.

The thesis PC runs the 10% memory part of the same three policies at the same time (about 2 to 3 hours).

What to do (about 5 minutes):
  1. Upload the NEW xv6_package.tar.gz: Kaggle -> your dataset "xv6-package" -> New Version -> drop in the new file -> Create.
     The package now contains the kernel with the three new policies, so it MUST be the new version.
  2. In each of your 4 notebooks: delete the code cell, paste the NEW notebook_N.py (N = 1..4), check the dataset input shows the new version,
     Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download kaggle_N_classic.csv from each notebook's Output tab into
     /home/gawwy/Thesis/xv6-riscv/kaggle_results3/   (Claude merges them).
  The runs are resumable: if a notebook stops, run it again. The self test at the start must say "faults 10511, expected 10511" (it did on the
  rebuilt kernel here); if it does not, stop and tell Claude.
