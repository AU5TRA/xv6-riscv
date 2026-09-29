#!/bin/bash
# Run a stream manifest in parallel lanes, each in its own copy of the tree
# on the WSL filesystem.
#
#   PHASES="pilot" bash tools/run_stream_lanes.sh [manifest] [lanes]
#
# Why copies: fs.img, the build and test-logs are per tree, so two runs in
# one tree would share a disk image. Why the WSL filesystem: the 9p-mounted
# Windows drive roughly halves throughput (kvbench at a fixed capacity: 50s
# there, 27s on ext4, identical counters). Paging and reference strings are
# deterministic, so which lane or filesystem a run used cannot change its
# result.
#
# Work is split longest-first onto the least-loaded lane (by the manifest's
# est_s), so the graph runs spread out instead of queueing on one lane.
# Every lane writes into the same OUT, here in the source tree, and a
# re-run skips streams already marked collected.
#
#   PHASES     manifest phases to run (default "pilot dataset")
#   LANE_ROOT  where the lane copies live (default ~/xv6-lanes)
#   OUT        collected streams (default <this tree>/traces/streams)

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$(realpath "${1:-$ROOT/tools/streams_manifest.tsv}")"
LANES="${2:-6}"
PHASES="${PHASES:-pilot dataset}"
LANE_ROOT="${LANE_ROOT:-$HOME/xv6-lanes}"
OUT="$(realpath -m "${OUT:-$ROOT/traces/streams}")"
mkdir -p "$OUT/.lanes"

# Longest-processing-time assignment of the selected, not-yet-collected runs.
python3 - "$MANIFEST" "$LANES" "$OUT" "$PHASES" <<'EOF'
import os, sys
manifest, lanes, out, phases = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4].split()
rows = []
for line in open(manifest):
    if line.startswith("#") or not line.strip():
        continue
    stem, est, phase, cmd = line.rstrip("\n").split("\t")
    done = os.path.join(out, stem.split("-")[0], stem + ".ok")   # per-workload folder
    if phase in phases and not os.path.exists(done):
        rows.append((int(est), line))
rows.sort(key=lambda r: -r[0])
load = [0] * lanes
files = [open(os.path.join(out, ".lanes", "lane%d.tsv" % i), "w") for i in range(lanes)]
for est, line in rows:
    i = load.index(min(load))
    load[i] += est
    files[i].write(line)
for f in files:
    f.close()
print("%d runs over %d lanes; estimated %.0f min per lane (max %.0f)"
      % (len(rows), lanes, sum(load) / lanes / 60, max(load) / 60))
EOF

# One copy of the built tree per lane. tar keeps modification times, so the
# copies do not rebuild what is already built.
for i in $(seq 0 $((LANES - 1))); do
  d="$LANE_ROOT/lane$i"
  rm -rf "$d"
  mkdir -p "$d"
  tar -C "$ROOT" --exclude=./traces --exclude=./test-logs --exclude=./.git \
      --exclude=./fs.img -cf - . | tar -C "$d" -xf -
done

pids=()
for i in $(seq 0 $((LANES - 1))); do
  OUT="$OUT" bash "$LANE_ROOT/lane$i/tools/collect_streams.sh" \
      "$OUT/.lanes/lane$i.tsv" "lane$i" > "$OUT/.lanes/lane$i.out" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do
  wait "$p" || true
done

echo "done. collected: $(ls "$OUT"/*.ok 2>/dev/null | wc -l) streams;" \
     "failed this pass: $(cat "$OUT"/RESULTS-lane*.tsv 2>/dev/null | grep -c FAILED)"
