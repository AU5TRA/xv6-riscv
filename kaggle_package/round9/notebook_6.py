# xv6 kernel runs for the thesis -- notebook __ID__ of 4.
# Paste this whole file into ONE code cell of a new Kaggle notebook (Accelerator: None, Internet: On) and use
# "Save Version" -> "Save & Run All (Commit)". When it has finished, download the files named kaggle_*.csv from the
# notebook's Output tab. See README.txt in the package.
import csv, glob, json, os, re, shutil, subprocess, sys, tarfile, threading, time

CONFIG = json.loads(r'''{
 "id": 6,
 "standard": [],
 "nets": [],
 "patapp": false,
 "sizes": [
  [
   "chase-list-s1",
   "0.05",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "lzw-r20-s5",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "bloom-k3-s1",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "btree-lookup-s5",
   "0.05",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "btree-scan-s5",
   "0.05",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "btree-mixedwal-s5",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "pat-scanhot-s5",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "pat-scanhotlo-s5",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "kv-T24-s1",
   "0.05",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "kv-T4-s1",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "app-hashjoin-s1",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ],
  [
   "sort-n60000-s2",
   "0.2",
   [
    "cnn-all",
    "mlp-all",
    "attention-all",
    "trees-all",
    "ranktrees-all"
   ]
  ]
 ],
 "short": [
  "app-bloom-s1",
  "app-chase-s1",
  "app-hashjoin-s1",
  "app-spmv-s1",
  "pat-loop-s5",
  "pat-phase-s5",
  "pat-phaseshort-s5",
  "pat-scanhot-s5",
  "pat-scanhotlo-s5",
  "pat-switch-s1",
  "pat-uniform-s5",
  "pat-zipf060-s5",
  "pat-zipf080-s5",
  "pat-zipf099-s5",
  "pat-zipf120-s1"
 ],
 "selftest": {
  "stem": "kv-A-s5",
  "faults": 10511,
  "frames": 53
 }
}''')

NETS = "cnn-kv,attention-graph,mlp-kv,ranktrees-graph,trees-kv"
NETS_ALL = "cnn-all,attention-all,mlp-all,ranktrees-all,trees-all"
SRC = os.environ.get("XV6_DIR", "/tmp/xv6")
OUTDIR = os.environ.get("XV6_OUT", "/kaggle/working")
T0 = time.time()


def say(*a):
    print(f"[{(time.time() - T0) / 60:6.1f} min]", *a, flush=True)


def sh(cmd, check=True, **kw):
    say("$", cmd)
    r = subprocess.run(cmd, shell=True, **kw)
    if check and r.returncode:
        raise SystemExit(f"command failed ({r.returncode}): {cmd}")
    return r


# 1. the package and the tools -------------------------------------------------------------------------------
INPUT = os.environ.get("XV6_INPUT", "/kaggle/input")
pk = glob.glob(f"{INPUT}/**/xv6_package.tar*", recursive=True) or glob.glob("./xv6_package.tar*")
extracted = [os.path.dirname(m) for m in glob.glob(f"{INPUT}/**/Makefile", recursive=True)
             if os.path.exists(os.path.join(os.path.dirname(m), "kernel", "vmpage.c"))]
if not pk and not extracted:
    say(f"nothing found under {INPUT}. What is there:")
    for root, dirs, files in os.walk(INPUT):
        if root.count(os.sep) - INPUT.count(os.sep) <= 3:
            print("  ", root, files[:8], flush=True)
    raise SystemExit("the xv6-package dataset is not attached to this notebook: use '+ Add Input' -> 'Your Datasets' "
                     "(or 'Datasets' tab), pick it, and check it appears under /kaggle/input in the right-hand panel")
if not os.environ.get("SKIP_APT"):
    sh("apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gcc-riscv64-linux-gnu "
       "binutils-riscv64-linux-gnu qemu-system-misc make rsync python3-pexpect")
sh("riscv64-linux-gnu-gcc --version | head -1; qemu-system-riscv64 --version | head -1; nproc")
shutil.rmtree(SRC, ignore_errors=True)
os.makedirs(os.path.dirname(SRC), exist_ok=True)
if pk:
    say("package file:", pk[0])
    with tarfile.open(pk[0]) as t:
        t.extractall(os.path.dirname(SRC))
    if os.path.basename(SRC) != "xv6":
        os.rename(os.path.join(os.path.dirname(SRC), "xv6"), SRC)
else:   # Kaggle unpacked the archive when the dataset was created
    say("package folder:", extracted[0])
    shutil.copytree(extracted[0], SRC)
os.makedirs(f"{SRC}/report/results2", exist_ok=True)
if os.path.exists(f"{SRC}/mkfs/mkfs"):      # a host binary from another machine; Kaggle datasets drop the executable bit, so build it here
    os.remove(f"{SRC}/mkfs/mkfs")
sh(f"cd {SRC} && make kernel/kernel fs.img > build.log 2>&1; tail -2 build.log")
if not os.path.exists(f"{SRC}/kernel/kernel") or not os.path.exists(f"{SRC}/fs.img"):
    raise SystemExit("the build failed; see build.log (printed below)\n" + open(f"{SRC}/build.log").read()[-3000:])
LANES = str(os.cpu_count() or 4)
RES = f"{SRC}/report/results2"
ENV = dict(os.environ, KERNEL_EVAL_LANES="/tmp/xv6lane")


def keval(out, args, start=None):
    """run kernel_eval.py; its result file is resumable, `start` = rows to begin with"""
    path = f"{RES}/{out}"
    if start and not os.path.exists(path):
        shutil.copyfile(f"{SRC}/{start}", path)
    env = dict(ENV, KERNEL_EVAL_OUT=out)
    return sh(f"cd {SRC}/tools/ml2 && python3 -u kernel_eval.py --lanes {LANES} {args}", check=False, env=env)


def save():
    for f in glob.glob(f"{RES}/kaggle_*.csv") + glob.glob(f"{RES}/sampling_kaggle_*.csv"):
        shutil.copyfile(f, f"{OUTDIR}/{os.path.basename(f)}")


def saver():
    while True:
        time.sleep(600)
        save()


threading.Thread(target=saver, daemon=True).start()

# 2. self test: one run must give exactly the fault count measured on the thesis machine ---------------------------
st = CONFIG["selftest"]
keval("selftest.csv", f"--fracs 0.1 --only {st['stem']} --splits test --nonml clock")
row = [r for r in csv.DictReader(open(f"{RES}/selftest.csv")) if r["status"] == "ok"]
got = int(row[0]["swap_faults"]) + int(row[0]["zero_faults"]) if row else None
say(f"self test: faults {got}, expected {st['faults']}")
if got != st["faults"]:
    raise SystemExit("SELF TEST FAILED: this machine's QEMU / compiler gives a different fault count; stop here and tell Claude.")

if os.environ.get("SELFTEST_ONLY"):
    raise SystemExit("self test passed (SELFTEST_ONLY)")

# 3. this notebook's share -----------------------------------------------------------------------------------------
i = CONFIG["id"]
if CONFIG["standard"]:
    keval(f"kaggle_{i}_standard.csv", f"--fracs 0.05,0.2 --only {','.join(CONFIG['standard'])} --splits test,heldout "
          f"--nonml fifo,clock,aging,lfu --models global,own", start="start_kernel_eval_w16e.csv")
    save()
if CONFIG["nets"]:
    keval(f"kaggle_{i}_nets.csv", f"--fracs 0.05,0.2 --only {','.join(CONFIG['nets'])} --splits test,heldout --models {NETS}",
          start="start_kernel_eval_w16f.csv")
    save()
if CONFIG.get("netsall"):
    for fr in ("0.05", "0.2"):
        sts = [st for st, f in CONFIG["netsall"] if f == fr]
        if sts:
            keval(f"kaggle_{i}_netsall.csv", f"--fracs {fr} --only {','.join(sts)} --splits test,heldout --models {NETS_ALL} --timeout 40000")
            save()
if CONFIG.get("classic"):
    for fr in ("0.05", "0.2"):
        for is_short in (False, True):
            sts = [st + "$" for st, f in CONFIG["classic"] if f == fr and (st in CONFIG["short"]) == is_short]
            if sts:
                keval(f"kaggle_{i}_{CONFIG.get('classic_tag', 'classic')}.csv", f"--fracs {fr} {'--accesses 50000 ' if is_short else ''}--only {','.join(sts)} --splits test,heldout "
                      f"--nonml {CONFIG.get('classic_policies', 'arck,s3fifo,lhd')} --timeout 40000")
                save()
if CONFIG.get("more"):
    for fr in ("0.05", "0.2"):
        for is_short in (False, True):
            sts = [st + "$" for st, f in CONFIG["more"] if f == fr and (st in CONFIG["short"]) == is_short]
            if sts:
                keval(f"kaggle_{i}_more.csv", f"--fracs {fr} {'--accesses 50000 ' if is_short else ''}--only {','.join(sts)} --splits test,heldout "
                      f"--nonml fifo,clock,aging,lfu,arck,s3fifo,lhd --models global --timeout 40000")
                save()
if CONFIG.get("models"):
    groups = {}
    for st, miss in CONFIG["models"]:
        groups.setdefault((tuple(miss), st in CONFIG["short"]), []).append(st + "$")
    for (miss, is_short), sts in sorted(groups.items()):
        keval(CONFIG.get("models_file", f"kaggle_{i}_models.csv"), f"--fracs 0.1 {'--accesses 50000 ' if is_short else ''}--only {','.join(sts)} --splits test,heldout "
              f"--models {','.join(miss)} --timeout 40000")
        save()
if CONFIG.get("sizes"):
    groups = {}
    for st, fr, miss in CONFIG["sizes"]:
        groups.setdefault((fr, tuple(miss), st in CONFIG["short"]), []).append(st + "$")
    for (fr, miss, is_short), sts in sorted(groups.items()):
        keval(f"kaggle_{i}_sizes.csv", f"--fracs {fr} {'--accesses 50000 ' if is_short else ''}--only {','.join(sts)} --splits test,heldout "
              f"--models {','.join(miss)} --timeout 40000")
        save()
if CONFIG["patapp"]:
    streams = "pat-zipf099-s5,pat-phase-s5,pat-scanhot-s5,pat-loop-s5,pat-uniform-s5,app-chase-s1,app-spmv-s1,app-hashjoin-s1,app-bloom-s1"
    keval(f"kaggle_{i}_patapp.csv", f"--fracs 0.05,0.2 --accesses 50000 --only {streams} --splits test,heldout "
          f"--nonml fifo,clock,aging,lfu --models global,global-k,{NETS}")
    save()
save()
say("DONE. Download kaggle_*.csv from the Output tab.")
