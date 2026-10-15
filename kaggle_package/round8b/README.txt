ROUND 8b (2026-10-16): the rest of round 8, on Kaggle instead of the thesis PC
==============================================================================
Round 8's four notebooks finished (21 streams x 6 sampling variants, all ok, in kaggle_results8/). The other 53 streams (318 runs) were meant for
the thesis PC; four Kaggle sessions are free, so they go to Kaggle too. SAME PACKAGE as round 8: do NOT upload anything new. The dataset's newest
version must still be round 8's xv6_package.tar.gz (the one you used for round 8; check it under the notebook's input).

WHAT: global@32, global@32n, global@32s, global@16, global@16n, global@16s (random, newest + random, evenly spread; 32 and 16 pages) at 10% memory
on 53 more streams: 14 + 14 + 14 + 11 streams = 318 runs.
ETA: about 2.7 hours per notebook at Kaggle speed on 4 cores plus 15 minutes of setup; allow up to 5 hours. No GPU: Accelerator = None, Internet = On.

What to do:
  1. Four notebooks (reuse the round 8 ones): delete the code cell, paste round8b/notebook_5.py ... notebook_8.py (one per notebook).
  2. Check the input shows the round 8 dataset version, Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download sampling_kaggle_5.csv ... sampling_kaggle_8.csv from each notebook's Output tab into
     /home/gawwy/Thesis/xv6-riscv/kaggle_results8b/ and tell Claude.
The self test at the start must say "faults 10511, expected 10511".
