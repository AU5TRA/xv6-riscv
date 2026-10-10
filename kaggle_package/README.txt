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
