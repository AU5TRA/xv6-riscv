#!/usr/bin/env bash
# "workloads" smoke test (WORK_PROMPT.md Phase 6 item 1): runs every
# Phase 2 benchmark at a small, fast configuration to catch a broken
# build/link/basic-usage regression quickly, without the cost of a
# real resident-limit sweep (see tools/trace_collect.sh for that).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PY="${1:-}"
if [ -z "$PY" ]; then
  if [ -x /tmp/claude-1000/-home-gawwy-Thesis-xv6-riscv/f1af484e-b41c-4672-a31a-3fa6e0ba03c4/scratchpad/venv/bin/python3 ]; then
    PY=/tmp/claude-1000/-home-gawwy-Thesis-xv6-riscv/f1af484e-b41c-4672-a31a-3fa6e0ba03c4/scratchpad/venv/bin/python3
  else
    PY=python3
  fi
fi

fail=0
run() {
  echo "=== $* ==="
  if ! "$PY" "$REPO_ROOT/tools/run_xv6_tests.py" --cpus 1 --timeout 60 "$*"; then
    fail=1
  fi
}

run vmbenchtest
run btreebench 20 20 50 1 mixed
run kvbench 8 8 100 1 A
run graphbench 10 10 2 1 both
run sortbench 10 10 500 1
run matmulbench 20 20 20 blocked
run lzwbench 100 1

if [ "$fail" -ne 0 ]; then
  echo
  echo "workloads smoke test: at least one benchmark FAILED"
  exit 1
fi
echo
echo "workloads smoke test: all benchmarks PASSED"
