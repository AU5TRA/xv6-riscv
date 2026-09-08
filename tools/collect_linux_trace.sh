#!/usr/bin/env bash
# Collects real SQLite and Redis memory-reference traces on Linux
# (WORK_PROMPT.md Phase 5 / WORK_PROMPT3.md Phase 2). Pure user-space
# observation: no kernel work, no root, no porting.
#
# Requires sqlite3, valgrind (with the lackey tool), redis-server, and
# redis-cli on PATH, plus VALGRIND_LIB pointing at valgrind's tool
# directory if it wasn't installed via a real package manager (see
# docs/calibration.md for how this session got them without root:
# `apt-get download` + `dpkg-deb -x`, no source build needed).
#
# Usage: tools/collect_linux_trace.sh <output_dir>
#
# Versions/workload shapes used (recorded here for reproducibility,
# per this script's own docstring requirement):
#   - sqlite3 3.45.1 (Ubuntu 24.04 "noble" package build)
#   - redis-server 7.0.15 (Ubuntu 24.04 "noble-updates" package build)
#   - valgrind 3.22.0 (Ubuntu 24.04 "noble" package build)
#   - SQLite workload: CREATE TABLE kv(k INTEGER PRIMARY KEY, v INTEGER);
#     2000 sequential inserts, then a mix of 500 point lookups (random
#     key) and 100 range scans (20 consecutive keys each) -- mirrors
#     btreebench's own insert/lookup/scan mix.
#   - Redis workload: 2000 SETs over a 500-key Zipfian-skewed keyspace
#     (skew matching tools/gen_zipf_table.py's S=0.99), then 2000 GETs
#     over the same skewed distribution -- mirrors kvbench's own
#     Zipfian YCSB-mode-A-like shape.
set -euo pipefail

OUT_DIR="${1:?usage: collect_linux_trace.sh <output_dir>}"
mkdir -p "$OUT_DIR"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VALGRIND_LIB="${VALGRIND_LIB:-$HOME/local/pkgroot/usr/libexec/valgrind}"

for tool in sqlite3 valgrind redis-server redis-cli; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "collect_linux_trace.sh: '$tool' not on PATH -- see docs/calibration.md" >&2
    exit 1
  fi
done

echo "=== versions ==="
sqlite3 --version
valgrind --version
redis-server --version

# ---- SQLite --------------------------------------------------------------
echo
echo "=== collecting SQLite trace ==="
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

python3 - "$WORKDIR/sqlite_workload.sql" << 'PYEOF'
import random
import sys

out = sys.argv[1]
random.seed(1)
lines = [
    "CREATE TABLE kv(k INTEGER PRIMARY KEY, v INTEGER);",
    "BEGIN;",
]
for k in range(2000):
    lines.append(f"INSERT INTO kv VALUES({k}, {k * 2});")
lines.append("COMMIT;")
for _ in range(500):
    k = random.randrange(2000)
    lines.append(f"SELECT v FROM kv WHERE k={k};")
for _ in range(100):
    start = random.randrange(1980)
    lines.append(f"SELECT v FROM kv WHERE k>={start} AND k<{start + 20};")
with open(out, "w") as f:
    f.write("\n".join(lines) + "\n")
PYEOF

valgrind --tool=lackey --trace-mem=yes \
    sqlite3 "$WORKDIR/test.db" ".read $WORKDIR/sqlite_workload.sql" \
    > /dev/null 2> "$WORKDIR/sqlite_raw.trace"

python3 "$REPO_ROOT/tools/trace_reduce.py" \
    --workload sqlite_real \
    --params "2000 inserts, 500 point lookups, 100 20-row range scans, seed=1" \
    -o "$OUT_DIR/sqlite_real.trace" \
    < "$WORKDIR/sqlite_raw.trace"

# ---- Redis ----------------------------------------------------------------
echo
echo "=== collecting Redis trace ==="
REDIS_PORT=16412
REDIS_LOG="$WORKDIR/redis.log"

valgrind --tool=lackey --trace-mem=yes \
    redis-server --port "$REDIS_PORT" --daemonize no --save "" --appendonly no \
    > "$WORKDIR/redis_stdout.log" 2> "$WORKDIR/redis_raw.trace" &
REDIS_PID=$!

# Wait for the (heavily slowed-down, under valgrind) server to accept
# connections rather than a fixed sleep.
for i in $(seq 1 60); do
  if redis-cli -p "$REDIS_PORT" PING > /dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! redis-cli -p "$REDIS_PORT" PING > /dev/null 2>&1; then
  echo "collect_linux_trace.sh: redis-server did not come up under valgrind" >&2
  kill "$REDIS_PID" 2>/dev/null || true
  exit 1
fi

python3 - "$REDIS_PORT" << 'PYEOF'
import random
import subprocess
import sys

port = sys.argv[1]
random.seed(1)

# Zipfian-ish skew (same S=0.99 shape as tools/gen_zipf_table.py,
# computed inline here since this is host-side Python with no
# floating-point restriction) over a 500-key space.
N = 500
S = 0.99
weights = [1.0 / ((k + 1) ** S) for k in range(N)]
total = sum(weights)
cum = []
running = 0.0
for w in weights:
    running += w
    cum.append(running / total)

def zipf_key():
    r = random.random()
    lo, hi = 0, N - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] >= r:
            hi = mid
        else:
            lo = mid + 1
    return lo

cmds = []
for _ in range(2000):
    cmds.append(f"SET key:{zipf_key()} value{random.randrange(1000000)}")
for _ in range(2000):
    cmds.append(f"GET key:{zipf_key()}")

proc = subprocess.run(
    ["redis-cli", "-p", port],
    input="\n".join(cmds) + "\n",
    text=True, capture_output=True)
if proc.returncode != 0:
    print(proc.stderr, file=sys.stderr)
    sys.exit(1)
PYEOF

redis-cli -p "$REDIS_PORT" SHUTDOWN NOSAVE 2>/dev/null || true
wait "$REDIS_PID" 2>/dev/null || true

python3 "$REPO_ROOT/tools/trace_reduce.py" \
    --workload redis_real \
    --params "2000 SETs + 2000 GETs, Zipfian S=0.99 over 500 keys, seed=1" \
    -o "$OUT_DIR/redis_real.trace" \
    < "$WORKDIR/redis_raw.trace"

echo
echo "done -- traces in $OUT_DIR/"
