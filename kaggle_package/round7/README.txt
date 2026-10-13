ROUND 7 (2026-10-14): LeCaR in the kernel at 5% and 20% memory (optional extra for R4 of the paper handoff)
==============================================================================================================
Earlier rounds are in round1/ .. round6/ (never changed). THIS ROUND USES A NEWER KERNEL (it has the LeCaR policy, commit d6f885f), so the
dataset "xv6-package" must get the new version from this folder. The kernel is otherwise the same as in round 6.

WHAT: the LeCaR policy (kernel form) on the 74 streams at 5% and 20% memory = 148 runs, split over the four notebooks (37 each).
The 10% runs are done on the thesis PC (kernel_eval_lecar.csv). Nothing else is run here.

ETA: each notebook about 5 lane-hours of runs at Kaggle speed on 4 cores = about 1.3 hours, plus about 15 minutes of setup.
My estimates for the heavier models in round 6 were about twice too low, so allow up to 3 to 4 hours per notebook. Limit is 12 hours per notebook.
No GPU: Accelerator = None.

What to do (about 5 minutes):
  1. Upload round7/xv6_package.tar.gz as a NEW VERSION of the dataset "xv6-package" (Kaggle -> dataset -> New Version).
  2. In each of the 4 notebooks: delete the code cell, paste round7/notebook_N.py (N = 1..4), check the input shows the new dataset version,
     Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download kaggle_N_lecar.csv from each notebook's Output tab into /home/gawwy/Thesis/xv6-riscv/kaggle_results7/ and tell Claude.
The self test at the start must say "faults 10511, expected 10511". Runs are resumable: if a notebook stops, run it again.
