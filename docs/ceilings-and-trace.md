# Trace infrastructure and raised ceilings

Record of what Phase 0 and Phase 1 of `ROADMAP.md` changed, where the
delivered numbers differ from the roadmap's targets and why, and what the
changes cost at run time. Nothing here is a research result; it is the
platform the research runs on.

---

## Phase 0 — trace infrastructure

### Ring size

| Constant | Was | Now |
|---|---|---|
| `VMTRACE_CAPACITY` | 128 | 65536 |
| `VMTRACE_READ_MAX` | 8 | 256 |
| `sizeof(struct vmtrace_event)` | 152 B | 64 B |
| `VMTRACE_VERSION` | 1 | 2 |

The ring is `static` in `kernel/vmtrace.c`, so it lives in kernel `.bss` and is
never pageable. `riscv64-unknown-elf-nm -S kernel/kernel` shows:

```
00000000804141f0 0000000000400040 b trace_ring
```

4 MiB, lowercase `b` (local `.bss`). That is the evidence for the plan's §14
requirement that trace buffers and metadata are non-pageable. `frame_table` is
a further 4 MiB, so the two together take about 8 MiB of the 128 MiB the
machine has.

### Record layout

`version` and `size` are gone from the per-record struct. They were 16 of the
old 152 bytes and restated the schema on every record. They now live in a
`struct vmtrace_header` returned once by the new `vmtrace_info()` syscall and
written at the front of a drained capture.

**Why 64 bytes and not the roadmap's ≤48.** The roadmap's own field-width list
adds up to more than 48:

```
5 × uint64 (sequence, cycle, ticks, generation, pte_flags)  = 40
7 × uint32 (vpn, victim_vpn, frame_index, swap_slot,
            resident_count, pid, queue_id)                  = 28
5 × uint8  (type, access, page_state, status, policy)        =  5
                                                              ---
                                                               73  -> 80 padded
```

48 bytes is only reachable by dropping fields the plan's §14 lists as the
minimum set. So the target was treated as "as small as possible while keeping
every field", which lands at 64:

* `ticks` narrowed to `uint32` — lossless, the kernel's `ticks` is already a
  `uint`.
* `generation` narrowed to `uint32` — 2^32 address-space generations per
  process is not reachable.
* `pte_flags` narrowed to `uint16` — every call site passes `PTE_FLAGS(...)`,
  which is ten bits.
* `status` kept at 32 bits, *not* the suggested `uint8` — it carries `-1` for
  failed operations and a running drop count for `VMTRACE_DROP` records, and a
  byte would silently truncate the latter. It is logically signed; decode it as
  `int32`.

64 bytes also divides `BSIZE`, so a record never straddles a block in a drained
capture, and `kernel/vmtrace.c` carries a compile-time assertion that both the
record and the header stay exactly 64 bytes. A field change that alters either
now has to be a deliberate schema bump.

The ring costs 65536 × 64 B = 4 MiB. At the plan's literal 80-byte layout it
would have been 5 MiB.

### New interfaces

* `vmtrace_info(struct vmtrace_header *)` — syscall 30. Returns the schema
  (version, record size, capacity, read batch limit) and the live counters
  (`sequence`, `dropped`, `buffered`, `enabled`).
* `vmctl(VM_TRACE_SET_CAPACITY, n)` — shrinks the effective ring to `n`
  records and resets it. Without this, the wrap and overflow tests would need
  tens of thousands of swap I/Os to fill a 65536-record ring; with it they run
  in under a second. It is also the way to study drop behaviour deliberately.
  The capacity is global kernel state, so every test that changes it restores
  it on all exit paths.

### Drop discipline

The rule is that any experiment with `drops != 0` is *invalid*, not warned
about. It is enforced in three places:

1. **In the kernel.** On overrun the oldest record is evicted, `drops` is
   incremented, and the incoming record is rewritten as a `VMTRACE_DROP`
   marker carrying the running count. A consequence worth knowing: under
   sustained overrun every surviving record becomes a marker, so an overrun
   window cannot be mistaken for data.
2. **In `user/vmdrain.c`.** It tracks sequence continuity while draining and
   prints `FAILED -- capture lost records; discard it` (and exits non-zero) if
   the header reports drops, if it saw a marker, if sequences skipped, or if
   records were still buffered at the end.
3. **In `tools/decode_trace.py`.** A capture is complete only when the first
   record is sequence 1, every following sequence is exactly one greater, and
   no record is a `DROP`. `--strict` writes no decoded output at all when any
   of that fails, so nothing downstream can consume a holed trace.

### Pipeline

```
        guest                                  host
  ------------------------            ---------------------------
  vmctl(VM_TRACE_ENABLE, 1)
  workload faults/evicts
  vmdrain out.bin collect <cmd>  -->  tools/extract_file.py fs.img out.bin -
                                      tools/decode_trace.py - --strict --csv
```

`user/vmdrain.c` has three modes: `collect <cmd>` runs a workload and drains
alongside it, `follow <ticks>` drains for a fixed window (for use with a
backgrounded workload), and `once` sweeps whatever is buffered.

`collect` has one soft edge worth naming. xv6's `wait()` blocks and there is no
non-blocking form, so a single-threaded drainer cannot wait on the workload and
drain at the same time. `collect` therefore drains until the ring has produced
nothing for 100 consecutive polls and only then reaps the child. Stopping early
is safe rather than silent: anything lost while blocked in `wait()` turns up as
a non-zero drop count and the capture is declared invalid.

`tools/extract_file.py` is the missing link between the two halves — the trace
lands inside the guest filesystem and xv6 cannot hand it to the host, so the
tool walks the root directory and the inode's block map (including the new
doubly-indirect level) and copies the bytes out. Verified byte-exact against
`user/_usertests` and `README`.

### Tests

| Test | What it establishes |
|---|---|
| `vmtest trace-schema` | header matches the compiled schema; a record straddling two lazy pages copies out correctly; so does the header |
| `vmtest trace-capacity` | `VM_TRACE_SET_CAPACITY` rejects 0 and anything above the compiled capacity |
| `vmtest trace-wrap` | head/tail wrap the array repeatedly with no loss and contiguous sequences |
| `vmtest trace-disabled` | disabled tracing emits nothing and leaves the counters at zero |
| `vmtest trace-drop` | overrun raises `dropped`, emits a marker, and leaves a window that does not start at sequence 1 |
| `vmtest trace-lossless` | dataset-scale stream at full capacity with zero drops and zero gaps |
| `decode_trace.py --selftest 1000000` | 1M records round-trip field-for-field; a removed record and a mid-record truncation are both detected |

---

## Phase 1 — raised ceilings

| Constant | File | Was | Now |
|---|---|---|---|
| `NSWAPSLOTS` | `kernel/swap.h`, `Makefile` | 1024 (4 MiB) | 8192 (32 MiB) |
| `USERSTACK` | `kernel/param.h` | 1 (4 KiB) | 16 (64 KiB) |
| `FSSIZE` | `kernel/param.h` | 2000 (2 MiB) | 100000 (100 MiB) |
| `NDIRECT` | `kernel/fs.h` | 12 | 11 + doubly-indirect |
| `MAXFILE` | `kernel/fs.h` | 268 blocks (268 KiB) | 65803 blocks (64.26 MiB) |
| `NBUF` | `kernel/param.h` | 30 | 30, deliberately |

`struct dinode` keeps its 13-entry `addrs[]`, so it stays 64 bytes and `IPB`
stays 16: eleven direct entries, one singly-indirect, one doubly-indirect.
`fs.img` is `FSSIZE * BSIZE + NSWAPSLOTS * 4096` = 135,954,432 bytes, and the
swap region still starts exactly at `FSSIZE`.

The block-mapping change had to be made twice, in `bmap()`/`itrunc()` in
`kernel/fs.c` and independently in `iappend()` in `mkfs/mkfs.c`. `mkfs`'s
`balloc()` was also generalised: with `FSSIZE` past `BPB` the free bitmap spans
13 blocks rather than one.

### Log capacity

`itrunc()` on a maximum-size file frees 65803 data blocks, 256 second-level
indirect blocks, and both indirect roots. Because `bfree()` only logs bitmap
blocks and log absorption collapses repeats, that is at most 13 bitmap blocks
plus the inode block — 14 of `LOGBLOCKS` = 30. `MAXOPBLOCKS`, `LOGBLOCKS` and
`NBUF` are unchanged.

### Verification

The kernel exposes no free-block count, so "no block leak" is checked from the
host by `tools/fsck_xv6.py`, which walks every allocated inode through all
three levels and compares the reachable set against the on-disk free bitmap. It
reports blocks marked used but unreachable (leaks), blocks referenced but
marked free (double-allocation), double references, and size/mapping
disagreements. A block mapped past a file's size is reported as a note, not an
error — `writei()` calls `bmap()` before copying, so a write that faults on its
source address legitimately leaves one behind, still reachable.

`user/bigfiletest.c` covers the guest side: a 5 MiB file written, `fstat`ed,
read back byte-exact and unlinked; each level transition (11 blocks, 267
blocks, 268 blocks, 524 blocks) written and fully re-verified; `O_TRUNC` over a
doubly-indirect file; recursion through 48 KiB of stack; and 8 MiB pushed
through swap, which is twice what the old 1024-slot region could hold.

### Test expectations that `USERSTACK` 1 → 16 invalidated

Three tests encoded the assumption that a process has a one-page stack, and so
a small resident set. None of them was testing that assumption on purpose.

* **`usertests.c` `bigargtest`** asserted that `exec` rejects 31 arguments of
  400 bytes. 12,400 bytes only overflows a one-page stack; at `USERSTACK=16`
  they fit, `exec` succeeded, and the test failed. The argument size is now
  derived from `USERSTACK` and `MAXARG`, so it tests the real invariant rather
  than a hard-coded page. (The similar check in `copyinstr2` was unaffected —
  `exec`'s per-argument `fetchstr` limit rejects that one, not the stack
  bound.)
* **`vmtest` `controls` and `inherit`** set absolute resident limits of 8 and
  7. `vmstate_ctl()` refuses a limit below the current resident count by
  design, and a process fresh out of exec now holds 26 pages, so both calls
  returned -1. Both limits are now relative to `resident_count`.
* **`vmtest` `dirty-writeback`** is the interesting one. It scans a 24-page
  lazy region with a resident limit of `resident_count + 4`, expecting the
  scan to be longer than the resident capacity so that FIFO cycles the region
  through swap. Once `resident_count` reached 26, the region was *smaller*
  than the baseline resident set, so FIFO evicted the process's own text and
  stack pages instead and the region never left memory: 2 swap faults where
  the test wanted 24. Note which of its two conditions fired — the property
  it exists to check (`clean.page_writes > warm.page_writes + 2`) passed
  vacuously at 22 == 22, because nothing was evicted at all; what caught the
  problem was the precondition guard next to it
  (`clean.swap_faults < warm.swap_faults + pages - 2`). The region is now
  sized as `resident_count + 24`, which restores the
  cyclic-scan-longer-than-capacity condition for any baseline. See
  `docs/phase0-phase1-report.md` §2.5 for why that distinction is the useful
  lesson here.

Two more of the same shape only showed up in the `VM_DEBUG` build, where the
fault-injection subtests and the full asynchronous prefetch matrix run:

* **`vmtest` `kill-fault` / `swap-fault-io-error`** (`fault_cleanup`) allocate
  40 pages and then touch page 0, expecting a swap-in that a `kill` or an
  injected I/O error interrupts. That needs page 0 to actually be in swap. With
  a 26-page baseline and a limit of 30, whether it was became policy-dependent:
  FIFO reached it, Clock did not, so under Clock the child completed normally
  and the test saw a zero exit status. The region is now sized from
  `resident_count`, and a second pass over every page *except* page 0 forces it
  out regardless of policy.
* **`prefetchtest`'s `make_swapped`** has the same problem, and every subtest
  depends on it: `sequential` faults page 3 to trigger a prefetch of page 4,
  `duplicate` and `waste` hint page 4, and `pressure` hints pages 0..23 and
  needs them accepted-or-dropped rather than rejected as resident. It now
  sweeps a scratch region larger than the resident limit twice after loading
  the region, which leaves no frame for a region page under any of the three
  policies. The scratch is allocated *below* the region so that
  `unmap_queued` and `shrink_inflight` — which unmap the region with
  `sbrk(-PAGES * PGSIZE)` — still target the region rather than the scratch,
  and both give the scratch back so it does not accumulate across the
  subtests, which share one process.

`prefetchtest` also gained an optional policy argument mirroring
`vmtest all-policy <policy>`, so the Phase 1 gate's "under FIFO, Clock and
Aging" is actually executable for it.

The common thread is worth stating plainly for the write-up: several tests
encoded "the region under test is much larger than everything else the process
has resident" as a fixed page count. `USERSTACK` 1 → 16 added fifteen pages to
every process's baseline and inverted that relationship. All five failed
rather than passing vacuously, because each happened to check something that
depended on its setup having worked — a marker file, a returned value, an exit
status, or an explicit precondition guard. That is the property to preserve:
where a test's meaning depends on state it establishes indirectly, through a
replacement policy or a resident limit, it needs to assert that the state was
established. All of them now derive their sizes from `resident_count`.

### One harness ordering hazard

`usertests` is not idempotent on a dirty filesystem: `unlinkcwd` starts with
`mkdir("/a")` and requires it to succeed, while `grind` creates `/a` via
`mkdir("grindir/../a")` and never removes it. Running `grind` before
`usertests -q` on the same persistent `fs.img` therefore fails the last quick
test. Any run of `usertests` needs a freshly built image.

### Run-time cost

Raising `MAXFILE` to 64 MiB makes `usertests -q` dramatically slower, because
`writebig` now writes a 64 MiB file one 1 KiB `write()` at a time and each of
those is its own log transaction. On the reference host (WSL2, `fs.img` on a
9p-mounted Windows drive) that measured about 40 KB/s, so `writebig` alone
takes roughly 30 minutes and `usertests -q` went from 88 s to about 32 min.

The rate is flat across the file, so this is disk-bound, not the O(n²) bitmap
scan in `balloc()` that the file size might suggest. Nothing was changed about
`balloc`: the cost is real but it is I/O, and the allocator's scan is not what
dominates at this scale.

One build-side cost was worth removing. `mkfs` used to write `FSSIZE` zero
blocks in a loop, which at 100000 blocks was 100k write syscalls and about 90
seconds on every rebuild that touched a user program. It now `ftruncate`s the
image to size in one step; a freshly truncated file reads as zeros in the
blocks nothing writes, so the image content is identical.
