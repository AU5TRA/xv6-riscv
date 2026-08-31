# Paging structure — hardware translation hierarchy and full mechanism

## Is there a separate "OS-level" page table hierarchy?

No — and this is worth being precise about. The OS-level page table **is**
the multi-level structure below, not a separate thing sitting apart from
it. The kernel builds that 3-level tree itself, one table page at a time
(`mappages()`/`walk()` in `kernel/vm.c` allocate and fill in L2/L1/L0
tables directly), and the CPU's MMU reads that exact same tree
automatically on every real memory access. One structure, two roles:
kernel writes it, hardware reads it at full speed without a trap on every
access. There's no second, separate software-only translation hierarchy
to add — the OS already fully owns the one that exists.

What *is* separate, and correctly stays flat (not hierarchical), is the
extra bookkeeping the paging subsystem layers alongside — the
frame-ownership table and the swap-slot table. Those answer different
questions ("who owns this frame," "is this disk slot free") over small,
bounded, dense keyspaces, so a flat array is the right tool, not a missing
hierarchy. See diagram 3 below.

---

## 1. The hardware translation hierarchy (walked by the CPU on every access, built by the kernel)

```
                    39-bit VIRTUAL ADDRESS
   +------------+------------+------------+--------------+
   |  L2 index  |  L1 index  |  L0 index  |    offset    |
   |  9 bits    |  9 bits    |  9 bits    |   12 bits    |
   +------------+------------+------------+--------------+

satp (per-process root)
   |
   v
+----------------+
|  L2 TABLE       |  512 entries
|  entry[L2 idx] -+----+
+----------------+     |  PPN of next table
                        v
              +----------------+
              |  L1 TABLE       |  512 entries
              |  entry[L1 idx] -+----+
              +----------------+     |  PPN of next table
                                      v
                            +----------------+
                            |  L0 TABLE       |  512 entries
                            |  entry[L0 idx] -+----+
                            +----------------+     |  this IS the leaf PTE
                                                    v
                                          PPN (44 bits) + offset (12 bits)
                                                    |
                                                    v
                                          PHYSICAL ADDRESS
```

## 2. The leaf PTE itself — every bit, stock vs. added

```
   63 ..................... 10  9    8    7   6   5   4   3   2   1   0
  +----------------------------+----+----+---+---+---+---+---+---+---+---+
  |   PPN (44 bits)            |BUSY|SWAP| D | A | G | U | X | W | R | V |
  +----------------------------+----+----+---+---+---+---+---+---+---+---+
                                 ^    ^     ^   ^        (stock: V R W X U G)
                                 |    |     |   |
                          added -+    |     |   +-- added (bit meaning existed
                          this        |     |        in hw, unused before)
                          repo        |     +-- added
                                 added-+

  When SWAPPED=1 and V=0: the PPN field above is REINTERPRETED --
  it no longer holds a physical frame number, it holds a swap slot
  number instead. Same 44 bits, different meaning depending on V/SWAPPED.
```

## 3. The full mechanism — one process's pages moving between RAM and disk

```
              LAZY HOLE  (*pte == 0, no PTE at all yet)
                    |
                    | first touch -> vmfault() zero-fault path
                    v
   +-----------------------------------------------------+
   |               RESIDENT  (PTE_V=1)                    |
   |   metadata says: Demand, or Prefetch-not-yet-used    |<---+
   +-----------------------------------------------------+    |
        |                                                     |
        | budget full -> reclaim_frame() picks a victim        | vmfault() SWAPPED
        v                                                     | branch: read it
   EVICTING (transient: locked, being written to disk)         | back from disk
        |                                                     |
        v                                                     |
   +-----------------------------------------------------+    |
   |     SWAPPED  (PTE_V=0, PTE_SWAPPED=1, PPN=slot#)     +----+
   +-----------------------------------------------------+
        |          ^
        | touched  | (PTE_BUSY=1 while the disk read is actually in flight
        v          |  -- this IS the "FETCHING" state, a PTE-bit combo,
   FETCHING --------+   not a separate metadata field)
        |
        | process exits / unmap
        v
      DEAD  (PTE cleared, frame and/or swap slot released back)


        RAM (this machine's physical frames)         DISK (the swap region)
   +--------------------------------+          +--------------------------------+
   | struct vm_page frame_table[]   |          |  ushort refs[NSWAPSLOTS]        |
   | flat array, 1 entry per        |          |  flat array, 1 entry per        |
   | physical frame (32768 total)   |          |  4KB swap slot (1024 total)     |
   |                                |          |                                  |
   | frame #32546  <-- resident ----+--evict-->|  slot 0  <-- now holds it       |
   | frame #32538  <-- resident     |<--fetch--+  slot 1  <-- another swapped pg |
   | frame #32539  <-- resident     |          |  slot 2     free                |
   +--------------------------------+          +--------------------------------+
             ^
             | this process's OWN frames only, threaded onto its own
             | linked list (vmstate.owned_head/tail) -- eviction never
             | searches any other process's frames
```

The Part-1 hierarchy is the *only* tree in this whole system — everything
in Part 3 (frame table, swap table, the per-process list) is deliberately
flat: those keyspaces are small and dense, so a tree would be solving a
problem that isn't there.
