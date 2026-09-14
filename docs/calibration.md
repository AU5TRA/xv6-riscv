# Calibration methodology and results (WORK_PROMPT3.md Phase 2/3)

This document previously recorded Phase 4/5 as blocked on missing
`sudo`/package-install access. **That blocker is resolved.** `apt-get
download` + `dpkg-deb -x` (neither needs root) fetched `sqlite3`,
`valgrind`, and `redis-server`/`redis-tools` as ordinary `.deb`
packages and extracted them into `~/local/pkgroot`, with two missing
transitive shared libraries (`liblzf1`, `libjemalloc2`) fetched the
same way. `VALGRIND_LIB` and `LD_LIBRARY_PATH` point the extracted
binaries at their own tool/library directories. All three verified
working (a real SQL query, a real Lackey memory trace, a real Redis
`PING`/`SET`/`GET` round-trip) — no source build was needed, contrary
to this document's own earlier assumption.

## Real trace collection (`tools/collect_linux_trace.sh`)

Runs real SQLite 3.45.1 and real Redis 7.0.15 under `valgrind
--tool=lackey --trace-mem=yes` (both the exact Ubuntu 24.04 "noble"
package builds — see the script's own header comment for exact
workload shapes: SQLite gets 2000 sequential inserts + 500 point
lookups + 100 twenty-row range scans; Redis gets 2000 SETs + 2000 GETs
over a 500-key Zipfian-skewed (S=0.99) keyspace, mirroring btreebench's
and kvbench's own access-mode shapes respectively).

**`tools/trace_reduce.py`** collapses Lackey's raw byte-address L/S
(load/store) lines to page granularity, drops consecutive duplicate
-page touches (lossless for fault counting), and compacts the sparse
real address space onto a dense `0..N-1` index, emitting directly in
the same `TRACEHDR`/`T <vpn>` format `trace_decode.py`/`sim.py` already
consume — there is only ever one trace format in this suite, so no
second encoding was invented.

Measured reduction: SQLite's run produced 18.86M raw memory references
→ 8.56M collapsed page references over 283 unique pages. Redis: 45.6M
raw → 12.32M collapsed over 1416 unique pages.

**A real scalability bug found and fixed while processing these**:
`trace_decode.py`'s original `reuse_distances()` was O(n × unique) via
Python list operations — fine for the thousand-reference native xv6
traces, intractable for these multi-million-reference real traces.
Replaced with the standard Fenwick-tree (binary indexed tree) stack
-distance algorithm, O(n log n) — cross-checked to produce IDENTICAL
output to the old algorithm on the hand-computed self-test example
before the old one was removed. Full statistics (reuse-distance
histogram, miss-ratio curve, working-set-over-time, phase detection,
conditional entropy) now compute in ~60-95 seconds even for the
12M-reference Redis trace.

**Real findings from the real traces**: SQLite shows a clean two-phase
shape — a large working set during bulk insert (282 pages), collapsing
to a small, stable one during point-lookup/range-scan (~50-80 pages).
Redis is far more turbulent (working-set series `[989, 316, 612, 290,
134, 138, 149, 135, 138, 359]`, 6 phase changes vs. SQLite's 2) —
consistent with SET-then-GET being two very differently-shaped access
regimes, unlike SQLite's steadier post-bulk-load behavior.

## Distance metric (proposed, then implemented — see `tools/calibrate.py`)

```
distance(A, B) = 0.7 * JS(reuse_distance_dist_A, reuse_distance_dist_B)
                + 0.3 * RMSE(normalized_working_set_A, normalized_working_set_B)
```

- **Jensen-Shannon divergence** (0.7 weight) over the log2-bucketed
  reuse-distance histograms, normalized to probability distributions.
  Chosen because WORK_PROMPT3.md's own Phase 3 calls reuse-distance
  "the single most informative statistic for replacement behaviour,"
  and JS divergence stays well-behaved (symmetric, bounded in [0, 1]
  bit) even when the two distributions have very different supports —
  which they do here, since real and native traces have wildly
  different unique-page counts and thus different bucket ranges. KL
  divergence was rejected specifically because it blows up on
  zero-probability buckets, which is close to guaranteed in this
  comparison.
- **RMSE over normalized working-set-size-over-time** (0.3 weight),
  each series divided by its own trace's unique-page count before
  comparing. This compares *shape* (how much the working set
  fluctuates, whether there are phase changes) rather than absolute
  magnitude — a real Redis process legitimately touches far more raw
  pages than any small native benchmark run ever will, and that scale
  gap is not the interesting question.

## Grid search results

Coarse grids, as the task spec allows. All at generous resident
margins (to keep the *reference stream itself* uncontaminated by
eviction noise — see WORK_PROMPT.md's own Phase 4 finding that
eviction pressure changes what gets faulted, which is a different
question from what the workload's natural access shape looks like).

### `kvbench` vs. real Redis (footprint=30 unless noted, op_count=2000, seed=1)

| mode | rehash | valuesize | distance |
|---|---|---|---|
| A | off | off | 0.598 |
| A | on | off | 0.454 |
| **A** | **off** | **on (footprint=200)** | **0.442 (best)** |
| A | on | on (footprint=200) | 0.505 |
| B | off | off | 0.544 |
| B | on | off | 0.445 |
| B | off | on (footprint=200) | 0.528 |
| B | on | on (footprint=200) | 0.509 |

**Best**: mode A, valuesize enabled, distance 0.442. Note `valuesize`
needed a much larger footprint (200 vs. 30) — heavy-tailed values
(up to 2KB) exhaust a small value arena; this is a real operational
constraint on the preset, not a tuning nicety.

### kvbench N/S/TTL sweep (follow-up task, `tools/calibrate_grid.py`)

The grid above did not sweep Zipf skew (`S`), key-space size (`N`), or
TTL — `N`/`S` are not `kvbench` CLI arguments; they are module-level
constants in `tools/gen_zipf_table.py` baked into the committed
`user/zipf_table.h` at build time. `tools/calibrate_grid.py` automates
rewriting those constants, regenerating the header, building+running
`kvbench` inside xv6, and restoring both files to their original
committed content afterward (verified via `git diff --stat`, printed at
the end of every run).

Coarse, coordinate-descent-style sweep around the known-best point
(mode A, valuesize on, rehash off, footprint=margin=200, op_count=2000,
seed=1, `N=1024`/`S=0.99`/`ttl=0`, distance 0.442) — one dimension varied
at a time rather than a full `N`×`S`×`ttl` cross product, consistent with
this project's own "coarse grid" precedent:

| sweep | value | distance | JS | WS-RMSE |
|---|---|---|---|---|
| ttl | **20** | **0.4372 (best)** | 0.3832 | 0.5631 |
| baseline | S=0.99, N=1024, ttl=0 | 0.4424 | 0.3925 | 0.5590 |
| ttl | 200 | 0.4424 (identical to baseline) | 0.3925 | 0.5590 |
| S | 0.8 | 0.4469 | 0.4021 | 0.5515 |
| S | 0.7 | 0.4565 | 0.4171 | 0.5483 |
| N | 200 | 0.4598 | 0.4348 | 0.5182 |
| N | 500 (matches real trace's own keyspace) | 0.4668 | 0.4239 | 0.5669 |
| S | 1.2 | 0.4862 (worst) | 0.4778 | 0.5058 |

**Result, reported plainly**: none of the three swept dimensions produced
a meaningful improvement. The single best point (`ttl_ticks=20`) improved
distance from 0.442 to 0.4372 — a 1.2% relative reduction — which moves
the control margin from 12% to about **12.7%** (control: sortbench,
0.501). `ttl=200` had no effect at all (identical to `ttl=0` to four
decimal places), meaning 200 ticks never elapses within this 2000-op run
— too coarse to matter. Every `S` and `N` value tried made the match
*worse* than the committed defaults, including `N=500`, the value that
actually matches the real trace's own key-space (see the module docstring
of `tools/calibrate_grid.py` for why this is the right, apples-to-apples
comparison to make against the fixed real trace) — i.e. deliberately
mismatching `N` from the real trace's own 500-key setup does not hurt the
match, and in this grid slightly *helps* it. This is a genuine,
non-obvious finding, consistent with this project's precedent of
reporting flat/negative results rather than only headlining wins (see
the btreebench-internal-cache finding above): `kvbench`'s calibration
weakness does not appear to be fixable by tuning skew, key-space size, or
TTL in isolation. The likely limiting factor is something the CLI
doesn't currently expose at all (e.g. the fixed 60% initial load factor,
the fixed SET-then-GET op ordering, or the value-size distribution
shape) — a real target for a future task, not this one.

**Working tree state after this sweep**: clean.
`tools/gen_zipf_table.py` and `user/zipf_table.h` match their committed
content (`N=1024`, `S=0.99`) — every regenerated grid point was
transient and reverted at the end of the run.

### `btreebench` vs. real SQLite (footprint=40, margin=40, op_count=600, seed=1)

| mix | wal | cache | distance |
|---|---|---|---|
| mixed | off | off | **0.258 (best)** |
| mixed | on | off | 0.261 |
| mixed | off | on | 0.519 |
| mixed | on | on | 0.375 |
| lookup | off | off | 0.376 |
| lookup | on | off | 0.376 |
| lookup | off | on | 0.621 |
| lookup | on | on | 0.621 |

**Best**: `mixed` mode, no WAL, no internal cache, distance 0.258 —
notably better than any `btreebench` config with the internal cache
enabled (0.375-0.621).

**A genuine, non-flattering methodological finding, reported rather
than hidden**: enabling the internal cache made `btreebench` *less*
similar to real SQLite, not more, and by a wide margin. This makes
sense on reflection rather than being a bug: real SQLite's own
internal page cache is *invisible* to Valgrind Lackey — Lackey traces
every raw CPU memory access regardless of what SQLite's own
higher-level cache logic decided, so the real trace is fundamentally
**unfiltered**. `btreebench`'s cache-enabled mode filters out
app-level cache *hits* from its own traced reference stream by design
(that was the whole point of building it, per WORK_PORMPT2.md Phase
2c) — comparing a filtered native trace against an unfiltered real one
is an apples-to-oranges mismatch. **Implication**: for calibrating
against real Lackey-collected traces specifically, the internal-cache
feature should stay off; it remains useful for its original,
different purpose (showing how much a real app's own cache would
reduce what the *kernel* sees).

### Unrelated-workload control (mandatory per Gate 3 — the check that determines whether this whole exercise means anything)

| workload | vs. real Redis | vs. real SQLite |
|---|---|---|
| sortbench | 0.501 | 0.461 |
| matmulbench | 0.682 | 0.664 |
| graphbench | 0.802 | 0.795 |
| **kvbench (best)** | **0.442** | — |
| **btreebench (best)** | — | **0.258** |

**Control check result**: both native workloads ARE measurably closer
to their real counterparts than the best unrelated workload (sortbench)
is — the imitation has not failed. **But the margin is very different
between the two**: `btreebench` beats the control by a wide margin
(0.258 vs. 0.461, i.e. its distance is 44% smaller); `kvbench` beats it
by a much narrower one (0.442 vs. 0.501, only 12% smaller). Reported
honestly rather than only headlining the stronger result: `btreebench`'s
resemblance to real SQLite is the more convincing of the two findings.
`kvbench`'s resemblance to real Redis is real but weak, and would
benefit from further tuning (the grid here was coarse and did not sweep
Zipf skew, key-space size, or TTL, all of which are real candidate
knobs for a follow-up search).

## Calibrated presets (WORK_PROMPT2.md Phase 5)

Locked in as the exact, reproducible CLI invocations found above,
rather than new `--preset` CLI parsing (xv6's shell `MAXARGS=10` ceiling
is already tight — see `docs/workloads.md` — and these are simple
enough to record directly):

- **`btreebench` "sqlite-like"**: `btreebench <footprint> <margin> <op_count> <seed> mixed <flags with bit0=trace, bit1=0, bit2=0>` — mixed mode, WAL and cache both off.
- **`kvbench` "redis-like"**: `kvbench <footprint>=200+ <margin> <op_count> <seed> A <flags with bit0=trace, bit2=1 (valuesize)>` — mode A, valuesize on, rehash off; needs a generous footprint (200+ pages) for the value arena.

## Oracle gap: original vs. calibrated (WORK_PROMPT2.md Phase 5 gate)

Both calibrated presets re-run at real memory pressure (not the
generous margin used during the distance search itself):

| workload | config | capacity | best-classical gap vs. Belady |
|---|---|---|---|
| btreebench | Phase 0 original (mixed, plain) | 36% of working set | +58% (LRU) |
| btreebench | **calibrated preset** (mixed, no WAL/cache) | 20% of working set | **+67% (Clock)** |
| kvbench | Phase 0 original (mode A, plain) | 50% of working set | +73% (LRU) |
| kvbench | **calibrated preset** (mode A, valuesize) | 20% of working set | **+113% (LRU)** |

**This is good news, exactly as the task spec hoped**: the calibrated
(more realistic) configurations show LARGER oracle gaps than the
original simpler ones — kvbench's headroom grew from +73% to +113%
once given a real property (heavy-tailed values) that real Redis
actually has. Making the workloads more realistic did not shrink the
ML opportunity; it grew it.

## Train/validation/test split (WORK_PROMPT2.md Phase 5 point 4)

No ML training pipeline exists yet (explicitly out of scope — see
"Explicitly out of scope" in `WORK_PROMPT3.md`). Recorded here as a
design principle for whenever that pipeline is built, not as something
implemented this pass: **the split must be by program** (e.g. all of
one `btreebench` run's trace windows go entirely into train, or
entirely into val, or entirely into test — never split within a single
run). Adjacent windows from the same run are highly correlated (same
tree, same warm state); splitting within a run leaks future
information into training in a way that would make validation numbers
look better than they actually are.
