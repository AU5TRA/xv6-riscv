# Page lifecycles — function glossary and step-by-step walkthroughs

Labels used in Part 1, verified against the pre-paging baseline commit
(`7d01506`, before AU5TRA's paging work began) with `git diff`, not from
memory:

- **[STOCK]** — existed before AU5TRA's paging work, completely unchanged.
- **[STOCK, MODIFIED]** — existed before, but AU5TRA (or this session)
  changed its signature or behavior.
- **[ADDED — AU5TRA]** — a brand new function, written as part of the
  paging/swap implementation.
- **[ADDED — this session]** — a brand new function added on top of
  AU5TRA's work, during the audit/fix work done in this chat.

---

# Part 1 — What each function actually does, and where it came from

**`kernel/sysproc.c`** (where a syscall's C code lives)
- `sys_sbrk()` **[STOCK]** — runs when a user program calls `sbrk()`/`sbrklazy()` to grow or shrink its memory. Either allocates real memory immediately, or (lazy mode) just promises the address space and does nothing yet.

**`kernel/proc.c`** (process lifecycle: create, fork, exit, sleep/wake)
- `growproc()` **[STOCK, MODIFIED]** — grows or shrinks a process's memory size, calling the real allocation/deallocation work below. Modified to pass the owning `struct proc*` through to `uvmalloc`, and to cancel any pending prefetch on shrink.
- `vm_prefetch_worker_start()` **[ADDED — AU5TRA]** — creates the one dedicated background kernel process ("pageio") whose only job is doing asynchronous prefetch disk reads.
- `kfork()` **[STOCK, MODIFIED]** — implements `fork()`: makes a new child process and copies the parent's memory into it. Modified to inherit paging state and to release the child's scheduler lock around the copy (since copying can now sleep for disk I/O).
- `kexit()` **[STOCK, MODIFIED]** — implements `exit()`: starts shutting a process down. Modified to drain any in-flight prefetch work first.
- `kwait()` **[STOCK, MODIFIED]** — implements `wait()`: a parent blocks here until a child exits; this is where a dead child's memory is actually released. Modified so the status copyout doesn't hold process-table locks across a copy that can now fault.
- `freeproc()` **[STOCK, MODIFIED]** — the real cleanup: releases everything belonging to a process once it's safe to. Modified to reset paging state.
- `proc_freepagetable()` **[STOCK]** — frees an entire page table and everything it maps. Unchanged itself (its callees changed underneath it).
- `sleep_prepare()` / `sleep()` **[STOCK]** — how kernel code voluntarily gives up the CPU while waiting for something, instead of spinning. Predates the paging work (part of this teaching fork's own earlier sleep/wakeup API, before AU5TRA's commits).
- `wakeup()` **[STOCK]** — the other half of sleep: wakes up whatever was waiting for a particular event.
- `setkilled()` **[STOCK]** — flags a process to die; it'll actually stop the next time it checks that flag.

**`kernel/trap.c`** (the first code that runs on any interrupt/fault/syscall)
- `usertrap()` **[STOCK, MODIFIED]** — runs the instant a user program causes a trap of any kind and dispatches to the right handler. Modified so page faults (now including instruction faults, not just load/store) route uniformly through `vmfault`.
- `devintr()` **[STOCK]** — figures out whether an interrupt came from a real device (like the disk) and routes it. Unchanged.

**`kernel/vm.c`** (page tables and the fault handler — the core of the whole system)
- `vmfault()` **[STOCK, MODIFIED]** — **the single most important function here.** The hook point existed before (a 15-line function: allocate-or-fail, nothing else), but was completely rewritten into a full dispatcher handling valid/swapped/busy/lazy-hole cases.
- `mappages()` **[STOCK]** — installs one translation into the page table. Unchanged.
- `walk()` **[STOCK]** — looks up (and can create) the page-table entry for an address. Unchanged.
- `uvmalloc()` **[STOCK, MODIFIED]** — grows a process's mapped pages. Modified to take the owning process and route allocation through the pageable-frame allocator instead of raw `kalloc`.
- `uvmdealloc()` **[STOCK]** — shrinks a process's mapped pages. Unchanged (its callee `uvmunmap` changed underneath it).
- `uvmunmap()` **[STOCK, MODIFIED]** — removes mappings over a range. Heavily modified: now releases swap slots for swapped pages and panics on an invariant violation (a still-busy leaf).
- `uvmfree()` **[STOCK]** — unmaps and frees an entire address space. Unchanged.
- `uvmcopy()` **[STOCK, MODIFIED]** — copies one process's address space into another's (the mechanism behind `fork()`). Heavily modified: handles swapped/busy source pages, refcounts shared swap slots, and (this session) waits rather than fails on a busy page.
- `copyin()` / `copyout()` / `copyinstr()` **[STOCK, MODIFIED]** — move data between kernel and user memory. Modified to trigger `vmfault` (and therefore possibly a swap-in) on memory that isn't currently resident, and to set access/dirty bits.

**`kernel/vmpage.c`** (frame bookkeeping and eviction — an entirely new file)
- `vm_frame_acquire()` **[ADDED — AU5TRA]** — what anything calls when it needs one physical frame.
- `reclaim_frame()` **[ADDED — AU5TRA]** — does the actual eviction.
- `page_is_candidate()` **[ADDED — AU5TRA]** — checks if a page is eligible for eviction right now.
- `choose_policy_victim()` **[ADDED — AU5TRA]** — dispatches to the configured policy and validates its answer.
- `choose_fifo()` **[ADDED — AU5TRA]** — picks the oldest resident candidate.
- `choose_clock()` **[ADDED — AU5TRA]** — the second-chance algorithm.
- `choose_aging()` **[ADDED — AU5TRA]** — the least-recently-used approximation via a history counter.
- `sample_page()` **[ADDED — AU5TRA]** — checks/clears a page's hardware accessed-bit.
- `setup_page()` **[ADDED — AU5TRA; modified this session]** — initializes a frame's ownership record. This session added a call to thread it onto the new per-process owned-frame list.
- `clear_page()` **[ADDED — AU5TRA; modified this session]** — wipes a frame's record back to unowned. This session added a call to detach it from that same list first.
- `owned_list_insert()` / `owned_list_remove()` **[ADDED — this session]** — brand new: maintain the intrusive per-process linked list of owned frames, added to replace an O(total physical RAM) full-table scan on every eviction with a search bounded by the process's own resident set.
- `vm_frame_release()` **[ADDED — AU5TRA]** — fully releases a resident frame that's no longer needed.
- `vm_frame_pin()` / `vm_frame_unpin()` **[ADDED — AU5TRA]** — temporarily protect/unprotect a frame from eviction.
- `vm_frame_set_backing()` **[ADDED — AU5TRA]** — remembers a page's last-known disk slot for possible reuse.
- `vm_frame_note_access()` **[ADDED — AU5TRA]** — records a real touch (used to promote a used prefetch).
- `vm_reclaim_to_limit()` **[ADDED — AU5TRA]** — evicts repeatedly until a process is back within budget (used after `exec`).

**`kernel/swap.c`** (the disk-side bookkeeping — an entirely new file)
- `swap_slot_alloc()`, `swap_slot_get()`, `swap_slot_put()`, `swap_page_write()`, `swap_page_read()`, `swap_page_io()` — all **[ADDED — AU5TRA]**.

**`kernel/virtio_disk.c`** (the real disk driver)
- `virtio_disk_raw_rw()` **[ADDED — AU5TRA]** — talks directly to the disk hardware for raw sector I/O (used for swap, bypassing the filesystem's buffer cache).
- `virtio_disk_intr()` **[STOCK, MODIFIED]** — runs when the disk signals a transfer finished. Modified so it can complete both ordinary filesystem I/O and the new raw swap I/O.

**`kernel/vmtrace.c`** (an entirely new file)
- `vmtrace_emit()` **[ADDED — AU5TRA]** — records one entry in the debug trace log.

**`kernel/prefetch.c`** (speculative fetch-ahead — an entirely new file)
- `vm_prefetch_hint()`, `vm_prefetch_service()`, `prefetch_one()`, `prefetch_async_one()`, `vm_prefetch_worker()`, `vm_prefetch_cancel_range()`, `vm_prefetch_drain()` — all **[ADDED — AU5TRA]**.

**`kernel/kalloc.c`** (the most basic layer of all)
- `kalloc()` / `kfree()` **[STOCK]** — the plain physical free-list allocator. Verified zero diff against baseline for this entire file — it has no idea paging/swap exists at all.

**`kernel/main.c`**
- `main()` **[STOCK, MODIFIED]** — the kernel's boot routine. Modified to initialize the new subsystems (`vmpage_init`, `swap_init`, `vm_prefetch_init`, `vmtrace_init`) and start the prefetch worker process, plus (this session) a warning if more than one hart boots.

---

# Part 2 — Every lifecycle, with the story explained at each step

## The two exits every page eventually takes

**Shrinking memory (`sbrk` with a negative size):**
```
sys_sbrk (kernel/sysproc.c)          — the syscall itself
  -> growproc (kernel/proc.c)         — "make this process's memory smaller"
       -> vm_prefetch_cancel_range (kernel/prefetch.c)  — first, cancel anything queued for
                                                           the memory about to disappear
       -> uvmdealloc (kernel/vm.c)    — "here's the new, smaller size"
            -> uvmunmap (kernel/vm.c) — walks every page in the freed range and releases it
```

**Exiting the process:**
```
kexit (kernel/proc.c)                — "I'm done" — but memory ISN'T freed yet here
  -> vm_prefetch_drain (kernel/prefetch.c)  — stop accepting new prefetch work, and wait
                                               for anything already in flight to finish
       -> vm_prefetch_cancel_range (kernel/prefetch.c)  — same cancellation as above, but
                                                            for the entire address space
       ... process sits as a "zombie" until its parent notices ...
kwait (kernel/proc.c)                — the PARENT calling wait() finally reaps it
  -> freeproc (kernel/proc.c)         — now it's actually safe to release everything
       -> proc_freepagetable (kernel/proc.c)  — free the whole page table
            -> uvmfree (kernel/vm.c)  -> uvmunmap (kernel/vm.c)   — same per-page release as above
```

**What `uvmunmap` (kernel/vm.c) does for one page, depending on its state at that moment:**
- **Resident** → `vm_frame_release` (kernel/vmpage.c) — "give this RAM frame back to the pool" — which internally calls `clear_page` (wipes the bookkeeping) and `kfree` (kernel/kalloc.c, actually returns the physical page).
- **Swapped** → `swap_slot_put` (kernel/swap.c) — "I don't need this disk slot anymore," PTE zeroed.
- **Lazy hole** → nothing — there was never anything to release.

---

## Lifecycle A — Stillborn: allowed to exist, never actually used

```
sys_sbrk (kernel/sysproc.c) — the process asked for more address space, but in "lazy" mode,
                               so the kernel just remembers "you're allowed to use this" and
                               stops there. No memory, no page table entry, nothing.
Dead — whenever this memory is freed or the process exits, uvmunmap finds *pte==0 for this
       address and does literally nothing — there was never anything to clean up.
```
This is the common case for most of a typical program's declared-but-unused address space.

## Lifecycle B — Touched once, stays resident, freed cleanly later

```
1. sys_sbrk (kernel/sysproc.c)
     — creates the "you're allowed to use this" placeholder, as in Lifecycle A.

2. The program actually reads or writes that address for the first time.
   usertrap (kernel/trap.c)
     — the CPU couldn't complete that access (nothing's mapped there) and trapped into
       the kernel to ask "what do I do?"

3. vmfault (kernel/vm.c)
     — sees the PTE is completely empty (a legitimate lazy hole, not an illegal address),
       so it decides: allocate this page for real, right now.

4. vm_frame_acquire (kernel/vmpage.c)
     — "I need one physical RAM frame." Since the process isn't at its limit, this is
       the easy case: no eviction needed.

5. kalloc (kernel/kalloc.c)
     — hands over one genuinely free physical page.

6. setup_page (kernel/vmpage.c)
     — writes down "this frame now belongs to this process, at this address."
       Internally calls clear_page (wipe old bookkeeping) and
       owned_list_insert (kernel/vmpage.c) — threads this frame onto the list of
       "everything this process owns," which is what eviction will search later.

7. mappages (kernel/vm.c)
     — actually installs the translation: this virtual address now points at that
       physical frame, with read/write/user permissions.

8. vm_frame_unpin (kernel/vmpage.c)
     — removes the temporary "don't touch this yet" protection the frame had while
       being set up, making it a normal, evictable page from now on.

9. vmtrace_emit (kernel/vmtrace.c), twice
     — purely for the trace log: records that a zero-fault happened, then that the
       page became mapped. Doesn't affect anything.

Page now sits Resident, untouched by eviction, indefinitely.

Dead — eventually freed via shrink or exit; uvmunmap's Resident branch runs
       (vm_frame_release -> clear_page + kfree).
```

## Lifecycle C — Evicted once, never touched again, dies while on disk

Steps 1-9 as in B, then some *other* page's fault needs a frame and the budget is full:

```
10. vm_frame_acquire (kernel/vmpage.c)
      — this time the process IS at its resident limit, so instead of the easy path,
        it calls reclaim_frame to make room.

11. reclaim_frame (kernel/vmpage.c)
      — walks the process's own list of owned frames (built by owned_list_insert
        earlier), filtering with page_is_candidate (kernel/vmpage.c) — "is this
        page even eligible right now (not pinned, not already busy)?"

12. choose_policy_victim (kernel/vmpage.c)
      — asks whichever policy is configured to name a victim, then sanity-checks
        the answer before trusting it.
      -> choose_fifo / choose_clock / choose_aging (kernel/vmpage.c)
      — THIS is where our page gets picked, because (say) it's the oldest one
        (FIFO), or hasn't been touched recently (Clock/Aging).

13. sample_page (kernel/vmpage.c)
      — checks the victim's hardware accessed-bit one last time, purely for stats.

14. vmtrace_emit (kernel/vmtrace.c) — logs "victim selected," then "eviction starting."

15. walk (kernel/vm.c)
      — re-finds the victim's actual page-table entry so it can be modified.

16. swap_slot_alloc (kernel/swap.c)
      — reserves a spot on the swap disk region for this page's data
        (skipped if the page already has an unmodified copy sitting on disk
         from before — no point writing the same bytes twice).

17. swap_page_write (kernel/swap.c)
      -> swap_page_io (kernel/swap.c) -> virtio_disk_raw_rw (kernel/virtio_disk.c)
      — the actual disk write: this page's 4096 bytes get copied out to that slot.
        (Completion is signaled later by virtio_disk_intr, kernel/virtio_disk.c,
         when the disk hardware finishes — dispatched via devintr, kernel/trap.c.)

18. vmtrace_emit (kernel/vmtrace.c) — logs the write finishing.

19. The victim's page-table entry is directly rewritten to say "not in RAM anymore,
    here's the disk slot instead" (this literally repurposes the same bits that
    used to hold a physical address).

20. setup_page (kernel/vmpage.c)
      — the now-empty physical frame gets reassigned to whatever NEW page
        originally triggered all of this.

21. sfence_vma() — tells the CPU "forget anything you had cached about this address,"
    so it doesn't accidentally use a stale translation.

22. swap_slot_put (kernel/swap.c)
      — only if the victim had an OLD retained disk copy that's now outdated
        (e.g. it was modified since last time), release that stale slot.

23. vmtrace_emit (kernel/vmtrace.c) — logs "eviction finished."

Page is now Swapped. Assume it's never touched again.

Dead — via shrink or exit; uvmunmap's Swapped branch runs (swap_slot_put).
```

## Lifecycle D — The full round trip: evicted, then brought back (can repeat)

Steps 1-23 as in C to reach Swapped, then the page is touched again:

```
24. usertrap (kernel/trap.c) -> vmfault (kernel/vm.c)
      — another fault, but this time the PTE says "swapped," not "empty" — a
        completely different situation, handled by a different branch.

25. vmtrace_emit (kernel/vmtrace.c) — logs "swap fault" (a fault on a page that's on disk).

26. The PTE is marked "busy" directly — a flag meaning "I/O is in progress on this
    exact page, nobody else touch it."

27. vm_frame_acquire (kernel/vmpage.c)
      — needs a frame to read the data INTO. If the budget's still full, this can
        recursively trigger ANOTHER eviction (steps 11-23, but for a different
        page entirely) before it can proceed.

28. vmtrace_emit (kernel/vmtrace.c) — logs "read starting."

29. swap_page_read (kernel/swap.c)
      -> swap_page_io (kernel/swap.c) -> virtio_disk_raw_rw (kernel/virtio_disk.c)
      — the actual disk read: this page's bytes come back from its slot.

30. vmtrace_emit (kernel/vmtrace.c) — logs "read finished."

31. The page-table entry is rewritten back to a normal, valid, in-RAM mapping.

32. sfence_vma() — again, clear any stale cached translation.

33. vm_frame_set_backing (kernel/vmpage.c)
      — remembers "this resident page's data still matches slot N on disk," so
        if it gets evicted again UNCHANGED, the write in step 17 can be skipped
        entirely next time.

34. vm_frame_unpin (kernel/vmpage.c) — makes the freshly-restored page evictable again.

35. vmtrace_emit (kernel/vmtrace.c) — logs "mapped."

36. wakeup (kernel/proc.c)
      — releases anyone else who happened to be waiting on this exact page
        (e.g. a prefetch that was also trying to fetch it).

37. (maybe) vm_prefetch_hint + vm_prefetch_service (kernel/prefetch.c)
      — if automatic prefetching is turned on, this ALSO speculatively kicks off
        fetching the NEXT page, betting the program will keep reading forward.

Back to Resident. Steps 10-37 can repeat any number of times if memory stays tight.

Dead — eventually, via shrink or exit.
```

## Lifecycle E — Started by a guess instead of a real touch (prefetch)

Reaches Swapped via an earlier cycle, then instead of the program touching it for real:

```
38. vm_prefetch_hint (kernel/prefetch.c)
      — either the kernel automatically guesses "the next page will probably be
        needed soon" (right after step 35 above), or a test program explicitly
        asks for this page to be prefetched. Either way, this just adds a note
        to a small queue — no disk activity yet.

39. vm_prefetch_service (kernel/prefetch.c)
      — actually processes that queued note and decides how to fetch it:
      -> prefetch_one (kernel/prefetch.c)          [synchronous: fetch it right now,
                                                     blocking this process's own thread]
      -> prefetch_async_one (kernel/prefetch.c)    [asynchronous: hand it to the
                                                     background worker instead and
                                                     move on immediately]
           the real work then happens later, in:
           vm_prefetch_worker (kernel/prefetch.c)   — a dedicated kernel process
             (started once, at boot, by vm_prefetch_worker_start in kernel/proc.c,
              called from main in kernel/main.c) that sits in a loop doing
              nothing but these background fetches.

40. vm_frame_acquire (kernel/vmpage.c), purpose = "prefetch"
      — gets a frame, marked specially so everyone knows this page hasn't
        actually been demonstrated to be needed yet.

41. swap_page_read (kernel/swap.c) -> virtio_disk_raw_rw (kernel/virtio_disk.c)
      — the actual speculative fetch.

42. PTE flipped valid, vm_frame_set_backing (kernel/vmpage.c), wakeup (kernel/proc.c)
      — same finishing steps as a normal fetch.

Now ONE of four things happens to this speculatively-fetched page:

  (a) It gets used for real before anything evicts it:
      vm_frame_note_access (kernel/vmpage.c) — called automatically whenever
        copyin/copyout/copyinstr (kernel/vm.c) touch it —
        or sample_page (kernel/vmpage.c) notices it was accessed during a later
        eviction scan.
      Either way: "oh, this guess paid off" — it's relabeled as an ordinary
      resident page and vmtrace_emit (kernel/vmtrace.c) logs "prefetch used."
      From here it just continues as a normal resident page (Lifecycle B/C/D).

  (b) It gets evicted before ever being touched — a wasted guess:
      reclaim_frame (kernel/vmpage.c) notices this was a still-unused prefetch
      and logs it (vmtrace_emit, "prefetch wasted") before going through the
      exact same eviction steps as Lifecycle C (11-23).

  (c) The memory gets freed, or the process exits, while the fetch is still
      in progress:
      vm_prefetch_cancel_range (kernel/prefetch.c) — marks the in-flight
        request as canceled and waits for the background worker to notice
        and back out cleanly, reverting the page to plain Swapped again.

  (d) The disk read itself fails:
      swap_page_read (kernel/swap.c) reports an error — the page reverts to
      Swapped, and the failure is counted in the stats.
```

---

## Extra interactions that can happen to any page above

**Forking a page (`kfork`, kernel/proc.c → `uvmcopy`, kernel/vm.c):**
- **Resident** → `vm_frame_pin` (kernel/vmpage.c) protects the parent's copy from being evicted mid-copy → `vm_frame_acquire` (kernel/vmpage.c) gets the *child* a brand-new frame → the bytes are physically duplicated → `vm_frame_unpin` releases the protection → `mappages` (kernel/vm.c) installs the child's own mapping. From this instant, parent and child have two completely independent copies with independent futures.
- **Swapped** → `swap_slot_get` (kernel/swap.c) just says "one more owner of this same disk slot" — no data is actually copied yet. Both parent and child point at the same slot until whichever one touches it first pulls its own private copy into RAM.
- **Mid-fetch (busy)** → `sleep_prepare`/`sleep` (kernel/proc.c) makes the fork wait for that in-flight fetch to finish, rather than giving up.

**Running a new program (`kexec`, kernel/exec.c):**
- Everything in the OLD address space — resident or swapped — gets torn down via the same `uvmunmap` path as any other exit (Dead for all of it), after `vm_prefetch_cancel_range` (kernel/prefetch.c) makes sure nothing's left half-finished.
- The NEW program's pages get loaded via `uvmalloc` (kernel/vm.c) while the resident limit is temporarily lifted (so loading the new program doesn't trigger pointless eviction of the old one, which is being thrown away anyway) — then `vm_reclaim_to_limit` (kernel/vmpage.c) brings it back down to the real configured budget once loading is done, possibly evicting some of the freshly-loaded pages immediately if the limit is tight.

**When something goes wrong:**
- No physical memory left at all → `vm_frame_acquire` (kernel/vmpage.c) fails outright → whatever caused the fault fails too → `setkilled` (kernel/proc.c) via `usertrap` (kernel/trap.c).
- Disk write fails during eviction → the victim page is put back exactly as it was (never actually evicted).
- Disk read fails during a fetch → the page reverts to plain Swapped, not busy.
- Wrong kind of access on a valid page (e.g. writing to read-only memory) → `vmfault` (kernel/vm.c) just refuses and the process gets killed — no state ever changes for that page at all.
