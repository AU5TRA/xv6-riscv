#!/bin/bash
# Run the capacity sweep (tools/collect_v2.sh) in parallel lanes, each in its
# own copy of the tree on the WSL filesystem, then merge the lanes into one
# campaign directory.
#
#   bash tools/run_sweep_lanes.sh ["lane spec" ...]
#
# A lane spec is either "workloads:<names>" (whole workloads, as WORKLOADS)
# or a space-separated list of run stems (as ONLY). With no specs the default
# split below is used. It is sized so the long runs set the wall time:
# graph-p5 (about an hour) has a lane of its own, the other graph capacities
# pair up on two more, kv/btree/matmul/sort share the fourth, and lzw's 12
# runs fill five more lanes of about 90 minutes each (lzw-r30-p5 alone takes
# that long). patbench's 70 runs (about 23 hours) take eight more lanes of
# about 2.8 hours, split longest-first by each run's FIFO fault count on the
# model's reference string at ~0.8 ms a fault, chasebench's and joinbench's
# 36 (about 6 hours) three of about 2.1 hours, and bloombench's, spmvbench's
# and heapbench's 54 (about 10.4 hours) five of about 2.1 hours.
# Twenty-five lanes in all -- more than this machine's 12 cores, so to
# re-collect one workload pass just its lanes.
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
         "workloads:kv btree matmul sort" \
         "lzw-r30-p5-c22" \
         "lzw-r20-p5-c16 lzw-r20-p30-c99 lzw-r30-p30-c133" \
         "lzw-r30-p10-c44 lzw-r30-p20-c89" \
         "lzw-r20-p10-c33 lzw-r30-p15-c67" \
         "lzw-r20-p15-c49 lzw-r20-p20-c66 lzw-r20-p25-c82 lzw-r30-p25-c111" \
         "pat-loop-p5-c51 pat-loop-p95-c973 pat-phase-p20-c205 pat-phase-p30-c307 \
          pat-switch-p25-c256 pat-zipf060-p10-c102 pat-zipf060-p15-c154 \
          pat-zipf080-p25-c256 pat-zipf099-p10-c102" \
         "pat-loop-p10-c102 pat-loop-p99-c1014 pat-phaseshort-p30-c307 \
          pat-scanhot-p10-c102 pat-switch-p30-c307 pat-uniform-p20-c205 \
          pat-zipf060-p30-c307 pat-zipf120-p15-c154 pat-zipf120-p5-c51" \
         "pat-loop-p15-c154 pat-phaseshort-p10-c102 pat-phaseshort-p15-c154 \
          pat-scanhotlo-p5-c51 pat-switch-p5-c51 pat-zipf060-p25-c256 \
          pat-zipf080-p5-c51 pat-zipf099-p5-c51" \
         "pat-loop-p20-c205 pat-phase-p25-c256 pat-phaseshort-p20-c205 \
          pat-scanhot-p20-c205 pat-scanhot-p5-c51 pat-uniform-p25-c256 \
          pat-uniform-p5-c51 pat-zipf080-p20-c205 pat-zipf080-p30-c307" \
         "pat-loop-p25-c256 pat-phase-p10-c102 pat-phase-p15-c154 \
          pat-scanhot-p25-c256 pat-scanhot-p30-c307 pat-scanhotlo-p10-c102 \
          pat-switch-p10-c102 pat-uniform-p15-c154 pat-zipf120-p30-c307" \
         "pat-loop-p30-c307 pat-scanhot-p15-c154 pat-scanhotlo-p15-c154 \
          pat-switch-p20-c205 pat-zipf060-p5-c51 pat-zipf080-p15-c154 \
          pat-zipf099-p25-c256 pat-zipf120-p10-c102 pat-zipf120-p25-c256" \
         "pat-loop-p80-c819 pat-phase-p5-c51 pat-scanhotlo-p20-c205 \
          pat-scanhotlo-p30-c307 pat-uniform-p30-c307 pat-zipf060-p20-c205 \
          pat-zipf099-p20-c205 pat-zipf099-p30-c307" \
         "pat-loop-p90-c922 pat-phaseshort-p25-c256 pat-phaseshort-p5-c51 \
          pat-scanhotlo-p25-c256 pat-switch-p15-c154 pat-uniform-p10-c102 \
          pat-zipf080-p10-c102 pat-zipf099-p15-c154 pat-zipf120-p20-c205" \
         "chase-list-p30-c307 chase-list-p5-c51 chase-n256-p25-c256 \
          chase-tree-p20-c205 chase-tree-p25-c256 chase-tree-p5-c51 \
          join-uni-p10-c128 join-uni-p15-c192 join-uni-p20-c256 join-uni-p5-c64 \
          join-zipf-p15-c192 join-zipf-p30-c384" \
         "chase-list-p10-c102 chase-list-p25-c256 chase-n256-p10-c102 \
          chase-n256-p15-c154 chase-n256-p30-c307 chase-tree-p10-c102 \
          join-r4-p20-c410 join-r4-p30-c614 join-r4-p5-c102 join-zipf-p10-c128 \
          join-zipf-p20-c256 join-zipf-p25-c320" \
         "chase-list-p15-c154 chase-list-p20-c205 chase-n256-p20-c205 \
          chase-n256-p5-c51 chase-tree-p15-c154 chase-tree-p30-c307 \
          join-r4-p10-c205 join-r4-p15-c307 join-r4-p25-c512 join-uni-p25-c320 \
          join-uni-p30-c384 join-zipf-p5-c64" \
         "bloom-k3-p20-c102 bloom-k3-p30-c154 bloom-k7-p5-c26 heap-churn-p10-c44 \
          heap-churn-p20-c88 heap-small-p20-c82 spmv-band-p30-c500 \
          spmv-rand-p15-c250 spmv-rand-p25-c417" \
         "bloom-k3-p15-c77 bloom-k7-p10-c51 heap-mixed-p25-c367 heap-small-p15-c61 \
          heap-small-p30-c123 spmv-band-p5-c83 spmv-rand-p30-c500 spmv-rand-p5-c83" \
         "bloom-k3-p10-c51 bloom-k7-p15-c77 heap-churn-p30-c131 heap-churn-p5-c22 \
          heap-mixed-p20-c294 heap-mixed-p5-c73 heap-small-p10-c41 \
          spmv-band-p10-c167 spmv-band-p25-c417" \
         "bloom-k3-p25-c128 bloom-k3-p5-c26 bloom-k7-p20-c102 heap-mixed-p30-c441 \
          heap-small-p25-c102 heap-small-p5-c20 spmv-band-p15-c250 \
          spmv-rand-p10-c167" \
         "bloom-k7-p25-c128 bloom-k7-p30-c154 heap-churn-p15-c66 heap-churn-p25-c110 \
          heap-mixed-p10-c147 heap-mixed-p15-c220 spmv-band-p20-c333 \
          spmv-rand-p20-c333"
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
    *)           env_args=(WORKLOADS="kv btree matmul sort graph lzw pat chase join bloom spmv heap" ONLY="$spec") ;;
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
