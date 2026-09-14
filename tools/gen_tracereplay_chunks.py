#!/usr/bin/env python3
"""Generate user/tracereplay.c's embedded trace-slice data files.

Runs on the HOST only, like tools/gen_zipf_table.py. Takes a prefix of
traces/real/redis_real.trace's "T <vpn>" reference lines and splits it
into fixed files small enough to fit xv6's per-file cap: MAXFILE =
NDIRECT(12) + NINDIRECT(BSIZE/sizeof(uint)=256) = 268 blocks = 268KB
(kernel/fs.h) -- the actual binding constraint (see user/tracereplay.c's
own header comment for the full arithmetic and why the aggregate ~6.3MB
of free filesystem space, while also checked, is NOT the tight limit).

A fixed LINE count per chunk doesn't work: VPN values grow in digit
count as the trace progresses (more distinct pages get first-seen), so
a fixed-line chunk near the end of the prefix can be meaningfully bigger
than one at the start -- this was caught empirically (a 55000-line chunk
came out at 307374 bytes, over the 274432-byte cap) before it broke
anything. This script instead packs whole lines into each chunk up to a
BYTE budget, closing a chunk (never splitting a line) once the next line
would exceed it.

To regenerate (e.g. if PREFIX_REFS or BYTE_BUDGET ever change):
    python3 tools/gen_tracereplay_chunks.py

Writes user/redisreplay0 .. redisreplayN directly (flat, no
subdirectory -- mkfs/mkfs.c's shortname derivation only strips a single
leading "user/" prefix and asserts no further '/' in the name). Prints
the chunk count and total references packed; user/tracereplay.c's
NUM_CHUNKS/ARENA_PAGES/CHUNK_FILES must match what this prints -- update
them by hand if the parameters below ever change (kept as plain
constants in the .c file, the same tradeoff gen_zipf_table.py makes for
N/S vs. a runtime-configurable kvbench).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_TRACE = REPO_ROOT / "traces" / "real" / "redis_real.trace"
OUT_DIR = REPO_ROOT / "user"
OUT_PREFIX = "redisreplay"

PREFIX_REFS = 825000       # references taken from the start of the trace
BYTE_BUDGET = 260000        # per-chunk cap, safely under MAXFILE=274432


def main():
    with SOURCE_TRACE.open() as f:
        header = f.readline()  # TRACEHDR line, not embedded
        assert header.startswith("TRACEHDR"), \
            f"{SOURCE_TRACE}: expected a TRACEHDR first line"
        lines = []
        for _ in range(PREFIX_REFS):
            line = f.readline()
            if not line:
                break
            lines.append(line)

    if len(lines) < PREFIX_REFS:
        print(f"WARNING: source trace only had {len(lines)} references, "
              f"wanted {PREFIX_REFS}", file=sys.stderr)

    chunks = []
    cur = []
    cur_bytes = 0
    max_vpn = -1
    for line in lines:
        lb = len(line.encode())
        if cur_bytes + lb > BYTE_BUDGET and cur:
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

    for old in OUT_DIR.glob(f"{OUT_PREFIX}*"):
        old.unlink()

    for i, chunk in enumerate(chunks):
        path = OUT_DIR / f"{OUT_PREFIX}{i}"
        path.write_text("".join(chunk))
        size = path.stat().st_size
        assert size <= 274432, f"{path}: {size} bytes exceeds MAXFILE"

    print(f"wrote {len(chunks)} chunks, {len(lines)} references total, "
          f"max_vpn={max_vpn} (=> ARENA_PAGES should be {max_vpn + 1})")
    print("update user/tracereplay.c's NUM_CHUNKS/ARENA_PAGES/CHUNK_FILES "
          "by hand if these numbers changed from what's already there.")


if __name__ == "__main__":
    main()
