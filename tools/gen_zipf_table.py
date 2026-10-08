#!/usr/bin/env python3
"""Generate a fixed-point Zipf CDF table for user/vmbench.c.

Runs on the HOST only (xv6 has no floating point -- see HANDOFF_PROMPT.md
SS7). Emits a committed C header: cumulative probability, scaled to the
full uint32 range, for rank 0 (hottest) through rank N-1 (coldest) under a
Zipfian distribution with skew parameter S.

With no arguments it writes user/zipf_table.h, the table kvbench's traces
depend on (`vmbench_zipf_cdf`, S=0.99, N=1024). Do not regenerate that file
with different settings:

    python3 tools/gen_zipf_table.py > user/zipf_table.h

With --name it writes a separate, named table instead -- one header per
skew, sampled with vmbench_zipf_sample_cdf() (patbench's zipf modes):

    python3 tools/gen_zipf_table.py --n 1024 --theta 0.60 --name 060 \\
        > user/zipf_table_060.h

defines VMBENCH_ZIPF_N_060 and `vmbench_zipf_cdf_060[]`.

With --buckets B as well it writes a bucketed table, for rank counts too
large for one entry per rank (joinbench's Zipf over 65536 probe keys):
`vmbench_zipf_cdf_<name>[]` over at most B buckets of consecutive ranks and
`vmbench_zipf_start_<name>[]`, each bucket's first rank. Sampled with
vmbench_zipf_sample_bucketed(): a bucket by its exact probability, then a
rank uniformly inside it.

    python3 tools/gen_zipf_table.py --n 65536 --theta 0.99 --name 64k099 \\
        --buckets 1024 > user/zipf_table_64k099.h

The samplers in user/vmbench.c draw a uniform uint32 from the xorshift64
PRNG and binary-search the table for the smallest index i such that
cdf[i] >= draw. The last entry is forced to exactly 0xFFFFFFFF so every
possible 32-bit draw always finds a match.
"""

import argparse
import sys

N = 1024          # number of distinct ranks (rank 0 = hottest)
S = 0.99           # Zipf skew exponent (classic web/cache-like skew)


def cdf_table(n, s):
    weights = [1.0 / ((k + 1) ** s) for k in range(n)]
    total = sum(weights)
    cumulative = []
    running = 0.0
    for w in weights:
        running += w
        cumulative.append(running / total)

    UINT32_MAX = 0xFFFFFFFF
    table = [round(c * UINT32_MAX) for c in cumulative]
    table[-1] = UINT32_MAX  # guarantee every draw resolves
    # Monotonic non-decreasing (rounding could in principle violate this
    # for adjacent near-equal values at very small k -- enforce it).
    for i in range(1, n):
        if table[i] < table[i - 1]:
            table[i] = table[i - 1]
    return table


def write_rows(out, table):
    for i in range(0, len(table), 8):
        row = table[i:i + 8]
        out.write("  " + ", ".join(f"{v}u" for v in row) + ",\n")


def write_default(out):
    """user/zipf_table.h, exactly as it has always been generated."""
    table = cdf_table(N, S)
    out.write("// GENERATED FILE -- do not hand-edit.\n")
    out.write("// Regenerate with: python3 tools/gen_zipf_table.py > "
              "user/zipf_table.h\n")
    out.write(f"// Zipf skew S={S}, N={N} ranks, cumulative probability "
              "scaled to uint32 range.\n")
    out.write("#ifndef XV6_ZIPF_TABLE_H\n#define XV6_ZIPF_TABLE_H\n\n")
    out.write(f"#define VMBENCH_ZIPF_N {N}\n\n")
    out.write("static const uint32 vmbench_zipf_cdf[VMBENCH_ZIPF_N] = {\n")
    write_rows(out, table)
    out.write("};\n\n#endif\n")


def write_named(out, n, theta, name):
    table = cdf_table(n, theta)
    guard = f"XV6_ZIPF_TABLE_{name.upper()}_H"
    out.write("// GENERATED FILE -- do not hand-edit.\n")
    out.write(f"// Regenerate with: python3 tools/gen_zipf_table.py --n {n} "
              f"--theta {theta:.2f} --name {name} > user/zipf_table_{name}.h\n")
    out.write(f"// Zipf skew S={theta:.2f}, N={n} ranks, cumulative probability "
              "scaled to uint32 range.\n")
    out.write(f"// Sample with vmbench_zipf_sample_cdf(rng, vmbench_zipf_cdf_{name}, "
              f"VMBENCH_ZIPF_N_{name}).\n")
    out.write(f"#ifndef {guard}\n#define {guard}\n\n")
    out.write(f"#define VMBENCH_ZIPF_N_{name} {n}\n\n")
    out.write(f"static const uint32 vmbench_zipf_cdf_{name}"
              f"[VMBENCH_ZIPF_N_{name}] = {{\n")
    write_rows(out, table)
    out.write("};\n\n#endif\n")


def bucket_starts(n, buckets):
    """First rank of each bucket, plus n at the end: single ranks at the
    head, then ranges growing geometrically by a ratio r, the smallest r
    that fits n ranks into at most `buckets` buckets. A bucket [a, b) then
    spans ranks whose probabilities differ by at most (b/a)^theta, about
    1 + r -- under 1% for 65536 ranks in 1024 buckets."""
    def starts_for(r):
        out, s = [], 0
        while s < n:
            out.append(s)
            s += max(1, int(s * r))
        return out + [n]
    lo, hi = 0.0, 1.0
    while len(starts_for(hi)) - 1 > buckets:
        hi *= 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if len(starts_for(mid)) - 1 > buckets:
            lo = mid
        else:
            hi = mid
    return starts_for(hi)


def write_bucketed(out, n, theta, name, buckets):
    starts = bucket_starts(n, buckets)
    nb = len(starts) - 1
    weights = [1.0 / ((k + 1) ** theta) for k in range(n)]
    total = sum(weights)
    UINT32_MAX = 0xFFFFFFFF
    table, running = [], 0.0
    for b in range(nb):
        running += sum(weights[starts[b]:starts[b + 1]])
        table.append(round(running / total * UINT32_MAX))
    table[-1] = UINT32_MAX
    for i in range(1, nb):
        if table[i] < table[i - 1]:
            table[i] = table[i - 1]
    # rank k has weight 1/(k+1)^theta, so bucket [a, b) spans a factor of
    # (b / (a+1))^theta between its first and last rank
    widest = max((starts[b + 1] / (starts[b] + 1)) ** theta
                 for b in range(nb) if starts[b + 1] - starts[b] > 1)
    guard = f"XV6_ZIPF_TABLE_{name.upper()}_H"
    out.write("// GENERATED FILE -- do not hand-edit.\n")
    out.write(f"// Regenerate with: python3 tools/gen_zipf_table.py --n {n} "
              f"--theta {theta:.2f} --name {name} --buckets {buckets} "
              f"> user/zipf_table_{name}.h\n")
    out.write(f"// Zipf skew S={theta:.2f} over N={n} ranks, in {nb} buckets: "
              "bucket b holds ranks\n")
    out.write(f"// start[b] .. start[b+1]-1 and cdf[b] is the cumulative "
              "probability through it,\n")
    out.write("// scaled to uint32 range. Single ranks at the head, then "
              "geometrically wider\n")
    out.write("// buckets; within one the ranks' probabilities differ by at "
              f"most a factor {widest:.4f}.\n")
    out.write(f"// Sample with vmbench_zipf_sample_bucketed(rng, "
              f"vmbench_zipf_cdf_{name}, vmbench_zipf_start_{name}, "
              f"VMBENCH_ZIPF_B_{name}).\n")
    out.write(f"#ifndef {guard}\n#define {guard}\n\n")
    out.write(f"#define VMBENCH_ZIPF_N_{name} {n}\n")
    out.write(f"#define VMBENCH_ZIPF_B_{name} {nb}\n\n")
    out.write(f"static const uint32 vmbench_zipf_cdf_{name}"
              f"[VMBENCH_ZIPF_B_{name}] = {{\n")
    write_rows(out, table)
    out.write("};\n\n")
    out.write(f"static const uint32 vmbench_zipf_start_{name}"
              f"[VMBENCH_ZIPF_B_{name} + 1] = {{\n")
    write_rows(out, starts)
    out.write("};\n\n#endif\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, help="number of ranks")
    ap.add_argument("--theta", type=float, help="Zipf skew exponent")
    ap.add_argument("--name", help="table suffix: letters and digits only")
    ap.add_argument("--buckets", type=int,
                    help="emit a bucketed table of at most this many buckets "
                         "(for N too large for one entry per rank)")
    args = ap.parse_args()
    if args.name is None:
        if args.n is not None or args.theta is not None:
            ap.error("--n and --theta need --name; the unnamed table is fixed")
        write_default(sys.stdout)
        return
    if args.n is None or args.theta is None:
        ap.error("--name needs --n and --theta")
    if not args.name.isalnum() or args.name == "":
        ap.error("--name must be letters and digits only")
    if args.n < 1:
        ap.error("--n must be at least 1")
    if args.buckets is not None:
        if args.buckets < 2:
            ap.error("--buckets must be at least 2")
        write_bucketed(sys.stdout, args.n, args.theta, args.name, args.buckets)
        return
    write_named(sys.stdout, args.n, args.theta, args.name)


if __name__ == "__main__":
    main()
