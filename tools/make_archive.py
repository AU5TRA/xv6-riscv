#!/usr/bin/env python3
"""Package the collected traces into a zip, organised by workload.

Within a workload the reference string is byte-identical at every capacity --
the program performs the same work regardless of how much memory it is given,
so only the kernel's response differs. Verified by checksum: the 36 .trace
files contain just 7 distinct reference strings. Shipping six copies of
lzwbench's 67MB trace would quintuple the archive for no information, so each
workload folder carries one reference string plus the six per-capacity logs
that actually differ.

Usage:  python3 tools/make_archive.py [outdir]
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWEEP = ROOT / "traces" / "sweep"
OUTZIP = Path(sys.argv[1] if len(sys.argv) > 1 else r"/mnt/d/thesis") / "xv6-traces.zip"
STAGE = ROOT / "traces" / ".archive-stage"

# folder name -> (stem prefixes, canonical trace name, description)
GROUPS = [
    ("kvbench", ["kv-"], "kvbench.trace",
     "Key-value cache, Zipf-skewed key popularity"),
    ("btreebench", ["btree-"], "btreebench.trace",
     "B-tree database index, root-to-leaf lookups"),
    ("sortbench", ["sort-"], "sortbench.trace",
     "External merge sort, streaming sequential access"),
    ("graphbench", ["graph-"], "graphbench.trace",
     "Graph analytics: breadth-first search plus PageRank"),
    ("lzwbench", ["lzw-"], "lzwbench.trace",
     "LZW compression over a real text corpus"),
    ("matmulbench", ["matmulN", "matmulB"], None,
     "Matrix multiply, naive row-major vs cache-tiled"),
]

FIELD = {k: re.compile(r"%s=(\d+)" % k)
         for k in ("swap_faults", "evictions", "resident_limit",
                   "page_reads", "page_writes")}


def scalar(path: Path, key: str):
    try:
        m = FIELD[key].search(path.read_text(errors="replace"))
    except OSError:
        return None
    return int(m.group(1)) if m else None


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    manifest = []      # (folder, run, limit, faults, evicts, trace)

    for folder, prefixes, canon, _desc in GROUPS:
        d = STAGE / folder
        d.mkdir()
        stems = sorted(s.stem for s in SWEEP.glob("*.trace")
                       if any(s.name.startswith(p) for p in prefixes))

        # one reference string per distinct checksum
        by_sum = {}
        for stem in stems:
            t = SWEEP / (stem + ".trace")
            by_sum.setdefault(md5(t), []).append(stem)

        sum_to_name = {}
        for digest, members in by_sum.items():
            if canon:
                name = canon
            else:
                variant = "naive" if members[0].startswith("matmulN") else "blocked"
                name = "matmulbench-%s.trace" % variant
            sum_to_name[digest] = name
            shutil.copy2(SWEEP / (members[0] + ".trace"), d / name)

        for stem in stems:
            shutil.copy2(SWEEP / (stem + ".log"), d / (stem + ".log"))
            log = SWEEP / (stem + ".log")
            manifest.append((
                folder, stem,
                scalar(log, "resident_limit"),
                scalar(log, "swap_faults"),
                scalar(log, "evictions"),
                sum_to_name[md5(SWEEP / (stem + ".trace"))],
            ))

    for extra in ("SUMMARY.txt", "RESULTS.tsv"):
        src = SWEEP / extra
        if src.exists():
            shutil.copy2(src, STAGE / extra)

    (STAGE / "README.txt").write_text(readme(manifest))

    OUTZIP.parent.mkdir(parents=True, exist_ok=True)
    if OUTZIP.exists():
        OUTZIP.unlink()
    with zipfile.ZipFile(OUTZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(STAGE.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(STAGE).as_posix())

    shutil.rmtree(STAGE)
    print("wrote %s (%.1f MB)" % (OUTZIP, OUTZIP.stat().st_size / 1e6))


def readme(manifest) -> str:
    L = []
    A = L.append
    A("=" * 78)
    A("xv6 PAGING TRACES -- WHAT IS IN THIS ARCHIVE")
    A("=" * 78)
    A("")
    A("36 runs: six workloads, each executed at six memory capacities.")
    A("")
    A("")
    A("LAYOUT")
    A("-" * 78)
    A("One folder per workload. Inside each:")
    A("")
    A("  *.trace    the reference string -- every page the program touched,")
    A("             in the order it touched them, one access per line.")
    A("  *.log      the full transcript of one run at one capacity, ending")
    A("             in RESULT lines with that run's fault and eviction counts.")
    A("")
    A("At the top level:")
    A("  SUMMARY.txt   per-workload tables of capacity, faults and evictions")
    A("  RESULTS.tsv   the same data as one raw tab-separated table")
    A("")
    A("")
    A("WHY ONE .trace BUT SIX .log PER WORKLOAD")
    A("-" * 78)
    A("The reference string does not depend on how much memory the program")
    A("was given. A sort sorts the same values in the same order whether it")
    A("has 8 frames or 28; only the kernel's response changes. This was")
    A("verified by checksum -- the 36 trace files produced by the 36 runs")
    A("contain exactly 7 distinct reference strings, one per workload, plus a")
    A("second for matmulbench because its naive and blocked variants are")
    A("genuinely different programs.")
    A("")
    A("So each folder holds ONE reference string and SIX logs. The logs are")
    A("where the six capacities differ. Shipping six identical copies of")
    A("lzwbench's 67 MB trace would have made this archive five times larger")
    A("and carried no extra information.")
    A("")
    A("")
    A("TRACE FILE FORMAT")
    A("-" * 78)
    A("Plain text, one line per memory access:")
    A("")
    A("    T 114")
    A("    T 114")
    A("    T 689")
    A("    T 114")
    A("")
    A("'T' marks a reference; the number is the virtual page number touched.")
    A("Pages are 4096 bytes. Order is exactly the order of execution. The")
    A("values read or written, whether it was a read or a write, and the time")
    A("it happened are all deliberately discarded -- page replacement depends")
    A("on none of them.")
    A("")
    A("Page numbers are absolute virtual page numbers, so the lowest number in")
    A("a file is wherever that program's arena happened to start. Only the")
    A("differences and repetitions matter; adding a constant to every line")
    A("would change nothing about any replacement decision.")
    A("")
    A("")
    A("LOG FILE NAMES")
    A("-" * 78)
    A("    <workload>-p<NN>-c<MM>.log")
    A("                 ^^^^   ^^^^")
    A("                 |      the capacity ARGUMENT passed on the command line")
    A("                 the capacity percentage that was INTENDED")
    A("")
    A("matmulbench instead uses matmulN (naive) and matmulB (blocked).")
    A("")
    A("*** Both numbers in the filename are labels from the original plan.")
    A("*** Neither is the capacity the run actually executed under.")
    A("")
    A("The command-line argument is a MARGIN added to the program's settled")
    A("baseline, not an absolute frame count, so the real limit is higher than")
    A("MM. The real value is recorded inside each log as resident_limit=, and")
    A("is listed in the table below and in SUMMARY.txt. For btreebench,")
    A("kvbench and graphbench the intended percentage is close to the truth;")
    A("for sortbench, lzwbench and matmulbench it is not. lzwbench in")
    A("particular ran at 47-71% of its working set, not the 5-30% its")
    A("filenames claim.")
    A("")
    A("Quote the FRAMES column, never the filename.")
    A("")
    A("")
    A("EVERY RUN")
    A("-" * 78)
    A("%-13s %-22s %7s %11s %11s  %s"
      % ("WORKLOAD", "LOG FILE", "FRAMES", "FAULTS", "EVICTIONS",
         "REFERENCE STRING"))
    A("-" * 78)
    last = None
    for folder, stem, limit, faults, evicts, trace in manifest:
        if last is not None and folder != last:
            A("")
        last = folder
        A("%-13s %-22s %7s %11s %11s  %s"
          % (folder, stem + ".log", limit,
             "{:,}".format(faults or 0), "{:,}".format(evicts or 0), trace))
    A("")
    A("")
    A("WHAT THE COLUMNS MEAN")
    A("-" * 78)
    A("FRAMES     physical pages the kernel allowed the program to hold at")
    A("           once. This is the real capacity, read back from the kernel.")
    A("FAULTS     times the program touched a page that was not resident, so")
    A("           the kernel had to fetch it from swap.")
    A("EVICTIONS  times a resident page had to be thrown out to make room.")
    A("")
    A("Faults and evictions differ by a small constant: the first pages")
    A("loaded into an empty frame set cost a fault but evict nothing.")
    A("")
    A("")
    A("HOW THE TRACES WERE COLLECTED")
    A("-" * 78)
    A("Each benchmark funnels its memory accesses through one accessor that")
    A("appends 'T <page>' into a 4 KB buffer. The buffer is written to a file")
    A("inside the xv6 filesystem whenever it fills -- roughly one write per")
    A("several hundred references. After the emulator exits, the file is")
    A("extracted from the disk image on the host, so the reference stream")
    A("never passes through the console.")
    A("")
    A("Hardware prefetching is disabled during tracing, so these are traces of")
    A("pure demand paging with nothing speculative.")
    A("")
    A("The fault and eviction counts come from the kernel separately, printed")
    A("as RESULT lines at the end of each run, and are joined to the trace")
    A("afterwards on the host.")
    A("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
