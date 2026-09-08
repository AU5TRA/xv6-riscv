#!/usr/bin/env python3
"""Generate a fixed-point Zipf CDF table for user/vmbench.c.

Runs on the HOST only (xv6 has no floating point -- see HANDOFF_PROMPT.md
SS7). Emits a committed C header, user/zipf_table.h, with a single
`const uint32 vmbench_zipf_cdf[N]` array: cumulative probability, scaled
to the full uint32 range, for rank 0 (hottest) through rank N-1 (coldest)
under a Zipfian distribution with skew parameter S.

To regenerate (e.g. if N or S ever change):
    python3 tools/gen_zipf_table.py > user/zipf_table.h

The sampler in user/vmbench.c draws a uniform uint32 from the xorshift64
PRNG and binary-searches this table for the smallest index i such that
cdf[i] >= draw. The last entry is forced to exactly 0xFFFFFFFF so every
possible 32-bit draw always finds a match.
"""

import sys

N = 1024          # number of distinct ranks (rank 0 = hottest)
S = 0.99           # Zipf skew exponent (classic web/cache-like skew)

def main():
    weights = [1.0 / ((k + 1) ** S) for k in range(N)]
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
    for i in range(1, N):
        if table[i] < table[i - 1]:
            table[i] = table[i - 1]

    out = sys.stdout
    out.write("// GENERATED FILE -- do not hand-edit.\n")
    out.write("// Regenerate with: python3 tools/gen_zipf_table.py > "
              "user/zipf_table.h\n")
    out.write(f"// Zipf skew S={S}, N={N} ranks, cumulative probability "
              "scaled to uint32 range.\n")
    out.write("#ifndef XV6_ZIPF_TABLE_H\n#define XV6_ZIPF_TABLE_H\n\n")
    out.write(f"#define VMBENCH_ZIPF_N {N}\n\n")
    out.write("static const uint32 vmbench_zipf_cdf[VMBENCH_ZIPF_N] = {\n")
    for i in range(0, N, 8):
        row = table[i:i + 8]
        out.write("  " + ", ".join(f"{v}u" for v in row) + ",\n")
    out.write("};\n\n#endif\n")

if __name__ == "__main__":
    main()
