#!/usr/bin/env bash
# Runs a matrix of vmbench workloads (with tracing enabled) under
# tools/run_xv6_tests.py and collects the resulting transcripts into
# traces/ (WORK_PROMPT.md Phase 3). Each transcript already contains a
# TRACEHDR line plus the full reference stream -- see
# tools/trace_decode.py to summarize one afterward.
#
# Usage: tools/trace_collect.sh [venv_python]
#   venv_python defaults to the pexpect venv this project's sessions
#   have used at /tmp/.../scratchpad/venv/bin/python3 if present, else
#   plain `python3` (pexpect must already be importable).
#
# NOTE: fs.img can only be held open by one QEMU instance at a time
# (see HANDOFF_PROMPT.md/WORK_PROMPT.md environment notes) -- this
# script runs the matrix strictly sequentially for that reason.
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

OUT_DIR="$REPO_ROOT/traces"
mkdir -p "$OUT_DIR"

# workload command args | percent-of-footprint labels for the margin arg
# Each entry: "<program> <footprint> <op_count_or_iters> <seed> <mode>"
# Margins are computed as 100%/50%/25%/12% of footprint, per Gate 3.
run_one() {
  local name="$1" footprint="$2" cmd_rest="$3" pct="$4"
  local margin=$(( footprint * pct / 100 ))
  if [ "$margin" -lt 1 ]; then margin=1; fi
  local cmd="$name $footprint $margin $cmd_rest 1"
  local safe
  safe=$(echo "$cmd" | tr -c 'A-Za-z0-9_' '-')
  local out="$OUT_DIR/${safe}.log"
  echo "=== $cmd  (pct=$pct%) ==="
  if "$PY" "$REPO_ROOT/tools/run_xv6_tests.py" --cpus 1 --timeout 120 "$cmd" \
      > "$out.harness" 2>&1; then
    echo "  harness: PASS"
  else
    echo "  harness: FAIL (see $out.harness) -- collecting transcript anyway"
  fi
  # run_xv6_tests.py prints the transcript path in its own PASS/FAIL line;
  # copy the referenced transcript alongside for convenience.
  transcript=$(grep -oE '/[^ ]+\.log' "$out.harness" | tail -1 || true)
  if [ -n "${transcript:-}" ] && [ -f "$transcript" ]; then
    cp "$transcript" "$out"
    echo "  trace saved: $out"
  else
    echo "  WARNING: could not locate transcript for $cmd"
  fi
}

for pct in 100 50 25 12; do
  run_one btreebench 40 "300 1 mixed" "$pct"
  run_one kvbench 8 "500 1 A" "$pct"
done

echo
echo "Collected traces are in $OUT_DIR/"
echo "Decode one with: python3 tools/trace_decode.py <file>"
