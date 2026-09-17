# xv6-riscv Paging Research — State and Roadmap

Companion document to `xv6_paging_lifecycle_agent_plan.txt`.

That file is the **implementation contract** for the paging platform, and it is
essentially complete. This file picks up where it stops: it records what exists
today, where the limits are, what has to happen next, and — for each phase —
what conclusion the work actually licenses you to draw.

This document is self-contained. Where the original plan is referenced, its text
is reproduced here rather than cited, so you never need both files open.

Steps are written as checklists. Phases are ordered by dependency, not by
calendar. Effort tags are relative (S / M / L), not schedules.

---

## Part 1 — Current state

### 1.1 What stock xv6 does not have

Baseline xv6-riscv has no virtual memory management of any kind. Pages are
allocated eagerly at `exec` and `sbrk`, live in RAM until the process exits, and
are never evicted. There is no page fault path for memory, no backing store, no
replacement policy, no frame metadata. That entire layer had to be built.

### 1.2 What is built

Six subsystems, all present in the tree:

**Lazy anonymous allocation.** `sbrklazy()` records a valid address range
without committing physical memory. Frames are supplied on first touch via the
fault path. This is what generates the fault stream the research depends on.

**Disk-backed swap** — `kernel/swap.c`, `kernel/swap.h`.
A raw region past the end of the filesystem (`SWAP_START_BLOCK = FSSIZE`),
`NSWAPSLOTS` slots of 4KB. Raw VirtIO transfers bypass the inode layer, the
journal, and the buffer cache. `fs.img` is extended by the Makefile so the
offset can never silently drift.

**Frame table** — `kernel/vmpage.c`, `kernel/vmpage.h`.
Per-physical-frame record: owner proc/pagetable/VA, state, `pin_count`, `busy`,
`referenced_sample`, `dirty_sample`, `load_sequence`, `last_access_epoch`,
`frequency`, `aging_counter`, `backing_slot`, `prefetch_request_id`,
`policy_index`, and an intrusive owner list.

**Replacement policies** — FIFO, Clock, Aging, selected at runtime through
`vmctl(VM_SET_POLICY, id)`. A common engine filters and validates candidates and
falls back to Clock if a policy returns a pinned, busy, foreign, or
out-of-range victim.

**Prefetch** — `kernel/prefetch.c`. Synchronous and asynchronous paths,
usefulness/waste accounting, and the full race matrix (demand-vs-prefetch,
unmap-while-queued, exit/kill in flight, I/O error, duplicate prediction).

**Tracing and stats** — `kernel/vmtrace.c`, `kernel/vmstats.h`. Structured
binary events for the whole page lifecycle plus ~35 counters exposed through
`vmstats()`.

Supporting infrastructure: `tools/run_xv6_tests.py` (pexpect harness),
`user/vmtest.c` and `user/prefetchtest.c` (~50 named tests), `kernel/vmdebug.c`
(invariant checker + deterministic delay/failure injection under `VM_DEBUG`).

### 1.3 Coverage against the original plan

| Plan phase | Content | Status |
|---|---|---|
| Phase 1 | VM types, frame metadata, `vmctl`/`vmstats` control API | Implemented |
| Phase 2 | Raw disk-backed swap slots outside the filesystem | Implemented |
| Phase 3 | Pageable frame acquisition and resident-limit accounting | Implemented |
| Phase 4 | Swap-out, swap-in, demand fault dispatcher, FIFO | Implemented |
| Phase 5 | Destruction and resize lifecycle (unmap, shrink, exit, kill) | Implemented |
| Phase 6 | Fork, exec, and kernel/user copy paths | Implemented |
| Phase 7 | Policy framework — FIFO, Clock, Aging, validated fallback | Implemented |
| Phase 8 | Synchronous prefetch lifecycle | Implemented |
| Phase 9 | Asynchronous prefetch and race completion | Implemented |
| Tracing | Bounded binary ring buffer and measurement interface | Implemented |
| Regression matrix | Full debug/release/policy/soak matrix | Signed off — `platform-v1.0` |
| Acceptance criteria | The 15-item completion checklist | Signed off — `platform-v1.0` |

Every test named in the plan exists in `vmtest.c` / `prefetchtest.c`. Both
outstanding items were discharged by Phase 2: 74 matrix steps, 0 failures,
tagged `platform-v1.0`. The full text of both is reproduced in Phase 2 below,
and the evidence is in `docs/phase2/`.

---

## Part 2 — What has not been done

1. **The learned policy.** `VM_POLICY_COUNT` is 3. There is no
   `VM_POLICY_LEARNED`. The hook exists (`policy_index`, the validation and
   fallback layer) but nothing is plugged into it.
2. **Workloads.** `pagingdemo.c` and the test programs only. Nothing that
   represents realistic application memory behaviour.
3. **Dataset pipeline.** No collection at scale, no feature extraction, no
   labels, no training, no quantisation back into kernel-usable form.
4. **Baselines.** No Belady oracle, no measured gap between existing heuristics
   and optimal.

---

## Part 3 — Known limitations

### Group A — Data collection (the actual bottleneck)

`VMTRACE_CAPACITY` is **128** events. `VMTRACE_READ_MAX` is **8**. Each
`struct vmtrace_event` is 19 × `uint64` = **152 bytes**.

Training needs on the order of 10^5–10^7 events. The ring holds 128 before
overwriting. Under any real workload it wraps constantly and `drops` climbs
without bound. **Nothing downstream of this works until it is fixed.**

A trace with silent holes is worse than no trace, because the model will learn
from a biased sample without anything flagging it.

### Group B — Scale ceilings

| Constant | File | Current | Consequence |
|---|---|---|---|
| `NSWAPSLOTS` | `kernel/swap.h` | 1024 | 4MB swap ceiling → working sets capped at ~4MB |
| `FSSIZE` | `kernel/param.h` | 2000 | 2MB filesystem |
| `MAXFILE` | `kernel/fs.h` | 268 blocks | **274,432 bytes** max file, including program binaries |
| `USERSTACK` | `kernel/param.h` | 1 | 4KB user stack; deep recursion faults |
| `NBUF` | `kernel/param.h` | 30 | Tiny block cache — **leave this alone**, pressure belongs in the paging layer |

`MAXFILE = NDIRECT (12) + NINDIRECT (256) = 268` blocks at `BSIZE 1024`.

### Group C — User environment

**`user/ulib.c` provides:** `strcpy`, `strcmp`, `strlen`, `memset`, `strchr`,
`gets`, `stat`, `atoi`, `memmove`, `memcmp`, `memcpy`, `sbrk`, `sbrklazy`, plus
`malloc`/`free` from `umalloc.c` and `printf`/`fprintf` from `printf.c`.

**Missing:** `strncmp`, `realloc`, `snprintf`, `errno`, all of `<math.h>`.

**Syscalls (29 total):** no `lseek`, no `pread`/`pwrite`, no `ftruncate`, no
real time-of-day, no sockets.

**Build:** `CFLAGS += -march=rv64gc` with no explicit `-mabi`, so the default
`lp64d` (hard float) applies. Linking is `$(LD)` directly under `-nostdlib`,
so libgcc is absent.

**The floating-point position, stated in full.** There is no safe floating point
anywhere in this system, kernel or user. The RISC-V toolchain defaults to the
hard-float ABI (`-mabi=lp64d`) even though nothing in the build explicitly
requests it. `kernel/swtch.S` saves and restores integer registers only — zero
FP registers — and nothing anywhere enables `sstatus.FS`. Any program that
executes an FP instruction will therefore either trap on an illegal instruction
or silently corrupt another process's FP state.

This is deliberate, not an oversight. The intended learned policy is a **frozen,
pre-trained, fixed-point/quantised model**, specifically so that no floating
point is ever needed in the kernel. Production kernels avoid FP for exactly
these reasons. Every decision below preserves that position: where floating
point is unavoidable in user space (Phase 3), it is handled with a soft-float
ABI and libgcc, not by enabling FP in the kernel.

### Group D — Deliberately out of scope

Declared as non-goals in the original plan; the judgement is correct, but each
must be **named explicitly in the thesis** rather than left for a reviewer to
discover:

- No global Linux-style memory reclaim
- No copy-on-write fork
- No shared memory, no memory-mapped files
- No file-backed executable demand paging (binaries load eagerly)
- No transparent multicore eviction of another running process. CPUS=1 is the
  scientific reference configuration; CPUS=3 may be used as a stress test only.
  Multicore paging correctness must not be claimed unless a real cross-hart TLB
  shootdown design is implemented and tested
- No QEMU instrumentation or host-kernel changes
- No networking stack — this is what makes Redis genuinely infeasible rather
  than merely difficult

One further standing rule from the plan, worth repeating because it is easy to
violate by accident: **do not reduce QEMU's `-m` value to create memory
pressure.** xv6 assumes physical memory extends to `PHYSTOP`. Keep QEMU at
128 MiB and enforce a logical user-resident frame limit inside xv6.

### Group E — Methodology risks

**Self-selection.** Hand-written benchmarks mean the access pattern was chosen
by the same person who designed the model. Defence: either run software you did
not write, or fix and publish the workload properties *before* training.

**Feature-space coverage.** The model does not learn "SQLite." It learns a map
from `(recency, frequency, age, dirty, referenced, aging_counter, fault
history)` to near-term reuse. Those features carry no program identity.
Generalisation therefore depends on whether training data **spans** the range of
reuse distances, working-set sizes and phase behaviours — not on provenance.

**The trivial-policy trap.** Train on purely sequential access and the model
learns "evict oldest," reinventing FIFO with inference overhead. The property
that makes learning worthwhile is workloads where **no single fixed heuristic
wins throughout**.

---

## Part 4 — Phases

> **Status: Phases 0, 1 and 2 are complete.**
> Phase 0 and Phase 1: `docs/phase0-phase1-report.md`.
> Phase 2: `docs/phase2/report.md` (analysis and conclusions),
> `docs/phase2/static-checks.md` (Step 1), `docs/phase2/gate-results.txt`
> (74 steps, 0 failures), `docs/vm-baseline.txt` (Step 9), tag
> `platform-v1.0`. Reproduce with `bash tools/phase2_gate.sh all`.
>
> Phase 2 found three defects — a kernel I/O-accounting bug that undercounted
> asynchronous prefetch reads by 41%, a randomised soak that had silently
> stopped paging, and a measurement artefact in Phase 2's own baseline that
> ran each policy at a different resident limit.
>
> It also measured a negative result: at `platform-v1.0` lossless tracing
> did not reach dataset scale — the drainer kept 53% of the stream and only
> 32% of events arrived intact. **`platform-v1.1` resolves it.** The ring is
> 262,144 records, a per-event-type mask halves the stream on demand, and
> the reference paging workload now captures with **zero loss** in both
> modes. The remaining Phase 4 work on tracing is the two *content* gaps,
> not volume: there is no reference string for a true Belady label, and
> eviction records carry the chosen victim's state but not the candidates'.
>
> **Next: Phase 3 (SQLite spike), or Phase 4 if the reduced-scope fallback
> in Part 7 applies.**


Each phase lists steps, an exit gate, and — under **What this establishes** —
the conclusion the phase actually supports. Do not start a phase before its
predecessor's gate is green.

---

### Phase 0 — Trace infrastructure  *(Effort: M)*

**Goal:** produce lossless traces at dataset scale.

**Steps**

- [x] Raise `VMTRACE_CAPACITY` from 128 to 65536 in `kernel/vmtrace.h`
- [x] Raise `VMTRACE_READ_MAX` from 8 to 256
- [x] Pack `struct vmtrace_event`:
  - [x] Move `version` and `size` out of the per-record struct into a one-time
        header returned by a separate call or written once at file start
  - [x] Narrow `type`, `access`, `page_state`, `status`, `policy` to `uint8`
  - [x] Narrow `vpn`, `victim_vpn`, `frame_index`, `swap_slot`,
        `resident_count`, `pid`, `queue_id` to `uint32`
  - [x] Keep `sequence`, `cycle`, `ticks`, `generation`, `pte_flags` at 64 bits
  - [x] Target ≤ 48 bytes per record
- [x] Bump `VMTRACE_VERSION` and update the schema test
- [x] Write `user/vmdrain.c` — a dedicated process that loops on
      `vmtrace_read()` and writes raw records to a file
- [x] Write `tools/decode_trace.py` — host-side binary → structured records
- [x] Add a `drops` assertion path: any experiment with `drops != 0` is marked
      invalid, not merely warned about

**Gate**

- [x] `vmtest swap-repeat` under tracing completes with `drops == 0`
- [x] `vmtest trace-schema`, `trace-wrap`, `trace-disabled`, `trace-drop` pass
- [x] Decoder round-trips a 1M-event capture without loss or misalignment
- [x] The original tracing requirements still hold after the rework:
  - [x] Event records have a stable version and byte size
  - [x] Ring wrap preserves the ordering of retained records
  - [x] Overflow increments `TRACE_DROP` without corrupting adjacent kernel
        memory
  - [x] Disabled tracing emits no records and does not change paging results
  - [x] Trace buffers and metadata are non-pageable
  - [x] Trace reads crossing swapped user-buffer pages complete correctly
- [x] Every experiment is run twice thereafter: once with tracing enabled for
      the dataset, once with tracing disabled for uncontaminated timing

**What this establishes**

- *Claim licensed:* "Every paging event in our experiments is recorded; no
  sampling, no loss." That single sentence is what makes every later number
  defensible.
- *Ruled out:* that a model was trained on a silently biased subset of events.
  Without a zero-drop guarantee you cannot distinguish "the model learned
  something real" from "the model learned the shape of the ring buffer's
  overflow pattern."
- *Negative result available here:* if the packed record still cannot keep up
  with the fault rate, that is itself a finding about the cost of kernel-
  resident instrumentation, and it forces an explicit, reported sampling rate
  rather than an accidental one.
- *What you still cannot say:* anything about replacement quality. This phase
  concerns instrument integrity only.

---

### Phase 1 — Raise the ceilings  *(Effort: M)*

**Goal:** remove the size limits that cap working sets and block real binaries.

**Steps**

- [x] `kernel/swap.h`: `NSWAPSLOTS` 1024 → 8192 (32MB swap)
- [x] `kernel/param.h`: `USERSTACK` 1 → 16
- [x] `kernel/param.h`: `FSSIZE` 2000 → 100000
- [x] `kernel/fs.h`: `NDIRECT` 12 → 11; add doubly-indirect entry; update
      `MAXFILE` to `NDIRECT + NINDIRECT + NINDIRECT*NINDIRECT` (65803 blocks
      ≈ 64MB); keep `addrs[]` the same size in `struct dinode`
- [x] `kernel/file.h`: match `addrs[]` length in `struct inode`
- [x] `kernel/fs.c`: extend `bmap()` for the doubly-indirect level
- [x] `kernel/fs.c`: extend `itrunc()` to free doubly-indirect blocks
- [x] **`mkfs/mkfs.c`: apply the same block-mapping change** — it has its own
      independent copy of the logic
- [x] Confirm `fs.img` truncation arithmetic in the Makefile still resolves
      (`FSSIZE * BSIZE + NSWAPSLOTS * 4096`)

**Gate**

- [x] `usertests -q` passes
- [x] `grind` passes
- [x] A 5MB file writes, reads back byte-exact, and deletes with no block leak
- [x] `vmtest all` and `prefetchtest all` pass under FIFO, Clock, and Aging
- [x] `vmcheck` clean after each

**Risk:** the `mkfs` half is the one that gets forgotten. The symptom is a
kernel that can read large files but a build that cannot create them.

**What this establishes**

- *Claim licensed:* "Working-set sizes in this study are bounded by
  experimental design, not by an artefact of the teaching kernel." Before this
  phase, every result would carry the caveat that the swap ceiling was 4MB and
  the largest possible file was 274KB — small enough that a reviewer can
  reasonably ask whether anything observed generalises past cache size.
- *Unlocked:* the ability to host any real third-party binary at all (Phase 3),
  and to run workloads whose data does not fit in the block cache (Phase 4).
- *Ruled out:* "your policy differences are just noise because nothing ever
  exceeded a few megabytes."
- *Negative result available here:* if raising the ceilings changes the relative
  ranking of FIFO/Clock/Aging on the *existing* tests, that is a scale-
  sensitivity finding worth recording — and a warning that any result taken at
  the old ceiling was an artefact.

---

### Phase 2 — Freeze the platform  *(Effort: S)*

**Goal:** a known-good, reproducible baseline to bisect against later.

This phase is the outstanding regression matrix and acceptance checklist from
the implementation plan. Both are reproduced in full below so this document
stands alone.

**Step 1 — Static checks**

```
git status --short
git diff --check
git diff --stat
rg -n "\*pte[[:space:]]*(=|\|=|&=)" kernel
rg -n "PTE_SWAPPED|PTE_BUSY|sfence_vma" kernel
rg -n "kalloc\(" kernel/vm.c kernel/exec.c kernel/proc.c
rg -n "uvmunmap|uvmdealloc|uvmfree|freewalk|freeproc" kernel
rg -n "uvmcopy|copyin|copyout|copyinstr|vm_fault" kernel
rg -n "swap_slot_(alloc|get|put)|inflight|prefetch" kernel
```

Every PTE mutation found by the first search must be manually classified as one
of: page-table construction; resident mapping installation; A/D sampling;
swap/fetch transition; permission change; unmap/cleanup.

**Step 2 — Debug matrix**

```
make clean
make -j"$(nproc)" CPUS=1 VM_DEBUG=1

python3 tools/run_xv6_tests.py --cpus 1 --timeout 1200 "usertests -q"
python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 "grind"
python3 tools/run_xv6_tests.py --cpus 1 --timeout 2400 "vmtest all"
python3 tools/run_xv6_tests.py --cpus 1 --timeout 2400 "prefetchtest all"
```

**Step 3 — Policy matrix**

```
for p in fifo clock aging; do
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 \
    "vmtest all-policy $p" || exit 1
done
```

**Step 4 — Release build, no debug instrumentation**

```
make clean
make -j"$(nproc)" CPUS=1
python3 tools/run_xv6_tests.py --cpus 1 --timeout 1200 "usertests -q"
python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 "vmtest all"
python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 "prefetchtest all"
```

**Step 5 — Optional multiprocessor stress** (stress only; not a release claim
unless cross-hart TLB requirements are fully addressed)

```
make clean
make -j"$(nproc)" CPUS=3 VM_DEBUG=1
python3 tools/run_xv6_tests.py --cpus 3 --timeout 2400 "vmtest multiproc"
python3 tools/run_xv6_tests.py --cpus 3 --timeout 2400 "prefetchtest worker-stress"
```

**Step 6 — Long randomised soak**

```
for seed in 1 2 3 4 5 17 31 127 1024 65535; do
  python3 tools/run_xv6_tests.py --cpus 1 --timeout 1800 \
    "vmtest random $seed 100000" || exit 1
done
```

**Step 7 — Regression gate**

- [x] The complete debug and release matrices pass from a clean build
- [x] Every randomised seed passes, or has a preserved reproducible failure log
- [x] All policy and prefetch modes produce identical application data results
- [x] `vmcheck` and final statistics report zero leaked frames, slots, requests,
      and in-flight operations after the test processes exit
- [x] `git diff --check` is clean and `git status` shows no unintended files

**Step 8 — Final acceptance criteria.** The platform is complete only if every
statement below is true:

- [x] Existing xv6 `usertests` and `grind` pass
- [x] A process can correctly use much more virtual memory than its resident
      frame limit
- [x] Byte patterns survive repeated swap-out/swap-in under FIFO, Clock, and
      Aging
- [x] Lazy holes, resident pages, swapped pages, and fetching pages are never
      confused
- [x] Unmap, shrink, failed exec, successful exec, exit, and kill release every
      frame, slot, request, and I/O reference
- [x] Fork works when source pages are lazy, resident, swapped, or temporarily
      busy
- [x] `copyin`, `copyout`, and `copyinstr` work across swapped page boundaries
- [x] Original read/write/execute/user permissions survive swapping
- [x] Swap-full and disk-error cases fail gracefully without corrupting the
      filesystem or panicking the kernel
- [x] Policies cannot select pinned, busy, foreign, or invalid pages
- [x] Invalid learned/predictive decisions fall back to Clock
- [x] Prefetch hints are bounded, duplicate requests are coalesced, demand has
      priority, and usefulness/waste are measurable
- [x] Demand-vs-prefetch, unmap-vs-prefetch, exit-vs-prefetch, and I/O-error
      races pass deterministic delay-injection tests
- [x] `vmcheck` passes throughout debug stress and all counters return to their
      baseline after test processes exit
- [x] The exact baseline commit, tool versions, configuration, frame limit,
      swap size, policy, prefetch mode, and random seed are printed for every
      experiment

**Step 9 — Record and tag**

- [x] Record compiler and QEMU versions in `docs/vm-baseline.txt`
- [x] Record baseline fault/eviction counts for FIFO, Clock, and Aging on the
      existing test programs
- [x] Tag the commit `platform-v1.0`
- [x] Retain all logs under `test-logs/`

**What this establishes**

- *Claim licensed:* "The platform is correct, and correctness is independent of
  replacement policy." The policy matrix proving that FIFO, Clock, and Aging
  produce **identical application data** is the specific evidence that any later
  difference between policies is a performance difference and not a bug.
- *Ruled out:* the worst possible thesis outcome — discovering at the end that a
  reported improvement came from a lifecycle bug (a leaked slot, a lost dirty
  bit, an eviction that quietly dropped data) rather than from better victim
  selection.
- *Also established:* a reproducibility baseline. The commit tag, tool versions,
  and recorded baseline counts are what let you say a later number changed
  *because of the change you made*.
- *Negative result available here:* any acceptance criterion that cannot be
  ticked is a scope limitation that must be declared in the thesis rather than
  quietly omitted.
- *Why this is not bureaucracy:* everything after this point is research. When a
  later experiment produces an implausible number, this tag is the point you
  bisect back to. Skipping it means later debugging has no fixed point.

---

### Phase 3 — SQLite spike (hard timebox)  *(Effort: L, abandonable)*

**Goal:** determine whether a real, third-party application can run — and
therefore whether the thesis gets a *methodological independence* argument.

**Steps**

- [ ] Verify the soft-float multilib exists:
      `riscv64-unknown-elf-gcc -print-multi-lib | grep lp64` — **do this first**
- [ ] Add `strncmp` to `user/ulib.c` and `user/user.h`
- [ ] Add `SYS_pread` / `SYS_pwrite` syscalls (positional I/O; preferred over
      `lseek` — no shared file offset, fewer syscalls per page)
- [ ] Switch user-space build to `-march=rv64imac -mabi=lp64`
- [ ] Add libgcc to the link line:
      `$(shell $(CC) -march=rv64imac -mabi=lp64 -print-libgcc-file-name)`
- [ ] Re-run `usertests -q` — the ABI change touches every existing UPROG
- [ ] Build the SQLite amalgamation with:
      `-DSQLITE_OS_OTHER=1 -DSQLITE_THREADSAFE=0 -DSQLITE_ZERO_MALLOC`
      `-DSQLITE_ENABLE_MEMSYS5 -DSQLITE_OMIT_WAL -DSQLITE_TEMP_STORE=3`
      `-DSQLITE_DEFAULT_MEMSTATUS=0 -DSQLITE_OMIT_LOAD_EXTENSION -Os`
- [ ] Provide `sqlite3_os_init()` / `sqlite3_os_end()` registering an xv6 VFS
      adapted from upstream `test_demovfs.c`
- [ ] Hand SQLite a heap via `sqlite3_config(SQLITE_CONFIG_HEAP, ...)` over an
      `sbrk`'d arena — this removes the `realloc` dependency entirely
- [ ] Stub `xLock`/`xUnlock`/`xCheckReservedLock` (single process)
- [ ] Stub `xCurrentTime`, `xSleep`, `xRandomness`
- [ ] Target: `speedtest1` runs

**Gate — this is a go/no-go, not a milestone**

- [ ] SQLite executes `CREATE TABLE`, `INSERT`, and `SELECT` correctly

**If the gate is not met, abandon SQLite permanently.** Do not extend the
timebox. The native workload suite carries the thesis either way.

**Kept regardless of outcome:** soft-float build, `pread`/`pwrite`, `strncmp`.

**Configuration note for later:** if SQLite does run, avoid the failure mode
where its own page cache absorbs all the interesting behaviour. Either use an
in-memory database (`:memory:`, whole DB in the heap), or a large `cache_size`
over a large on-disk DB so the buffer pool itself exceeds the resident limit.

**What this establishes**

- *If it succeeds — claim licensed:* "The evaluation includes an application we
  did not write and whose access pattern we did not choose." This is the
  strongest available answer to the self-selection objection in Group E, and it
  is the entire reason to attempt the port. It is **not** primarily about
  realism; a hand-written B+tree can match SQLite's page-level behaviour closely.
  It is about independence.
- *If it succeeds — also unlocked:* a genuine cross-domain held-out test set in
  Phase 8, where training and deployment differ in allocator, address-space
  layout, and program identity.
- *If it fails — claim licensed:* "Hosting unmodified third-party software on a
  teaching kernel is bounded by the user-space environment, not the VM
  subsystem." Document precisely which of the missing pieces blocked it. That is
  a legitimate, reportable systems finding about the cost of workload realism on
  minimal kernels, and it justifies the native-workload methodology to a
  reviewer far better than silence would.
- *Either way:* the phase converts an open question into a decided one early,
  which is its real function. A failure discovered here costs two weeks; the
  same failure discovered late would cost the thesis.

---

### Phase 4 — Workload suite  *(Effort: L)*

**Goal:** benchmarks with the right statistical properties, driven by real input
data rather than synthetic distributions alone.

**Steps** — build six programs, each with a burn-in phase, a fixed seed, and a
recorded configuration banner:

- [ ] **B+tree** over an `sbrk`'d arena, 4KB nodes — root-to-leaf pointer
      chasing, hot upper levels, cold leaves, sequential leaf scans
- [ ] **Hash table, Zipfian keys**, YCSB-style read/write mixes. Precompute the
      Zipf CDF as a fixed-point integer table on the host; binary-search it with
      an integer PRNG (no FP in the generator)
- [ ] **BFS or PageRank** over a *real* graph shipped in `fs.img`
- [ ] **LZ4 or LZW** over a *real* text corpus
- [ ] **External merge sort**
- [ ] **Blocked vs. naive matrix multiply** — a deliberate locality contrast
      pair, integer arithmetic only

**Gate**

- [ ] Each produces a trace with `drops == 0`
- [ ] Reuse-distance histograms plotted for all six
- [ ] The six histograms are visibly distinct — they do not collapse onto one
      shape

**What this establishes**

- *Claim licensed:* "Our training and evaluation data span a wide range of
  reuse-distance distributions, working-set sizes, and phase behaviours."
  Because the model learns from kernel-observable features that carry no program
  identity, coverage of the feature space — not provenance — is what
  generalisation actually depends on. This phase is where that coverage is
  demonstrated rather than asserted.
- *Ruled out:* "you picked workloads your model likes." The reuse-distance plot,
  produced **before** any training, is the artefact that answers this. Produced
  after training, it answers nothing.
- *Negative result available here:* if the six histograms collapse onto one
  shape, you have learned that your benchmark design is not as diverse as
  intended, and you must add or replace workloads before spending effort on a
  dataset. Better to find this now than in Phase 6 when the model refuses to
  generalise.
- *Also established:* the locality contrast pair (blocked vs. naive matmul) is a
  sanity check on the whole apparatus. If your instrumentation cannot
  distinguish those two, something is wrong upstream.

---

### Phase 5 — Dataset and offline baselines  *(Effort: M)*

**Goal:** a labelled dataset, and the honest answer to whether there is any
headroom for learning at all.

**Steps**

- [ ] Collect traces: 6 workloads × several resident limits × 3 policies
- [ ] Host pipeline: trace → per-eviction-decision feature vectors
- [ ] Implement a **Belady oracle** offline — the trace contains the full
      future, so optimal is directly computable
- [ ] Label each decision against the oracle
- [ ] Measure FIFO / Clock / Aging / Belady fault counts on every workload
- [ ] Plot the Clock-to-Belady gap per workload and per resident limit

**Gate**

- [ ] Oracle implementation validated on a small hand-checkable trace
- [ ] Gap analysis complete

**What this establishes**

- *Claim licensed:* "Here is the maximum improvement any replacement policy
  could achieve on these workloads, and here is how much of it existing
  heuristics already capture." This is the headroom number, and it determines
  whether the rest of the project is worth doing.
- *This is your first genuine result, and it exists whether or not the ML
  works.* A characterisation of where classical heuristics fall short of optimal
  — and under which working-set-to-memory ratios — is publishable on its own.
- *Decision forced:* if the Clock-to-Belady gap is small across all workloads
  and all resident limits, then no learned policy can help much, and continuing
  to Phase 6 would be building a solution to a non-problem. The correct response
  is to pivot the thesis framing to "learned replacement is not worth its cost
  in this regime, and here is the evidence" — which is a real contribution, not
  a failure.
- *Ruled out:* reporting a small improvement over Clock without context. Once
  the oracle bound is known, every later result can be stated as a fraction of
  the achievable gap rather than as a bare percentage.

---

### Phase 6 — Offline model  *(Effort: M)*

**Goal:** know whether a kernel-deployable model beats Clock, before writing any
kernel code.

**Steps**

- [ ] Train on the host in Python — no kernel involvement at all
- [ ] Start simple: logistic regression or a shallow decision tree over
      `recency`, `frequency`, `age`, `dirty_sample`, `referenced_sample`,
      `aging_counter`, and fault history
- [ ] **Split by workload, not by random sample.** Hold out entire workloads.
      Training on 80% of a B+tree trace and testing on the other 20% proves
      nothing
- [ ] Evaluate against the Belady labels: fraction of matching decisions, and
      simulated fault count if the model's choices were followed
- [ ] Quantise to fixed point and re-evaluate
- [ ] Estimate inference cost in integer ops per eviction

**Gate**

- [ ] The **quantised** model beats Clock by a margin that justifies its
      inference cost
- [ ] If not: stop. Revisit features or workloads. Do not write kernel code.

**What this establishes**

- *Claim licensed:* "A model constrained to kernel-observable features and
  fixed-point arithmetic captures X% of the gap between Clock and optimal." Both
  constraints matter: a floating-point model with access to future information
  would be a different and much weaker claim.
- *Critical separation:* the quantisation step is evaluated *before* kernel
  work, so if fixed-point conversion destroys the advantage you learn it in
  Python rather than after weeks of kernel debugging. This is the single most
  common way projects of this shape waste time.
- *Ruled out:* an inflated result from same-workload testing. Splitting by
  workload rather than by sample means the reported number is a generalisation
  number from the start.
- *Negative result available here:* "simple learned scorers over
  kernel-observable features do not beat Clock at realistic inference budgets"
  is a clean, useful finding. It says something specific about which features
  are available to an OS at eviction time, which is a real constraint the
  cache-replacement literature often assumes away.

---

### Phase 7 — In-kernel learned policy  *(Effort: M)*

**Goal:** the model runs inside xv6, safely.

**Steps**

- [ ] Add `VM_POLICY_LEARNED` as index 3; `VM_POLICY_COUNT` → 4
- [ ] Implement the policy against the existing interface: `init`,
      `page_inserted`, `page_sampled`, `page_removed`, `choose_victim`
- [ ] Fixed-point inference only — **no floating point in the kernel**, per the
      position stated in Group C
- [ ] Model parameters as a static const table; no runtime allocation
- [ ] Wire through the existing candidate validation and Clock fallback
- [ ] Add a counter for how often the fallback fires

**Gate**

- [ ] `vmtest policies-correctness` passes under the learned policy — byte-exact
      application results identical to FIFO
- [ ] `vmtest invalid-policy-fallback` still passes
- [ ] `vmcheck` clean throughout
- [ ] Inference cost per eviction measured and reported as overhead
- [ ] Learned-policy fault counts match the offline simulation from Phase 6

**What this establishes**

- *Claim licensed:* "The policy runs in a real kernel, at real eviction time,
  with no floating point and no dynamic allocation, and the measured fault
  counts match the offline prediction." The match between kernel and simulator
  is the important part: it validates the offline methodology retroactively.
- *Safety contribution, and it deserves its own section in the write-up:* a bad,
  stale, or adversarial model **cannot corrupt memory**, because the common
  engine validates every returned victim and falls back to Clock on a pinned,
  busy, foreign, or out-of-range answer. Most learned-systems work assumes the
  model is trusted. This design does not, and the fallback counter quantifies
  how often the assumption would have been violated.
- *Ruled out:* "it only works in simulation." Also ruled out: hidden costs — the
  overhead is measured in the same kernel that produces the benefit, so the
  net-benefit claim is honest.
- *Negative result available here:* if kernel fault counts diverge from the
  offline simulation, something in the feature pipeline differs between trace
  time and decision time. That discrepancy is worth chasing and reporting; it is
  a known hazard in learned-systems deployment.

---

### Phase 8 — Generalisation and workload shift  *(Effort: M)*

**Goal:** the analysis the grant promises — where it fails under workload shift.

**Steps**

- [ ] Train on workloads A–D, test on E–F
- [ ] Sweep resident limits at test time that were not seen during training
- [ ] If Phase 3 succeeded: use SQLite traces as a **pure held-out set**.
      Training and deployment then differ in allocator, address-space layout,
      and program identity — the strongest available test
- [ ] Characterise *which* feature-space regions degrade, not just that
      accuracy drops

**Gate**

- [ ] The experiment is designed so that **either outcome is a result.**
      "The model degrades under shift toward real applications" is legitimate
      and publishable; it must not be treated as a failure condition

**What this establishes**

- *Claim licensed:* "The policy's advantage does / does not survive a shift to
  workloads absent from training, and here are the specific feature-space
  regions where it breaks down." The second half is what distinguishes an
  analysis from a leaderboard entry.
- *Directly answers the reviewer's question* — "does this work on real
  applications?" — with a number rather than a hope, and it produces a publishable
  answer either way.
- *Ruled out:* the accusation that reported gains are memorisation of the
  training workloads. Unseen resident limits test the same thing along a second
  axis.
- *Negative result available here, and it is the expected one:* degradation
  under shift is the normal outcome in learned-systems work. Reporting *where*
  and *how much* is more valuable than a uniformly good number, because it tells
  a future implementer when the policy is safe to enable.

---

### Phase 9 — Write-up  *(Effort: L, overlapping)*

**Steps**

- [ ] Draft the platform/implementation chapter starting during Phase 5 — it is
      already fully specified by the implementation plan and does not depend on
      any result
- [ ] Explicitly name every Group D non-goal as declared scope
- [ ] Report the trace-drop discipline as a data-integrity method
- [ ] Report inference overhead honestly alongside fault-count improvements
- [ ] State every result as a fraction of the Clock-to-Belady gap from Phase 5,
      not as a bare percentage
- [ ] Results, analysis, revision

**What this establishes**

- *Claim licensed:* the thesis itself. Note that the implementation chapter is
  writable from Phase 5 onward regardless of how Phases 6–8 turn out, so a
  substantial portion of the document is never at risk from a negative result.
- *Ruled out:* the scenario where scope limitations are discovered by an
  examiner rather than declared by the author. Naming the Group D non-goals
  converts them from weaknesses into design decisions.

---

## Part 5 — What each phase lets you claim

| Phase | Conclusion it supports | Value if it "fails" |
|---|---|---|
| 0 Trace | Data is complete and unbiased | Forces an explicit, reported sampling rate; a finding about instrumentation cost |
| 1 Ceilings | Results are not artefacts of a 4MB swap and 274KB files | Scale-sensitivity finding; invalidates any earlier small-scale result |
| 2 Freeze | Correctness is independent of policy; results are reproducible | Any unticked criterion becomes a declared scope limitation |
| 3 SQLite | Evaluation includes software we did not write | A reportable systems finding on the cost of workload realism |
| 4 Workloads | Training data spans the feature space | Reveals insufficient benchmark diversity before the dataset is built |
| 5 Baselines | Here is the achievable headroom over Clock | If headroom is small, pivot the thesis — a real contribution |
| 6 Offline model | A fixed-point, kernel-feasible model captures X% of it | "Simple learned scorers don't beat Clock at realistic budgets" is publishable |
| 7 In-kernel | It runs for real, at measured cost, and cannot corrupt memory | Kernel/simulator divergence exposes a feature-pipeline bug worth reporting |
| 8 Shift | Where it generalises and where it breaks | Degradation is the expected result and is the analysis, not a failure |
| 9 Write-up | The thesis | — |

The pattern worth noticing: **every phase from 3 onward has a defensible
negative outcome.** None of them can sink the project, provided the phase before
it was completed honestly. That property is deliberate and is the reason for
this ordering.

---

## Part 6 — Decision points

| After phase | Question | If the answer is no |
|---|---|---|
| 0 | Zero trace drops under load? | Fix before anything else. Non-negotiable. |
| 1 | Big files work in both kernel and mkfs? | Do not proceed; the binary won't fit later. |
| 2 | Every acceptance criterion ticked with evidence? | Stop and fix. Research on an unverified platform is wasted. |
| 3 | Does SQLite run a query? | Drop it permanently. Native workloads carry the thesis. |
| 4 | Do the six workloads span distinct reuse-distance profiles? | Add or replace workloads before collecting the dataset. |
| 5 | Is the Clock-to-Belady gap large anywhere? | Pivot the thesis framing now: "learned replacement is not worth it in this regime" is a valid contribution. |
| 6 | Does the quantised model beat Clock offline? | Do not write kernel code. Revisit features. |
| 7 | Do kernel fault counts match the offline simulation? | Chase the discrepancy; it is a feature-pipeline bug, and it is reportable. |

---

## Part 7 — Reduced-scope fallback

If time compresses, cut in this order:

1. **Phase 3 (SQLite)** — first to go. It buys an argument, not a capability.
2. **Phase 4** — reduce from six workloads to four. Keep the B+tree, the
   Zipfian hash table, the graph traversal, and the locality contrast pair.
3. **Phase 8** — fold a smaller shift experiment into Phase 7 rather than
   running it standalone.

**Never cut:**

- Phase 0 (the trace fix) — without it there is no data
- Phase 2 (the platform freeze) — without it there is no trustworthy result
- Phase 5's Belady baseline — without it there is no way to say whether any of
  this was worth doing, and no denominator for any improvement you report

---

## Appendix A — Constants quick reference

| Constant | File | Now | Target |
|---|---|---|---|
| `VMTRACE_CAPACITY` | `kernel/vmtrace.h` | 128 | 65536, then 262144 at v1.1 |
| `VMTRACE_READ_MAX` | `kernel/vmtrace.h` | 8 | 256 |
| `sizeof(struct vmtrace_event)` | `kernel/vmtrace.h` | 152 B | ≤ 48 B |
| `NSWAPSLOTS` | `kernel/swap.h` | 1024 | 8192 |
| `FSSIZE` | `kernel/param.h` | 2000 | 100000 |
| `USERSTACK` | `kernel/param.h` | 1 | 16 |
| `NDIRECT` | `kernel/fs.h` | 12 | 11 + doubly-indirect |
| `MAXFILE` | `kernel/fs.h` | 268 blocks | 65803 blocks |
| `NBUF` | `kernel/param.h` | 30 | unchanged (deliberate) |
| `VM_POLICY_COUNT` | `kernel/vmstats.h` | 3 | 4 |
| user ABI | `Makefile` | `rv64gc` / `lp64d` | `rv64imac` / `lp64` |

## Appendix B — Files touched per phase

- **Phase 0:** `kernel/vmtrace.h`, `kernel/vmtrace.c`, `user/vmdrain.c` (new),
  `tools/decode_trace.py` (new), `user/vmtest.c`, `Makefile`
- **Phase 1:** `kernel/param.h`, `kernel/swap.h`, `kernel/fs.h`, `kernel/fs.c`,
  `kernel/file.h`, `mkfs/mkfs.c`
- **Phase 2:** `docs/vm-baseline.txt`, `test-logs/`
- **Phase 3:** `Makefile`, `user/ulib.c`, `user/user.h`, `user/usys.pl`,
  `kernel/syscall.h`, `kernel/syscall.c`, `kernel/sysfile.c`,
  `user/sqlite3.c` + `user/xv6vfs.c` (new)
- **Phase 4:** `user/*.c` (new benchmarks), `Makefile` (UPROGS), `mkfs` inputs
- **Phase 5–6:** host-side only
- **Phase 7:** `kernel/vmstats.h`, policy implementation, `user/vmtest.c`

## Appendix C — Standing rules carried over from the implementation plan

These applied during platform construction and continue to apply to every
experiment:

1. Complete one phase and its gate before beginning the next.
2. Keep commits small and phase-specific; never combine swap correctness with
   ML policy work.
3. After each failure, preserve the failing seed, QEMU output, `vmstats`, and
   the last trace records.
4. Never fix a lifecycle failure by disabling the test or by leaking or pinning
   the affected page permanently.
5. Never hold a spinlock across disk I/O or sleep.
6. Never reuse a proc, frame, swap slot, or request object until all in-flight
   references have drained.
7. Run `git diff --check` and the phase regression before every commit.
8. If the design deviates from the plan, document the changed invariant, the
   reason, and the replacement test *before* coding the deviation.
