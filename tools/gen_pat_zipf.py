#!/usr/bin/env python3
"""Named Zipf CDF tables for user/patbench.c, one per skew theta.

    python3 tools/gen_pat_zipf.py > user/pat_zipf.h

Same construction as tools/gen_zipf_table.py (which this does not replace and
user/zipf_table.h is left untouched, because kvbench's traces depend on it):
weight(rank k) = 1/(k+1)^theta, cumulative, scaled to the uint32 range, last
entry forced to 0xFFFFFFFF, forced monotonic. N = 1024 ranks, rank 0 hottest.
theta = 0.99 reproduces user/zipf_table.h exactly (checked by
tools/patbench_model.py). tools/patbench_model.py imports cdf() so the host
model and the C tables come from one function.
"""
import sys

N = 1024
THETAS = {"060": 0.60, "080": 0.80, "099": 0.99, "120": 1.20}


def cdf(theta, n=N):
    w = [1.0 / ((k + 1) ** theta) for k in range(n)]
    total = sum(w)
    run, out = 0.0, []
    for x in w:
        run += x
        out.append(round(run / total * 0xFFFFFFFF))
    out[-1] = 0xFFFFFFFF
    for i in range(1, n):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


def main():
    o = sys.stdout
    o.write("// GENERATED FILE -- do not hand-edit.\n")
    o.write("// Regenerate with: python3 tools/gen_pat_zipf.py > user/pat_zipf.h\n")
    o.write("#ifndef XV6_PAT_ZIPF_H\n#define XV6_PAT_ZIPF_H\n\n")
    o.write(f"#define PAT_ZIPF_N {N}\n\n")
    for name, th in THETAS.items():
        o.write(f"// theta = {th}\nstatic const uint32 pat_zipf_cdf_{name}[PAT_ZIPF_N] = {{\n")
        t = cdf(th)
        for i in range(0, N, 8):
            o.write("  " + ", ".join(f"{v}u" for v in t[i:i + 8]) + ",\n")
        o.write("};\n\n")
    o.write("#endif\n")


if __name__ == "__main__":
    main()
