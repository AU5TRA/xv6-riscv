# Exact instructions per eviction (QEMU instruction counting) for code changes that should pick exactly the same victims.
import shutil, subprocess, sys, threading
from pathlib import Path
sys.path.insert(0, "/home/gawwy/Thesis/xv6-riscv/tools/ml2")
import cost_grid as cg
BASE = Path("/tmp/xv6fastsrc")
VARIANTS = {
    "log_inline_msb": "CFLAGS += -DML_FAST_LOGCACHE -DML_FAST_INLINE -DML_FAST_MSB",
    "log_inline_unroll": "CFLAGS += -DML_FAST_LOGCACHE -DML_FAST_INLINE -DML_FAST_UNROLL",
    "log_inline_msb_unroll": "CFLAGS += -DML_FAST_LOGCACHE -DML_FAST_INLINE -DML_FAST_MSB -DML_FAST_UNROLL",
}
OLD = {
    "plain": "",
    "logcache": "CFLAGS += -DML_FAST_LOGCACHE",
    "onepass": "CFLAGS += -DML_FAST_ONEPASS",
    "both": "CFLAGS += -DML_FAST_LOGCACHE -DML_FAST_ONEPASS",
    "both_O2_vm": "CFLAGS += -DML_FAST_LOGCACHE -DML_FAST_ONEPASS\nkernel/vmpage.o kernel/vm.o: CFLAGS += -O2",
    "both_O3_vm": "CFLAGS += -DML_FAST_LOGCACHE -DML_FAST_ONEPASS\nkernel/vmpage.o kernel/vm.o: CFLAGS += -O3",
}
RUNS = [(64, "ml", "global"), (256, "ml", "global"), (64, "ml", "global@32"), (64, "aging", ""), (64, "arck", ""), (64, "lhd", ""), (16, "ml", "global"), (512, "ml", "global")]
def lane(name, extra):
    d = Path(f"/tmp/xv6fastvar_{name}")
    if d.exists(): shutil.rmtree(d)
    subprocess.run(["rsync", "-a", f"{BASE}/", f"{d}/"], check=True)
    mk = d / "Makefile"; t = mk.read_text()
    t = t.replace("format=raw,id=x0\n", "format=raw,id=x0,cache=unsafe\n")
    i = t.index("CFLAGS += -std=gnu99")
    t = t[:i] + (extra + "\n" if extra and "kernel/vmpage.o" not in extra else (extra.split("\n")[0] + "\n" if extra else "")) + t[i:]
    if "kernel/vmpage.o" in extra:
        t += "\n" + extra.split("\n")[1] + "\n"
    mk.write_text(t)
    for pat in ("kernel/*.o", "kernel/*.d", "user/*.o", "user/*.d", "kernel/kernel", "user/_*", "fs.img"):
        for f in d.glob(pat): f.unlink()
    return d
out = open("/tmp/fast_result3.csv", "w"); out.write("variant,frames,policy,model,select_instr,path_instr,faults\n")
lock = threading.Lock()
def work(name, extra):
    d = lane(name, extra)
    for n, pol, model in RUNS:
        r = cg.one(d, n, pol, model, 20000)
        with lock:
            if r:
                ev = max(r["evictions"], 1)
                out.write(f"{name},{n},{pol},{model},{round(100*r['select_ticks']/ev)},{round(100*r['path_ticks']/ev)},{r['swap_faults']+r['zero_faults']}\n")
            else:
                out.write(f"{name},{n},{pol},{model},FAILED,,\n")
            out.flush()
ts = [threading.Thread(target=work, args=(n, e)) for n, e in VARIANTS.items()]
[t.start() for t in ts]; [t.join() for t in ts]
print("done")
