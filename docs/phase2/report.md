# Phase 2 — Freeze the platform: completion report

What the freeze actually consisted of, the three defects it found, the
conclusions the evidence licenses, and what is deliberately left undone.

Companion documents:

- `docs/phase2/static-checks.md` — Step 1, the PTE mutation audit
- `docs/phase2/gate-results.txt` — Steps 2–8, every step with its duration
  and exit status
- `docs/vm-baseline.txt` — Step 9, the recorded reference point
- `docs/phase0-phase1-report.md` — the phases this one certifies

---

## 1. Status

**Phase 2 is complete.** The full matrix runs clean from a clean build in
both configurations, and every one of the fifteen acceptance criteria is
ticked with named evidence (§5).

| | |
|---|---|
| Steps in the matrix | 74 |
| Failures | 0 |
| Configurations | `CPUS=1` release, `CPUS=1 VM_DEBUG=1`, `CPUS=3 VM_DEBUG=1` (stress only) |
| Policies exercised | FIFO, Clock, Aging — each under both prefetch modes |
| Randomised seeds | 1, 2, 3, 4, 5, 17, 31, 127, 1024, 65535 — in both configurations |
| Wall clock | about 80 minutes, of which 53 are two `usertests -q` runs |

Reproduce with:

```sh
bash tools/phase2_gate.sh all        # or: debugbuild debugtests
                                     #     releasebuild releasetests
                                     #     bigtrace smp
```

---

## 2. What Phase 2 added

Phase 2 is a freeze, not a feature phase, so the additions are all
instruments — things that turn an assertion into evidence.

### 2.1 `vmtest data-invariance`

The acceptance criterion *"all policy and prefetch modes produce identical
application data results"* had no direct test. Every existing policy test
fixes one policy and checks that process in isolation, which establishes
that each policy is individually correct but never that they agree.

`data-invariance` runs one deterministic 64-page workload — write the
pattern, read it back four times alternating direction, then 1024
pseudorandom probes — under all three policies crossed with synchronous and
asynchronous prefetch, six configurations in all.

Three design decisions matter more than the test itself:

**Each configuration runs in its own forked child.** The first version
reconfigured a single process in a loop and was wrong in an instructive
way — see §3.3.

**The comparison is against a value derived from the pattern definition,
not against another run.** `expected_workload_checksum()` computes the
answer arithmetically without touching memory. Comparing configurations
only to each other would pass if a bug corrupted all six identically;
comparing each to the specification cannot.

**Three guards, so the test cannot pass vacuously.** Per configuration it
asserts that eviction and swap-fault counts are non-zero (the region really
cycled through swap), that `prefetch_accepted` is non-zero (prefetch really
engaged in this mode), and a conservation inequality on swap read I/O that
is what caught the defect in §3.1.

### 2.2 `vmtest baseline`

The same workload with prefetch disabled, printing per-policy fault,
eviction and I/O counts. This is the Step 9 reference table: the numbers a
later change is bisected against.

### 2.3 Provenance on every transcript

Acceptance criterion 15 asks that the configuration of every experiment be
*printed*, not reconstructed afterwards. Two halves:

- `kernel/main.c:vm_print_config()` prints the compile-time paging
  configuration at boot — frame count, resident-limit ceiling, policy
  count, swap slots, filesystem size, `NBUF`, `USERSTACK`, trace version,
  ring capacity, record size, and whether `VM_DEBUG` is on. A transcript
  without these two lines was produced by a different kernel than the
  numbers are attributed to.
- `tools/run_xv6_tests.py` writes a header with the commit, `git describe`,
  the modified and untracked file counts, the compiler and QEMU banners,
  the Python version, the host kernel, `CPUS`, and `VM_DEBUG`.

### 2.4 `tools/phase2_gate.sh`

The matrix driver. Two things in it are not bureaucracy:

- `make clean` between the release and `VM_DEBUG` configurations. Without
  it the user programs recompile without `-DVM_DEBUG` while the kernel
  keeps it, and the debug-only subtests silently do not run — this cost
  real time in Phase 0/1 (§2.10 of that report).
- A fresh `fs.img` before every step that needs a known filesystem state.
  `usertests` is not idempotent on a dirty image: `grind` leaves `/a`
  behind and `unlinkcwd` opens with an `mkdir("/a")` it requires to
  succeed.

---

## 3. Defects found

Three. One is a real kernel defect that would have corrupted a later
analysis; one is a test that had quietly stopped testing anything; one is a
measurement artefact in Phase 2's own new code. All three are the same
species — **a quantity that was correct when it was written and was
invalidated by something that changed underneath it** — which is precisely
the species a freeze exists to catch.

### 3.1 Asynchronous prefetch reads were billed to the wrong process

**Symptom.** In the first `data-invariance` run, every asynchronous
configuration reported `page_reads` *exactly* equal to `swap_faults`:
1456 = 1456, 1303 = 1303, 1270 = 1270 across all three policies. Under
synchronous prefetch the same workload reported `page_reads` =
`swap_faults` + `prefetch_accepted` — 1537 = 1044 + 493. An exact equality
holding across three unrelated policies is not a coincidence; it is a
counter that is not being incremented.

**Cause.** `kernel/swap.c:account_io()` took its process from `myproc()`:

```c
static void
account_io(int write, int error)
{
  struct proc *p = myproc();
  ...
  p->vm.stats.page_reads++;
```

The asynchronous prefetch worker (`kernel/prefetch.c:vm_prefetch_worker`)
is a separate kernel process. Every read it issued on another process's
behalf was therefore billed to the worker's own `vm.stats`, which nothing
ever reads. The synchronous path runs in the requesting process's own
context, so it was always correct — which is exactly why the bug survived:
half the code path was right.

**Fix.** Thread an explicit owner through `swap_page_io()` and add
`swap_page_read_owner()` for the worker.

**Why it mattered.** `page_reads` and `block_reads` are the platform's only
measure of device traffic. Under asynchronous prefetch they understated it
by the number of completed prefetches — roughly 1000 reads out of 2450 in
the workload above, a **41% undercount**. Phase 5 compares I/O cost across
prefetch modes. That comparison would have concluded that asynchronous
prefetch performs dramatically less I/O than synchronous prefetch for the
same fault count, which is the opposite of the truth: it performs slightly
more, because a few more of its prefetches are wasted.

**The regression.** Guard 3 of `data-invariance` asserts a conservation
identity rather than a specific number:

```
page_reads + prefetch_useful + prefetch_late  >=  swap_faults + prefetch_completed
```

Every demand fault either performs a read or is satisfied by a prefetch
already in flight (`useful`/`late`); every completed prefetch performs
exactly one read. Before the fix the inequality failed by roughly the
number of completed prefetches. An identity like this is worth more than a
threshold, because it stays meaningful when the workload changes.

**Inference.** `myproc()` is correct only in a syscall context. Any
accounting that can be reached from a kernel worker thread needs the
subject passed in explicitly. There is exactly one such worker today; the
learned policy in Phase 7 does not add another, but a background reclaim
thread would, and this is the trap it would fall into.

### 3.2 The randomised soak had stopped paging

**Symptom.** The million-event capture step produced **174 events** from a
400,000-operation workload. The kernel's own counter agreed
(`emitted=174`), so this was not a drainer artefact — the workload really
had not paged.

**Cause.** `random_workload()` allocated a fixed 24-page region under a
limit of `resident_count + 8`. That was right when a process arrived from
`exec` holding about eleven frames: the limit was 19 and 24 random pages
did not fit. At `USERSTACK=16` a process holds 27 frames, the limit is 35,
and the 24-page region fits inside it with room to spare. The workload
evicted eighteen cold pages during warm-up, reached a steady state, and
then ran 400,000 operations without a single fault.

This is the *same* defect as sections 2.4–2.7 of the Phase 0/1 report, in a
test those fixes did not reach. Five tests were corrected there for exactly
this reason; `random_workload` was the sixth and was missed because it kept
passing — it verifies data, and the data was fine.

**Fix.** Size the region from observed state, `pages = resident_count + 24`,
so it is strictly larger than the capacity for the whole run. And add the
guard whose absence let this hide: the workload now asserts afterwards that
`swap_faults` and `evictions` both increased, and prints them.

**Effect.** 100,000 operations went from 18 evictions to **37,495 swap
faults, 37,538 evictions and 19,744 page writes**. Soak wall time went from
4 seconds to about 75.

**Inference, and it is the single most transferable lesson of this phase.**
Every soak seed had been green for the entire life of the project while
testing a steady state. A passing test is not evidence that the mechanism
under test ran. Where a test's meaning depends on a state it establishes
indirectly — through a limit, a policy, a fault — assert that the state was
established. Phase 4's workloads must carry the same guard, because a
benchmark whose working set accidentally fits the resident limit will
produce a beautiful, meaningless reuse-distance histogram.

### 3.3 A measurement artefact in Phase 2's own baseline

**Symptom.** The first `baseline` table looked like a result:

```
policy=0 limit=34 ... swap_faults=181 evictions=237
policy=1 limit=12 ... swap_faults=247 evictions=303
policy=2 limit=12 ... swap_faults=240 evictions=296
```

FIFO appeared to evict 22% fewer pages than Clock. The matching
`data-invariance` run said FIFO evicted 1593 against Clock's 2404 — FIFO
apparently 34% better, which contradicts every published result about
FIFO versus Clock.

**Cause.** Look at the `limit` column. The loop reconfigured one process,
freeing the region at the end of each iteration; the second and later
iterations therefore observed a much smaller `resident_count` and derived a
much smaller limit from it. FIFO ran with 34 frames and Clock ran with 12.
The measurement had perturbed the thing it was deriving its own magnitude
from.

**Fix.** Compute the limit once in the parent and run each configuration in
a forked child, so every row starts from an identical state.

**Corrected result** — same code, honest capacities:

```
policy=FIFO   limit=35 start_resident=27  swap_faults=1440  evictions=1496
policy=Clock  limit=35 start_resident=27  swap_faults=1325  evictions=1381
policy=Aging  limit=35 start_resident=27  swap_faults=1405  evictions=1461
```

Clock is 8.0% better than FIFO; Aging sits between them. Plausible, modest,
and in the expected order.

**Inference.** This one is uncomfortable, and it belongs in the write-up
rather than being quietly fixed. The wrong version produced a *publishable-
looking* number in the right direction for an interesting story, and it
took a glance at a column that was not the result to notice. Phase 5 and
Phase 6 compare policies for a living. Every such comparison must record
the capacity each arm actually ran at, not the capacity it was asked for.

---

## 4. The trace-capture ceiling — a measured negative result

Fixing §3.2 immediately produced the outcome Phase 0's gate explicitly
allowed for:

> *Negative result available here:* if the packed record still cannot keep
> up with the fault rate, that is itself a finding about the cost of
> kernel-resident instrumentation, and it forces an explicit, reported
> sampling rate rather than an accidental one.

**Measurement.** `vmdrain trace.bin collect vmtest random 1 100000`:

```
vmdrain: kernel: emitted=302243 dropped=142629 buffered=0 capacity=65536
vmdrain: INVALID: dropped=142629 drop_records=69874 sequence_gaps=252
FAILED -- capture lost records; discard it
```

The emitted count is deterministic across runs (302,243 both times); the
dropped count is not (142,280 and 142,629), because it depends on how the
drainer and the workload interleave.

**47% of events were lost.** The arithmetic is not subtle:

| | |
|---|---|
| Emission rate, paging workload | ~12,000 records/s |
| Drain rate, `vmdrain` to the xv6 filesystem | ~5,300 records/s |
| Ring capacity | 65,536 records |
| Time to overflow at that deficit | ~10 s |

The bottleneck is the guest filesystem write path, not the ring and not the
record size. `vmdrain` wrote 160k records in about 30 seconds — 10.2 MB at
roughly 400 KB/s, which is what xv6's log-per-transaction write path
sustains with 16 KB writes. The Phase 0 packing work (152 B → 64 B per
record) bought a factor of 2.4 and was necessary; it was not sufficient.

**Why this is a finding and not a gap.** It converts an unknown into a
number. The lossless envelope is now stated rather than assumed:

| Workload | Result |
|---|---|
| `vmtest swap-repeat` | 28,274 records, 0 drops — lossless, decoded `--strict` |
| `vmtest random <seed> 100000` | 302,243 emitted, 142,629 dropped — **rejected** |

Both are in the matrix on purpose. The second is the positive evidence that
the drop discipline fires: an overrunning capture is discarded *whole*,
never truncated to the part that survived. The gate step passes only when
the run fails and `vmdrain` reports `INVALID` — which also means that if a
future change ever made an overrun silently succeed, this step would go
red.

**Consequence for Phase 4 and Phase 5, stated now so it is not discovered
later.** Dataset collection must satisfy one of:

1. **Pace the workload** so emission stays under ~5k records/s. Traces do
   not need wall-clock realism; they need completeness.
2. **Enlarge the ring** to hold an entire experiment. A 512k-record ring is
   32 MiB of the 128 MiB machine — affordable, but it changes the free-frame
   pool and therefore every absolute page count in an experiment
   configuration, so it would have to be done before, not during,
   collection.
3. **Reduce the event rate at the source** by not emitting the
   `*_BEGIN`/`*_END` pairs. Roughly three of every eight records are I/O
   span markers; dropping them would cost the ability to measure I/O
   latency from the trace.

Option 1 is the right default because it changes nothing about the platform
being measured. Option 2 is the right choice if I/O timing matters.

**What this does not license.** The Phase 0 gate item *"decoder round-trips
a 1M-event capture without loss or misalignment"* is met by the decoder
self-test — 1,000,000 synthetic records round-tripped field-for-field, plus
detection of a removed record and of a mid-record truncation — and by a
real guest-to-host capture at 28,274 records. A genuine 1,000,000-record
*in-guest* capture is **not** met, and is not currently reachable without
one of the three changes above. That is now a measured limitation with a
plan attached rather than an open item, but it is a limitation and it is
declared.

---

## 5. Acceptance criteria — Step 8

Each criterion with the evidence that discharges it. Debug-only tests are
marked `(D)`; they exist because deterministic delay and failure injection
is compiled in only under `VM_DEBUG`.

| # | Criterion | Evidence |
|---|---|---|
| 1 | `usertests` and `grind` pass | `usertests -q` and `grind 200`, both configurations, each on a fresh `fs.img` |
| 2 | A process uses much more virtual memory than its resident limit | `baseline`, `data-invariance`: 64-page region, limit 35. Soak: 51 pages, limit 35 |
| 3 | Byte patterns survive repeated swap under all three policies | `data-invariance` — six configurations, all `checksum=AB0C8578`, equal to the value derived from the pattern definition |
| 4 | Lazy holes, resident, swapped and fetching are never confused | `lazy-zero`, `swap-pattern`, `swap-repeat`, `shrink-swapped`; `swap-bounds` (D) |
| 5 | Unmap, shrink, failed exec, exec, exit and kill release everything | `shrink-swapped`, `exit-leak`, `exec-pressure`, `exec-loop`; `kill-fault`, `exec-fail-cleanup` (D) |
| 6 | Fork works on lazy, resident, swapped and busy source pages | `fork-resident`, `fork-swapped`, `fork-lazy-hole`, `fork-diverge`, `fork-low-limit`; `prefetchtest fork-race` |
| 7 | `copyin`, `copyout`, `copyinstr` cross swapped boundaries | `copyin-swapped`, `copyout-swapped`, `copyinstr-cross-page-swapped`; `usertests lazy_copyinstr` |
| 8 | Permissions survive swapping | `permissions`; the eviction path preserves `PTE_FLAGS` and restores them on install (`static-checks.md` §1.2b/d) |
| 9 | Swap-full and disk errors fail gracefully | `swap-full`, `swap-io-error`, `swap-fault-io-error` (D); `fsck_xv6.py` clean after every filesystem-touching step |
| 10 | Policies cannot select pinned, busy, foreign or invalid pages | `pin`, `metadata-reuse` (D); `page_is_candidate()` filters before selection and the engine revalidates after |
| 11 | Invalid predictive decisions fall back to Clock | `invalid-policy-fallback` (D) — injects an out-of-range victim and requires `policy_fallbacks` to increase |
| 12 | Prefetch is bounded, coalesced, demand-prioritised, and measurable | `prefetchtest all` under each policy: `pressure`, `duplicate`, `waste`, `sequential`, `invalid` |
| 13 | The four race classes pass delay-injection tests | `demand-race`, `unmap-queued`, `shrink-inflight`, `exit-inflight`, `kill-inflight`, `io-error`, `duplicate-race` (D) |
| 14 | `vmcheck` clean throughout; counters return to baseline | `vmcheck()` is the return value of essentially every subtest and of `run_isolated()` after each child exits |
| 15 | Commit, tool versions, configuration, limit, swap size, policy, prefetch mode and seed printed for every experiment | Boot banner + harness provenance header (§2.3); `vmtest random` prints its seed, iterations, page count and limit; `baseline` and `data-invariance` print policy, mode and limit per row |

**No criterion is unticked.** Two carry qualifications that belong in the
thesis rather than in a footnote:

- Criterion 1 passes with `usertests -q`, the quick list, not the full
  suite. This matches the roadmap's own instruction.
- Criteria 9–13 rest substantially on `VM_DEBUG`-only tests. That is by
  design — deterministic failure injection cannot be in a release build —
  but it means the release build's evidence for those properties is
  indirect. Both configurations run the full matrix, so the release build
  is shown to behave identically wherever the tests exist in both.

---

## 6. What the evidence licenses

### 6.1 Correctness is independent of replacement policy

Six configurations — three policies crossed with two prefetch modes — differ
by up to **17% in evictions** (1487 to 1746), by **13% in swap faults**
(998 to 1127), and by a factor of **29 in wasted prefetches** (12 to 347).
Every one of them produces `checksum=AB0C8578`, byte-for-byte, and that
value is the one computed from the pattern definition without touching
memory at all.

This is the load-bearing claim of the whole phase. **Any difference a later
experiment reports between policies is a performance difference, because
the data is provably the same.** Without it, a reported improvement could
always be a lifecycle bug — a leaked slot, a lost dirty bit, an eviction
that quietly dropped a page — and there would be no way to tell from the
outside.

### 6.2 The platform is reproducible, with two stated exceptions

This was measured, not assumed, and the result is sharper than expected.

**Synchronous configurations are deterministic.** Every synchronous row of
the matrix is bit-identical between the release build and the `VM_DEBUG`
build and across repeated runs of the same tree — all twelve counters, not
just the fault count. So is the whole prefetch-disabled baseline table.
For an emulated machine running a preemptive kernel that is a stronger
property than one has any right to expect, and it is worth stating plainly
because it means a one-count difference in a later experiment is signal.

**Asynchronous configurations reproduce in data only.** Clock-async gave
1714 evictions in the debug build and 1721 in the release build of the
same tree; the same row moved between runs by a comparable amount. The
worker is scheduled concurrently with the workload, so the interleaving —
and therefore which pages were resident when a victim was chosen — varies.
Constraint, not defect: **dataset collection that needs counter-level
reproducibility must use synchronous prefetch or none.** Phase 5's feature
vectors are derived from per-eviction state, so this matters directly.

**The counts belong to a build of the test program, not to a policy.**
Clock read 1325 baseline faults after the §3.2 fix and 1327 before it —
with no change to the policy, the limit, or the measured workload. The
only thing that changed was `user/vmtest.c`, which changed the binary's
page layout, which changed which of the process's own text and data pages
were cold and therefore attractive victims. This is the same effect as the
26-resident-page overhead noted in the Phase 0/1 report §3, seen from the
other side. **Re-record the baseline table whenever the workload binary
changes, even if its logic did not**, or a Phase 5 comparison will
attribute a layout artefact to a policy.

### 6.3 A reproducibility fixed point exists

The tag, the recorded tool versions, the boot banner and the baseline
tables are what let a later statement of the form *"this number changed
because of the change I made"* be true rather than hoped for. That is the
entire function of the phase.

### 6.4 What the phase does *not* license

- **Nothing about replacement quality.** Clock beating FIFO by 8.0% on one
  64-page cyclic workload is a sanity check that the policies are
  distinguishable, not a result. It is one workload with one reuse pattern
  at one capacity.
- **Nothing about multicore.** `CPUS=3` runs `vmtest multiproc` and
  `prefetchtest worker-stress` as stress only. No cross-hart TLB shootdown
  exists. Multicore paging correctness is not claimed, and Group D of the
  roadmap says so explicitly.
- **Nothing about dataset-scale tracing**, per §4.

---

## 7. Outstanding, carried forward

Ordered by how much they will hurt.

**7.1 Lossless capture at dataset scale (§4).** The blocker for Phase 5.
Must be resolved before collection begins, by pacing, by a larger ring, or
by a lower event rate. The decision changes the platform's memory profile
in one of those three cases, so it belongs before Phase 4's workloads are
calibrated, not after.

**7.2 `balloc` is O(n²) in a file's block count.** Unchanged from the
Phase 0/1 report §5.2. Not the current bottleneck — `usertests -q` is
disk-bound at a flat ~50 KB/s — but Phase 4 rewrites large workload inputs
repeatedly. The fix (remember the block after the last allocation, wrap
once) changes allocation order and deserves its own regression run.

**7.3 `usertests -q` takes 26 minutes.** 1582 s debug, 1568 s release.
`writebig` writes a 64 MiB file one 1 KiB `write()` at a time, each its own
log transaction. Moving `fs.img` off the 9p mount onto WSL's native ext4 is
the largest available win and costs no code, but it changes the documented
reference configuration and would require re-recording `vm-baseline.txt`.

**7.4 Tracing is a single global switch.** `trace_ring.enabled` is global,
not per-process, so a capture contains the drainer's and the shell's events
as well as the workload's. Records carry a pid so the decoder filters
cleanly. A per-process enable would make captures self-contained and would
also directly reduce the emission rate in §4.

**7.5 `vmdrain collect` stops on a heuristic.** xv6's `wait()` blocks and
has no non-blocking form, so the drainer drains until the ring has been
quiet for 100 consecutive polls and only then reaps the child. The failure
mode is loud — anything lost while blocked appears as a drop and invalidates
the capture — but a workload with a long non-paging phase in the middle
could end a capture early.

**7.6 Stale artefacts.** `trace.txt` and `trace_readable.txt` at the repo
root are sample dumps in the old v1 record format. They should be
regenerated or deleted before anyone decodes them against the v2 schema.

---

## 8. Answering the roadmap's Phase 2 decision point

> **After Phase 2:** *Every acceptance criterion ticked with evidence?*
> If no — stop and fix. Research on an unverified platform is wasted.

**Yes**, with the two qualifications in §5 and the one declared limitation
in §4. Phase 3 may begin.

The phase found three defects. Two of them (§3.1, §3.3) would have produced
plausible, publishable-looking numbers pointing in the wrong direction, and
neither would have been visible from a test result — both were found by
looking at a column that was not the answer. The third (§3.2) had been
green for the entire life of the project while testing nothing.

That is the argument for the phase existing, and it is worth making in the
thesis in those terms: the freeze did not confirm that the platform was
correct, it found the three places where it was not.
