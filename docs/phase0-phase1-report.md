# Phase 0 and Phase 1 — completion report

What was built, every failure hit along the way with its root cause and fix,
what those failures say about the platform, and what is still outstanding.

Companion to `docs/ceilings-and-trace.md`, which is the reference record of the
constants and interfaces. This file is the narrative and the analysis.

Reference configuration for every number below: CPUS=1, QEMU 8.2.2, 128 MiB,
`riscv64-unknown-elf-gcc` 13.2.0, `fs.img` on a 9p-mounted Windows drive under
WSL2. That last detail matters for the timings and nothing else.

---

## 1. Final status

Both phases are complete. Every gate item passes, in both the release and the
`VM_DEBUG` build.

### Phase 0 gate

| Gate item | Result |
|---|---|
| `vmtest swap-repeat` under tracing completes with `drops == 0` | 27,445 records, sequence 1..27445, 0 gaps, 0 drop markers |
| `trace-schema`, `trace-wrap`, `trace-disabled`, `trace-drop` pass | pass, plus two new tests: `trace-capacity`, `trace-lossless` |
| Decoder round-trips a 1M-event capture without loss or misalignment | pass; also detects a removed record and a mid-record truncation |
| Trace buffers remain non-pageable | `nm`: `804141f0 0000000000400040 b trace_ring` — 4 MiB, local `.bss` |

### Phase 1 gate

| Gate item | Result |
|---|---|
| `usertests -q` passes | ALL TESTS PASSED, 1380 s |
| `grind` passes | pass |
| A 5 MiB file writes, reads back byte-exact, deletes with no block leak | pass; host fsck: used == reachable, 0 leaked |
| `vmtest all` and `prefetchtest all` under FIFO, Clock and Aging | pass in release **and** `VM_DEBUG` |
| `vmcheck` clean after each | yes |

### What changed

Phase 0: ring 128 → 65536 records, read batch 8 → 256, record 152 B → 64 B
with `version`/`size` lifted out into a one-time header behind a new
`vmtrace_info()` syscall. New `user/vmdrain.c` (guest-side drainer),
`tools/decode_trace.py` (host decoder and validator), `tools/extract_file.py`
(pulls a capture out of `fs.img`).

Phase 1: `NSWAPSLOTS` 1024 → 8192 (32 MiB swap), `USERSTACK` 1 → 16 (64 KiB),
`FSSIZE` 2000 → 100000 (100 MiB), `NDIRECT` 12 → 11 plus a doubly-indirect
level giving `MAXFILE` 268 → 65803 blocks (64.26 MiB). `NBUF` left at 30 on
purpose. New `user/bigfiletest.c` (guest-side coverage) and
`tools/fsck_xv6.py` (host-side leak and consistency checker).

---

## 2. Failures, root causes, and fixes

Ten distinct failures. Only two were defects in the phases' own new code; the
rest were pre-existing assumptions that the new constants invalidated, plus
three self-inflicted tooling mistakes that are worth recording because they
cost real time.

### 2.1 `vmtest trace-capacity` — new command not wired into the dispatcher

**Symptom.** `vmctl(VM_TRACE_SET_CAPACITY, n)` returned -1 for every value.

**Cause.** The trace controls travel through two layers: the `vmctl` syscall
lands in `vmstate_ctl()` in `kernel/vmstate.c`, which forwards a whitelisted
set of commands to `vmtrace_control()` in `kernel/vmtrace.c`. I added the new
command to the second layer only, so the first layer rejected it as unknown.

**Fix.** Add `case VM_TRACE_SET_CAPACITY:` alongside the existing
`VM_TRACE_ENABLE` / `VM_TRACE_RESET` in `vmstate_ctl()`.

**Inference.** The control interface is not self-registering: every new `vmctl`
command needs an entry in `vmstate.c` *and* a handler. The failure was loud and
immediate, which is the right behaviour — `vmstate_ctl()`'s `default:` returns
-1 rather than silently ignoring. Worth remembering when Phase 7 adds the
learned policy's controls.

### 2.2 `vmtest trace-drop` — my assertion misread the kernel's overrun path

**Symptom.** The test demanded an internal sequence gap among the surviving
records and never found one.

**Cause.** My mental model of the overrun path was wrong. On overrun
`vmtrace_emit()` does two things: it evicts the oldest record *and* rewrites
the incoming record as a `VMTRACE_DROP` marker carrying the running drop count.
So the surviving window is always the newest `capacity` sequence numbers, which
are contiguous among themselves. The loss shows up as the window *starting
late*, never as a hole inside it.

**Fix.** Assert that the window does not begin at sequence 1, that it is
internally contiguous, that its length is exactly the capacity, and that a drop
marker is present.

**Inference — this one matters for the data pipeline.** Because every record
admitted after the ring fills is rewritten as a marker, sustained overrun turns
the *entire* surviving window into markers. That is excellent for the drop
discipline: an overrun window can never be mistaken for data, no matter which
end of it you read. It also means a capture that overran is not partially
salvageable — you lose the window, not just the oldest record. That is the
right trade for training data, but it should be a conscious one, and it is why
`vmdrain` and `decode_trace.py` both treat any drop as invalidating the whole
capture rather than truncating to the good part.

### 2.3 `usertests bigargtest` — hard-coded one-page stack

**Symptom.** `bigargtest: bigarg test failed!` The transcript also carried a
long run of spaces: `echo` had actually run.

**Cause.** The test builds 31 arguments of 400 bytes and requires `exec` to
reject them. 12,400 bytes only overflows a one-page stack. At `USERSTACK=16`
the arguments fit in the 64 KiB stack, `exec` succeeded, `echo` printed its
12 KB of spaces, and the child never created the `bigarg-ok` marker the parent
looks for.

**Fix.** Derive the argument size from the constants it actually depends on:
`(USERSTACK * PGSIZE) / (MAXARG - 1) + 64`. Each argument stays under `PGSIZE`
so that `exec`'s per-argument `fetchstr` limit is not what rejects them — the
stack bound is, which is what the test is about.

**Inference.** The similar-looking check in `copyinstr2` (three arguments of
`PGSIZE + 1` bytes) was *not* affected, and understanding why is the useful
part: it is rejected by `fetchstr`'s `PGSIZE` per-argument cap, not by the
stack bound. Two tests that look like they test the same thing test different
mechanisms. Only one of them was coupled to `USERSTACK`.

### 2.4 `vmtest controls` and `inherit` — absolute resident limits

**Symptom.** `vmtest all-policy fifo` failed on its very first subtest.

**Cause.** Both tests call `vmctl(VM_SET_LIMIT, 8)` / `(…, 7)`.
`vmstate_ctl()` refuses a limit below the caller's current resident count by
design:

```c
case VM_SET_LIMIT:
  if(value > VM_MAX_RESIDENT_LIMIT ||
     (value != VM_LIMIT_UNLIMITED && value < p->vm.resident_count))
    result = -1;
```

A process fresh out of `exec` now holds 26 resident pages, so both calls
returned -1.

**Fix.** Make both limits relative to `resident_count`. Neither test is about
the number: `controls` checks that the control interface round-trips through
`vmstats` and that invalid values are rejected without disturbing the current
value; `inherit` checks that vm state crosses `fork`.

**Inference.** `VM_SET_LIMIT`'s "no limit below what you already hold"
semantics is a deliberate design choice, and it is the right one — the
alternative is a control that silently triggers an unbounded reclaim. But it
means *no* test can use an absolute limit smaller than a process's post-exec
footprint, and that footprint is now 26 pages. Any future test setting a limit
must compute it from `resident_count`.

### 2.5 `vmtest dirty-writeback` — the region became smaller than the baseline

**Symptom.**

```
dirty: writes warm=22 clean=22  faults warm=2 clean=2  resident=30 limit=30 base=26
```

**Cause.** The test scans a 24-page lazy region under a limit of
`resident_count + 4`, relying on the scan being longer than the resident
capacity so that FIFO cycles the region through swap. With `base = 26` the
capacity is 30 and the region is 24 — the region is *smaller* than the
capacity. FIFO therefore evicted the 22 cold pages the process arrived from
`exec` with (unused stack pages, text pages for code not executing) and the
region under test never left memory: **2 swap faults where the test needed 24.**

**Fix.** Size the region from the baseline: `pages = resident_count + 24`, and
keep the headroom at 4. That restores the invariant the test depends on — a
cyclic scan strictly longer than the resident capacity, which gives a 100% miss
rate under FIFO, Clock and Aging alike — for any baseline.

**Inference, and a correction worth being precise about.** The test *did* fail
loudly. Look at which of its two conditions fired:

```c
if(clean.page_writes > warm.page_writes + 2 ||          /* the property:  passed trivially, 22 == 22 */
   clean.swap_faults < warm.swap_faults + pages - 2){   /* the guard:     fired, 2 < 24 */
```

The property the test exists to verify — that re-evicting a *clean* page
recycles its backing slot without a second page write — passed vacuously,
because nothing was evicted at all. What caught the problem was the second
condition, which is not a property assertion but a **precondition guard**:
"the scan must actually have missed on nearly every page, or I am not measuring
what I claim to measure."

That is the lesson, and it is an encouraging one rather than a worrying one:
this test was written well enough to detect that its own setup had stopped
working. A test with only the `page_writes` check would have gone green while
measuring nothing. **When a test's meaning depends on a state it sets up
indirectly — through a replacement policy, a limit, a fault — assert that the
setup took effect.** Every fix in §2.5–2.7 amounts to restoring or adding such
a guard.

### 2.6 `vmtest kill-fault` under `VM_DEBUG` + Clock — policy-dependent victim

**Symptom.** Passed under FIFO, failed under Clock. Only visible in the
`VM_DEBUG` build, since the fault-injection subtests are compiled out
otherwise.

**Cause.** Same shape as §2.5. `fault_cleanup()` allocates 40 pages, touches
them all, then injects a 20-tick I/O delay and touches page 0 — the parent
kills the child mid-swap-in and checks that no swap slot leaked. That requires
page 0 to actually be *in swap* when the final touch happens. With `base = 26`
and a limit of 30, only about ten of the forty pages get evicted, and *which*
ten depends on the policy: FIFO's queue order reached page 0, Clock's reference
bits did not. Under Clock the child faulted nothing, completed normally, and
the parent's `status == 0` check failed.

**Fix.** Two changes, so the precondition holds by construction rather than by
luck:

1. Size the region from `resident_count` (`pages = resident_count + 40`).
2. Add a second pass over every page **except page 0**.

After more pages than the resident limit have been referenced while page 0 was
not, page 0 cannot still be resident under FIFO, Clock or Aging. The test no
longer depends on which policy is active.

**Inference.** A test that needs "page X is swapped" must *force* it, not
assume it. Sequential-touch-then-hope produces a victim set that is a function
of the policy under test — which is exactly the wrong thing for a test that is
supposed to hold across policies. The general recipe: reference everything
else more times than there are frames.

### 2.7 `prefetchtest all clock` under `VM_DEBUG` — the shared helper, same cause

**Symptom.** Failed in the synchronous group under Clock; passed under FIFO.

**Cause.** `make_swapped()` is the setup helper for *every* prefetch subtest,
and it has the identical flaw: 40 fixed pages under a limit of
`resident_count + 5`. Every caller depends on the whole region being swapped:

- `sequential()` faults page 3 to trigger an automatic prefetch of page 4;
- `duplicate()` and `waste()` hint page 4 and expect the hint accepted;
- `pressure()` hints pages 0..23 and needs each one either accepted or dropped
  for queue pressure — a hint on a *resident* page is rejected as invalid
  instead, which zeroes `prefetch_dropped_pressure` and fails the test.

**Fix.** After loading the region, sweep a scratch region larger than the
resident limit, twice. Nothing of the region can then still be resident under
any policy. `PAGES` and `TARGET_PAGE` keep their fixed values, so no subtest's
indices change.

**Inference.** One flawed setup helper silently weakened fourteen subtests. The
prefetch suite's real coverage was a function of `USERSTACK`, and nobody would
have known: under FIFO it all passed. Shared setup helpers deserve the
precondition guards of §2.5 more than individual tests do, because a
regression in one is invisibly multiplied.

### 2.8 `prefetchtest all fifo` — self-inflicted, while fixing §2.7

**Symptom.** My §2.7 fix broke the asynchronous group, which had been passing.

**Cause.** I allocated the scratch region *after* the region under test, so
scratch sat on top of it in the address space. `unmap_queued()` and
`shrink_inflight()` unmap the region with `sbrk(-PAGES * PGSIZE)` while a
prefetch for it is queued, and `sbrk` shrinks from the top — so they unmapped
the scratch, left the region mapped, and `prefetch_canceled` never moved.

**Fix.** Allocate scratch *first* so the region stays the topmost allocation.
The sweep order (region, then scratch) is what matters for eviction and is
independent of the allocation order. Both tests now also give the scratch back,
since all subtests share one process and it would otherwise accumulate.

**Inference.** `sbrk(-n)` is positional, so any test that unmaps "the region"
by shrinking is coupled to the region being on top. That coupling is invisible
at the call site — `sbrk(-PAGES * PGSIZE)` reads as "free my region" but means
"free the top PAGES pages". Anything added to the address space between setup
and teardown breaks it.

### 2.9 `usertests unlinkcwd` — harness ordering, not a code defect

**Symptom.** `unlinkcwd: mkdir /a failed` — the last test in the quick list,
after 24 minutes of run time.

**Cause.** `unlinkcwd` opens with `mkdir("/a")` and requires it to succeed; it
has no `unlink("/a")` first. `grind` creates `/a` as a side effect of
`mkdir("grindir/../a")` and never removes it. I had run `grind 200` before
`usertests -q` against the same persistent `fs.img`.

**Fix.** Rebuild `fs.img` before any `usertests` run. Every gate step that
needs a known filesystem state now does.

**Inference.** `usertests` is not idempotent on a dirty image and never was —
this is stock xv6 behaviour, unrelated to either phase. But `fs.img` persists
across `make qemu` invocations, so a test matrix that runs several programs in
sequence will hit it. Any recorded run of `usertests` needs a fresh image, and
Phase 2's evidence matrix should build one per step rather than per matrix.

### 2.10 Three tooling mistakes, recorded because they cost time

- **Editing a shell script while bash was executing it.** Bash reads scripts
  incrementally by byte offset. Rewriting `gate.sh` mid-run made it resume at
  its saved offset inside the newly inserted text, execute a garbled fragment,
  and start an unintended `VM_DEBUG` build that polluted the next result.
- **A Python edit wrote the script with CRLF.** `open(path, 'w')` in text mode
  on Windows translates `\n` to `\r\n`; bash then failed on `$'\r'` and the
  whole run was a no-op that reported success per step.
- **`make -j4` against a `VM_DEBUG` tree.** Without `VM_DEBUG=1` the user
  programs recompiled without `-DVM_DEBUG` while the kernel kept it, so
  `prefetchtest all` silently ran the *release* subset of subtests — two
  instead of eleven — and the result looked like a pass of something it had not
  run. Switching between the two configurations requires `make clean`; the
  gate script now has separate `release` and `debugbuild` steps that do.

---

## 3. What the failures say, taken together

**One root cause produced five of them.** §2.3, §2.4, §2.5, §2.6 and §2.7 are
all the same defect: a test encoded "the thing I am testing is much larger than
everything else this process has resident" as a fixed page count. `USERSTACK`
1 → 16 added fifteen pages to every process's baseline and inverted that
relationship. A single constant change in `param.h` invalidated assumptions in
two test programs and five distinct tests, none of which mentioned `USERSTACK`.

**The failures were loud, which is the platform working.** Every one of the five
failed rather than passing vacuously. That is not luck: `bigargtest` checks for
a marker file, `controls` checks the value round-trips, `dirty-writeback` and
`prefetchtest` have precondition guards, `kill-fault` checks the child's exit
status. The one part that *did* go vacuous — `dirty-writeback`'s `page_writes`
comparison — was caught by the guard next to it.

**The generalisable rule.** Derive test magnitudes from observed state, not from
literals; and where the test's meaning depends on a state it establishes
indirectly, assert that the state was established. Phase 7 will add a learned
policy whose victim choices are by construction less predictable than FIFO's;
any test that assumes a particular page got evicted will be fragile in exactly
this way. §2.6's recipe — reference everything else more times than there are
frames — is policy-independent and is the pattern to reuse.

**A measurement caution for Phases 5–6.** `USERSTACK=16` means every process
carries roughly 26 resident pages before it allocates anything. When a workload
runs under a resident limit, a substantial and *cold* fraction of the limit is
the process's own image and unused stack. Those pages are the most attractive
victims under every policy, so a naive "limit = N" experiment is not measuring
"working set of N pages" — it is measuring N minus a policy-dependent slice
consumed by process overhead. Workload configurations should express limits
relative to the measured baseline, exactly as the fixed tests now do, or the
reuse-distance and Belady analysis will be comparing different effective
capacities across workloads.

---

## 4. Deliberate deviations from the roadmap

These are choices, not failures, but a reviewer will notice them.

| Roadmap says | Delivered | Why |
|---|---|---|
| record ≤ 48 bytes | **64 bytes** | The roadmap's own field-width list sums to 5×8 + 7×4 + 5×1 = 73 B, so 48 is unreachable without dropping fields §14 calls the minimum set. 64 keeps every field, wastes no padding, and divides `BSIZE` so a record never straddles a block in a capture. Down from 152 B. |
| `status` → `uint8` | **`uint32`, signed** | It carries `-1` for failed operations and a running drop count for `DROP` records. A byte would truncate the latter. |
| keep `ticks`, `generation`, `pte_flags` at 64 bits | **32 / 32 / 16 bits** | All three are lossless: the kernel's `ticks` is already a `uint`, and every `pte_flags` call site passes `PTE_FLAGS(...)`, which is ten bits. |
| — | added `vmctl(VM_TRACE_SET_CAPACITY, n)` | Filling a 65536-record ring for real costs tens of thousands of swap I/Os. Shrinking it keeps the wrap and overflow tests under a second, and is independently useful for studying drop behaviour. |
| — | added `tools/extract_file.py` | A gap in the roadmap's pipeline: the capture lands inside the guest filesystem and xv6 cannot hand it to the host. Verified byte-exact against `user/_usertests` and `README`. |
| — | `mkfs` `ftruncate`s the image | The old loop wrote `FSSIZE` zero blocks — 100k write syscalls, ~90 s per rebuild. A freshly truncated file reads as zeros in the blocks nothing writes, so the image is identical. |

---

## 5. Outstanding — known, not fixed

Ordered by how much they will hurt.

### 5.1 `usertests -q` takes ~23 minutes (was 88 s)

`writebig` writes a 64 MiB file one 1 KiB `write()` at a time, and each is its
own log transaction — roughly ten disk writes per kilobyte of file. Measured
~50 KB/s, and the rate is **flat across the whole file**, which is the evidence
that this is disk-bound rather than the O(n²) allocator scan the file size
might suggest.

Options, roughly in order of appeal:

- Move `fs.img` off the 9p mount onto WSL's native ext4. Likely the largest win
  by far, costs no code, but changes the documented reference configuration —
  so if you do it, re-record `docs/vm-baseline.txt` at the same time.
- Leave it. It is a one-off cost per recorded matrix run, and Phase 2 runs the
  matrix once.
- Batch `writebig`'s writes. Editing stock `usertests` for speed is a bad trade
  against the value of running it unmodified.

`bigfiletest` writes at ~100 KB/s for comparison, because it writes in 8 KiB
chunks: `filewrite` still splits into 3072-byte transactions, so it pays about
a third as many transactions per byte.

### 5.2 `balloc` is O(n²) in a file's block count

`balloc` rescans the free bitmap from block 0 on every allocation, so writing a
file of *n* blocks costs Θ(n²) bit tests — for `MAXFILE` that is about
2.2 × 10⁹. Measurement says it is not the current bottleneck (see §5.1), so I
changed nothing: a fix alters allocation order, and Phase 1 did not ask for it.

It will matter when Phase 4/5 write and rewrite large workload inputs
repeatedly. The fix is small and well understood — remember the block after the
last successful allocation and start the scan there, wrapping once — and makes
append-heavy allocation amortised O(1). Worth doing *before* dataset
collection, and worth doing as its own change with its own regression run,
because it changes which blocks a file gets.

### 5.3 `vmdrain collect` stops on a heuristic

xv6's `wait()` blocks and has no non-blocking form, so a single-threaded
drainer cannot wait on the workload and drain at the same time. `collect`
therefore drains until the ring has been quiet for 100 consecutive polls and
only then reaps the child.

The failure mode is loud, not silent: anything lost while blocked in `wait()`
appears as a non-zero drop count and the capture is declared invalid. But a
workload with a long non-paging phase in the middle could end a capture early.
Mitigations, in order of cost: use `follow <ticks>` with a backgrounded
workload (fully deterministic, no heuristic); or add a non-blocking
`wait`/`waitpid(WNOHANG)`; or have the workload signal completion through a
pipe that a small helper converts into something pollable.

### 5.4 Tracing is a single global switch

`trace_ring.enabled` is global, not per-process. A capture therefore contains
the drainer's and the shell's events as well as the workload's. Records carry a
pid so the decoder filters cleanly, and in practice the contamination is small
(the drainer's buffer is in `.bss` and resident; its writes are kernel-side).
For Phase 5 this is fine, but a per-process enable would make captures
self-contained and remove a filtering step from the pipeline.

### 5.5 The 1M-event gate was met in two halves, not one

The roadmap asks for a 1M-event capture round-tripped without loss. I verified
the decoder against 1,000,000 synthetic records — field-for-field, plus
detection of a removed record and a mid-record truncation — and the real
guest→host path at 27,445 records. A genuine 1M-event in-guest capture needs a
64 MB file and, at §5.1's rate, about half an hour of writing; `MAXFILE` is
large enough that it fits in a single file, which is presumably why Phase 1
raised it. Worth doing once during Phase 2 as recorded evidence.

### 5.6 Memory and log headroom

- The trace ring (4 MiB) plus the frame table (4 MiB) is about 8 MiB of the
  128 MiB machine, so the free frame pool drops by roughly 6%. Fine, but it is
  the kind of thing that makes an absolute page count in an experiment
  configuration drift.
- `LOGBLOCKS` and `NBUF` are unchanged at 30. `itrunc` on a maximum-size file
  logs at most 14 blocks (13 bitmap blocks plus the inode), so a single
  transaction has room. Three *concurrent* unlinks of maximum-size files
  spanning the whole bitmap would approach the limit. No current test comes
  near it; worth knowing before Phase 4 adds workloads that hold several large
  files at once.

### 5.7 Minor

- `trace.txt` and `trace_readable.txt` at the repo root are sample dumps in the
  old v1 record format. They are stale and should be regenerated or deleted so
  nobody decodes them against the v2 schema.
- `tools/fsck_xv6.py` reports one *note* after `usertests`: an inode with a
  block mapped past its size. That is legitimate and expected — `writei` calls
  `bmap` before copying, so `copyin`'s deliberate write from a bad address
  leaves an allocated block the failed write never covered. The block stays
  reachable, so it is not a leak. The checker distinguishes the two cases on
  purpose.

---

## 6. Reproducing the gate

```sh
# Phase 0
python3 tools/decode_trace.py /tmp/synthetic.bin --selftest 1000000
python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 \
  "vmtest trace-schema" "vmtest trace-capacity" "vmtest trace-wrap" \
  "vmtest trace-disabled" "vmtest trace-drop" "vmtest trace-lossless"

rm -f fs.img && make fs.img
python3 tools/run_xv6_tests.py --cpus 1 --timeout 2400 \
  "vmdrain trace.bin collect vmtest swap-repeat"
python3 tools/extract_file.py fs.img trace.bin /tmp/trace.bin
python3 tools/decode_trace.py /tmp/trace.bin --strict --csv /tmp/trace.csv

# Phase 1 — each on a fresh image
rm -f fs.img && make fs.img
python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 "bigfiletest all"
python3 tools/fsck_xv6.py fs.img --fssize 100000

rm -f fs.img && make fs.img
python3 tools/run_xv6_tests.py --cpus 1 --timeout 5400 "usertests -q"
python3 tools/fsck_xv6.py fs.img --fssize 100000

rm -f fs.img && make fs.img
python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 "grind 200"

# Policy matrix, in both configurations
for p in fifo clock aging; do
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 2400 \
    "vmtest all-policy $p" "prefetchtest all $p"
done
make clean && make VM_DEBUG=1 && make VM_DEBUG=1 fs.img   # then repeat the loop
make clean && make                                        # back to release
```

`make clean` between the release and `VM_DEBUG` configurations is not optional
— see §2.10.
