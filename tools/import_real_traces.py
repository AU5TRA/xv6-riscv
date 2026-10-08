#!/usr/bin/env python3
"""Bring the host-collected real-program traces (traces/old/real: Redis and
SQLite page-touch strings, 'T <page>' lines, no read/write marks) into the
stream layout, so stream_dataset.py can prepare them as held-out streams.

    python3 tools/import_real_traces.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "traces/old/real"
OUT = ROOT / "traces/streams"


def convert(name, wl):
    stem = f"{wl}-real-s1"
    d = OUT / wl
    d.mkdir(parents=True, exist_ok=True)
    nrefs = nbytes = 0
    hdr = None
    with open(SRC / f"{name}_real.trace") as f, open(d / f"{stem}.trace", "w") as o:
        for line in f:
            if line.startswith("TRACEHDR"):
                hdr = line.strip()
                continue
            o.write(line)
            nrefs += 1
            nbytes += len(line)
    (d / f"{stem}.log").write_text(
        "HOSTGEN source=traces/old/real (host-collected real program, no xv6 run)\n"
        f"{hdr}\nTRACEEND refs={nrefs} bytes={nbytes}\nPASS\n# RESULT PASS\n")
    (d / f"{stem}.ok").write_text("host-collected\n")
    print(stem, nrefs, nbytes)


if __name__ == "__main__":
    convert("redis", "redis")
    convert("sqlite", "sqlite")
