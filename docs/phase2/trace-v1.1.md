# Trace subsystem v1.1 — recording the decision, and capturing all of it

Three changes to the paging trace, made after `platform-v1.0` was signed off
and before Phase 4 begins. Together they take the reference paging workload
from **31.7% of events usable** to **100%**, and add the one feature a
replacement model most needs and could not previously get.

| | |
|---|---|
| Supersedes | `platform-v1.0` |
| Schema | `VMTRACE_VERSION` 2 → 3 |
| Evidence | `docs/phase2/gate-results.txt` |
| Reproduce | `bash tools/phase2_gate.sh all` |

---

## 1. The victim's accessed and dirty bits are now recorded

### What was wrong

A capture recorded *which* page was evicted and never *why*. Three separate
places conspired:

- `VICTIM_SELECTED` passed `VMTRACE_NONE` for `pte_flags`
- `EVICT_BEGIN` did the same
- `EVICT_END` passed `flags`, which had `PTE_A` and `PTE_D` **masked out**:

```c
uint flags = PTE_FLAGS(*pte) & ~(PTE_V | PTE_SWAPPED | PTE_BUSY | PTE_A | PTE_D);
```

The masking is correct *as code* — `flags` is reused to build the new swapped
PTE, where those bits must not be set. The trace was simply borrowing the
wrong variable.

The consequence: **"was this page referenced since it was last sampled" — the
single most informative feature a replacement policy has — was unrecoverable
from a capture.** Dirty could be inferred indirectly, by comparing the
victim's existing backing slot against the slot it ended up in, since those
differ exactly when a write-back was needed. Referenced could not be inferred
at all.

### The fix

`reclaim_frame()` now captures the PTE flags immediately after
`sample_page()` has refreshed them — the same state the policy used to choose
— and passes them to every decision record:

```c
sample_page(victim, 0);
pte_t *victim_pte = walk(victim->pagetable, victim->va, 0);
uint64 victim_flags = victim_pte ? PTE_FLAGS(*victim_pte) : (uint64)VMTRACE_NONE;
```

`EVICT_END` and the `SWAP_WRITE_*` pair now emit `report_flags` (unmasked)
while the PTE write keeps using the masked `flags`. `walk()` with `alloc=0`
neither allocates nor sleeps, and `sample_page()` already calls it under the
same lock, so this adds no new locking assumption.

### Evidence

Decoding a 150,223-record capture of the reference workload, every one of the
37,538 eviction decisions now carries real flags:

| Victim state at eviction | Count | Share |
|---|---:|---:|
| accessed, dirty | 19,719 | 52.5% |
| accessed, clean | 17,798 | 47.4% |
| neither | 21 | 0.1% |
| *without flags* | **0** | — |

The 19,719 dirty victims cross-check against the 19,744 `SWAP_WRITE_BEGIN`
records in the full capture; the 25-record difference is first-eviction pages
that had no backing slot yet and so needed a write despite being clean.

---

## 2. Event types can be masked at runtime

### Why

A swap fault produces **~8 records** — 7 for a clean eviction, 9 when the
victim is dirty. Six of them are `*_BEGIN`/`*_END` span markers whose fields
duplicate their partner's and whose only unique contribution is a timestamp,
i.e. I/O latency.

For a page-replacement dataset that is pure overhead. But deleting the events
outright would cost the correctness and I/O-cost analysis that Phase 2 relies
on, so the choice is made a **runtime switch** rather than a schema deletion.

### How

`vmctl(VM_TRACE_SET_MASK, bits)` — bit *N* enables `enum vmtrace_type` value
*N*. `VMTRACE_MASK_DATASET` is the predefined subset. `vmdrain <file> compact
<command>` selects it for a capture.

**One ordering detail carries the whole design.** A masked-out event is
rejected *before* it is assigned a sequence number:

```c
acquire(&trace_ring.lock);
// Order matters: a masked-out event is rejected here, BEFORE it is given a
// sequence number below.
if(!trace_ring.enabled || (trace_ring.event_mask & VMTRACE_BIT(type)) == 0){
```

Numbering first and discarding after would punch a hole in the sequence that
is **indistinguishable from real loss**, which would destroy the one property
the whole subsystem exists to provide. `vmtest trace-mask` asserts that a
masked capture's sequence is contiguous from 1.

Two further safeguards: a zero mask is refused, and `VMTRACE_DROP` is forced
on regardless of what the caller asks for — masking away the loss markers
would leave an overrun capture looking clean.

The mask is recorded in the capture header, so a decoded trace is never
ambiguous about what it contains.

---

## 3. The ring holds 262,144 records

`65,536` was not enough, and the arithmetic says so precisely. The ring buys
a fixed **backlog**, not a rate: a capture is lossless as long as the drainer
never falls more than `capacity` records behind, and `vmdrain` keeps draining
after the workload exits, so a bounded experiment only has to fit its *peak*
backlog.

The reference workload emits 302,243 events over 152 s against a drainer
sustaining ~1,050 records/s — a peak backlog of about **143,000 records**,
more than twice the old capacity. Hence the 47% loss.

262,144 records covers it with 1.8× margin, at a cost of 16 MiB of kernel
`.bss` (up from 4 MiB). That reduces the free frame pool, which is why the
boot banner prints `trace_capacity` — experiments quote a *logical* resident
limit, so paging behaviour is unaffected, but absolute free-frame counts move.

---

## 4. Measured result

Same workload (`vmtest random 1 100000`), same host, release build:

| Configuration | Records kept | Lost | Wall clock |
|---|---:|---:|---:|
| v1.0 — 65,536 ring, all events | 161,285 | **47.2%** | 156 s |
| v1.1 — 262,144 ring, all events | 302,243 | **0.0%** | 252 s |
| v1.1 — 262,144 ring, dataset mask | 150,223 | **0.0%** | 158 s |

Both v1.1 captures decode `--strict` clean: sequence 1..*N*, no gaps, no
`DROP` records.

The mask removes exactly what it claims and nothing else — the kept types
have **identical counts** in both v1.1 captures:

```
MAP 37,548   VICTIM_SELECTED 37,538   EVICT_END 37,538
SWAP_FAULT 37,497   ZERO_FAULT 51   UNMAP 51
```

Planning numbers that fall out of this:

- **~8 events per swap fault** with all events, **~4** with the dataset mask
- **1 eviction decision per ~4 events** in compact mode
- A capture file is capped by `MAXFILE` at 67.4 MB, i.e. about **1.05 million
  records**; past that, split across captures

---

## 5. What broke, and what it taught

The full matrix passed **73 of 74** steps on the first run. The one failure is
worth recording because it is the same species as every other defect this
project has found:

```
===== STEP trace: overrun is rejected =====
UNEXPECTED: an overrunning capture was reported lossless
```

That step exists to prove the drop discipline fires: it runs a capture that
*should* overrun and passes only when `vmdrain` rejects it. It produced the
overrun by having the workload outrun the ring — and enlarging the ring made
the capture lossless, so the test correctly reported that **its own premise
had evaporated**.

Exactly the pattern from §3.2 of the Phase 2 report: a magnitude that was
right when written and was invalidated by something that changed underneath
it. The fix is the same one that applied there — force the condition instead
of hoping for it. `vmdrain <file> smallring <cap> <command>` shrinks the ring
deliberately, so the test is now independent of `VMTRACE_CAPACITY`:

```
vmdrain: kernel: emitted=91507 dropped=58578 buffered=0 capacity=4096
vmdrain: INVALID: dropped=58578 drop_records=8659 sequence_gaps=106
```

**Nothing else regressed.** The `baseline` and `data-invariance` tables are
*identical* to `platform-v1.0` — same fault counts, same eviction counts, same
checksum `AB0C8578` across all six policy/prefetch configurations. That is the
check that matters: adding a `walk()` to the eviction path did not perturb
victim selection.

---

## 6. Still outstanding for Phase 4

Volume is solved. The two remaining gaps are about **content**, and both are
cheaper to fix before the workloads are written than after:

**No reference string.** The trace records page *faults*, not memory
accesses — a resident page accessed a million times emits nothing. Belady's
optimal needs the next *reference* time of every resident page, and a fault
stream cannot supply it. Worse, the bias is circular: pages the running policy
kept resident never fault, so they look unused, which makes that policy's own
decisions look optimal. The fix is workload-level access logging, which is
cheap for the Phase 4 synthetic benchmarks and gives an exactly reproducible
input that every policy — including Belady — can be simulated against offline.

**No candidate features.** Eviction records now carry the chosen victim's
A/D bits, but still nothing about the pages that were *not* chosen, and
nothing about `aging_counter`, `frequency` or `last_access_epoch`. That is
enough to train a model to imitate Clock; it is not enough to train a scorer
that ranks candidates, and reconstructing features offline risks exactly the
kernel/simulator divergence the roadmap warns about in Phase 7. Emitting
per-candidate records would multiply the event rate by the candidate count —
which is affordable now that the mask can pay for it, but is a deliberate
design decision rather than a patch.
