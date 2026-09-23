#!/usr/bin/env python3
"""Verify the trace archive: entry count, sizes, and compression ratio."""
import zipfile

Z = "/mnt/d/thesis/xv6-traces.zip"
z = zipfile.ZipFile(Z)
info = z.infolist()

tot = sum(i.file_size for i in info)
comp = sum(i.compress_size for i in info)
print("entries       : %d" % len(info))
print("uncompressed  : %.1f MB" % (tot / 1e6))
print("compressed    : %.1f MB" % (comp / 1e6))
print("ratio         : %.1f : 1" % (tot / comp if comp else 0))
print()
print("%14s %12s  %s" % ("UNCOMPRESSED", "COMPRESSED", "FILE"))
for i in sorted(info, key=lambda x: -x.file_size)[:12]:
    print("%14d %12d  %s" % (i.file_size, i.compress_size, i.filename))
print()
bad = z.testzip()
print("integrity     : %s" % ("OK" if bad is None else "CORRUPT: " + bad))
print()
print("folders:")
seen = {}
for i in info:
    top = i.filename.split("/")[0] if "/" in i.filename else "(root)"
    seen.setdefault(top, [0, 0])
    seen[top][0] += 1
    seen[top][1] += i.file_size
for k in sorted(seen):
    print("  %-14s %2d files  %10.1f MB" % (k, seen[k][0], seen[k][1] / 1e6))
