# Handoff to GawwyG: eleven new benchmarks for the paging study

**Written for**: GawwyG, implementing the next set of benchmarks (from
AU5TRA, 2026-10-07). It assumes you can build xv6 and run the collection
scripts, but not that you followed this week's changes on the workload side.

**Status**: nothing below is implemented yet. This file is the plan: four
questions to settle first (section 2), what each workload should do, the
rules every benchmark in this tree must follow (each learned from a bug),
and every file a new workload has to be registered in.

**Read first**: `report/LZW_BENCHMARK.docx` (how a benchmark, its traces and
its checks fit together, end to end) and `AUSTRA_HANDOFF.md` (the ML side).

---

## 1. Why these workloads

The six current workloads are kvbench (Redis-like, Zipf keys), btreebench
(SQLite-like B-tree), graphbench (BFS + PageRank over CSR), sortbench
(external merge sort), matmulbench (naive vs blocked) and lzwbench
(`compress`'s LZW over six texts). They are realistic programs, but two
things are missing:

* **Controlled patterns with known answers.** No current workload isolates a
  single behaviour (a loop just larger than memory, a scan through a hot set,
  a skew you can turn up and down), so nothing shows *why* one policy beats
  another. The six synthetic patterns below do that, and several have a
  textbook answer the simulator and kernel can be checked against.
* **Some classic access shapes.** Serial pointer chasing, indirect
  `x[col[i]]` access, a hash join's build/probe split, Bloom-filter probing
  and allocator churn are each absent or only partly present.

| Group | Workload | Program / mode | Behaviour it tests |
|---|---|---|---|
| Patterns | Cyclic loop just larger than memory | `patbench loop` | LRU, FIFO and Clock miss every time; MRU and Belady barely miss |
| | Scan + hot set | `patbench scanhot` | Scan resistance: LRU and FIFO lose the hot set |
| | Zipf with a skew knob | `patbench zipf` | Results vs skew (θ = 0.6 → 1.2); LFU should be best online |
| | Uniform random (GUPS-style) | `patbench uniform` | "No free lunch": every online policy should tie |
| | Phase change | `patbench phase` | Adaptation: LFU sticks to the old hot set |
| | Frequency/recency switch | `patbench switch` | Whether a policy blends recency and frequency (ARC-style) |
| Applications | SpMV, CSR (NAS CG core) | `spmvbench` | Indirect `x[col[i]]` access |
| | Pointer chasing (SPEC mcf-like) | `chasebench` | Serial dependence, no stride |
| | Hash join | `joinbench` | Random hot structure + sequential scan |
| | Bloom filter | `bloombench` | k random probes per op over a fixed bit array |
| | malloc/free churn | `heapbench` | Allocator metadata walks, heap growth, fragmentation |

**Packaging.** The six patterns share all their machinery (one arena of P
pages, a seeded RNG, a sequence of page touches), so they belong in **one
program with a mode argument**, like kvbench's A–F. The five application
kernels are separate programs. That is six new programs, not eleven.

---

## 2. Open decisions: settle these before writing code

These change what gets measured, so they need an answer from both of us
(and the supervisor where it affects the thesis) before the work they touch
starts. None has been decided yet.

1. **Sweep sizes for `loop`.** The convention is 5–30% of pages touched,
   and the ML data set's capacity grid is the same (`CAPACITY_GRID` in
   `tools/stream_dataset.py`). The `loop` result only shows near 100%. Add
   high-percentage points for this workload only, or for all?
2. **MRU and ARC in the kernel**, or in the simulator only? Simulator-only
   is enough to show the patterns' known answers; kernel versions would let
   the in-kernel evaluation compare against them.
3. **SpMV vs PageRank.** graphbench's PageRank already performs an SpMV.
   Keep `spmvbench` (uniform and banded structures make it distinct) or drop
   it?
4. **How many seeds and which held-out variants** per workload. The current
   workloads use 5 seeds (kv, btree, lzw) or 3 (sort, graph).

---

## 3. Rules every new benchmark must follow

Each of these was a real bug in this tree. Breaking one produces traces that
look fine and are wrong.

1. **Trace every access to the arena, with the right access type.** Use
   `vmbench_trace_ref()` (or `touch_r`/`touch_w`) for every load and store to
   arena memory, `W` if the access modifies the page. Code, stack and globals
   are not traced, and that is fine; arena data that is not traced is not.
   *Why*: graphbench traced only its edge array and lzwbench only its hash
   table, so a replay of the trace could never reproduce the kernel's fault
   counts. Both had to be fixed and re-collected.
2. **Put all working data in one arena from `vmbench_arena()`.** No `malloc`,
   no large globals, no data on the stack. *Why*: anything outside the arena
   is untraced but still pages, so it silently distorts the kernel's counts.
3. **Touch only arena page 0 before `vmbench_burn()`; load or initialise the
   data after `VM_SET_LIMIT`.** The order is: allocate arena →
   `*(volatile int *)arena = 0` → `vmbench_burn()` →
   `vmctl(VM_SET_LIMIT, settled + margin)` → build/load the data (setup,
   untraced) → `vmbench_reset_and_snapshot()` → `vmbench_trace_start()` →
   workload → `vmbench_trace_stop()` → `RESULT` lines. *Why*: lzwbench loaded
   its input before the burn, the burn counted those pages as baseline, and
   a "5%" sweep run got 194–288 frames instead of ~20. The whole sweep was
   wasted (commit `7bd16bd`).
4. **Integer arithmetic only.** xv6 does not save floating-point registers,
   so user programs cannot use them. Anything needing real numbers (Zipf
   tables, matrix values) is precomputed on the host or done in fixed point.
5. **Deterministic, and every seed different.** The same arguments must give
   a byte-identical trace (each stream is collected twice to check), and
   different seeds must give different traces (`tools/check_streams.py`
   checks this). Use `vmbench_rng_seed()`/`vmbench_rng_next()`; never time,
   `uptime()` or addresses.
6. **Stay inside the size budget.** A trace must stay under 90% of xv6's
   maximum file size, about 60 MB, which is roughly 8–10 million references
   at 6–7 bytes per line. Aim for **1–6 million references** and **500–2000
   pages touched**, like the current workloads. Runs are slow under QEMU:
   about 10,000 references per second with tracing on, and about 1–2 ms
   per fault in a tight-memory sweep run (lzw-r30 at 5%: 4.1 million faults
   in 90 minutes).
7. **Footprint limits.** The kernel's resident limit cannot exceed 16,384
   pages (`VM_MAX_RESIDENT_LIMIT`), and the swap area has 8,192 slots in
   total (`NSWAPSLOTS`). Keep a workload's arena well under 8,000 pages.
8. **Use the standard argument order:**
   `<name>bench <footprint_pages> <resident_margin> <size/ops> <seed> <mode> [flags]`,
   with `flags` last (`9` = trace to file). `tools/ml2/kernel_eval.py`
   rewrites argument 2 (the margin) and the last argument (the flags) of
   every stream command. lzwbench breaks this order and needed a special case
   in `kernel_eval.py`; do not add more.
9. **Print `RESULT` lines for every parameter and a checksum** of the
   program's output (a sum of results, a match count), so a host-side model
   can be checked against the run.
10. **Write a host-side model.** A short Python re-implementation that
    predicts the exact reference count (and the checksum) for given
    arguments. It is the only way to prove a trace is the whole run; it
    found lzwbench's truncation and both tracing gaps.

Do **not** regenerate `user/zipf_table.h`. kvbench's traces depend on the
exact table. New tables get new names (see `patbench zipf`).

---

## 4. Naming

`tools/stream_dataset.py` parses stems with
`^(<workload>[a-z]+)-(<variant>[A-Za-z0-9]+)-s(<seed>\d+)$`, and several tools
take the folder name from the part before the first `-`. So:

* **workload names are lowercase letters only**: `pat`, `spmv`, `chase`,
  `join`, `bloom`, `heap`;
* **variant names are letters and digits only**, no `-` or `_`:
  `pat-loop`, `pat-zipf099`, `join-r4`, `chase-n64`;
* stream stems are `<workload>-<variant>-s<seed>`, sweep stems
  `<workload>-<variant>-p<percent>-c<frames>`.

---

## 5. Workload specifications

Sizes below are starting points; tune them so each stream lands in the
budget of rule 6, and record the final numbers in the manifest comments.
"Expected" lines are predictions to check, not results.

### 4.1 `patbench`: six synthetic patterns

One arena of P pages (default P = 1024). Each "access" touches one word on
one page: a read, or a read-modify-write (`W`) for a seeded fraction w of
accesses (default w = 0.1, so dirty-page handling is exercised). All page
choices come from the seeded RNG. Usage:

```
patbench <footprint_pages> <resident_margin> <accesses> <seed> <mode> [flags]
```

**`loop`: cyclic loop just larger than memory.** Visit a fixed sequence of L
pages (L ≤ P) in order, repeatedly. The seed permutes the order of the L
pages, so seeds differ while the pattern stays a pure loop.
* Variants: `loop` at L = P. The interesting memory sizes are just below L.
* Expected: with C < L frames, LRU, FIFO and Clock miss on every access once
  warm (L misses per pass). MRU and Belady miss only about L − C times per
  pass.
* Note: the standard sweep (5–30% of pages) is far below L, where everything
  thrashes. This workload also needs points at about 80, 90, 95 and 99% of L
  (see open decision 1).

**`scanhot`: scan through a hot set.** A hot set of H pages (default
H = P/16) is touched with probability h (default 0.5). Otherwise the next
page of a sequential scan over the remaining P − H pages is touched; the
scan wraps around.
* Variants: `scanhot` (h = 0.5), `scanhotlo` (h = 0.2).
* Expected: whenever more than C − H scan pages pass between two touches of
  a hot page, LRU and FIFO evict hot pages and fault on them again.
  Scan-resistant policies (LFU, Aging, ARC) keep the hot set; Belady does.

**`zipf`: Zipf with a skew knob.** Each access picks a rank from a Zipf
distribution with skew θ and maps it to a page through a seeded permutation
(so the hottest pages are scattered, not page 0..k).
* Variants: `zipf060`, `zipf080`, `zipf099`, `zipf120`.
* Implementation: extend `tools/gen_zipf_table.py` to take N and θ and emit
  a *named* table (`vmbench_zipf_cdf_099[]`), one header per θ under
  `user/`, with N = P ranks. Add a sampler that takes the table as an
  argument. Leave `vmbench_zipf_sample()` and `user/zipf_table.h`
  untouched.
* Expected: under independent references, keeping the C most popular pages
  is the best an online policy can do, so LFU should be the best online
  policy and a learned one should approach it. Belady's lead should shrink
  as θ rises.

**`uniform`: uniform random (GUPS-style).** Each access picks a page
uniformly from P; for w of them it is an update (`W`), as in GUPS.
* Variants: `uniform`.
* Expected: with references independent and uniform, every online policy
  has a miss rate of 1 − C/P (exactly, in the limit). FIFO, Clock, Aging,
  LFU, LRU and ML must all land there; Belady will be lower because it sees
  the future. This is the control: **if a learned policy beats Clock here,
  look for a bug or a leak of future information into its features.**

**`phase`: phase change.** A hot set of H pages, drawn at random from P, gets
fraction h of accesses (the rest uniform over P). Every K accesses the hot
set is redrawn.
* Variants: `phase` (K = accesses/8), `phaseshort` (K = accesses/32).
* Expected: LFU without decay keeps the old hot pages (their counts are
  high) and misses the new ones; LRU and Aging adapt within about one hot
  set's worth of accesses. A learned policy has to rely on recency features
  to adapt.

**`switch`: frequency/recency switch.** Alternate phases of length K:
`loop` over L pages (recency hurts), then `zipf099` over P pages
(frequency helps), and repeat.
* Variants: `switch` (K = accesses/8).
* Expected: no single classic policy is good in both phases; ARC is
  designed for this. Compare against ARC in the simulator (section 7).

### 4.2 `spmvbench`: sparse matrix × vector (CSR, NAS CG core)

Arrays in the arena: `row_ptr[n+1]`, `col[nnz]`, `val[nnz]` (int32),
`x[n]`, `y[n]`. Repeat for `iters`: `y[i] = Σ val[j] * x[col[j]]` over row
i's entries, then `x = f(y)` (an integer rescale, so the next iteration
reads new values; this mirrors CG's update). Trace `row_ptr`, `col`, `val`
and `y` (sequential) and every `x[col[j]]` (the irregular one).
* Matrix structure, seeded, built during setup:
  `random` (NAS CG-like: ~k non-zeros per row at uniform random columns),
  `banded` (non-zeros within ±b of the diagonal: the indirect access has
  locality).
* Variants: `spmv-rand`, `spmv-band`; size n so `x` alone spans a few
  hundred pages.
* Overlap: graphbench's PageRank is an SpMV over a scale-free graph. Keep
  the uniform and banded structures so this workload is distinct; do not
  add a power-law variant.

### 4.3 `chasebench`: pointer chasing (SPEC mcf-like)

Nodes of `node_bytes` bytes (holding a `next` index and a payload) placed in
the arena in a seeded random permutation, so consecutive nodes are on
unrelated pages. Every step reads the node it is on (`R`) to find the next;
a fraction of steps also updates the payload (`W`).
* Modes:
  * `list`: K linked lists; each traversal starts at a random list head and
    walks a random number of steps. (Walking the whole list every time
    would just be the cyclic loop in disguise.)
  * `tree`: a random tree with parent pointers; each operation picks a
    random node and walks to the root, as network-simplex code like mcf
    does. Nodes near the root become hot; leaves stay cold.
* Variants: `chase-list`, `chase-tree`, and `chase-n256` (bigger nodes,
  fewer per page).
* Expected: no stride to exploit; the tree mode has natural skew by depth.

### 4.4 `joinbench`: hash join

Relations R (build side, |R| tuples) and S (probe side, |S| tuples) as
arrays of (key, payload) in the arena; a hash table built from R
(open addressing, sized to stay under ~70% full; do not repeat lzwbench's
100%-full mistake); an output buffer.
* Build: scan R (`R`), insert each tuple (`W` on the table).
* Probe: scan S sequentially (`R`), probe the table for each key (`R`), and
  append matches to the output (`W`).
* Seeded keys: S's keys uniform over R's keys, or Zipf-skewed (a few hot
  buckets).
* Variants: `join-uni`, `join-zipf` (probe keys Zipf θ = 0.99), and
  `join-r4` (|S| = 4·|R|). The table should be a few hundred pages and S
  several times larger.
* Expected: the table is a random-access hot structure while S streams
  through once; scan-resistant policies should keep the table.

### 4.5 `bloombench`: Bloom filter

An m-bit array spanning a few hundred to ~1000 pages, k seeded hash
functions (integer multiply–xorshift mixers, in the style of
`vmbench_rng_next()`).
* Insert phase: n keys, setting k bits each (`W`).
* Query phase: q lookups, a seeded mix of present and absent keys, reading
  up to k bits each (`R`; stop at the first zero bit, as a real filter does).
* Variants: `bloom-k3`, `bloom-k7`.
* Expected: close to uniform random over the bit array (like `uniform`), but
  with k correlated probes per operation and a read-mostly mix. Plain
  hash-table probing is not added: kvbench and lzwbench already cover it.

### 4.6 `heapbench`: malloc/free churn

Use the benchmark's **own allocator inside the arena**, not xv6's `malloc`.
xv6's `umalloc.c` grows the heap with `sbrk` outside any arena and walks its
free list through untraced headers, which breaks rules 1 and 2.
* Copy the K&R free-list design of `user/umalloc.c` into heapbench, with
  every header read and write traced. "Growing the heap"
  moves a break pointer up within the pre-reserved arena; pages above the
  break are never touched.
* Operations (seeded): allocate a size from a mixed distribution (many small
  objects, a few large ones), write it (`W`), occasionally read live objects
  (`R`), and free random live objects so the heap fragments and free-list
  walks get longer.
* Variants: `heap-small` (16–256 bytes), `heap-mixed` (16 bytes to 16 KB),
  `heap-churn` (high free rate).
* Expected: the allocator's metadata (free-list headers scattered through
  the heap) is a hot, scattered structure under a growing data set.
* Overlap: kvbench's value allocator (size classes, used by `kv-Avsize`) is a
  different design; this one is a general-purpose free list.

---

## 6. Registering a new workload

Each item is a place that silently drops or breaks on an unknown workload.

| # | File | What to add |
|---|---|---|
| 1 | `Makefile` | `$U/_<name>bench` in `UPROGS`; any new data files (Zipf headers are headers, not fs files) |
| 2 | `tools/make_stream_manifest.py` | A `VARIANTS` row per variant: estimated seconds, seed list (5 or 3 seeds), command template with `{m}` margin and `{s}` seed. Then `python3 tools/make_stream_manifest.py > tools/streams_manifest.tsv` and check the diff only adds rows. |
| 3 | `tools/stream_dataset.py` | One held-out variant per workload in `HELD_OUT` (e.g. `pat-zipf120`, `join-r4`) |
| 4 | `tools/collect_v2.sh` | The workload name in the `case` list (with its run count) and in the default `WORKLOADS`; a block of six sweep runs at 5–30% of **pages touched** (measure them from the stream run, as lzw's 329/444 were); its own timeout if a run takes over 90 minutes |
| 5 | `tools/run_sweep_lanes.sh` | Lanes for the new stems in the default split; the workload name in the `WORKLOADS` list of the `ONLY` branch |
| 6 | `tools/make_summary.py` | An entry in `MODELS` **and** in the `order` list (an unknown family raises an error) |
| 7 | `tools/make_archive.py` | An entry in `GROUPS`; for several variants, one trace name per variant (see the `lzwbench` case). Without an entry the workload is silently left out of the archive. |
| 8 | `tools/check_streams.py` | Only if a variant's seed truly has no effect (then add it to the `matmul` exception). Rule 5 says it should have one. |
| 9 | `tools/ml2/` | The name in `WORKLOADS` (`models.py`, `analyze.py`) and `WL` (`figures.py`, `tables.py`) |
| 10 | `tools/sim.py` | Nothing per workload; but see section 7 for the two policies the patterns need |

---

## 7. Simulator additions

Two of the comparisons above need policies that exist nowhere in the tree.
The kernel has FIFO, Clock, Aging, LFU and ML (`kernel/vmpage.c`); the
simulator (`tools/sim.py`) has FIFO, Clock, Aging, LFU, LRU and Belady.

* **MRU** (evict the most recently used page): needed to show the `loop`
  result. A few lines in `tools/sim.py`.
* **ARC** (Megiddo & Modha, 2003): the reference for `switch` and `phase`.
  Implement it in `tools/sim.py` with its two lists and ghost lists, and test
  it on a hand-made trace before trusting it.

Adding either to the kernel is optional (open decision 2).

---

## 8. Checks before a workload's traces count

For each new workload, in this order:

1. **Model match.** For a small run, the host model predicts the exact
   reference count, write count and checksum.
2. **Complete.** Every collected trace has exactly the reference and byte
   counts in its run's `TRACEEND` line (the stream collector checks this;
   for a sweep, see the Completeness line of `make_summary.py`'s output).
3. **Deterministic.** Each pilot stream's `-rep` is byte-identical.
4. **Seeds differ.** `python3 tools/check_streams.py` passes.
5. **Kernel agreement.** On the sweep, a FIFO replay of the trace with a
   few always-resident untraced pages reproduces the kernel's evictions:
   `make_summary.py`'s FIT column within ±5% with 3–9 untraced frames, as for
   the other workloads. A worse fit means untraced arena data (rule 1) or a
   setup-order problem (rule 3).
6. **Known answers** (patterns only): the expectations in section 5.1 hold
   in the simulator, e.g. LRU misses every access on `loop` and all online
   policies tie on `uniform`.

Then run `python3 tools/stream_dataset.py prepare` (it only computes streams
it has not seen), regenerate `SUMMARY.txt` with `make_summary.py`, and
rebuild the archive with `make_archive.py`.

---

## 9. Suggested order

1. **MRU and ARC in `tools/sim.py`** (small; the patterns need them).
2. **`patbench`**, all six modes: one program, cheap runs, and its known
   answers validate the simulator and the kernel policies before anything
   else depends on them.
3. **`chasebench`** and **`joinbench`**: simple algorithms, clear new
   behaviour.
4. **`bloombench`**: small; mostly a variation on `uniform`.
5. **`spmvbench`**: needs the matrix generator and the integer `x` update.
6. **`heapbench`**: the most work (a traced allocator).

Collect streams per workload as each is finished, rather than all at the
end; the stream runner skips anything already marked `.ok`.
