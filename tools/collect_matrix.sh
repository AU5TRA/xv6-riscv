#!/bin/bash
# Stage 2: the capacity matrix.
#
# 6 workloads x 6 capacities. Each run emits a reference string (the "T <vpn>"
# stream Belady needs) and the kernel's own fault/eviction counters at that
# capacity, both in one transcript.
#
# Capacities are percentages of pages ACTUALLY TOUCHED, measured in stage 1/1b,
# not of the footprint argument -- workloads routinely request more arena than
# they use.
#
# STATUS.txt is rewritten after every run.

cd /mnt/d/thesis/xv6-riscv
. /home/ashfaq/xv6env.sh
unset VM_DEBUG
make -j"$(nproc)" CPUS=1 >/dev/null 2>&1
rm -f fs.img && make fs.img >/dev/null 2>&1

OUT=traces/sweep
RES="$OUT/RESULTS.tsv"
STATUS="$OUT/STATUS.txt"
mkdir -p "$OUT"
: > "$RES"

TOTAL=36
DONE=0
PACED=0
STARTED=$(date -Is)

write_status() {
  local current="$1"
  {
    echo "TRACE COLLECTION STATUS"
    echo "======================="
    echo "started  $STARTED"
    echo "updated  $(date -Is)"
    echo
    echo "PROGRESS:  $DONE of $TOTAL runs complete"
    if [ -n "$current" ]; then
      echo "RUNNING :  $current"
    else
      echo "RUNNING :  -"
    fi
    echo "PACED   :  $PACED run(s) needed pacing"
    echo
    printf "%-13s %6s %6s %9s %8s %8s %6s %s\n" \
      WORKLOAD PCT FRAMES REFS FAULTS EVICTS PACED RESULT
    printf "%-13s %6s %6s %9s %8s %8s %6s %s\n" \
      ------------- ------ ------ --------- -------- -------- ------ ------
    cat "$RES" 2>/dev/null
    echo
    echo "PAGE COUNTS (measured, stage 1/1b) -- percentages are of these:"
    echo "  btreebench 1773   kvbench 528   graphbench 1334"
    echo "  sortbench    81   matmul   18   lzwbench    50"
    echo
    echo "NOTE: matmulbench has only 18 pages, so a 6-point percentage sweep"
    echo "      cannot be resolved on it. It runs instead as its intended"
    echo "      locality contrast: 3 capacities x naive/blocked."
  } > "$STATUS"
}

# $1 label  $2 pct  $3 frames  $4 outfile-stem  $5... command
run_one() {
  local label="$1" pct="$2" frames="$3" stem="$4"; shift 4
  local s e rc L refs faults evicts result paced="no"
  write_status "$label ${pct}% (${frames} frames)"

  s=$(date +%s)
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 2400 "$*" \
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

  # Completeness. These runs stream the reference string to the console rather
  # than through the kernel ring, so there is no drop counter to consult; the
  # checks are that the workload reached its own PASS marker and actually
  # emitted references.
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

# --- btreebench: 1773 pages -------------------------------------------------
for spec in "5 89" "10 177" "15 266" "20 355" "25 443" "30 532"; do
  set -- $spec
  run_one btreebench "$1" "$2" "btree-p$1-c$2" \
    btreebench 5000 "$2" 45000 1 mixed 1
done

# --- kvbench: 528 pages -----------------------------------------------------
for spec in "5 26" "10 53" "15 79" "20 106" "25 132" "30 158"; do
  set -- $spec
  run_one kvbench "$1" "$2" "kv-p$1-c$2" \
    kvbench 2000 "$2" 20000 1 A 1
done

# --- graphbench: 1334 pages -------------------------------------------------
for spec in "5 67" "10 133" "15 200" "20 267" "25 334" "30 400"; do
  set -- $spec
  run_one graphbench "$1" "$2" "graph-p$1-c$2" \
    graphbench 2000 "$2" 2 1 both 1
done

# --- sortbench: 81 pages ----------------------------------------------------
for spec in "5 4" "10 8" "15 12" "20 16" "25 20" "30 24"; do
  set -- $spec
  run_one sortbench "$1" "$2" "sort-p$1-c$2" \
    sortbench 2000 "$2" 40000 1 1
done

# --- lzwbench: 50 pages -----------------------------------------------------
for spec in "5 3" "10 5" "15 8" "20 10" "25 13" "30 15"; do
  set -- $spec
  run_one lzwbench "$1" "$2" "lzw-p$1-c$2" \
    lzwbench "$2" 2 1
done

# --- matmulbench: 18 pages, locality contrast instead of a % sweep ----------
for spec in "22 4" "44 8" "67 12"; do
  set -- $spec
  run_one matmul-naive "$1" "$2" "matmulN-c$2" \
    matmulbench 2000 "$2" 96 naive 1
  run_one matmul-block "$1" "$2" "matmulB-c$2" \
    matmulbench 2000 "$2" 96 blocked 1
done

write_status ""
echo "matrix complete: $DONE runs"
