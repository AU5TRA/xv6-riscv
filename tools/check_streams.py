#!/usr/bin/env python3
"""Check a collected stream set (tools/collect_streams.sh output) against
the manifest it came from.

  python3 tools/check_streams.py [streams_dir] [manifest]

For every manifest stem, reports whether it was collected, its reference
count, size, distinct pages and write share. Then checks the properties the
dataset depends on:
  * every "-rep" repeat is byte-identical to its original (determinism);
  * every trace stays under BUDGET, 90% of xv6's MAXFILE;
  * the seeds of a variant give different strings -- except matmulbench,
    whose seed argument does not exist.
Exits non-zero if any check fails or any stem is missing.
"""
import collections, hashlib, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "traces", "streams")
MANIFEST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "tools", "streams_manifest.tsv")
MAXFILE = (11 + 256 + 65536) * 1024
BUDGET = int(MAXFILE * 0.9)


def stats(path):
    h = hashlib.md5()
    pages, n, w = set(), 0, 0
    with open(path, "rb") as f:
        for line in f:
            h.update(line)
            n += 1
            w += line[:1] == b"W"
            pages.add(line[2:])
    return h.hexdigest(), n, len(pages), w


stems = []
for line in open(MANIFEST):
    if line.startswith("#") or not line.strip():
        continue
    stems.append(line.split("\t")[0])

problems, info = [], {}
print("%-26s %10s %11s %6s %6s  %s" % ("STREAM", "REFS", "BYTES", "PAGES", "W%", "STATUS"))
for stem in stems:
    folder = os.path.join(OUT, stem.split("-")[0])     # one folder per workload
    trace = os.path.join(folder, stem + ".trace")
    if not os.path.exists(os.path.join(folder, stem + ".ok")):
        print("%-26s %10s %11s %6s %6s  %s" % (stem, "-", "-", "-", "-", "MISSING"))
        problems.append(stem + ": not collected")
        continue
    digest, n, pages, w = stats(trace)
    size = os.path.getsize(trace)
    info[stem] = digest
    status = "ok"
    if size > BUDGET:
        status = "OVER BUDGET"
        problems.append("%s: %d bytes > %d" % (stem, size, BUDGET))
    print("%-26s %10s %11s %6d %5.1f%%  %s"
          % (stem, "{:,}".format(n), "{:,}".format(size), pages, 100.0 * w / n, status))

print()
for stem, digest in info.items():
    if stem.endswith("-rep"):
        orig = stem[:-4]
        if orig in info:
            same = info[orig] == digest
            print("determinism %-24s %s" % (orig, "identical" if same else "DIFFERENT"))
            if not same:
                problems.append(orig + ": repeat differs")

by_variant = collections.defaultdict(dict)
for stem, digest in info.items():
    m = re.match(r"^(.*)-s(\d+)$", stem)
    if m:
        by_variant[m.group(1)][int(m.group(2))] = digest
for variant, seeds in sorted(by_variant.items()):
    if len(seeds) > 1 and len(set(seeds.values())) != len(seeds):
        problems.append(variant + ": two seeds gave the same string")
        print("seeds       %-24s SOME IDENTICAL" % variant)

print()
print("PROBLEMS:" if problems else "all checks passed", *problems, sep="\n  ")
sys.exit(1 if problems else 0)
