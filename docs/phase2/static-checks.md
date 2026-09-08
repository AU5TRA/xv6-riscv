# Phase 2, Step 1 — static checks

Every search prescribed by `docs/ROADMAP.md` Phase 2 Step 1, its result, and
the manual classification the roadmap requires. Run against the working tree
that became the `platform-v1.0` freeze.

`rg` is not installed on the reference host; `grep -En` with the identical
regex is used instead. This is a tool substitution, not a change of query.

---

## 1.1 `git status --short`, `git diff --check`, `git diff --stat`

`git diff --check` is clean — no trailing whitespace, no whitespace-before-tab,
no conflict markers.

The checkout is a Windows Git worktree with CRLF conversion, so all three
commands are run through Windows Git rather than inside WSL; running them under
WSL misclassifies every unchanged CRLF file as a whole-file rewrite.

`git status --short` shows only the Phase 0/1/2 work: modified kernel, user and
build files, plus the new `docs/`, `tools/` and `user/` additions those phases
introduced. No editor backups, no build artefacts, no stray captures.

---

## 1.2 PTE mutations — `\*pte[[:space:]]*(=|\|=|&=)`

**The prescribed regex is incomplete, and that is the first finding of this
step.** It anchors on the identifier `pte` immediately after the dereference,
so it misses every write through a differently-named pointer. Three real
mutation sites are invisible to it:

| Site | Statement | Why the regex misses it |
|---|---|---|
| `kernel/vm.c:372` | `*childpte = *pte;` | pointer is named `childpte` |
| `kernel/prefetch.c:421` | `*request.pte = PA2PTE(...) \| flags \| PTE_V;` | write is through a struct field |
| `kernel/prefetch.c:433` | `*request.pte = SLOT2PTE(...) \| flags \| PTE_SWAPPED;` | same |

The broadened search actually used, which finds all of them:

```
grep -En '\*[A-Za-z_][A-Za-z0-9_.>-]*pte[A-Za-z0-9_]*[[:space:]]*(=[^=]|\|=|&=)' kernel/*.c
```

`kernel/kernel.asm` is a build artefact (disassembly) and is excluded; it
duplicates every site below.

### Classification

Every mutation falls into exactly one of the six categories the roadmap names.

**(a) Page-table construction** — writes to a table that is not yet the active
address space, or to an interior level. No user TLB fence required.

| Site | Function | Statement |
|---|---|---|
| `vm.c:116` | `walk()` | `*pte = PA2PTE(pagetable) \| PTE_V` — interior level allocation |
| `vm.c:372` | `uvmcopy()` | `*childpte = *pte` — duplicate a SWAPPED entry into the child, after `swap_slot_get()` has taken a reference |

**(b) Resident mapping installation** — a frame becomes valid and reachable.

| Site | Function | Statement | Fenced |
|---|---|---|---|
| `vm.c:172` | `mappages()` | `*pte = PA2PTE(pa) \| perm \| PTE_V` | caller's context; new table, or `sfence` by caller |
| `vm.c:651` | `vmfault()` | `*pte = PA2PTE(mem) \| flags \| accessed \| PTE_V` | `sfence_vma()` at `vm.c:652` |
| `prefetch.c:184` | `prefetch_one()` (synchronous) | `*pte = PA2PTE(pa) \| flags \| PTE_V` | `sfence_vma()` at `prefetch.c:185` |
| `prefetch.c:421` | `vm_prefetch_worker()` (asynchronous) | `*request.pte = PA2PTE(request.pa) \| request.flags \| PTE_V` | `sfence_vma()` at `prefetch.c:422` |

Each of the three fault/prefetch installations revalidates
`(*pte & (PTE_SWAPPED|PTE_BUSY)) == (PTE_SWAPPED|PTE_BUSY)` **and** the slot
number immediately before writing, so a racing unmap, exit or competing fetch
cannot be overwritten.

**(c) A/D sampling** — software accounting of access and dirty state. Never
changes validity, permissions or the target frame.

| Site | Function | Statement |
|---|---|---|
| `vm.c:438` | `copyout()` | `*pte \|= PTE_A \| PTE_D` — after the `PTE_W` permission check |
| `vm.c:471` | `copyin()` | `*pte \|= PTE_A` |
| `vm.c:506` | `copyinstr()` | `*pte \|= PTE_A` |
| `vm.c:560` | `vmfault()` resident fast path | `*pte \|= PTE_A \| (write ? PTE_D : 0)` |
| `vm.c:689` | `vmfault()` lazy-zero path | same |
| `vmpage.c:129` | `sample_page()` | `*pte &= ~PTE_A` — policy reference sampling, followed by `sfence_vma()` |

`sample_page()` is the only one that *clears* a bit and is therefore the only
one that needs a fence; `vmpage.c:157/163/184` issue it on each policy path.

**(d) Swap / fetch transitions** — the resident ⇄ swapped state machine.

| Site | Function | Statement | Meaning |
|---|---|---|---|
| `vm.c:602` | `vmfault()` | `*pte \|= PTE_BUSY` | claim the entry for a demand fetch |
| `vm.c:614` | `vmfault()` | `*pte &= ~PTE_BUSY` | frame acquisition failed; release the claim and wake waiters |
| `vm.c:635` | `vmfault()` | `*pte = SLOT2PTE(slot) \| flags \| PTE_SWAPPED` | read error; restore the original swapped entry |
| `vmpage.c:336` | `reclaim_frame()` | `*pte = SLOT2PTE(slot) \| flags \| PTE_SWAPPED` | eviction commit, after re-validating owner, pagetable, va, state and `PTE2PA`; `sfence_vma()` at `vmpage.c:339` |
| `prefetch.c:142` | `prefetch_one()` | `*pte \|= PTE_BUSY` | claim for a synchronous prefetch |
| `prefetch.c:146` | `prefetch_one()` | restore `PTE_SWAPPED` | frame acquisition failed |
| `prefetch.c:164` | `prefetch_one()` | restore `PTE_SWAPPED` | read failed |
| `prefetch.c:223` | `prefetch_async_one()` | `*pte \|= PTE_BUSY` | claim for an async prefetch |
| `prefetch.c:227` | `prefetch_async_one()` | restore `PTE_SWAPPED` | frame acquisition failed |
| `prefetch.c:243` | `prefetch_async_one()` | restore `PTE_SWAPPED` | no free async request slot |
| `prefetch.c:433` | `vm_prefetch_worker()` | restore `PTE_SWAPPED` | cancelled, stale, or read error |

Every `PTE_BUSY` set has a matching clear or terminal rewrite on every exit
path, and every terminal transition is followed by `wakeup(pte)`. `vmfault()`
and `uvmcopy()` both wait on that exact channel, which is what makes
fork-vs-prefetch and demand-vs-prefetch safe.

**(e) Permission change**

| Site | Function | Statement |
|---|---|---|
| `vm.c:410` | `uvmclear()` | `*pte &= ~PTE_U` — exec stack guard page |

**(f) Unmap / cleanup**

| Site | Function | Statement |
|---|---|---|
| `vm.c:226` | `uvmunmap()` | `*pte = 0` for a SWAPPED entry, after `swap_slot_put()`; panics on `PTE_BUSY` |
| `vm.c:240` | `uvmunmap()` | `*pte = 0` for a resident entry, after `vm_frame_release()` |

The `panic("uvmunmap: busy")` in that first branch is the deliberate loud
failure for "a pagetable is being torn down with I/O still owning one of its
entries". `kexit()` relies on `vm_prefetch_drain()` running first to guarantee
it cannot fire.

**Conclusion of the classification.** All 24 sites classify cleanly. No site
writes a PTE without either (i) constructing a table that is not yet active,
(ii) re-validating the entry it is about to overwrite, or (iii) touching only
the software A/D bits. Every mutation that invalidates or replaces a *current*
user mapping is followed by `sfence_vma()` before returning to user mode.

---

## 1.3 `PTE_SWAPPED|PTE_BUSY|sfence_vma`

49 hits across `kernel/*.c` and `kernel/*.h`. The `sfence_vma()` call sites:

| Site | Reason |
|---|---|
| `vm.c:82`, `vm.c:87` | `kvminithart()` — boot, stock xv6 |
| `vm.c:561` | resident fast path after restoring A/D on a re-faulted entry |
| `vm.c:652` | demand swap-in installation |
| `vmpage.c:157`, `:163` | Clock reference-bit sampling |
| `vmpage.c:184` | Aging reference-bit sampling |
| `vmpage.c:339` | eviction commit |
| `prefetch.c:185` | synchronous prefetch installation |
| `prefetch.c:422` | asynchronous prefetch installation |

CPUS=1 is the correctness claim. These fences are hart-local; no cross-hart
shootdown exists, which is why CPUS=3 is stress-only (Group D).

---

## 1.4 `kalloc\(` in `vm.c`, `exec.c`, `proc.c`

| Site | Purpose |
|---|---|
| `vm.c:30` | `kvmmake()` — the kernel page-table root |
| `vm.c:113` | `walk()` — an interior page-table level |
| `vm.c:187` | `uvmcreate()` — a user page-table root |
| `proc.c:38` | per-process kernel stack |
| `proc.c:131` | trapframe |

`kernel/exec.c` contains **no** `kalloc()` call at all.

**This is the property the whole platform rests on, and it holds:** not one of
these five allocations is a user *data* frame. Every page that can hold user
data comes from `vm_frame_acquire()`, which is what makes it accounted,
evictable, pinnable and traceable. A `kalloc()` appearing on a user-data path
in a later phase would silently create an unmanaged, uncountable frame — this
search is the check for that, and it should be re-run before every commit.

---

## 1.5 `uvmunmap|uvmdealloc|uvmfree|freewalk|freeproc`

33 hits in `kernel/*.c`. Teardown funnels through `uvmunmap()`, which is the
single point where a swap-slot reference is dropped (`swap_slot_put`) and the
single point where a frame is returned (`vm_frame_release`). `freewalk()`
panics if a leaf survives, so a missed `uvmunmap()` cannot be silent.

## 1.6 `uvmcopy|copyin|copyout|copyinstr|vmfault`

40 hits. All three copy paths call `vmfault()` on a non-resident page rather
than failing, and all three update A/D afterwards (§1.2c).

## 1.7 `swap_slot_(alloc|get|put)|inflight|prefetch`

178 hits — the largest surface, as expected. Reviewed for the reference-count
discipline: `swap_slot_get()` before duplicating a SWAPPED PTE into a child,
`swap_slot_put()` on every path that destroys or replaces one.

---

## 1.8 Defect found during this step

One real defect surfaced while building the Step 3 evidence rather than from
the searches themselves. It is recorded here because it is an *attribution*
property of exactly the kind this step is meant to police:

`kernel/swap.c:account_io()` took its process from `myproc()`. The
asynchronous prefetch worker (`kernel/prefetch.c:vm_prefetch_worker`) is a
separate kernel process, so every read it performed on another process's
behalf was billed to the worker's own `vm.stats`, which nothing ever reads.
The requesting process's `page_reads` and `block_reads` therefore came out
**exactly equal to its `swap_faults`** under asynchronous prefetch, no matter
how much device traffic the prefetcher actually generated.

Fixed by threading an explicit owner through `swap_page_io()` and adding
`swap_page_read_owner()` for the worker. The regression that catches it is
Guard 3 in `vmtest data-invariance` — see `docs/phase2/report.md` §3.
