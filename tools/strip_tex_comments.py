#!/usr/bin/env python3
"""Write a copy of a .tex file without comments (for anonymous source uploads): drops whole-line comments and the comment part of other
lines; keeps escaped \\% and verbatim-free text as is.   python3 tools/strip_tex_comments.py in.tex out.tex"""
import re
import sys

out = []
for line in open(sys.argv[1], encoding="utf-8"):
    m = re.search(r"(?<!\\)%", line)
    if m is None:
        out.append(line)
        continue
    kept = line[:m.start()].rstrip()
    if kept:
        out.append(kept + "%\n")        # keep the % so a line end does not add a space
    elif not line.lstrip().startswith("%"):
        out.append("\n")
open(sys.argv[2], "w", encoding="utf-8").write("".join(out))
