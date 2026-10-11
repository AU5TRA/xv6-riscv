ROUND 2 (2026-10-11): the five model kinds trained on ALL workloads, at 5% and 20% memory
==========================================================================================
This folder now holds the round-2 package. Round 1 (your notebooks that already finished) is described further down.

REAL ETA: notebooks 2, 3 and 4 about 1.5 hours each; notebook 1 about 3.5 hours (it holds the Bloom filter at 5%: five runs of 1.5-3 hours each, which cannot be
split). All four run at the same time, plus about 15 minutes to install and build. The thesis PC runs the heaviest part (pointer chase at 5% and 20%, Bloom
filter at 20%: 15 runs, 6-9 hours each at Kaggle speed) in parallel, about 4 hours. The whole round finishes in about 4 to 4.5 hours.
How this was estimated (the round-1 estimate of 1.7 h was wrong; those notebooks took 6-8 h): 180 runs were repeated on the thesis PC and compared with the
Kaggle runs. The faults, evictions and writes were IDENTICAL on all 180, but the Kaggle machines are about 3.1 times slower than the PC (median; quartiles 2.9-3.2).
If a Kaggle machine is slower than usual allow up to 6 hours for notebook 1.

What to do (about 5 minutes, then waiting):
  1. Upload the NEW xv6_package.tar.gz: Kaggle -> your dataset "xv6-package" -> New Version -> drop in the new file -> Create.
     (Or make a second dataset and attach that one; the notebook finds any xv6_package.tar* under /kaggle/input.)
  2. In each of your 4 notebooks: delete the code cell, paste the NEW notebook_N.py (N = 1..4; they were rewritten), check the dataset input shows the new
     version, Accelerator = None, Internet = On, then Save Version -> Save & Run All (Commit).
  3. When they finish, download the files named kaggle_N_netsall.csv from each notebook's Output tab and put them into
     /home/gawwy/Thesis/xv6-riscv/report/results2/  (Claude merges them; nothing else to do).
  The runs are resumable: if a notebook stops, run it again. Each single run may now take up to 11 hours (the 3-hour limit that killed the Bloom runs in
  round 1 was raised). The self test at the start must say "faults 10511, expected 10511"; if it does not, stop and tell Claude.

------------------------------------------------------------------------------------------

KAGGLE PACKAGE: 4 notebooks that run part of the thesis' xv6 kernel tests
==========================================================================

WHAT THIS DOES
  Each notebook installs QEMU and a RISC-V compiler, builds the xv6 kernel, checks that one run gives exactly the
  same fault count as on your PC, and then runs its share of the 5% / 20% memory-size tests (about 1.7 hours each,
  4 notebooks at once). The tests only use CPU, so the notebooks need NO GPU.

WHAT YOU NEED TO SET UP (once)
  1. A Kaggle account with a verified phone number (needed to turn Internet on in notebooks).
  2. Upload the dataset:
       Kaggle -> Datasets -> New Dataset -> drag in  xv6_package.tar.gz  (0.7 MB, in this folder) -> name it
       "xv6-package" -> Create (Private is fine).
  3. Create 4 notebooks (Kaggle -> Code -> New Notebook), and in EACH one:
       a. Right-hand "Session options" / Settings: Accelerator = None (CPU only), Internet = On.
       b. + Add Input -> Your Datasets -> xv6-package.
       c. Delete the default code, paste the whole contents of notebook_N.py (N = 1..4, one file per notebook)
          into the first code cell.
       d. Save Version -> "Save & Run All (Commit)" -> Save. It runs in the background; you may close the tab.
          Do not use the interactive "Run" button: it stops when you leave.
  4. Tell me when the 4 notebooks have STARTED. I then restart my local jobs on my own (smaller) share, so nothing
     is run twice. Until then my local jobs keep running everything.

WHEN THEY FINISH (about 1.7 hours, 12 hours is the Kaggle limit)
  Open each notebook -> Versions -> the finished version -> Output tab -> download the files named
     kaggle_N_standard.csv, kaggle_N_nets.csv, kaggle_4_patapp.csv      (only the ones that exist)
  Copy them into  /home/gawwy/Thesis/xv6-riscv/report/results2/  (from Windows: \\wsl$\<your distro>\home\gawwy\...)
  and tell me. I merge them with the local results.

IF SOMETHING GOES WRONG
  - "xv6_package.tar.gz not found": you did not add the dataset as an input (step 3b).
  - apt-get / network errors: Internet is not On (step 3a) or the phone is not verified.
  - "SELF TEST FAILED": Kaggle's QEMU gives a different result than my machine. Stop, copy the message to me.
  - The notebook stops by itself on any error and prints the reason in its log; send me the last lines.

WHAT IS IN HERE
  xv6_package.tar.gz   the xv6 sources, the run scripts and the memory sizes (no traces)
  notebook_1..4.py     one script per notebook (each has its own list of streams to run)
  plan.json            which streams go to which notebook (and what stays local)
  local_resume.sh      restarts the local jobs on the local share (I run this after step 4)
