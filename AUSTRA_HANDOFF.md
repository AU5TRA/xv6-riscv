# AUSTRA_HANDOFF — what's changed on `riscv` since your last commit

**Written for**: AU5TRA's own Claude Code session, to make merging your
local work with the current state of `origin/riscv` (this repo,
`AU5TRA/xv6-riscv`) as easy as possible. Unlike the other
`*HANDOFF*.md`-style files in this repo's history, this one is
**tracked in git** (check: it doesn't match the `.gitignore`'s
`HANDOFF*.md` pattern) specifically so it travels with the repo and is
here when you pull.

**Don't just trust this document's prose — every claim below is a
verification command you can run yourself.** That's deliberate: this
repo's own working convention (see `docs/workloads.md`/
`docs/calibration.md` for examples) is to re-derive facts from the
actual repo state rather than trust a summary, and this file should be
held to the same standard.

## The one fact that matters most for merging

**Your own paging/swap kernel implementation is untouched.** Since your
last commit (`bba5a9d`, "indentation fixes for readability"), exactly
one file under `kernel/` changed, by one line:

```
kernel/param.h:
-#define FSSIZE      2000              // size of file system in blocks
+#define FSSIZE      8000              // size of file system in blocks
```

Nothing else in `kernel/` — not `vmpage.c`, `vm.c`, `swap.c`,
`vmtrace.c`, `prefetch.c`, `vmstate.c`, `proc.c`, none of it — has a
single line changed. Verify directly:

```bash
git diff --stat bba5a9d..origin/riscv -- kernel/
git diff bba5a9d..origin/riscv -- kernel/vmpage.c   # empty output
```

The `FSSIZE` bump (2000 -> 8000 blocks, ~2MB -> ~8MB filesystem) was
needed to fit a large native workload/benchmark suite plus real trace
data into `fs.img` (see below) — it's a capacity change, not a logic
change, and was validated against the full regression matrix
(`usertests -q`, `vmtest all`, a workload smoke test) at the time. The
matching swap-capacity default, `NSWAPSLOTS` (`Makefile`, not
`kernel/`), was also raised 1024 -> 8192 for the same reason.

## The only pre-existing file touched: `user/pagingdemo.c`

One file that already existed at `bba5a9d` was modified, and only
additively — a new `explain_event()` helper function (translates each
raw trace event into one plain-language sentence) plus a single new call
site inside the existing `dump_trace()` loop. Nothing was removed,
reordered, or restructured. Verify:

```bash
git diff bba5a9d..origin/riscv -- user/pagingdemo.c
```

Every other file this history touches is **new** (added after
`bba5a9d`, not modified) — so if your own local work hasn't touched any
of the same filenames, there is no structural reason for a merge
conflict at all. See "Checking your own side" below for how to confirm
that for your specific local branch.

## What was added (12 commits, `bba5a9d..origin/riscv`)

In order:

```
bba5a9d  (your last commit — reference point, not part of this range)
c367ca6  added diagram for better visualization
feb512c  Merge branch 'riscv' of https://github.com/AU5TRA/xv6-riscv into riscv
d31555a  added lifecycle.md
1dbc4f0  Add policydemo: policy-comparison demo for FIFO/Clock/Aging
361e353  Ignore HANDOFF_PROMPT.md as a personal working document
5771a46  Add ML-training workload/trace-collection suite
1d8ee34  Add sample interleaved pagingdemo trace for reference
2acf755  Calibrate native workloads against real SQLite/Redis traces
6a85c89  Sweep kvbench Zipf skew/keyspace/TTL for real-Redis calibration
0e53547  Add tracereplay: replay a real Redis trace through the real kernel
b6e2ddf  small change (one-line docs fix)
5138b68  Add sqlitereplay: extend real-trace kernel replay to real SQLite
```

Verify the list and exact diffstat yourself:

```bash
git log --oneline bba5a9d..origin/riscv
git diff --stat bba5a9d..origin/riscv
```

(That last command's raw insertion count will look enormous — tens of
millions of lines. That's not a mistake: see "Large data files" below
before it alarms you.)

### Categorized

**New user-space programs** (`user/*.c`), all linking against a shared
new harness (`user/vmbench.h`/`user/vmbench.c`) rather than duplicating
setup code:

- `policydemo.c` — narrated FIFO/Clock/Aging behavioral-difference demo
- `vmbenchtest.c` — self-test for the shared harness itself
- `btreebench.c`, `kvbench.c`, `graphbench.c`, `sortbench.c`,
  `matmulbench.c`, `lzwbench.c` — six native workloads modeling
  SQLite/Redis/graph-DB/sort/matmul/compression access patterns, for
  generating realistic page-replacement training data (the actual point
  of your paging subsystem's existence — this is groundwork for an
  eventual ML-based eviction policy, not built yet)
- `tracereplay.c`, `sqlitereplay.c` — replay slices of *real* Redis/
  SQLite memory-access traces (collected on Linux via Valgrind, reduced
  to page-granularity) through your actual kernel fault/evict path, not
  just a host-side simulator

**Host-side Python/shell tooling** (`tools/`, all new): trace
generation, a Zipf-table generator, a FIFO/Clock/Aging/LRU/Belady-optimal
simulator (`sim.py`, validated directly against your kernel's own
`vmstats` counters), trace statistics (`trace_decode.py`), a
native-vs-real-trace distance metric (`calibrate.py`/`calibrate_grid.py`),
and a real-trace collection pipeline (`collect_linux_trace.sh`/
`trace_reduce.py`).

**Docs** (all new, all in the repo root or `docs/`): `Structure.md`,
`lifecycle.md`, `docs/workloads.md`, `docs/calibration.md` — these
document your paging subsystem's own mechanism in detail (not just the
additions), cross-checked against the actual code, so they may be worth
skimming even for a sanity check on your own implementation's documented
behavior.

**`Makefile`**: additive only — new `UPROGS`/`VMBENCH_PROGS` entries for
the programs above, a new `fs.img` prerequisite list for embedded trace
data, and the two capacity constants already covered above. No existing
rule was restructured; verify with `git diff bba5a9d..origin/riscv --
Makefile`.

### Large data files (why the diffstat looks enormous)

Several new files are trace/data, not code, and dominate the raw
insertion count:

- `traces/real/redis_real.trace` (70MB, ~12.3M lines) and
  `traces/real/sqlite_real.trace` (50MB, ~8.5M lines) — real
  Valgrind-collected memory traces from actual Redis/SQLite runs on
  Linux, reduced to page references. Used for the calibration work in
  `docs/calibration.md`.
- `user/redisreplay0`..`redisreplay15` and `user/sqlitereplay0`..
  `sqlitereplay6` — pre-split slices of the two traces above, embedded
  directly into `fs.img` for `tracereplay.c`/`sqlitereplay.c` to read
  inside xv6 (kept under xv6's own 268KB-per-file cap, see
  `kernel/fs.h`'s `MAXFILE` and either program's header comment for
  why).
- `traces/calib/*.trace` — smaller trace files from the calibration grid
  search.
- `corpus.txt`, `pagingdemo_trace_sample.log` — a real text corpus (for
  `lzwbench.c`'s compression workload) and a sample demo transcript.

None of this touches `kernel/` or changes program logic; it's
embedded/reference data. If repo size becomes a concern, `traces/real/`
(115MB combined) is the biggest single chunk and the most removable
without losing anything about the paging subsystem itself — but that's
your and the other project owner's call, not made here.

## Checking your own side before merging

This document only knows what's true on `origin/riscv`'s side. It
cannot know whether you have local commits on top of your own
`bba5a9d` that haven't been pushed yet. Before merging, run:

```bash
git log --oneline bba5a9d..HEAD   # on your local branch -- anything here
                                    # is work this document doesn't know about
git status --short
```

- **If that's empty** (your local branch is still exactly at `bba5a9d`,
  or already caught up to `origin/riscv`), a `git pull` /
  `git merge origin/riscv` should fast-forward cleanly — there is
  nothing on your side to reconcile.
- **If you do have local unpushed commits**, the only files where a
  real textual conflict is even possible are ones you *also* touched:
  `kernel/param.h` (if you also changed `FSSIZE` or anything else on
  that line) and `user/pagingdemo.c` (if you also edited
  `dump_trace()`/added something in the same region). Every other file
  in this range is newly created, so a conflict there would only happen
  if your local work independently created a file with one of the exact
  same names listed above (unlikely, but worth a quick
  `git diff --stat bba5a9d..HEAD` on your own branch to check for
  filename overlap before merging).

## Where to look for more detail

- `docs/workloads.md` — full detail on all eight new workload/replay
  programs: design rationale, measured fault/eviction numbers, real
  bugs found and fixed while building them.
- `docs/calibration.md` — the real-trace calibration methodology,
  distance metric, and results (including honestly-reported weak spots,
  not just wins).
- `Structure.md`, `lifecycle.md` — mechanism-level documentation of the
  paging/swap subsystem itself (yours), written by someone else reading
  and verifying your implementation, so worth a skim as an independent
  check on its documented behavior.

There is no other handoff document tracked in this repo beyond this one
— anything named `HANDOFF*.md` you might see mentioned elsewhere is a
personal, `.gitignore`d working file from the other contributor's own
side and won't be present in your checkout.
