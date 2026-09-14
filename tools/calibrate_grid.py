#!/usr/bin/env python3
"""Grid-search driver for kvbench's real-Redis calibration margin.

Sweeps Zipf skew (S), key-space size (N), and TTL (ttl_ticks) around the
existing best-known kvbench config from docs/calibration.md (mode A,
valuesize on, rehash off, footprint=margin=200, op_count=2000, seed=1,
distance 0.442 vs. real Redis). Builds on top of tools/calibrate.py's
existing pairwise trace_features()/distance() (not modified here) and
tools/run_xv6_tests.py's existing build/boot/run pattern (also not
modified -- this script only shells out to it, the same way
tools/trace_collect.sh does).

N and S are not kvbench CLI arguments -- they are module-level constants
in tools/gen_zipf_table.py, baked into the committed user/zipf_table.h
at build time (see that script's own docstring). This driver rewrites
those two constants, regenerates the header, builds+runs kvbench inside
xv6, and restores both files to their original committed content when
done (regardless of which grid point scored best) -- the working tree
should be clean after a run, which this script checks and reports.

The real reference trace (traces/real/redis_real.trace) was collected at
a fixed N=500/S=0.99 keyspace (see tools/collect_linux_trace.sh's header)
and does not move. Sweeping N/S on the native side away from 500/0.99
therefore tests "does deviating from the real trace's actual skew/key
-space make kvbench less representative," not "is there a skew that
matches Redis better" -- the ground truth is fixed. See HANDOFF_PROMPT.md
step 2 for the full reasoning; this is deliberate, not an oversight.

Usage:
    python3 tools/calibrate_grid.py [--real PATH] [--timeout SECONDS]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from calibrate import trace_features, distance  # noqa: E402

GEN_SCRIPT = REPO_ROOT / "tools" / "gen_zipf_table.py"
ZIPF_HEADER = REPO_ROOT / "user" / "zipf_table.h"
REAL_TRACE_DEFAULT = REPO_ROOT / "traces" / "real" / "redis_real.trace"

# Best-known base config, verbatim from docs/calibration.md's existing
# grid (the trace that produced distance 0.442): mode A, flags=5 (bit0
# trace + bit2 valuesize, rehash off), footprint=margin=200 (generous,
# no eviction -- this project's calibration convention throughout, see
# docs/calibration.md's "all at generous resident margins").
FOOTPRINT = 200
MARGIN = 200
OP_COUNT = 2000
SEED = 1
MODE = "A"
FLAGS = 5
DEFAULT_TIMEOUT = 120.0

PASS_RE = re.compile(r"^PASS: (\S+\.log)\s*$", re.MULTILINE)
FAIL_RE = re.compile(r"transcript: (\S+\.log)")


def read_original_zipf_constants() -> tuple[int, float, str]:
    text = GEN_SCRIPT.read_text()
    n = int(re.search(r"^N = (\d+)", text, re.MULTILINE).group(1))
    s = float(re.search(r"^S = ([\d.]+)", text, re.MULTILINE).group(1))
    return n, s, text


def write_zipf_constants(n: int, s: float, orig_text: str) -> None:
    text = re.sub(r"^N = \d+(\s*)", f"N = {n}\\1", orig_text, count=1,
                  flags=re.MULTILINE)
    text = re.sub(r"^S = [\d.]+(\s*)", f"S = {s}\\1", text, count=1,
                  flags=re.MULTILINE)
    GEN_SCRIPT.write_text(text)
    with ZIPF_HEADER.open("w") as f:
        subprocess.run([sys.executable, str(GEN_SCRIPT)], stdout=f, check=True)


def run_kvbench(ttl_ticks: int, timeout: float) -> tuple[str, str]:
    cmd = f"kvbench {FOOTPRINT} {MARGIN} {OP_COUNT} {SEED} {MODE} {FLAGS} {ttl_ticks}"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "run_xv6_tests.py"),
         "--cpus", "1", "--timeout", str(timeout), cmd],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    m = PASS_RE.search(out)
    if m:
        return m.group(1), cmd
    m = FAIL_RE.search(out)
    if m:
        print(f"  WARNING: harness reported failure for {cmd!r} "
              f"(see {m.group(1)}); using transcript anyway", file=sys.stderr)
        return m.group(1), cmd
    raise RuntimeError(f"could not find a transcript path in output:\n{out}")


def build_grid_points(base_n: int, base_s: float) -> list[dict]:
    # Coarse, coordinate-descent-style sweep around the known-best point
    # (N=base_n, S=base_s, ttl=0) -- one dimension at a time, per
    # HANDOFF_PROMPT.md step 3, rather than a full N x S x ttl cross
    # product (36 points for the suggested ranges, too much for "coarse
    # is fine"). N=500 (matching the real trace's own key-space, see
    # module docstring) is included in the N sweep.
    points = []
    for s in (0.7, 0.8, 0.99, 1.2):
        points.append({"N": base_n, "S": s, "ttl": 0,
                        "tag": f"S={s}" + (" (baseline)" if s == base_s else "")})
    for n in (200, 500, 1024):
        if n == base_n:
            continue
        tag = f"N={n}" + (" (matches real trace)" if n == 500 else "")
        points.append({"N": n, "S": base_s, "ttl": 0, "tag": tag})
    for ttl in (20, 200):
        points.append({"N": base_n, "S": base_s, "ttl": ttl, "tag": f"ttl={ttl}"})
    return points


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--real", default=str(REAL_TRACE_DEFAULT))
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = ap.parse_args()

    orig_n, orig_s, orig_gen_text = read_original_zipf_constants()
    print(f"original committed zipf_table.h constants: N={orig_n} S={orig_s}")
    print(f"loading real reference trace: {args.real} (this can take ~60-90s "
          f"for the multi-million-reference redis trace)")
    real_feat = trace_features(args.real)
    print(f"  real trace: unique={real_feat['unique']} "
          f"refs={real_feat['total_refs']}")

    points = build_grid_points(orig_n, orig_s)
    results = []
    cur_n, cur_s = None, None
    try:
        for pt in points:
            if (pt["N"], pt["S"]) != (cur_n, cur_s):
                print(f"regenerating zipf table: N={pt['N']} S={pt['S']}")
                write_zipf_constants(pt["N"], pt["S"], orig_gen_text)
                cur_n, cur_s = pt["N"], pt["S"]
            print(f"=== {pt['tag']}: N={pt['N']} S={pt['S']} ttl={pt['ttl']} ===")
            log_path, cmd = run_kvbench(pt["ttl"], timeout=args.timeout)
            feat = trace_features(log_path)
            d, js, ws_rmse = distance(feat, real_feat)
            row = {**pt, "cmd": cmd, "log": log_path, "distance": d, "js": js,
                   "ws_rmse": ws_rmse, "unique": feat["unique"],
                   "total_refs": feat["total_refs"]}
            results.append(row)
            print(f"  distance={d:.4f} (js={js:.4f} ws_rmse={ws_rmse:.4f}) "
                  f"unique={feat['unique']} refs={feat['total_refs']}")
    finally:
        print(f"restoring committed zipf_table.h constants: N={orig_n} S={orig_s}")
        write_zipf_constants(orig_n, orig_s, orig_gen_text)
        diff = subprocess.run(
            ["git", "diff", "--stat", "--", "tools/gen_zipf_table.py",
             "user/zipf_table.h"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        ).stdout.strip()
        if diff:
            print("WARNING: working tree not restored cleanly:\n" + diff)
        else:
            print("working tree check: tools/gen_zipf_table.py and "
                  "user/zipf_table.h match their committed content (clean).")

    results.sort(key=lambda r: r["distance"])
    print("\n=== grid results, best first ===")
    header = f"{'tag':<24} {'N':<6} {'S':<6} {'ttl':<6} {'distance':<10} {'js':<8} {'ws_rmse':<8}"
    print(header)
    for r in results:
        print(f"{r['tag']:<24} {r['N']:<6} {r['S']:<6} {r['ttl']:<6} "
              f"{r['distance']:<10.4f} {r['js']:<8.4f} {r['ws_rmse']:<8.4f}")

    best = results[0]
    print(f"\nbest: {best['tag']} distance={best['distance']:.4f}")
    print(f"  cmd: {best['cmd']}")
    print(f"  (compare to prior best 0.442 and control 0.501, "
          f"see docs/calibration.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
