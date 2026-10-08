#!/usr/bin/env python3
"""One pass over the cache_ext Twitter archive: for every cluster's *_bench.txt
keep the first ROWS requests as (key id, op) with ids numbered by first
appearance, and print the key-popularity shape.

    ~/.venvs/twx/bin/python -I tools/twitter_extract.py ARCHIVE.tar.zst OUTDIR [ROWS [cluster4,cluster18,...]]

Writes OUTDIR/clusterN.npz (ids uint32, op uint8: 0 get, 1 write) and
OUTDIR/SHAPE.tsv. Keys are mapped to ids so no key text is kept.
"""
import sys
import tarfile
from pathlib import Path

import numpy as np
import zstandard


def main():
    archive, out = sys.argv[1], Path(sys.argv[2])
    rows = int(sys.argv[3]) if len(sys.argv) > 3 else 3_000_000
    only = set(sys.argv[4].split(",")) if len(sys.argv) > 4 else None
    out.mkdir(parents=True, exist_ok=True)
    shape = ["cluster\trows\tunique\ttop1pct_share\ttop10pct_share\twrite_frac\tops"]
    t = tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(open(archive, "rb")), mode="r|")
    for m in t:
        if not m.name.endswith("_bench.txt"):
            continue
        name = Path(m.name).name.split("_")[0]
        if only and name not in only:
            continue
        f = t.extractfile(m)
        ids, ops, seen, opnames = [], [], {}, {}
        for _ in range(rows):
            line = f.readline()
            if not line:
                break
            op, _, key = line.decode("latin-1").rstrip("\n").partition(" ")
            opnames[op] = opnames.get(op, 0) + 1
            ids.append(seen.setdefault(key, len(seen)))
            ops.append(0 if op in ("get", "gets") else 1)
        ids = np.array(ids, dtype=np.uint32)
        ops = np.array(ops, dtype=np.uint8)
        cnt = np.sort(np.bincount(ids))[::-1]
        u = len(cnt)
        share = lambda p: cnt[:max(1, int(u * p))].sum() / cnt.sum()
        np.savez(out / f"{name}.npz", ids=ids, op=ops)
        shape.append(f"{name}\t{len(ids)}\t{u}\t{share(.01):.3f}\t{share(.1):.3f}\t{ops.mean():.3f}\t{opnames}")
        print(shape[-1], flush=True)
    (out / "SHAPE.tsv").write_text("\n".join(shape) + "\n")


if __name__ == "__main__":
    main()
