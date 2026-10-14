# Instruction count per eviction (exact, QEMU icount mode) under different compiler flags, on private copies of the tree.
import re, shutil, subprocess, sys, threading
from pathlib import Path
sys.path.insert(0, "/home/gawwy/Thesis/xv6-riscv/tools/ml2")
import cost_grid as cg
ROOT = Path("/home/gawwy/Thesis/xv6-riscv")
VARIANTS = {"O1_baseline": "-O", "O2": "-O2", "O3": "-O3", "O2_nofp": "-O2 -fomit-frame-pointer", "Os": "-Os"}
def lane(name, flags):
    d = Path(f"/tmp/xv6flags_{name}")
    if d.exists(): shutil.rmtree(d)
    subprocess.run(["rsync", "-a", "--exclude", "traces", "--exclude", "traces2", "--exclude", "report", "--exclude", ".git", "--exclude", "test-logs", f"{ROOT}/", f"{d}/"], check=True)
    mk = d / "Makefile"; t = mk.read_text()
    assert "-O -fno-omit-frame-pointer" in t
    t = t.replace("-O -fno-omit-frame-pointer", flags + (" " if "omit-frame" in flags else " -fno-omit-frame-pointer"))
    t = t.replace("format=raw,id=x0\n", "format=raw,id=x0,cache=unsafe\n")
    mk.write_text(t)
    for pat in ("kernel/*.o", "kernel/*.d", "user/*.o", "user/*.d", "kernel/kernel", "user/_*", "fs.img"):
        for f in d.glob(pat): f.unlink()
    return d
out = open("/tmp/flags_result.csv", "w"); out.write("variant,policy,model,select_instr,path_instr,candidates\n")
lock = threading.Lock()
def work(name, flags):
    d = lane(name, flags)
    for pol, model in (("clock", ""), ("aging", ""), ("ml", "global"), ("ml", "global@32")):
        r = cg.one(d, 64, pol, model, 20000)
        with lock:
            if r:
                ev = max(r["evictions"], 1)
                out.write(f"{name},{pol},{model},{round(100*r['select_ticks']/ev)},{round(100*r['path_ticks']/ev)},{round(r['candidates_scanned']/ev,1)}\n")
            else:
                out.write(f"{name},{pol},{model},FAILED,,\n")
            out.flush()
ts = [threading.Thread(target=work, args=(n, f)) for n, f in VARIANTS.items()]
[t.start() for t in ts]; [t.join() for t in ts]
print("done")
