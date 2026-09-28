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
        SWEEP=traces/sweep-rw python3 tools/make_archive.py [outdir]

SWEEP picks the campaign to package (default traces/sweep).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWEEP = ROOT / os.environ.get("SWEEP", "traces/sweep")
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
        stems = sorted(s.stem for s in SWEEP.glob("*.trace")
                       if any(s.name.startswith(p) for p in prefixes))
        if not stems:
            continue            # a workload this campaign did not collect
        d = STAGE / folder
        d.mkdir()

        # one reference string per distinct checksum
        by_sum = {}
        for stem in stems:
            t = SWEEP / (stem + ".trace")
            by_sum.setdefault(md5(t), []).append(stem)
        # A workload's capacities must share one reference string; the
        # single canonical name below depends on it. Two different strings
        # mean a truncated or non-deterministic run, and writing both to the
        # same name would silently keep only one of them.
        if canon and len(by_sum) > 1:
            groups = "; ".join(", ".join(m) for m in by_sum.values())
            shutil.rmtree(STAGE)
            sys.exit("make_archive: %s runs do not share one reference "
                     "string (%s) -- refusing to archive" % (folder, groups))

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
    n_runs = len(manifest)
    n_workloads = len({folder for folder, *_ in manifest})
    n_strings = len({(folder, trace) for folder, *_rest, trace in manifest})
    A("=" * 78)
    A("xv6 PAGING TRACES -- WHAT IS IN THIS ARCHIVE")
    A("=" * 78)
    A("")
    A("%d runs: %d workloads, each executed at several memory capacities."
      % (n_runs, n_workloads))
    A("")
    A("")
    A("LAYOUT")
    A("-" * 78)
    A("One folder per workload. Inside each:")
    A("")
    A("  *.trace    the reference string -- every access the workload made to")
    A("             its own data, in order, one access per line. The")
    A("             program's code and stack are not traced.")
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
    A("verified by checksum when this archive was built -- the %d trace files"
      % n_runs)
    A("produced by the %d runs contain exactly %d distinct reference strings,"
      % (n_runs, n_strings))
    A("one per workload, with matmulbench's naive and blocked variants")
    A("counted separately because they are genuinely different programs.")
    A("")
    A("So each folder holds ONE reference string and one log per capacity.")
    A("The logs are where the capacities differ. Shipping an identical copy")
    A("of the trace per capacity would multiply the archive's size and carry")
    A("no extra information.")
    A("")
    A("")
    A("TRACE FILE FORMAT")
    A("-" * 78)
    A("Plain text, one line per memory access:")
    A("")
    A("    R 114")
    A("    W 114")
    A("    R 689")
    A("    R 114")
    A("")
    A("The letter is the access type: 'W' if the access modified the page at")
    A("all, 'R' if it only read it. It decides which evictions cost a")
    A("write-back to swap, and the kernel's page_writes count in each log is")
    A("the matching ground truth. The number is the virtual page number")
    A("touched. Pages are 4096 bytes. Order is exactly the order of")
    A("execution. The values read or written and the time of each access are")
    A("deliberately discarded -- page replacement depends on neither.")
    A("")
    A("Traces collected before the access type was recorded use 'T' on every")
    A("line instead of 'R' or 'W'. They have the same page sequence, just no")
    A("read/write distinction.")
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
    A("for sortbench, lzwbench and matmulbench it is not.")
    A("")
    A("Quote the FRAMES column, never the filename -- and when simulating a")
    A("trace, use the ARENA column of SUMMARY.txt instead (see below).")
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
    A("           once, read back from the kernel. This is the whole")
    A("           process: the traced data AND its own code and stack, which")
    A("           the trace does not contain. The frames the traced pages")
    A("           actually had are the ARENA column of SUMMARY.txt, a few")
    A("           fewer; simulate a trace at ARENA, not FRAMES.")
    A("FAULTS     times the program touched a page that was swapped out, so")
    A("           the kernel had to fetch it from swap.")
    A("EVICTIONS  times a resident page had to be thrown out to make room.")
    A("")
    A("In every log, EVICTIONS = FAULTS + zero_faults (first touches of")
    A("never-used pages) - the frames that were still free when measuring")
    A("began.")
    A("")
    A("")
    A("HOW THE TRACES WERE COLLECTED")
    A("-" * 78)
    A("Every access a benchmark makes to its data goes through an accessor")
    A("that appends 'R <page>' or 'W <page>' to a 4 KB buffer. The buffer is")
    A("written to a file")
    A("inside the xv6 filesystem whenever it fills -- roughly one write per")
    A("several hundred references. After the emulator exits, the file is")
    A("extracted from the disk image on the host, so the reference stream")
    A("never passes through the console.")
    A("")
    A("The kernel's prefetcher is disabled during tracing, so these are")
    A("traces of pure demand paging with nothing speculative.")
    A("")
    A("The fault and eviction counts come from the kernel separately, printed")
    A("as RESULT lines at the end of each run, and are joined to the trace")
    A("afterwards on the host.")
    A("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
