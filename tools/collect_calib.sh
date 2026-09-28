#!/bin/bash
# Stage 1: size each workload. Short runs, measuring references emitted and
# distinct pages touched, so Stage 2 can pick an op count that lands near a
# target reference budget and compute capacity margins against pages ACTUALLY
# touched rather than pages requested.
cd /mnt/d/thesis/xv6-riscv
. /home/ashfaq/xv6env.sh
unset VM_DEBUG
make -j"$(nproc)" CPUS=1 >/dev/null 2>&1
rm -f fs.img && make fs.img >/dev/null 2>&1

OUT=traces/sweep
mkdir -p "$OUT"
CAL="$OUT/CALIBRATION.txt"
: > "$CAL"

cal() {   # $1=name  $2=third-arg value used  $3...=command
  local name="$1" arg="$2"; shift 2
  local s e rc L refs pages
  s=$(date +%s)
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 600 "$*" >/tmp/c.txt 2>&1
  rc=$?; e=$(date +%s)
  L=$(grep -oE '/[^ ]+\.log' /tmp/c.txt | tail -1)
  if [ -z "$L" ] || [ ! -f "$L" ]; then
    printf "%-12s ARG=%-8s FAILED no transcript\n" "$name" "$arg" | tee -a "$CAL"; return
  fi
  refs=$(grep -cE "^[TRW] " "$L")
  pages=$(grep -E "^[TRW] " "$L" | awk '{print $2}' | sort -u | wc -l)
  printf "%-12s arg=%-8s rc=%d %4ds refs=%-8s pages=%-6s refs_per_arg=%.2f\n" \
    "$name" "$arg" "$rc" "$((e-s))" "$refs" "$pages" \
    "$(awk -v r=$refs -v a=$arg 'BEGIN{print (a>0)? r/a : 0}')" | tee -a "$CAL"
  if [ "$rc" != "0" ]; then
    grep -vE "^[TRW] |^\\$|^#" "$L" | tail -2 | sed 's/^/             /' | tee -a "$CAL"
  fi
}

echo "# Stage 1 calibration  $(date -Is)" | tee -a "$CAL"
cal btreebench  4000  btreebench 4000 600 4000 1 mixed 1
cal kvbench     4000  kvbench 2000 300 4000 1 A 1
cal graphbench     3  graphbench 2000 300 3 1 both 1
cal sortbench  40000  sortbench 2000 300 40000 1 1
cal matmulbench   96  matmulbench 2000 300 96 naive 1
cal lzwbench       2  lzwbench 300 2 1
echo "# done $(date -Is)" | tee -a "$CAL"
