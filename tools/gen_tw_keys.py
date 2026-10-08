#!/usr/bin/env python3
"""Turn the extracted Twitter key streams into user/twk<cluster>.bin for kvbench mode T.

    python3 tools/gen_tw_keys.py IDS_DIR user [MAX_OPS]

kvbench holds at most VMBENCH_ZIPF_N = 1024 logical keys, so each cluster is
spatially sampled: keep the requests whose key hash falls in 1/m of the key
space (m = ceil(unique/1000), so about 1000 keys survive), renumber the kept
keys densely in order of first appearance, and cut at MAX_OPS requests.
Sampling by key (not by request) keeps each key's whole request sequence, so
popularity skew and reuse distances among kept keys are those of the real
trace, scaled down. Each file is little-endian uint16 entries key*2 + is_write (write = insert / update).
"""
import sys
import zlib
from pathlib import Path

import numpy as np

KEYS_MAX = 1024


def build(ids, op, max_ops):
    u = int(ids.max()) + 1
    m = max(1, -(-u // 1000))
    h = np.array([zlib.crc32(int(k).to_bytes(4, "little")) % m for k in range(u)], dtype=np.uint32)
    keep = h[ids] == 0
    ids, op = ids[keep], op[keep]
    dense, out = {}, []
    for k in ids.tolist():
        if k not in dense:
            if len(dense) >= KEYS_MAX:
                break
            dense[k] = len(dense)
        out.append(dense[k])
        if len(out) >= max_ops:
            break
    n = len(out)
    return np.array(out, dtype=np.uint16), op[:n], m, u, len(dense)


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    max_ops = int(sys.argv[3]) if len(sys.argv) > 3 else 40000
    tab = []
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("cluster*.npz"), key=lambda p: int(p.stem[7:])):
        z = np.load(f)
        keys, op, m, u, nk = build(z["ids"], z["op"], max_ops)
        c = int(f.stem[7:])
        vals = keys.astype(np.uint32) * 2 + op.astype(np.uint32)
        (dst / f"twk{c}.bin").write_bytes(vals.astype("<u2").tobytes())
        tab.append((c, len(vals)))
        hot = np.sort(np.bincount(keys))[::-1]
        print(f"cluster{c}: {u} unique -> 1/{m} sample, {nk} keys, {len(vals)} ops, "
              f"top1% share {hot[:max(1, nk // 100)].sum() / len(keys):.3f}, writes {op[:len(keys)].mean():.3f}")
    print("wrote", len(tab), "files")


if __name__ == "__main__":
    main()
