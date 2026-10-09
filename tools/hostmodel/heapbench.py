"""Host model of user/heapbench.c: the K&R allocator of user/umalloc.c run
over unit offsets instead of pointers, with the same field accesses and the
same PRNG draws, so the same reference string and RESULT lines.

    python3 tools/hostmodel/heapbench.py <footprint> <margin> <ops> <seed> <mode> [flags]
"""
from __future__ import annotations

if __package__ in (None, ""):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .common import PGSIZE, Rng

UNIT = 16              # sizeof(Header)
MORECORE_MIN = 4096    # units, as umalloc.c's morecore
TABLE_ENTRY = 8        # {uint32 payload unit, uint32 bytes}
MAX_LIVE = 65536
TABLE_PAGES = MAX_LIVE * TABLE_ENTRY // PGSIZE
MAX_PAGES = 4096

# name -> (alloc %, free %, sizes); the rest of the draws are reads
MODES = {
    "small": (60, 20, "small"),
    "mixed": (60, 20, "mixed"),
    "churn": (50, 40, "mixed"),
}


def draw_size(rng, sizes):
    if sizes == "small":
        return 16 + rng.below(241)                 # 16..256 bytes
    if rng.below(100) < 95:
        return 16 + rng.below(241)
    return 1024 + rng.below(15361)                 # 1 KB..16 KB


class Heap:
    """umalloc.c's allocator. Headers are unit numbers counted from the
    heap region's base header (unit 0); ptr[u] and size[u] are its fields.
    Each field access is one reference to the page holding the header."""

    def __init__(self, base_byte, heap_units, ref):
        self.base_byte = base_byte
        self.limit = heap_units
        self.ref = ref
        self.ptr = {0: 0}
        self.size = {0: 0}
        self.freep = 0
        self.brk = 1            # the first unit above the base header
        self.morecores = 0
        self.walk = 0           # header visits in malloc/free loops

    def page(self, u):
        return (self.base_byte + u * UNIT) // PGSIZE

    def nxt(self, u):
        self.ref(self.page(u), False)
        return self.ptr[u]

    def sz(self, u):
        self.ref(self.page(u), False)
        return self.size[u]

    def set_nxt(self, u, v):
        self.ptr[u] = v
        self.ref(self.page(u), True)

    def set_sz(self, u, v):
        self.size[u] = v
        self.ref(self.page(u), True)

    def free(self, ap):
        bp = ap - 1
        p = self.freep
        while True:
            q = self.nxt(p)
            self.walk += 1
            if bp > p and bp < q:
                break
            if p >= q and (bp > p or bp < q):
                break
            p = q
        bsize = self.sz(bp)
        if bp + bsize == q:
            qsize = self.sz(q)
            qn = self.nxt(q)
            self.set_sz(bp, bsize + qsize)
            self.set_nxt(bp, qn)
        else:
            self.set_nxt(bp, q)
        psize = self.sz(p)
        if p + psize == bp:
            self.set_sz(p, psize + self.sz(bp))
            self.set_nxt(p, self.nxt(bp))
        else:
            self.set_nxt(p, bp)
        self.freep = p

    def morecore(self, nu):
        if nu < MORECORE_MIN:
            nu = MORECORE_MIN
        if self.brk + nu > self.limit:
            return None
        hp = self.brk
        self.brk += nu
        self.morecores += 1
        self.set_sz(hp, nu)
        self.free(hp + 1)
        return self.freep

    def malloc(self, nbytes):
        nunits = (nbytes + UNIT - 1) // UNIT + 1
        prevp = self.freep
        p = self.nxt(prevp)
        while True:
            self.walk += 1
            psize = self.sz(p)
            if psize >= nunits:
                if psize == nunits:
                    self.set_nxt(prevp, self.nxt(p))
                else:
                    self.set_sz(p, psize - nunits)
                    p += psize - nunits
                    self.set_sz(p, nunits)
                self.freep = prevp
                return p + 1
            if p == self.freep:
                p = self.morecore(nunits)
                if p is None:
                    return None
            prevp = p
            p = self.nxt(p)


def run(args, ref):
    if len(args) not in (5, 6):
        raise SystemExit("heapbench model: want 5 or 6 arguments")
    P, margin, ops, seed = (int(a) for a in args[:4])
    if args[4] not in MODES:
        raise SystemExit("heapbench model: unknown mode %r" % args[4])
    p_alloc, p_free, sizes = MODES[args[4]]
    if not TABLE_PAGES + 16 < P <= MAX_PAGES or ops < 1:
        raise SystemExit("heapbench model: arguments out of range")
    count = [0]
    outer_ref = ref

    def ref(page, write):
        count[0] += 1
        outer_ref(page, write)

    heap_base = TABLE_PAGES * PGSIZE
    heap = Heap(heap_base, (P - TABLE_PAGES) * PGSIZE // UNIT, ref)

    def touch_object(ap, nbytes, write):
        first = (heap_base + ap * UNIT) // PGSIZE
        last = (heap_base + ap * UNIT + nbytes - 1) // PGSIZE
        for pg in range(first, last + 1):
            ref(pg, write)

    rng = Rng(seed)
    t_off = []      # live table: payload unit of each live object
    t_len = []      # and its size in bytes
    allocs = frees = reads = 0
    live_bytes = peak_live = checksum = 0

    def table_ref(i, write):
        ref(i * TABLE_ENTRY // PGSIZE, write)

    for _ in range(ops):
        r = rng.below(100)
        n_live = len(t_off)
        if r < p_alloc or n_live == 0:
            nbytes = draw_size(rng, sizes)
            ap = heap.malloc(nbytes)
            if ap is None:
                raise SystemExit("heapbench model: heap exhausted")
            if n_live == MAX_LIVE:
                raise SystemExit("heapbench model: live table full")
            touch_object(ap, nbytes, True)
            t_off.append(ap)
            t_len.append(nbytes)
            table_ref(n_live, True)
            allocs += 1
            live_bytes += nbytes
            peak_live = max(peak_live, n_live + 1)
            checksum += ap
        elif r < p_alloc + p_free:
            i = rng.below(n_live)
            table_ref(i, False)
            ap, nbytes = t_off[i], t_len[i]
            heap.free(ap)
            last = n_live - 1
            if i != last:
                table_ref(last, False)
                t_off[i], t_len[i] = t_off[last], t_len[last]
                table_ref(i, True)
            t_off.pop()
            t_len.pop()
            frees += 1
            live_bytes -= nbytes
        else:
            i = rng.below(n_live)
            table_ref(i, False)
            touch_object(t_off[i], t_len[i], False)
            reads += 1

    # free-list length at the end (not traced: the run counts it the same
    # way, after tracing stops)
    flen, p = 0, heap.ptr[heap.freep]
    while True:
        flen += 1
        if p == heap.freep:
            break
        p = heap.ptr[p]

    return {
        "footprint_pages": P,
        "resident_margin": margin,
        "ops": ops,
        "seed": seed,
        "alloc_pct": p_alloc,
        "free_pct": p_free,
        "max_object": 256 if sizes == "small" else 16384,
        "allocs": allocs,
        "frees": frees,
        "reads": reads,
        "live_objects": len(t_off),
        "peak_live": peak_live,
        "live_bytes": live_bytes,
        "heap_pages": (heap.brk * UNIT + PGSIZE - 1) // PGSIZE,
        "morecores": heap.morecores,
        "free_list_blocks": flen,
        "walk_steps": heap.walk,
        "checksum": checksum,
        "trace_refs": count[0],
    }


if __name__ == "__main__":
    from .check_run import model_main
    model_main("heapbench")
