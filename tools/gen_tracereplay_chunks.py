#!/usr/bin/env python3
"""Generate embedded trace-slice data files for user/tracereplay.c and
user/sqlitereplay.c.

Runs on the HOST only, like tools/gen_zipf_table.py. Takes a prefix of a
source trace's "T <vpn>" reference lines and splits it into fixed files
small enough to fit xv6's per-file cap: at the time this was written,
MAXFILE = NDIRECT(12) + NINDIRECT(BSIZE/sizeof(uint)=256) = 268 blocks =
268KB (kernel/fs.h) -- the actual binding constraint (see
user/tracereplay.c's own header comment for the full arithmetic and why
aggregate free filesystem space, while also checked, is NOT the tight
limit). A later merge (Austra-dev's doubly-indirect block support)
raised MAXFILE to 65,803 blocks (~64MB); DEFAULT_BYTE_BUDGET/the 274432
-byte assert below are now more conservative than strictly required,
but were left as-is since the already-generated chunk files remain
correct and there's no functional benefit to tightening them.

A fixed LINE count per chunk doesn't work: VPN values grow in digit
count as the trace progresses (more distinct pages get first-seen), so
a fixed-line chunk near the end of the prefix can be meaningfully bigger
than one at the start -- this was caught empirically on the Redis trace
(a 55000-line chunk came out at 307374 bytes, over the 274432-byte cap)
before it broke anything, and is not specific to Redis's access pattern
-- it's a property of trace length and page-count growth, so the SQLite
trace is packed by the same byte-budget logic, not line count.

Parameterized (source trace / output prefix / PREFIX_REFS) since this
logic is trace-agnostic -- was hardcoded to Redis only in an earlier
version of this script; re-running with no arguments reproduces the
existing Redis chunks unchanged (verify with a byte-identical diff after
any change to this script).

Usage:
    python3 tools/gen_tracereplay_chunks.py [--trace PATH] [--out-prefix NAME]
        [--prefix-refs N] [--byte-budget N]

Defaults reproduce the existing Redis chunks (user/redisreplay0..15,
PREFIX_REFS=825000). For SQLite:
    python3 tools/gen_tracereplay_chunks.py \\
        --trace traces/real/sqlite_real.trace --out-prefix sqlitereplay \\
        --prefix-refs 300000

Writes user/<out-prefix>0 .. <out-prefix>N directly (flat, no
subdirectory -- mkfs/mkfs.c's shortname derivation only strips a single
leading "user/" prefix and asserts no further '/' in the name). Prints
the chunk count and total references packed; the corresponding .c
program's NUM_CHUNKS/ARENA_PAGES/CHUNK_FILES must match what this prints
-- update them by hand if the parameters ever change (kept as plain
constants in the .c file, the same tradeoff gen_zipf_table.py makes for
N/S vs. a runtime-configurable kvbench).
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "user"

DEFAULT_TRACE = REPO_ROOT / "traces" / "real" / "redis_real.trace"
DEFAULT_OUT_PREFIX = "redisreplay"
DEFAULT_PREFIX_REFS = 825000
DEFAULT_BYTE_BUDGET = 260000  # per-chunk cap, safely under MAXFILE=274432


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    ap.add_argument("--out-prefix", default=DEFAULT_OUT_PREFIX)
    ap.add_argument("--prefix-refs", type=int, default=DEFAULT_PREFIX_REFS)
    ap.add_argument("--byte-budget", type=int, default=DEFAULT_BYTE_BUDGET)
    args = ap.parse_args()

    with args.trace.open() as f:
        header = f.readline()  # TRACEHDR line, not embedded
        assert header.startswith("TRACEHDR"), \
            f"{args.trace}: expected a TRACEHDR first line"
        lines = []
        for _ in range(args.prefix_refs):
            line = f.readline()
            if not line:
                break
            lines.append(line)

    with args.trace.open() as f:
        full_ref_count = sum(1 for _ in f) - 1  # minus the TRACEHDR line

    if len(lines) < args.prefix_refs:
        print(f"WARNING: source trace only had {len(lines)} references, "
              f"wanted {args.prefix_refs}", file=sys.stderr)

    chunks = []
    cur = []
    cur_bytes = 0
    max_vpn = -1
    for line in lines:
        lb = len(line.encode())
        if cur_bytes + lb > args.byte_budget and cur:
            chunks.append(cur)
            cur = []
            cur_bytes = 0
        cur.append(line)
        cur_bytes += lb
        vpn = int(line.split()[1])
        if vpn > max_vpn:
            max_vpn = vpn
    if cur:
        chunks.append(cur)

    for old in OUT_DIR.glob(f"{args.out_prefix}*"):
        old.unlink()

    for i, chunk in enumerate(chunks):
        path = OUT_DIR / f"{args.out_prefix}{i}"
        path.write_text("".join(chunk))
        size = path.stat().st_size
        assert size <= 274432, f"{path}: {size} bytes exceeds MAXFILE"

    pct = 100.0 * len(lines) / full_ref_count if full_ref_count else 0.0
    print(f"wrote {len(chunks)} chunks, {len(lines)} references total "
          f"({pct:.2f}% of the full {full_ref_count}-reference trace), "
          f"max_vpn={max_vpn} (=> ARENA_PAGES should be {max_vpn + 1})")
    print("update the corresponding .c program's "
          "NUM_CHUNKS/ARENA_PAGES/CHUNK_FILES by hand if these numbers "
          "changed from what's already there.")


if __name__ == "__main__":
    main()
