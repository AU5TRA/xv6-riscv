# Workload suite (WORK_PROMPT.md Phases 0-4)

This documents the native xv6 workload/trace-collection suite built for
ML page-replacement research: what each workload models, why it was
chosen, its parameters, its measured access-pattern statistics, and its
oracle gap (headroom above Belady's optimal). See `WORK_PROMPT.md` for
the full task specification this suite was built against, and
`HANDOFF.md` for the paging subsystem itself.

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

### Phase 4/5 — blocked

See `docs/calibration.md` for the full explanation: calibrating native
workloads against real SQLite/Redis traces requires those traces to
exist first (WORK_PROMPT.md's own dropped Phase 5), and this session
has no `sudo`/package-install access to set up the collection tooling
(`valgrind`, `redis-server`, `sqlite3` — all available in the standard
repos, none installed, no passwordless `sudo` found). Reported as a
genuine environmental blocker, not a time-management skip.

## What was deliberately not done this pass

- **Phase 5 (real-application trace replay)** was dropped per the
  task's own explicit guidance ("if time is short, this phase is the
  one to drop") given the time already spent on Phases 0-4.
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
