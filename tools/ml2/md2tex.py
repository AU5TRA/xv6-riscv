#!/usr/bin/env python3
"""report/ML_REPORT.md -> report/ML_REPORT.tex (and .pdf with --pdf).

The Markdown stays the source of truth (fill_report.py writes its tables);
this converts the subset it uses -- headings, paragraphs, nested lists,
pipe tables, figures, indented code, **bold**, *italic*, `code` -- to LaTeX,
so the LaTeX version never carries a number the Markdown does not.

    python3 md2tex.py [--pdf]      (needs pdflatex)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "report" / "ML_REPORT.md"
OUT = ROOT / "report" / "ML_REPORT.tex"

PREAMBLE = r"""\documentclass[10pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{textcomp}
\usepackage[margin=2.2cm]{geometry}
\usepackage{microtype}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{tabularx}
\usepackage{adjustbox}
\usepackage{fancyvrb}
\usepackage{enumitem}
\usepackage{xcolor}
\usepackage{newunicodechar}
\usepackage[hidelinks]{hyperref}
\setlist{itemsep=2pt,topsep=3pt}
\setlength{\parskip}{4pt}
\setlength{\parindent}{0pt}
\setlength{\emergencystretch}{3em}
\renewcommand{\arraystretch}{1.1}
\newunicodechar{∪}{\ensuremath{\cup}}
\newunicodechar{→}{\ensuremath{\to}}
\newunicodechar{≥}{\ensuremath{\geq}}
\newunicodechar{≤}{\ensuremath{\leq}}
\newunicodechar{−}{\ensuremath{-}}
\newunicodechar{≈}{\ensuremath{\approx}}
\newunicodechar{±}{\ensuremath{\pm}}
\newunicodechar{×}{\ensuremath{\times}}
\newunicodechar{·}{\ensuremath{\cdot}}
\newunicodechar{Σ}{\ensuremath{\Sigma}}
\newunicodechar{⁻}{\ensuremath{^{-}}}
\newunicodechar{⁰}{\ensuremath{^{0}}}
\newunicodechar{²}{\ensuremath{^{2}}}
\newunicodechar{⁵}{\ensuremath{^{5}}}
\newunicodechar{⁶}{\ensuremath{^{6}}}
\newcommand{\code}[1]{\texttt{#1}}
\newcommand{\tablecaption}[1]{\par\smallskip\noindent{\small #1}\par\nopagebreak}
\newcommand{\tablenote}[1]{\par\noindent{\footnotesize #1}\par\medskip}
"""

ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
       "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}"}


def esc(t):
    return "".join(ESC.get(c, c) for c in t)


def code(t):
    # allow line breaks after path and identifier separators
    out = esc(t)
    for sep in ("/", r"\_", ".", ","):
        out = out.replace(sep, sep + r"\allowbreak{}")
    return r"\code{" + out + "}"


def inline(t):
    # code spans become placeholders so emphasis can span them
    spans = []

    def keep(m):
        spans.append(code(m.group(1)))
        return f"\x00{len(spans) - 1}\x00"

    p = esc(re.sub(r"`([^`]+)`", keep, t))
    p = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", p)
    p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", p)
    p = re.sub(r'"(\S[^"]*?)"', r"``\1''", p)
    return re.sub("\x00(\\d+)\x00", lambda m: spans[int(m.group(1))], p)


ITEM = re.compile(r"^( *)([*-]|\d+\.) +(.*)$")


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def is_numeric(cell):
    return bool(re.fullmatch(r"[\s≥≤~+\-−0-9.,%×()|→/—]*", cell)) and any(c.isdigit() for c in cell) \
        or cell.strip() in ("—", "")


def table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], [c for c in cells[2:]]
    n = len(head)
    align = "l" + "".join("r" if all(is_numeric(r[i]) for r in body if i < len(r)) else "l"
                          for i in range(1, n))
    lines = [" & ".join(r"\textbf{" + inline(h) + "}" for h in head) + r" \\ \midrule"]
    for r in body:
        r = (r + [""] * n)[:n]
        lines.append(" & ".join(inline(c) for c in r) + r" \\")
    width = [max(len(r[i]) if i < len(r) else 0 for r in cells) for i in range(n)]
    if sum(width) > 110:
        # prose cells: wrap them instead of shrinking the whole table
        align = "".join("X" if w > 24 else ("r" if align[i] == "r" else "l")
                        for i, w in enumerate(width))
        return ("\\begin{center}\\footnotesize\n\\begin{tabularx}{\\linewidth}{" + align +
                "}\n\\toprule\n" + "\n".join(lines) +
                "\n\\bottomrule\n\\end{tabularx}\n\\end{center}\n")
    if len(body) > 28:
        return ("{\\footnotesize\\setlength{\\tabcolsep}{4pt}\n\\begin{longtable}{" + align +
                "}\n\\toprule\n" + lines[0] + "\n\\endhead\n" + "\n".join(lines[1:]) +
                "\n\\bottomrule\n\\end{longtable}}\n")
    return ("\\begin{center}\\footnotesize\n\\begin{adjustbox}{max width=\\linewidth}\n"
            "\\begin{tabular}{" + align + "}\n\\toprule\n" + "\n".join(lines) +
            "\n\\bottomrule\n\\end{tabular}\n\\end{adjustbox}\n\\end{center}\n")


def heading(level, text):
    if level == 1:
        return None
    cmd = {2: "section", 3: "subsection"}.get(level, "subsubsection")
    t = inline(text)
    return f"\\{cmd}*{{{t}}}\n\\addcontentsline{{toc}}{{{cmd}}}{{{t}}}\n"


def blocks(lines, top=False):
    out = []
    i, n = 0, len(lines)
    prev_blank = True
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            prev_blank = True
            i += 1
            continue
        m = re.match(r"^(#+) +(.*)$", line)
        if m:
            h = heading(len(m.group(1)), m.group(2))
            if h:
                out.append(h)
            i += 1
        elif s == "---":
            i += 1
        elif s.startswith("|"):
            j = i
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            out.append(table(lines[i:j]))
            i = j
        elif re.match(r"^!\[[^\]]*\]\(([^)]+)\)$", s):
            src = re.match(r"^!\[[^\]]*\]\(([^)]+)\)$", s).group(1)
            pdf = Path(src).with_suffix(".pdf")
            src = str(pdf) if (ROOT / "report" / pdf).exists() else src
            out.append("\\begin{center}\n\\includegraphics[width=\\linewidth,height=.42\\textheight,"
                       "keepaspectratio]{" + src + "}\n\\end{center}\n")
            i += 1
        elif top and prev_blank and indent_of(line) >= 4 and not ITEM.match(line):
            j = i
            while j < n and (indent_of(lines[j]) >= 4 or not lines[j].strip()):
                j += 1
            while j > i and not lines[j - 1].strip():
                j -= 1
            body = "\n".join(l[4:] for l in lines[i:j])
            out.append("\\begin{Verbatim}[fontsize=\\scriptsize,xleftmargin=1em]\n" + body +
                       "\n\\end{Verbatim}\n")
            i = j
        elif ITEM.match(line):
            base = indent_of(line)
            numbered = ITEM.match(line).group(2)[0].isdigit()
            items = []
            while i < n:
                m = ITEM.match(lines[i])
                if not m or indent_of(lines[i]) != base:
                    break
                width = len(m.group(1)) + len(m.group(2)) + 1
                content = [m.group(3)]
                i += 1
                while i < n:
                    l = lines[i]
                    if not l.strip():
                        # a blank line continues the item only if indented text follows
                        k = i
                        while k < n and not lines[k].strip():
                            k += 1
                        if k < n and indent_of(lines[k]) > base:
                            content += [""] * (k - i)
                            i = k
                            continue
                        break
                    if indent_of(l) <= base:
                        break
                    content.append(l[width:] if indent_of(l) >= width else l.lstrip())
                    i += 1
                items.append(content)
            env = "enumerate" if numbered else "itemize"
            body = "".join("\\item " + blocks(c).strip() + "\n" for c in items)
            out.append(f"\\begin{{{env}}}\n{body}\\end{{{env}}}\n")
        else:
            j = i
            para = []
            while j < n and lines[j].strip() and not ITEM.match(lines[j]) \
                    and not lines[j].strip().startswith(("|", "#", "![")):
                para.append(lines[j].strip())
                j += 1
            text = re.sub(r"(?<=[A-Za-z])- (?=[a-z])", "-", " ".join(para))
            i = j
            if re.fullmatch(r"\*\*[^*].*\*\*", text) and i < n and \
                    any(lines[k].strip().startswith("|") for k in range(i, min(i + 2, n))):
                out.append(r"\tablecaption{" + inline(text) + "}\n")
            elif re.fullmatch(r"\*[^*].*\*", text) and out and ("tabular" in out[-1] or "longtable" in out[-1]):
                out.append(r"\tablenote{" + inline(text) + "}\n")
            else:
                out.append(inline(text) + "\n")
        prev_blank = False
        if i < n and not lines[i].strip():
            prev_blank = True
    return "\n".join(out)


def main():
    md = re.sub(r"<!--.*?-->\n?", "", SRC.read_text(), flags=re.S)
    lines = md.split("\n")
    title = re.match(r"^# +(.*)$", lines[0]).group(1)
    body = blocks(lines[1:], top=True)
    tex = (PREAMBLE + "\\title{" + inline(title) + "}\n\\date{}\n\\begin{document}\n"
           "\\maketitle\n\\vspace{-2em}\n" + body.replace("\\section*{1.", "\\clearpage\\tableofcontents\\clearpage\n\\section*{1.", 1)
           + "\n\\end{document}\n")
    OUT.write_text(tex)
    print("written", OUT)
    if "--pdf" in sys.argv:
        for _ in range(2):
            r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                                OUT.name], cwd=OUT.parent, capture_output=True, text=True)
            if r.returncode:
                print(r.stdout[-3000:])
                sys.exit(1)
        print("written", OUT.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
