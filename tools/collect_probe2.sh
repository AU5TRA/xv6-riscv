#!/bin/bash
# Find a size at which each of the four stalled workloads actually COMPLETES.
#
# Diagnosis: these workloads need millions of references to finish one run,
# and the reference string goes to the console at only ~450-1000 refs/s.
# graphbench's reference count rose with capacity (1.19M at 5% -> 1.69M at
# 30%) without ever finishing, which means the runs were progressing steadily
# and simply never reached the end -- not stalling, just far too long.
#
# Cutting graphbench from 3 PageRank iterations to 1 barely helped, so the
# cost is dominated by graph construction and BFS, not by the iteration count.
# The lever has to be the DATA SIZE argument.
#
# Each probe runs with a generous margin so paging is not the bottleneck; the
# question here is only "how many references does one complete run need".

cd /mnt/d/thesis/xv6-riscv
. /home/ashfaq/xv6env.sh
unset VM_DEBUG
P=traces/sweep/PROBE2.txt
: > "$P"

probe() {
  local name="$1"; shift
  local s e rc L refs pages
  s=$(date +%s)
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 900 "$*" >/tmp/q.txt 2>&1
  rc=$?; e=$(date +%s)
  L=$(grep -oE '/[^ ]+\.log' /tmp/q.txt | tail -1)
  refs=$(grep -c "^T " "$L" 2>/dev/null)
  pages=$(grep "^T " "$L" 2>/dev/null | awk '{print $2}' | sort -u | wc -l)
  printf "%-22s rc=%d %4ds refs=%-9s pages=%-6s %s\n" \
    "$name" "$rc" "$((e-s))" "${refs:-0}" "${pages:-0}" \
    "$([ "$rc" = 0 ] && echo COMPLETED || echo 'still too big')" | tee -a "$P"
}

echo "# probe2 $(date -Is)  -- generous margins, looking for completion" | tee -a "$P"
probe "graphbench f=400"   graphbench 400 300 1 1 both 1
probe "sortbench n=8000"   sortbench 2000 300 8000 1 1
probe "lzwbench r=1"       lzwbench 300 1 1
probe "matmulbench n=48"   matmulbench 2000 300 48 naive 1
echo "# done $(date -Is)" | tee -a "$P"
