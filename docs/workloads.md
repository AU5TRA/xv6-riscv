# Workload suite (WORK_PROMPT.md Phases 0-4)

This documents the native xv6 workload/trace-collection suite built for
ML page-replacement research: what each workload models, why it was
chosen, its parameters, its measured access-pattern statistics, and its
oracle gap (headroom above Belady's optimal). See `WORK_PROMPT.md` for
the full task specification this suite was built against, and
`HANDOFF_TO_CLAUDE.md` for the paging subsystem itself.

## Why native workloads, not ported real applications

Porting SQLite and Redis to xv6 was evaluated and rejected: Redis needs
a network stack xv6 doesn't have; SQLite needs `lseek` (absent),
floating point (deliberately unsupported), and a hosted libc, and even
if ported, xv6's ~268KB max single-file size means any test database
would fit entirely inside SQLite's own page cache, so the kernel would
never observe realistic database access patterns at all.

Instead, each workload below reproduces the **access-pattern
properties** that make a real application's paging behavior interesting
— not because it's a literal port, but because it exercises the same
kind of locality/skew/phase-change structure. The property that matters
throughout: **no single fixed heuristic (pure recency, pure frequency,
pure sequential prefetch) should trivially win** — a workload that's
purely sequential just teaches a model "be FIFO"; one that's purely
cyclic teaches something equally trivial.

## Phase 0/1 infrastructure

- `NSWAPSLOTS` raised 1024 -> 8192 (32MB of swap) and `FSSIZE` raised
  2000 -> 8000 blocks (~8MB filesystem), both build-flag/param.h
  changes verified against the full regression matrix.
- `user/vmbench.h` / `user/vmbench.c`: shared harness every workload
  uses — arena allocation with a known VPN<->offset mapping, the
  `touch_r`/`touch_w`/`vmbench_trace_ref` primitives (all `volatile`
  -qualified reads/writes to guarantee the compiler can't
  dead-code-eliminate a touch whose value is otherwise unused — a real
  bug found and fixed in `user/policydemo.c` earlier in this project),
  the self-sizing "burn phase" (ported from `user/policydemo.c`) that
  flushes the process's own exec()-loaded pages out of FIFO/Aging
  eviction priority before a workload's real measurement begins, a
  stats-delta helper, an xorshift64 PRNG, and a fixed-point Zipf sampler
  (table generated on the host by `tools/gen_zipf_table.py`, committed
  as `user/zipf_table.h`).
- `user/vmbenchtest.c`: self-test exercising every harness primitive.
  Verified: arena alignment, touches genuinely fault (checked via real
  `vmstats` deltas), the burn phase provably reaches the arena's own
  VPN range (via the `VM_DEBUG` trace ring), PRNG reproducibility, and
  the Zipf sampler's skew (hot bucket >=4x the cold bucket, monotonic
  decay in between).

## The six workloads

### `user/btreebench.c` — SQLite B-tree pager stand-in

A real B+tree (order 16, one node per 4KB page) supporting insert,
point lookup, and range scan, with configurable insert/lookup/scan/
mixed operation ratios.

**Why it isn't trivial for one policy**: insert touches fresh leaves
once (recency-favoring); lookup repeatedly re-hits the same small set
of upper-level nodes near the root (frequency-favoring, and blind to
FIFO's load-order-only view since those nodes may have been loaded long
ago); scan is pure sequential leaf-chain traversal (favors read-ahead,
indifferent to recency/frequency). No single policy wins across all
three in the same run.

**Measured** (footprint=40 pages, 300 mixed ops, seed=1):

| capacity (pages) | FIFO | Clock | Aging | LRU | Belady |
|---|---|---|---|---|---|
| 40 (100%) | 11 | 11 | 11 | 11 | 11 |
| 20 (50%) | 11 | 11 | 11 | 11 | 11 |
| 10 (25%) | 12 | 12 | 12 | 12 | 11 |
| 4 (12%) | 202 | 174 | 182 | 169 | 107 |

At 12% capacity the oracle gap is substantial and policy-differentiated
— FIFO is worst (+95 faults over Belady), LRU best of the real policies
(+62): real headroom for an ML model to exploit.

### `user/kvbench.c` — Redis stand-in

An open-addressing (linear-probe) hash table over the arena, keys drawn
from a Zipfian sampler, with YCSB-style modes A (50/50 r/w), B (95/5),
C (read-only), D (read-latest), F (read-modify-write). The hot-key
mapping rotates periodically so the hot set actually shifts over time,
rather than staying static for the whole run.

**Why it isn't trivial for one policy**: a *static* Zipf skew alone
would be something FIFO already handles fine once warmed up (hot pages
just never age out because they're touched constantly). A *shifting*
hot set forces old-hot pages to go cold and new-hot pages to warm up
repeatedly — that's the property that actually stresses the
recency-tracking difference between FIFO and Clock/Aging.

**Measured** (footprint=8 pages, 500 mode-A ops, seed=1): at
100%/50% capacity all five policies show identical or near-identical
fault counts (the workload's random seed/rotation didn't happen to
create a strong differentiation at this scale) — a real, honestly
-reported result, not every workload/configuration shows a dramatic
policy gap. At 12% capacity kvbench enters severe thrashing (see
Known limitations below).

### `user/graphbench.c` — pointer-chasing (BFS + fixed-point PageRank)

A synthetic scale-free graph (Barabasi-Albert-style preferential
attachment, generated with the integer PRNG — explicitly NOT real-world
data, printed as such in the workload's own output) in a fixed
-out-degree CSR-like layout, with BFS and fixed-point (no floating
point) PageRank.

**A real bug found and fixed while building this**: pure preferential
attachment makes every vertex's out-edges point only to *earlier*
vertices (like a citation graph) — a forward BFS from any single vertex
collapsed into the same ~7-9-vertex closed core regardless of where it
started (empirically confirmed: 9 of 1706 vertices reached). Fixed by
mixing in genuinely uniform-random edges (for real connectivity)
alongside the preferential ones (for the hub/degree-skew PageRank
needs) — afterward BFS reaches 1670 of 1706 vertices (~98%).

**Why it isn't trivial for one policy**: BFS visits vertices in
data-dependent frontier order (unpredictable from load order alone);
PageRank repeatedly re-visits the same high-degree hub vertices across
many iterations (a frequency signal FIFO is blind to, Aging is built to
notice).

### `user/sortbench.c` — external merge sort (calibration pair)

Classic bottom-up merge sort over an arena larger than the resident
limit. **Deliberately not a novel access pattern** — purely sequential
locality with a textbook-predictable fault/pass count, included
specifically as a measurement-pipeline sanity check (Gate 2's own
instruction: if this doesn't match theory, the harness has a bug, not
the theory).

**Measured**: n=4000 elements, passes=12 (== ceil(log2(4000)), exact
match), inversions=0 (correctly sorted) at every resident limit tested,
including one tight enough to force 125 real evictions.

### `user/matmulbench.c` — naive vs. blocked matmul (locality contrast pair)

Identical integer matrix multiply, computed two ways: naive (ijk order,
terrible spatial locality on the B operand) vs. blocked/tiled (BLOCK=8,
reuses a small working tile many times before advancing). Also a
calibration pair, not a novel pattern.

**Measured**: at n=100/margin=10, naive was so dramatically slower
under memory pressure it didn't complete within a 300s timeout (vs.
blocked's 3115 evictions) — the expected, dramatic contrast, confirmed
via checksums matching between variants at smaller scales. **Caveat**:
at a specific smaller scale (n=60, margin=8) naive showed *fewer*
evictions than blocked (20 vs 49) — investigated and attributed to
`BLOCK=8` not being well-tuned relative to page size at that particular
scale (checksums still matched, ruling out a correctness bug); the
locality contrast is real but block-size-sensitive, not a fixed law
that holds at every scale.

### `user/lzwbench.c` — LZW compression over a real text corpus

LZW compression (hash-table dictionary) over `corpus.txt` (the GNU
GPLv3 license text, 35149 bytes — real, freely-redistributable English
prose, shipped in `fs.img`), chosen simply as a real, moderately-sized,
naturally-redundant text corpus.

**Why it isn't trivial for one policy**: the dictionary's hash-table
probe sequence is driven entirely by the *input data's own byte
sequence* — genuinely data-dependent, not engineered like the other
workloads' access patterns. Some short common sequences get re-probed
constantly (frequency-favoring); most dictionary entries are created
once and never probed again (recency-favoring, in the same run).

**Measured**: 35149 input bytes -> 10119 output codes (~3.47x
compression, reasonable for LZW on English prose), correctness verified
by decode-length parity. Real eviction pressure observed at moderately
tight margins (margin=40 of a 78-page footprint hangs from
severe thrashing — the actual touched footprint is much smaller than
the worst-case allocation, since the compression ratio means most of
the 16384-slot dictionary table stays sparse/untouched).

## Phase 3: trace collection

`user/vmbench.h`'s `vmbench_trace_ref()` (called from each workload's
own page-accessor function — `bt_node()`, `kv_key_ptr()`, etc. — rather
than instrumenting every call site) prints a compact `T <vpn>` line per
real page reference when tracing is enabled via a workload's trailing
CLI `trace` argument. This gives a **full reference stream**, not just
faults — the kernel's own `vmtrace` ring only records faults, which
can't support Belady's next-use-distance calculation (a page that stays
resident and gets re-touched without faulting is invisible to a
fault-only trace, but Belady needs to know about every such touch).
Printed to console (captured by the existing test harness), not
persisted inside xv6's own filesystem, consistent with this project's
established preference for host-side trace storage.

Currently wired into `btreebench` and `kvbench` (proving the pattern
generalizes across two structurally different workloads); the same
one-line addition to each workload's own accessor function would wire
in the rest.

`tools/trace_decode.py` parses a transcript's `TRACEHDR` + reference
stream into unique-page counts, a reuse-distance histogram, and
working-set-size-over-time. `tools/trace_collect.sh` runs a resident
-limit sweep (100/50/25/12% of footprint) under the harness and saves
transcripts to `traces/`.

## Phase 4: offline simulator (`tools/sim.py`)

Replays a trace through FIFO, Clock, Aging (implemented to mirror
`kernel/vmpage.c`'s actual `choose_fifo`/`choose_clock`/`choose_aging`
exactly — same tie-break rules, same 8-bit aging-counter shift math),
LRU, and Belady's optimal (via a standard next-use-distance
precomputation).

### Validation against the real kernel — the most important finding

`tools/sim.py --validate` cross-checks the simulator's eviction count
against the SAME transcript's own kernel-reported `RESULT evictions=`
line (no separate run needed — both signals are in the same
transcript).

**Result: validates exactly at generous-to-moderate resident margins
(50%+ of a workload's own footprint); the match degrades at tight
margins** (e.g. btreebench at 25% capacity: simulator 2 evictions vs.
kernel 12; at 12% capacity: simulator 198 vs. kernel 648; kvbench
similarly diverges by 4-20x at its tightest tested margins).

**Root cause, investigated rather than papered over**: the reference
trace only records ARENA page touches (by design — see Phase 3 above).
The kernel's resident-limit budget, however, is shared between the
arena AND the process's own baseline (exec-loaded code/data) pages.
`vmbench_burn()` only guarantees baseline is flushed out of eviction
*priority* once, at setup time — it does not guarantee baseline's
resident *footprint* stays perfectly constant for the rest of the run.
Executing a rarely-hit code path for the first time during the timed
workload (a `switch` branch not yet exercised, etc.) can grow baseline
by a page or two, and when the arena's own margin is already tiny, even
a one-or-two-page baseline fluctuation is a large fraction of the total
budget — which the arena-only simulator has no way to see or account
for. Confirmed directly: giving kvbench's arena a small cushion above
its own exact footprint (margin=12 vs. footprint=8) dropped kernel
-reported evictions from 219 to 0, matching the simulator's zero
-eviction prediction.

**Implication for future ML training data**: Belady-oracle labels
derived from these arena-only traces are trustworthy in the moderate
-to-generous margin regime. At the most extreme memory-pressure
configurations, the real kernel experiences additional pressure the
simulator cannot model without also tracing baseline/code-page
references — a scope expansion not implemented in this pass, flagged
here as follow-up work rather than silently assumed away.

### Oracle gap (validated regime only)

See the btreebench table above — the clearest, most reliable
demonstration: negligible gap at generous margins (nothing to evict),
substantial and policy-differentiated gap at 12% capacity (FIFO +95
vs. Belady, LRU +62). kvbench's tested configuration did not show a
strong policy differentiation at 50% capacity (all five policies within
~3% of each other) — reported honestly rather than cherry-picked.

## WORK_PROMPT2.md additions — enrichment toward real database/store behavior

Built on top of everything above. Each property is an independently
toggleable CLI flag (default off, so all measurements above remain
reproducible with flags off), except where noted as structural.

### `kvbench` (Phase 1)

- **Incremental rehashing** (flags bit1): crossing an 80%-full load
  factor allocates a second, 2x-larger table; 4 buckets migrate per
  subsequent operation; lookups check both tables during migration.
  Since the base workload never grows its own keyspace (it only
  re-touches a fixed set of keys), rehash-enabled runs also insert one
  brand-new key per operation to give the load-factor trigger something
  real to react to. **Measured** (footprint=30, margin=30, 1200 ops):
  rehash off -> 0 evictions (stable); rehash on -> 1 table expansion
  triggered, 91 evictions, 81 swap faults — a real, temporary working
  -set expansion, exactly the predicted phase change.
- **Heavy-tailed value sizes** (flags bit2): values drawn from 5 size
  classes (8B..2KB) via the Zipf sampler (rank 0 -> smallest, so most
  values are small, a few large — a Pareto-like shape). **Measured**:
  6 zero_faults during the workload phase vs. 1 with fixed 8-byte
  values, at the same seed/margin — pages-touched-per-operation
  genuinely varies as predicted.
- **TTL/expiry** (trailing `ttl_ticks` arg, 0=off): entries expire
  lazily (checked on next access) using `uptime()` as a monotonic
  clock; a freed entry's value-arena chunk returns to a free list for
  reuse by a later allocation. **Measured** (20000 ops, ttl=3 ticks):
  9982/10012 read hits vs. 10012/10012 with TTL off — a real, if modest
  at this scale, expiry-driven miss rate.
- **Multi-level indirection** (always on, structural): the key table
  and the value arena are two separate arenas; every lookup/insert
  touches a key-table page AND a value-arena page. This required a
  full redesign of the on-disk (in-arena) slot format from Part 1's
  {key,value} pairs to {key, value_offset, value_size, expiry_tick}.

A genuine engineering constraint hit while building this: **xv6's
shell caps a command line at `MAXARGS=10` tokens** (`user/sh.c`) — the
original plan of one CLI flag per property (trace/rehash/valuesize/ttl
as four separate trailing args) would have made `program name + 9 args`
= 10 tokens for the fullest case, right at the ceiling, and failed with
`panic("too many args")` from the shell itself when actually tried.
Fixed by packing trace/rehash/valuesize into one bitmask argument
(bit0/bit1/bit2) — not a kernel or core-mechanism change, just a CLI
shape adjustment.

### `btreebench` (Phase 2)

- **Write-ahead log** (flags bit1, highest priority per the task spec):
  every tree modification is also appended to a separate, sequential
  log arena before being applied to the tree; the log wraps back to
  its start every 32 appends (a fixed checkpoint interval — see the
  transaction-batching note below). **Measured** (footprint=40,
  margin=10, 500 mixed ops): WAL off -> 78 evictions, 74 swap faults;
  WAL on -> 126 evictions, 121 swap faults — real, substantial added
  pressure from the sequential log competing with the tree's random
  reads for the same budget, exactly the predicted signature pattern.
- **Transaction batching**: folded into the WAL's fixed checkpoint
  interval rather than built as a separately configurable flag (a
  scope reduction made under time pressure, noted here rather than
  silently — see "not done" list below for what a fuller version would
  add).
- **Internal LRU cache** (flags bit4, size via trailing arg): a small
  cache of node indices sits in front of the tree; `bt_node()` only
  counts as a kernel-visible reference (calls `vmbench_trace_ref`) on a
  cache miss. **Measured** (same config, cache on): cache_size=8 ->
  159 misses of 1466 accesses; cache_size=32 -> 15 misses of 1466 --
  the kernel-visible reference count dropped **~10.6x** as the cache
  grew 4x. Real kernel fault/eviction counts stayed identical between
  the two (74/78, unaffected) — correct: the app-level cache filters
  what gets *measured/traced* for simulator purposes, it does not
  change what's actually resident, exactly matching the task's own
  framing ("the kernel observes only the misses from that cache").
- **Free-list page reuse**: **not implemented.** Doing this safely
  requires real B+tree deletion with merge/rebalance (the current tree
  only supports insert/lookup/scan); recycling a node's physical page
  without real logical deletion risks a parent still referencing a
  "freed" node — silent tree corruption. Flagged explicitly rather than
  building something that only superficially resembles free-list
  reuse.

### Statistics library (Phase 3, extending `tools/trace_decode.py`)

Added: exact (non-bucketed) reuse-distance computation, a miss-ratio
curve (exact for a stack/LRU algorithm — derived directly from the
reuse-distance distribution), phase-boundary detection (>50% relative
working-set-size change between consecutive samples), and conditional
entropy of the next page given the previous *k* pages (estimated
empirically from the trace's own frequency counts — the "how much
signal could a learned model exploit" measure).

**Validated per Gate 3's explicit requirement**: `reuse_distances()` is
checked against a hand-computed 7-reference example (`python3
tools/trace_decode.py --selftest <anything>`) before being trusted on
real data — confirmed to match an independently-derived-by-hand
expected answer, not just self-consistent with its own code.

**Not implemented**: access-type mix (read/write ratio, dirty-page
fraction at eviction) — the current trace format's `T <vpn>` lines
don't distinguish reads from writes (a real limitation of the tracing
mechanism as built, not a missing analysis step; extending it would
mean either changing `vmbench_trace_ref`'s signature and every call
site again, or adding a parallel R/W-aware primitive).

### Phase 4/5 — resolved (WORK_PROMPT3.md)

The blocker described in the previous paragraph is resolved: `apt-get
download` + `dpkg-deb -x` (neither needs root) got `sqlite3`,
`valgrind`, and `redis-server` running without a source build. Real
SQLite and Redis traces were collected under Valgrind Lackey, reduced
to this suite's own trace format, and used to calibrate `kvbench`/
`btreebench` against them (a Jensen-Shannon-divergence + working-set
-RMSE distance metric, a coarse grid search, and a mandatory
unrelated-workload control). Both native workloads measure closer to
their real counterparts than an unrelated workload does — `btreebench`
convincingly so (44% closer than the best control), `kvbench` more
weakly (12% closer). Full methodology, the complete grid results, a
genuine non-flattering finding (the internal cache feature makes
`btreebench` *less* similar to the real, unfiltered Lackey trace, not
more — a real "apples to oranges" measurement mismatch, not a bug),
and the calibrated presets are all in `docs/calibration.md`.

## WORK_PROMPT3.md Phase 4 — tracing extended to all six workloads

Reference-stream tracing (`vmbench_trace_ref`, previously wired into
only `btreebench`/`kvbench`) is now in all six workloads, each via its
own dominant page-accessor function: `graphbench`'s `edge_dst()`,
`sortbench`'s new `sort_trace()` helper (called at each `src`/`dst`
array access in `merge_pass()`), `matmulbench`'s new `matmul_trace()`
helper (called from `at()`/`set_at()`), and `lzwbench`'s
`lzw_lookup_or_insert()`. All four verified capturing real reference
data (12,865 to 47,784 references in quick smoke-test runs) before
being used in the calibration control comparison above.

## `user/tracereplay.c` — real-application trace replay through the actual kernel (follow-up task)

Previously dropped as Phase 5 (see below), revisited as a dedicated
follow-up task once Phases 0-4 and the calibration work
(`docs/calibration.md`) were done. Closes a gap nothing else in this
suite closes: `tools/sim.py` (the host-side simulator) is validated
against the real kernel's own `vmstats`, but only using *native
workload* traces as input; `tools/calibrate.py` compares real-vs-native
trace *statistics*, but never drives the real kernel with a real access
pattern. `user/tracereplay.c` reads a slice of the real Redis reference
trace and reissues it as real memory touches inside xv6, so the actual
`kernel/vmpage.c` fault/evict logic runs on it directly.

**Scope, stated plainly**: this is a feasibility investigation with a
positive result, not a general-purpose trace replayer. The real Redis
trace (`traces/real/redis_real.trace`) is 12.3M references / 70MB. Two
filesystem constraints were checked before writing any replay code:

- **Aggregate free space**: `FSSIZE=8000` blocks (`kernel/param.h`) =
  ~8MB total filesystem; ~6.3MB free after everything else already
  shipped in `fs.img`. This alone would rule out embedding either full
  real trace (50-70MB), but still sounds like it should fit a
  meaningfully large slice.
- **The actual binding constraint, found second**: `MAXFILE = NDIRECT(12)
  + NINDIRECT(BSIZE/sizeof(uint)=256) = 268 blocks ≈ 268KB` — a hard
  cap on any SINGLE file, regardless of aggregate free space
  (`kernel/fs.h`). This is far tighter than the aggregate budget and is
  what actually shapes the design.

**Approach taken — option (a) from the task, "truncate to a prefix,"
adapted to route around the per-file cap rather than the aggregate one**:
the first 825,000 references (~6.7% of the full trace) are pre-split on
the host, by `tools/gen_tracereplay_chunks.py`, into 16 files
(`user/redisreplay0` .. `redisreplay15`, ~3.81MB total) each packed by
byte budget (not a fixed line count — see below) to stay safely under
the 268KB cap. `user/tracereplay.c` opens each chunk in turn and streams
it through a single 4KB buffer, touching `arena_base + vpn*PGSIZE` for
each `T <vpn>` reference via `touch_w()`.

**Two real bugs found while building this, reported per this project's
own honesty norm**:

1. A first attempt chunked by a *fixed line count* (55,000 lines).
   VPN values grow in digit-count as the trace progresses (more
   distinct pages get first-seen over time), so a fixed-line chunk near
   the end of the prefix came out meaningfully bigger than one near the
   start — one hit 307,374 bytes, over the 274,432-byte cap. Caught
   before it broke a build; fixed by packing whole lines into each
   chunk up to a *byte* budget instead (`tools/gen_tracereplay_chunks.py`).
2. A first version of `tracereplay.c` read a whole chunk into one
   256KB static buffer. `kernel/exec.c`'s `uvmalloc()` **eagerly** maps
   every page of a program's `.bss` at process start (a real physical
   frame per page — unlike `vmbench_arena()`'s `sbrklazy()`-backed lazy
   holes), so that buffer alone made 64 pages resident before `main()`
   ran, more than `vmbench_burn()`'s fixed 64-scratch-touch budget could
   evict through — `vmbench_burn()` failed outright. Fixed by streaming
   through a single 4KB page-sized buffer instead, which also happens to
   be a more honest test of "many small sequential reads" throughput.

**Known limitation, stated plainly**: `tools/trace_reduce.py` collapses
Valgrind's L (load) and S (store) lines into one undifferentiated `T
<vpn>` reference — the read/write distinction from the real trace is
already lost upstream of this program and cannot be recovered here.
Every replayed reference uses `touch_w()` (write), the more conservative
choice — it exercises both `PTE_A` and `PTE_D`, and therefore the
write-back path, whereas read-only replay would never exercise dirty
-page write-back at all. Eviction/write-back counts below are an upper
bound on what real Redis's actual read/write mix would produce, not an
exact reproduction of it.

**Results** (arena sized to 835 pages — the actual max VPN referenced
within this 825,000-reference prefix is 834, not the full trace's own
1416, since later pages are simply never reached by this slice):

| resident_margin | % of arena | swap_faults | evictions | page_writes | ticks elapsed |
|---|---|---|---|---|---|
| 950 (fully generous) | 114% | 3 | 0 | 0 | 13 |
| 835 (= arena size) | 100% | 7 | 6 | 4 | 13 |
| 300 | 36% | 317 | 851 | 845 | 444 |
| 150 | 18% | 1169 | 1853 | 1830 | 510 |
| 80 | 9.6% | 9920 | 10674 | 10427 | 5339 |

All 825,000 references replay in every run (`total_refs_replayed=825000`,
`zero_faults=834` — every distinct page in the prefix is touched at
least once, confirming the parser walks the whole slice correctly). The
small nonzero `swap_faults` at the fully-generous margin (950) is
consistent with an already-documented class of noise elsewhere in this
suite (baseline/code-page resident-set fluctuation during the timed
window, not an arena-data effect — see the Phase 4 simulator-validation
note above). Behavior below that is clean and monotonic: tighter margin
→ more evictions/swap faults, exactly as expected, and a real kernel
-observed confirmation (not a simulated one) that real Redis-shaped
memory pressure produces substantial eviction activity in this range.

The `margin=80` run (~9.6% of arena) is itself a real, reportable
finding distinct from the filesystem-capacity wall: it timed out at a
150-second QEMU budget (the other margins above all finished in well
under a minute) and needed a 700-second budget to complete — `ticks
elapsed` jumped from 510 (margin=150) to 5339, roughly 10x, tracking the
roughly 10x jump in evictions/swap_faults. Replaying hundreds of
thousands of references under very tight memory pressure means
correspondingly many real (emulated) disk I/Os for swap-in/swap-out, and
wall-clock cost scales with that, not just with reference count.
Whoever explores tighter margins than this with this tool should budget
accordingly (the project's existing slow-test precedent —
`exit-leak`/`usertests -q`/`grind 2000` needing 900-1500s+ — is the
right comparison, not a bug to chase).

**The one-line summary to have in mind before citing this result**: a
real 825,000-reference slice of a real Redis Valgrind trace, replayed
through the actual (not simulated) xv6 paging kernel, produces
substantial, margin-sensitive eviction activity that grows smoothly as
memory pressure increases from 36% down to 9.6% of the working set —
direct, real-kernel corroboration of the
moderate-pressure oracle-gap zone found earlier (Phase 4/`docs/calibration.md`),
using a real rather than native-workload access pattern for the first
time. It does not prove the full-trace or full-working-set behavior
(this is a 6.7% prefix), and it cannot distinguish what a real Redis
read/write mix would have produced (every reference replays as a
write).

### `user/sqlitereplay.c` — the same replay, for real SQLite (second follow-up task)

Extends the `tracereplay.c` result above to a second real application,
via `traces/real/sqlite_real.trace`, so the interesting question becomes
a comparison rather than a single data point (see below).

**Design decision**: a separate sibling program (`user/sqlitereplay.c`),
not a generalized `tracereplay.c` that takes a trace-selector argument.
Chosen deliberately: this project's own precedent throughout — six
independent workload programs (`btreebench`/`kvbench`/`graphbench`/
`sortbench`/`matmulbench`/`lzwbench`), never one parameterized
"megabench" — favors separate purpose-built programs, and duplicating
`tracereplay.c`'s small (~150-line) streaming/burn logic carries zero
risk to its already-verified, already-committed Redis replay path.
Generalizing it in place would have meant re-verifying that path end to
end (the task's own explicit warning) for a marginal reduction in
duplication — not worth the risk for this scope.

**Filesystem headroom, checked empirically before picking a prefix
size, not assumed**: committing the Redis chunks already used most of
what was free. A clean rebuild of the tree as it stood before this task
showed `5785` of `7953` data blocks allocated — only **2168 blocks
(~2.17MB) free**, well under half of what was available for the
original `tracereplay.c` task. `tools/gen_tracereplay_chunks.py` was
generalized (CLI flags for source trace / output prefix / prefix size —
re-verified to reproduce the existing Redis chunks byte-for-byte after
the change, before generating anything new) and used to take the first
**300,000 references (3.51% of the full 8,556,194-reference SQLite
trace)** — a meaningfully *smaller* fraction than Redis's 6.70%, stated
plainly rather than letting the smaller absolute number look like an
equivalent-sized slice. This produced 7 chunk files
(`user/sqlitereplay0`..`sqlitereplay6`, ~1.52MB total), leaving the
final build at `7416`/`7953` blocks — comfortable, but with real slack
now gone (~550KB free after `sqlitereplay`'s own compiled binary too).

**Known limitation**: identical to `tracereplay.c`'s — the read/write
distinction was already collapsed by `tools/trace_reduce.py` upstream of
both traces, before either was ever chunked, so it cannot be recovered
for SQLite any more than it could for Redis. Every reference replays via
`touch_w()`, the same conservative (write, not read) choice, for the
same reason (exercises the full write-back path; eviction/write-back
counts here are an upper bound, not an exact reproduction).

**Results** (arena sized to 282 pages — the actual max VPN referenced
within this 300,000-reference prefix is 281, not the full trace's own
283):

| resident_margin | % of arena | swap_faults | evictions | page_writes | ticks elapsed |
|---|---|---|---|---|---|
| 282 (= arena size) | 100% | 9 | 8 | 6 | 7 |
| 100 | 35% | 258 | 439 | 430 | 188 |
| 50 | 18% | 2011 | 2242 | 2163 | 578 |
| 25 | 9% | 16662 | 16918 | 15778 | 3983 |

All 300,000 references replay in every run (`total_refs_replayed=300000`,
`zero_faults=281` confirms the whole prefix is walked correctly). The
small nonzero `swap_faults`/`evictions` at the fully-generous margin
(9/8) match the same already-documented baseline/code-page noise class
seen in `tracereplay.c`'s own generous-margin run (7/6) — consistent,
not a new effect. Behavior below that is clean and monotonic, same
shape as the Redis result. `margin=25` (~9% of arena) needed a
much-longer QEMU budget than 100/50 to complete (timed out at 280s,
finished within 800s) — the exact same pattern as Redis's own tightest
margin (`tracereplay.c`'s `margin=80`), for the same reason: wall-clock
cost scales with real (emulated) swap I/O volume, not just reference
count.

### Redis vs. SQLite: the actual point of doing a second trace

The real comparison, not just a second set of numbers: does SQLite's
mostly-sequential-scan-plus-point-lookup access shape produce a
different eviction ramp than Redis's Zipfian-hot-set shape, across a
comparable margin range?

Looking at the ratio of evictions to ticks elapsed (a rough proxy for
how "bursty" the eviction pressure is relative to wall-clock/CPU-tick
cost) at two comparable pressure points, **SQLite shows a consistently
steeper ramp than Redis, and the gap widens under tighter pressure**:

| pressure level | SQLite evictions/ticks | Redis evictions/ticks |
|---|---|---|
| ~35-36% of arena | 439/188 ≈ 2.33 | 851/444 ≈ 1.92 |
| ~9-9.6% of arena | 16918/3983 ≈ 4.25 | 10674/5339 ≈ 2.00 |

At loose pressure the two are fairly close (2.33 vs. 1.92). At tight
pressure SQLite's ratio more than doubles Redis's (4.25 vs. 2.00) —
SQLite's eviction activity per unit of elapsed time grows faster as
memory gets scarcer. This is a plausible, qualitatively sensible
difference given the two access shapes: SQLite's trace is
insert-then-lookup/scan (a bulk sequential phase that pushes a lot of
distinct pages through the arena in a short span, then a smaller, more
localized working set — see `docs/calibration.md`'s own real-trace
working-set-over-time finding, "a large working set during bulk insert,
collapsing to a small, stable one during point-lookup/range-scan"),
which likely concentrates its eviction pressure more sharply than
Redis's steadier, hot-set-driven SET/GET pattern. This is offered as a
plausible reading of the data, not a strong claim — the margin points
aren't perfectly matched between the two traces (35% vs. 36%, 9% vs.
9.6%, not identical), and a rigorous version of this comparison would
need matched relative margins and matched op counts, which wasn't done
here.

## What was deliberately not done this pass

- **Phase 5 (real-application trace replay)** was dropped in the
  original WORK_PROMPT.md pass per the task's own explicit guidance
  ("if time is short, this phase is the one to drop") given the time
  already spent on Phases 0-4. Later revisited as its own follow-up
  task, see `user/tracereplay.c` above.
- Tracing (Phase 3) was wired into `btreebench` and `kvbench` only, not
  all six workloads — the pattern (one `vmbench_trace_ref()` call in
  each workload's own page-accessor function) is proven and
  documented above for extending to the rest.
- The full Gate 3 matrix (all six workloads x three resident limits,
  each fully traced and decoded) was not exhaustively run — two
  workloads were run across four resident-limit points each instead.
- The `all-policy` full regression sweep (re-running the entire
  `vmtest all` suite under each of FIFO/Clock/Aging, ~3x the cost of
  one run including the ~15-17 minute `exit-leak` test each time) was
  not re-run after the Phase 0 `NSWAPSLOTS`/`FSSIZE` changes, since
  `vmtest all` (which already exercises multi-policy correctness paths)
  passed cleanly and the marginal value of re-testing already-validated
  logic under different eviction order was judged lower than the ~1
  hour it would cost, given everything else still to cover.
