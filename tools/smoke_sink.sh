#!/bin/bash
# End-to-end check of the file sink before committing to a 36-run campaign.
#
# lzwbench 300 1 <trace> is the cheapest workload that completes: with the
# reference stream on the console it took 63s and emitted 48,927 references
# (before lzwbench became compress(1)'s encoder; it now emits 133,967).
# Running the identical workload with the stream routed to a file must
# reproduce that reference count exactly -- the workload is deterministic, so
# the sink cannot change how many pages it touches. Anything else means the
# file sink is losing data or the run was truncated.

cd /mnt/d/thesis/xv6-riscv || exit 1
. /home/ashfaq/xv6env.sh
unset VM_DEBUG

echo "=== rebuilding fs.img so the run starts from a clean disk ==="
rm -f fs.img && make fs.img >/dev/null 2>&1 || { echo "fs.img build failed"; exit 1; }

echo "=== run: lzwbench 300 1 9  (trace on, file sink) ==="
S=$(date +%s)
python3 tools/run_xv6_tests.py --cpus 1 --timeout 600 "lzwbench 300 1 9" \
    > /tmp/smoke.txt 2>&1
RC=$?
E=$(date +%s)
echo "rc=$RC elapsed=$((E-S))s"

L=$(grep -oE '/[^ ]+\.log' /tmp/smoke.txt | tail -1)
echo "transcript: $L"
echo "console reference lines in transcript: $(grep -cE '^[TRW] ' "$L" 2>/dev/null)  (expect 0)"
grep -E "RESULT (PASS|FAIL)" "$L" 2>/dev/null | head -3
grep -oE "swap_faults=[0-9]+|evictions=[0-9]+|resident_limit=[0-9]+" "$L" 2>/dev/null | head -5

echo "=== extracting reftrace.txt from fs.img ==="
python3 tools/extract_file.py fs.img --list 2>&1 | head -20
mkdir -p /tmp/sm
python3 tools/extract_file.py fs.img reftrace.txt /tmp/sm/reftrace.txt 2>&1 | tail -3
if [ -f /tmp/sm/reftrace.txt ]; then
  echo "extracted bytes: $(stat -c %s /tmp/sm/reftrace.txt)"
  echo "reference lines: $(grep -cE '^[TRW] ' /tmp/sm/reftrace.txt)   (expect 133967)"
  echo "distinct pages : $(awk '/^[TRW] /{print $2}' /tmp/sm/reftrace.txt | sort -u | wc -l)"
  echo "--- first 3 ---"; head -3 /tmp/sm/reftrace.txt
  echo "--- last 3 ---";  tail -3 /tmp/sm/reftrace.txt
  echo "malformed lines: $(grep -vcE '^[TRW] [0-9]+$' /tmp/sm/reftrace.txt)   (expect 0)"
else
  echo "EXTRACTION FAILED"
fi
