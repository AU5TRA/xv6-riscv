#!/bin/bash
# Run the capacity sweep (tools/collect_v2.sh) in parallel lanes, each in its
# own copy of the tree on the WSL filesystem, then merge the lanes into one
# campaign directory.
#
#   bash tools/run_sweep_lanes.sh ["lane spec" ...]
#
# A lane spec is either "workloads:<names>" (whole workloads, as WORKLOADS)
# or a space-separated list of run stems (as ONLY). With no specs the default
# split below is used. It is sized so the one long run -- graph-p5, about an
# hour -- sets the wall time: the other graph capacities pair up on two more
# lanes, and every other workload shares the fourth.
#
# Each lane gets its own tree because fs.img, the build and test-logs are per
# tree; the WSL filesystem because the 9p-mounted Windows drive roughly
# halves throughput. Paging is deterministic, so neither choice can change a
# result. Every lane compares against the same BASE.
#
#   OUT        merged campaign (default <this tree>/traces/sweep-rw); must not
#              already hold traces
#   BASE       baseline campaign (default <this tree>/traces/sweep)
#   LANE_ROOT  where the lane copies live (default ~/xv6-sweep)

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(realpath -m "${OUT:-$ROOT/traces/sweep-rw}")"
BASE="$(realpath -m "${BASE:-$ROOT/traces/sweep}")"
LANE_ROOT="${LANE_ROOT:-$HOME/xv6-sweep}"

if ls "$OUT"/*.trace >/dev/null 2>&1; then
  echo "run_sweep_lanes: $OUT already holds traces; refusing to overwrite them" >&2
  exit 1
fi

if [ $# -eq 0 ]; then
  set -- "graph-p5-c67" \
         "graph-p10-c133 graph-p25-c334" \
         "graph-p15-c200 graph-p20-c267 graph-p30-c400" \
         "workloads:kv btree matmul sort"
fi

i=0
pids=()
for spec in "$@"; do
  d="$LANE_ROOT/lane$i"
  rm -rf "$d"
  mkdir -p "$d"
  tar -C "$ROOT" --exclude=./traces --exclude=./test-logs --exclude=./.git \
      --exclude=./fs.img -cf - . | tar -C "$d" -xf -
  case "$spec" in
    workloads:*) env_args=(WORKLOADS="${spec#workloads:}" ONLY=) ;;
    *)           env_args=(WORKLOADS="kv btree matmul sort graph" ONLY="$spec") ;;
  esac
  echo "lane$i: $spec"
  env "${env_args[@]}" OUT=traces/sweep-rw BASE="$BASE" \
      bash "$d/tools/collect_v2.sh" > "$d/lane.out" 2>&1 &
  pids+=($!)
  i=$((i + 1))
done
for p in "${pids[@]}"; do
  wait "$p" || true
done

# ---- merge ----------------------------------------------------------------
mkdir -p "$OUT"
: > "$OUT/RESULTS.tsv"
: > "$OUT/COMPARISON.tsv"
for d in "$LANE_ROOT"/lane*; do
  src="$d/traces/sweep-rw"
  [ -d "$src" ] || continue
  cp "$src"/*.trace "$src"/*.log "$src"/*.harness "$OUT"/ 2>/dev/null || true
  cat "$src/RESULTS.tsv" >> "$OUT/RESULTS.tsv"
  cat "$src/COMPARISON.tsv" >> "$OUT/COMPARISON.tsv"
done
{
  echo "CAPACITY SWEEP -- merged from $(ls -d "$LANE_ROOT"/lane* | wc -l) lanes, $(date -Is)"
  echo "baseline: $BASE"
  echo
  echo "RESULTS"
  cat "$OUT/RESULTS.tsv"
  echo
  echo "COMPARISON AGAINST BASELINE"
  cat "$OUT/COMPARISON.tsv"
} > "$OUT/STATUS.txt"
echo "merged into $OUT: $(ls "$OUT"/*.trace 2>/dev/null | wc -l) traces," \
     "$(grep -c ' ok ' "$OUT/RESULTS.tsv") ok"
