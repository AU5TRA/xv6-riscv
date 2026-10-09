#!/usr/bin/env python3
"""Where do the kernel and the simulator choose different victims?

Runs one stream in xv6 with `vmrun -v` (every victim printed on the console) and in the simulator with the same
policy and memory size, then compares the two lists eviction by eviction: how many kernel victims are not arena pages
(code, stack: the simulator's trace has none), how long the two agree, the candidate counts, and the first
disagreement.

    python3 victims_cmp.py STEM FRACTION POLICY [MODEL]       e.g.   kv-T17-s1 0.1 ml kv
"""
import re
import subprocess
import sys

import numpy as np

import kernel_eval as ke
import kernel_vs_sim as kvs
import pagesim as ps

ROOT = ke.ROOT


def run_kernel(cmd, timeout=3600):
    p = subprocess.run(["python3", "tools/run_xv6_tests.py", "--cpus", "1", "--timeout", str(timeout), " ".join(cmd)],
                       cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"(/\S+\.log)", p.stdout + p.stderr)
    return open(m.group(1), errors="replace").read()


def arena_base(stem, frames):
    """vpn of the arena's first page in the current binary: a traced run with room for everything."""
    cmd = ke.command(stem, 8000)
    cmd[ke.FLAGS_ARG.get(cmd[0], -1)] = "9"
    cmd = [c for c in cmd]
    txt = run_kernel(cmd)
    return int(re.search(r"arena_start_vpn=(\d+)", txt).group(1))


def main():
    stem, frac, pol = sys.argv[1:4]
    model = sys.argv[4] if len(sys.argv) > 4 else ""
    s = ps.load_stream(stem)
    frames = s.capacities[frac]
    base = arena_base(stem, frames)
    cmd = ["vmrun", "-v", pol] + ([model] if model else []) + ke.command(stem, frames)
    txt = run_kernel(cmd)
    cut = re.search(r"== \w+: workload ==", txt)       # evictions before this line are setup and populate
    pre = len(re.findall(r"^VICTIM ", txt[:cut.start()], re.M)) if cut else 0
    kv = [(int(a), int(b, 16), int(c)) for a, b, c in re.findall(r"^VICTIM (\d+) ([0-9a-f]+) (\d+)", txt[cut.start():] if cut else txt, re.M)]
    print(f"  evictions before the workload starts (setup, populate): {pre}")
    kvpn = np.array([v[1] for v in kv])
    kcnt = np.array([v[2] for v in kv])
    ent = [e for e in ke.json.load(open(ke.INDEX))["streams"] if e["stem"] == stem][0]
    r = {"policy": pol, "model": model, "frames": frames, "split": ent["split"], "workload": ent["workload"]}
    sim_model = None
    if pol == "ml":
        r["policy"] = "ml"
        sim_model = kvs.simulate.__globals__["netint"].scored(kvs.Z.load_spec(kvs.NETS[model.split("@")[0]]), 2) \
            if model.split("@")[0] in kvs.NETS else None
        if sim_model is None:
            spec = kvs.FM[model]
            import numpy as _np
            sim_model = ps.ScoredModel("mlp", features=spec["features"], mean=spec["mean"], std=spec["std"],
                                       layers=[(_np.asarray(L["W"], _np.float32), _np.asarray(L["b"], _np.float32))
                                               for L in spec["layers"]], quant_w=8, protect_age=spec.get("protect_age", 0))
    if sim_model is None:
        raise SystemExit("only ml policies for now")
    svpn, scnt = ps.victims(s, frames, sim_model)
    # simulator pages are numbered from the dataset's own base; shift to the kernel's
    svpn = svpn - svpn.min() if False else svpn
    shift = base - int(s.vpns.min())
    svpn = svpn + shift
    n = min(len(kvpn), len(svpn))
    inarena = kvpn >= base                      # below the arena: program text, data, stack
    print(f"{stem} {frac} frames={frames} policy={pol}:{model}")
    print(f"  evictions: kernel {len(kvpn)}, simulator {len(svpn)}; arena base vpn {base}")
    print(f"  kernel victims below the arena (text, data, stack): {int((~inarena).sum())} ({100 * (~inarena).mean():.1f}%)"
          f"  distinct such pages {len(set(kvpn[~inarena].tolist()))}")
    print(f"  candidate count: kernel mean {kcnt.mean():.1f} (min {kcnt.min()}, max {kcnt.max()}), simulator mean {scnt.mean():.1f}"
          f" (min {scnt.min()}, max {scnt.max()})")
    same = (kvpn[:n] == svpn[:n])
    first = int(np.argmin(same)) if not same.all() else n
    print(f"  same victim in {100 * same.mean():.1f}% of the first {n} evictions; first difference at eviction {first}")
    for i in range(first, min(first + 6, n)):
        print(f"    eviction {i}: kernel vpn {kvpn[i]} (candidates {kcnt[i]}), simulator vpn {svpn[i]} (candidates {scnt[i]})")
    # after the first difference the runs are in different states, so also compare the aggregate behaviour
    kf = np.bincount((kvpn - base)[inarena], minlength=s.n_pages)
    sf = np.bincount(svpn - base, minlength=s.n_pages) if svpn.min() >= base else None
    if sf is not None:
        print(f"  correlation of per-page eviction counts, kernel vs simulator: {np.corrcoef(kf, sf[:len(kf)])[0, 1]:.3f}")


if __name__ == "__main__":
    main()
