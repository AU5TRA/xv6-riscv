cd /mnt/d/thesis/xv6-riscv
. /home/ashfaq/xv6env.sh
unset VM_DEBUG
P=traces/sweep/PROBE.txt; : > "$P"
probe() {
  local name="$1"; shift
  local s e rc L refs pages
  s=$(date +%s)
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 "$*" >/tmp/p.txt 2>&1
  rc=$?; e=$(date +%s)
  L=$(grep -oE '/[^ ]+\.log' /tmp/p.txt | tail -1)
  refs=$(grep -c "^T " "$L" 2>/dev/null)
  pages=$(grep "^T " "$L" 2>/dev/null | awk '{print $2}' | sort -u | wc -l)
  printf "%-12s rc=%d %4ds refs=%-8s pages=%-6s\n" "$name" "$rc" "$((e-s))" "$refs" "$pages" | tee -a "$P"
}
probe btreebench btreebench 5000 900 45000 1 mixed 1
probe kvbench    kvbench 2000 400 20000 1 A 1
