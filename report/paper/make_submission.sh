#!/bin/bash
# Build the two PDFs MLSys 2027 wants (call for research papers: "If you wish to include an appendix, please upload this separately
# from your main paper"), from ONE build so every "Appendix X" / "Table N" reference in the body resolves (building the paper with
# \withappendixfalse leaves those references as "??").
#   bash make_submission.sh [main2]      -> submission/<name>_paper.pdf  and  submission/<name>_appendix.pdf
set -e
cd "$(dirname "$0")"
NAME=${1:-main2}
sed 's/\\withappendixfalse/\\withappendixtrue/' "$NAME.tex" > "_sub_$NAME.tex"
for i in 1; do pdflatex -interaction=nonstopmode "_sub_$NAME.tex" >/dev/null; done
bibtex "_sub_$NAME" >/dev/null
pdflatex -interaction=nonstopmode "_sub_$NAME.tex" >/dev/null
pdflatex -interaction=nonstopmode "_sub_$NAME.tex" > "_sub_$NAME.build.log"
for i in 1 2; do grep -q "Rerun to get" "_sub_$NAME.build.log" && pdflatex -interaction=nonstopmode "_sub_$NAME.tex" > "_sub_$NAME.build.log"; done
grep -q "Rerun to get" "_sub_$NAME.build.log" && { echo "CROSS-REFERENCES STILL CHANGING"; exit 1; }
if grep -q "undefined" "_sub_$NAME.build.log"; then echo "UNDEFINED REFERENCES:"; grep "undefined" "_sub_$NAME.build.log" | sort -u; exit 1; fi
TOTAL=$(mutool info "_sub_$NAME.pdf" | awk '/^Pages:/{print $2}')
page_of() { python3 -c "import re,sys; m=re.search(r'\\\\newlabel\{'+sys.argv[1]+r'\}\{\{[^}]*\}\{(\d+)\}', open(sys.argv[2]).read()); print(m.group(1))" "$1" "_sub_$NAME.aux"; }
APP=$(page_of app:data)           # first page of the appendix
CONC=$(page_of sec:conclusion)
END=$(page_of sec:end-of-main)    # the last line of the conclusion
mkdir -p submission
mutool merge -o "submission/${NAME}_paper.pdf" "_sub_$NAME.pdf" "1-$((APP - 1))"
mutool merge -o "submission/${NAME}_appendix.pdf" "_sub_$NAME.pdf" "$APP-$TOTAL"
[ "$END" -le 10 ] || { echo "MAIN TEXT TOO LONG: the conclusion ends on page $END"; exit 1; }
echo "conclusion on pages $CONC-$END (main text must end by page 10); paper PDF: pages 1-$((APP - 1)) (main text, references, AI Usage Disclosure); appendix PDF: pages $APP-$TOTAL"
rm -f "_sub_$NAME".{aux,bbl,blg,log,out,tex,pdf}
