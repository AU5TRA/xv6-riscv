#!/bin/bash
# Stage 2, part 2: the remaining 24 runs.
#
# btreebench and kvbench (12 runs) completed cleanly in part 1 and are kept;
# this appends to the same RESULTS.tsv.
#
# Changes from part 1:
#   graphbench  2 PageRank iterations -> 1.  At 5% capacity (67 frames of
#               1334 pages) two iterations could not finish inside 2400s:
#               681,417 references emitted, no RESULT counters, truncated.
#               All six capacity points must run the SAME workload or the
#               curve compares different things, so all six are redone at 1
#               iteration rather than patching the one that failed.
#   timeout     2400s -> 3600s.  The tight-capacity points thrash hardest and
#               are always the slowest; the cap was mine, not the workload's.

cd /mnt/d/thesis/xv6-riscv
. /home/ashfaq/xv6env.sh
unset VM_DEBUG
make -j"$(nproc)" CPUS=1 >/dev/null 2>&1
rm -f fs.img && make fs.img >/dev/null 2>&1

OUT=traces/sweep
RES="$OUT/RESULTS.tsv"
STATUS="$OUT/STATUS.txt"

TOTAL=36
DONE=$(grep -c . "$RES" 2>/dev/null || echo 0)
PACED=0
STARTED=$(date -Is)

write_status() {
  local current="$1"
  {
    echo "TRACE COLLECTION STATUS"
    echo "======================="
    echo "part 2 started  $STARTED"
    echo "updated         $(date -Is)"
    echo
    echo "PROGRESS:  $DONE of $TOTAL runs complete"
    if [ -n "$current" ]; then echo "RUNNING :  $current"; else echo "RUNNING :  -"; fi
    echo "PACED   :  $PACED run(s) needed pacing"
    echo
    printf "%-13s %6s %6s %9s %8s %8s %6s %s\n" \
      WORKLOAD PCT FRAMES REFS FAULTS EVICTS PACED RESULT
    printf "%-13s %6s %6s %9s %8s %8s %6s %s\n" \
      ------------- ------ ------ --------- -------- -------- ------ ------
    cat "$RES" 2>/dev/null
    echo
    echo "PAGE COUNTS (measured) -- percentages are of these:"
    echo "  btreebench 1773   kvbench 528   graphbench 1334"
    echo "  sortbench    81   matmul   18   lzwbench    50"
    echo
    echo "DEVIATIONS:"
    echo "  graphbench  redone at 1 PageRank iteration; 2 could not finish"
    echo "              at 5% capacity inside 2400s (truncated, no counters)."
    echo "  matmulbench only 18 pages, so a 6-point percentage sweep cannot"
    echo "              be resolved. Runs as its intended locality contrast:"
    echo "              3 capacities x naive/blocked."
  } > "$STATUS"
}

run_one() {
  local label="$1" pct="$2" frames="$3" stem="$4"; shift 4
  local s e rc L refs faults evicts result paced="no"
  write_status "$label ${pct}% (${frames} frames)"
  s=$(date +%s)
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 3600 "$*" \
      > "$OUT/$stem.harness" 2>&1
  rc=$?; e=$(date +%s)
  L=$(grep -oE '/[^ ]+\.log' "$OUT/$stem.harness" | tail -1)
  if [ -n "$L" ] && [ -f "$L" ]; then
    cp "$L" "$OUT/$stem.log"
    refs=$(grep -cE "^[TRW] " "$OUT/$stem.log")
    faults=$(grep -oE "swap_faults=[0-9]+" "$OUT/$stem.log" | head -1 | cut -d= -f2)
    evicts=$(grep -oE "evictions=[0-9]+" "$OUT/$stem.log" | head -1 | cut -d= -f2)
  else
    refs=0; faults="-"; evicts="-"
  fi
  if [ "$rc" = "0" ] && [ "${refs:-0}" -gt 0 ]; then
    result="ok"
  elif [ "${refs:-0}" -gt 0 ]; then
    result="INCOMPLETE(rc=$rc)"
  else
    result="FAILED(rc=$rc)"
  fi
  printf "%-13s %5s%% %6s %9s %8s %8s %6s %s (%ds)\n" \
    "$label" "$pct" "$frames" "${refs:-0}" "${faults:--}" "${evicts:--}" \
    "$paced" "$result" "$((e-s))" >> "$RES"
  DONE=$((DONE+1))
  write_status ""
}

write_status ""

for spec in "5 67" "10 133" "15 200" "20 267" "25 334" "30 400"; do
  set -- $spec
  run_one graphbench "$1" "$2" "graph-p$1-c$2" graphbench 2000 "$2" 1 1 both 1
done

for spec in "5 4" "10 8" "15 12" "20 16" "25 20" "30 24"; do
  set -- $spec
  run_one sortbench "$1" "$2" "sort-p$1-c$2" sortbench 2000 "$2" 40000 1 1
done

for spec in "5 3" "10 5" "15 8" "20 10" "25 13" "30 15"; do
  set -- $spec
  run_one lzwbench "$1" "$2" "lzw-p$1-c$2" lzwbench "$2" 2 1
done

for spec in "22 4" "44 8" "67 12"; do
  set -- $spec
  run_one matmul-naive "$1" "$2" "matmulN-c$2" matmulbench 2000 "$2" 96 naive 1
  run_one matmul-block "$1" "$2" "matmulB-c$2" matmulbench 2000 "$2" 96 blocked 1
done

write_status ""
echo "matrix complete: $DONE of $TOTAL"
