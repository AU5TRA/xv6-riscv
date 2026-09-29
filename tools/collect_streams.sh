#!/bin/bash
# Collect reference streams listed in a manifest (tools/streams_manifest.tsv
# format: stem, est_s, phase, command), one traced run each.
#
#   OUT=<dir> bash tools/collect_streams.sh <manifest> [lane-name]
#
# Each run gets a freshly built fs.img, so a trace left by one run cannot
# change the next run's block layout. A stream counts as collected only when
#   * the run printed PASS and exited 0,
#   * the log carries TRACEEND refs=N bytes=M (user/vmbench.c), and
#   * the extracted trace has exactly N lines, exactly M bytes, and no line
#     that is not "R <vpn>" or "W <vpn>".
# Collected streams get an <stem>.ok marker and are skipped on a re-run, so
# an interrupted lane resumes where it stopped. Anything else is recorded as
# FAILED with the reason and retried next time.
#
# Usually started by tools/run_stream_lanes.sh, one copy per lane, but it
# runs standalone too.

cd "$(dirname "$0")/.." || exit 1
. "$HOME/xv6env.sh"
unset VM_DEBUG

MANIFEST="$1"
LANE="${2:-lane0}"
OUT="${OUT:-traces/streams}"
TIMEOUT="${TIMEOUT:-7200}"
[ -f "$MANIFEST" ] || { echo "collect_streams: no manifest '$MANIFEST'" >&2; exit 1; }
mkdir -p "$OUT" test-logs
RES="$OUT/RESULTS-$LANE.tsv"

grep -v '^#' "$MANIFEST" | while IFS=$'\t' read -r stem est phase cmd; do
  # A manifest written or checked out on Windows ends lines in CRLF; a
  # trailing \r would reach xv6's shell as part of the last argument.
  cmd="${cmd%$'\r'}"
  [ -n "$stem" ] || continue
  if [ -f "$OUT/$stem.ok" ]; then
    continue
  fi
  rm -f fs.img "$OUT/$stem.trace"
  make fs.img >/dev/null 2>&1

  s=$(date +%s)
  python3 tools/run_xv6_tests.py --cpus 1 --timeout "$TIMEOUT" "$cmd" \
      > "$OUT/$stem.harness" 2>&1 < /dev/null
  rc=$?
  e=$(date +%s)

  L=$(grep -oE '/[^ ]+\.log' "$OUT/$stem.harness" | tail -1)
  [ -n "$L" ] && [ -f "$L" ] && cp "$L" "$OUT/$stem.log"
  python3 tools/extract_file.py fs.img reftrace.txt "$OUT/$stem.trace" \
      >/dev/null 2>&1

  want_refs=$(grep -oE 'TRACEEND refs=[0-9]+' "$OUT/$stem.log" 2>/dev/null | cut -d= -f2)
  want_bytes=$(grep -oE 'TRACEEND refs=[0-9]+ bytes=[0-9]+' "$OUT/$stem.log" 2>/dev/null | sed 's/.*bytes=//')
  got_refs=0; got_bytes=0; bad=-1
  if [ -f "$OUT/$stem.trace" ]; then
    got_refs=$(wc -l < "$OUT/$stem.trace")
    got_bytes=$(wc -c < "$OUT/$stem.trace")
    bad=$(grep -vcE '^[RW] [0-9]+$' "$OUT/$stem.trace")
  fi

  if [ "$rc" != 0 ] || ! grep -q '^PASS' "$OUT/$stem.log" 2>/dev/null; then
    result="FAILED(run rc=$rc)"
  elif [ -z "$want_refs" ]; then
    result="FAILED(no TRACEEND)"
  elif [ "$got_refs" != "$want_refs" ] || [ "$got_bytes" != "$want_bytes" ]; then
    result="FAILED(trace $got_refs/$got_bytes != TRACEEND $want_refs/$want_bytes)"
  elif [ "$bad" != 0 ]; then
    result="FAILED($bad malformed lines)"
  else
    result="ok"
    touch "$OUT/$stem.ok"
  fi
  printf "%s\t%s\t%s\t%s\t%s\t%ds\t%s\n" "$stem" "$phase" "$got_refs" \
    "$got_bytes" "$rc" "$((e - s))" "$result" >> "$RES"
done
