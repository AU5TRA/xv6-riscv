// heapbench: malloc/free churn through a general-purpose free-list
// allocator (GAWWY_HANDOFF_NEW_BENCHMARKS.md, section 4.6).
//
//   heapbench <footprint_pages> <resident_margin> <ops> <seed> <mode>
//             [trace: 1=console, 9=file]
//
// The allocator is user/umalloc.c's -- Kernighan and Ritchie's, The C
// Programming Language, 2nd ed., section 8.7 -- run over this program's
// own arena instead of sbrk(), with every header field it reads or writes
// traced: xv6's malloc grows the heap outside any arena and walks its free
// list through untraced headers. Its base header lives in the arena too,
// and "growing the heap" moves a break pointer up within the pre-reserved
// arena, by at least HEAP_MORECORE_MIN units as umalloc's morecore does;
// pages above the break are never touched. free() walks the
// address-ordered free list from the roving pointer to the block's place,
// so as the heap fragments its walks get longer: most of this workload's
// references are those walks, over headers scattered through the heap.
//
// Arena layout: a table of the live objects first (the program's own
// pointers to them, 8 bytes each: payload unit and size), traced, then the
// heap. Each operation, drawn from the PRNG:
//   alloc  malloc a size from the mode's distribution, write the object
//          (one W per page it spans), record it in the table (W);
//   free   pick a live object (table R), free it, and move the table's
//          last entry into its place (R, W);
//   read   pick a live object (table R) and read it (one R per page).
// An operation drawn as a free or read with nothing live allocates.
// Modes:
//   small  60% alloc, 20% free, 20% read; sizes 16-256 bytes, uniform
//   mixed  the same mix; 95% of sizes 16-256 bytes, 5% 1-16 KB
//   churn  50% alloc, 40% free, 10% read; sizes as mixed
//
// PRNG draws, in order, per operation (tools/hostmodel/heapbench.py
// repeats them): kind = below(100); then for an alloc its size (small:
// 16 + below(241); mixed/churn: below(100) < 95 ? 16 + below(241) :
// 1024 + below(15361)), for a free or read the table index below(live).
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define HEAP_MORECORE_MIN 4096 // units, as umalloc.c's morecore
#define HEAP_MAX_LIVE 65536
#define HEAP_MAX_PAGES 4096

typedef long Align;

union header {
  struct {
    union header *ptr;
    uint size;
  } s;
  Align x;
};

typedef union header Header;

struct live {
  uint unit;  // the payload's unit, counted from the base header
  uint bytes;
};

#define HEAP_TABLE_PAGES (HEAP_MAX_LIVE * (int)sizeof(struct live) / VMBENCH_PGSIZE)

struct heap_mode {
  const char *name;
  int alloc_pct;
  int free_pct;
  int mixed_sizes;
};

static const struct heap_mode MODES[] = {
  {"small", 60, 20, 0},
  {"mixed", 60, 20, 1},
  {"churn", 50, 40, 1},
};
#define NMODES ((int)(sizeof(MODES) / sizeof(MODES[0])))

static char *g_arena;
static Header *g_base;  // the heap's base header, in the arena
static Header *g_freep;
static char *g_brk;     // the next unit morecore hands out
static char *g_heap_end;
static long g_morecores, g_walk, g_refs;

static void
htrace(const void *p, char access)
{
  g_refs++;
  vmbench_trace_ref(g_arena,
                    (uint64)(((const char *)p - g_arena) / VMBENCH_PGSIZE),
                    access);
}

// Every header field access is one reference.
static Header *
nxt(Header *h)
{
  htrace(h, VMBENCH_READ);
  return h->s.ptr;
}

static uint
sz(Header *h)
{
  htrace(h, VMBENCH_READ);
  return h->s.size;
}

static void
set_nxt(Header *h, Header *v)
{
  h->s.ptr = v;
  htrace(h, VMBENCH_WRITE);
}

static void
set_sz(Header *h, uint v)
{
  h->s.size = v;
  htrace(h, VMBENCH_WRITE);
}

// umalloc.c's free(), each p->s.ptr read once per step of the walk.
static void
hfree(void *ap)
{
  Header *bp = (Header *)ap - 1, *p = g_freep, *q;
  for(;;){
    q = nxt(p);
    g_walk++;
    if(bp > p && bp < q)
      break;
    if(p >= q && (bp > p || bp < q))
      break;
    p = q;
  }
  uint bsize = sz(bp);
  if(bp + bsize == q){
    uint qsize = sz(q);
    Header *qn = nxt(q);
    set_sz(bp, bsize + qsize);
    set_nxt(bp, qn);
  } else {
    set_nxt(bp, q);
  }
  uint psize = sz(p);
  if(p + psize == bp){
    uint bs = sz(bp);
    set_sz(p, psize + bs);
    Header *bn = nxt(bp);
    set_nxt(p, bn);
  } else {
    set_nxt(p, bp);
  }
  g_freep = p;
}

static Header *
morecore(uint nu)
{
  if(nu < HEAP_MORECORE_MIN)
    nu = HEAP_MORECORE_MIN;
  if(g_brk + (long)nu * (long)sizeof(Header) > g_heap_end)
    return 0;
  Header *hp = (Header *)g_brk;
  g_brk += (long)nu * (long)sizeof(Header);
  g_morecores++;
  set_sz(hp, nu);
  hfree((void *)(hp + 1));
  return g_freep;
}

// umalloc.c's malloc(), with the base header set up in advance.
static void *
hmalloc(uint nbytes)
{
  uint nunits = (nbytes + sizeof(Header) - 1) / sizeof(Header) + 1;
  Header *prevp = g_freep;
  Header *p = nxt(prevp);
  for(;;){
    g_walk++;
    uint psize = sz(p);
    if(psize >= nunits){
      if(psize == nunits){
        Header *pn = nxt(p);
        set_nxt(prevp, pn);
      } else {
        set_sz(p, psize - nunits);
        p += psize - nunits;
        set_sz(p, nunits);
      }
      g_freep = prevp;
      return (void *)(p + 1);
    }
    if(p == g_freep)
      if((p = morecore(nunits)) == 0)
        return 0;
    prevp = p;
    p = nxt(p);
  }
}

// One reference per page the object spans, at the object's first byte in
// that page, so nothing outside it -- a neighbour's header -- is touched.
static void
touch_object(char *obj, uint bytes, char access, uchar val, uint64 *sum)
{
  long first = (obj - g_arena) / VMBENCH_PGSIZE;
  long last = (obj + bytes - 1 - g_arena) / VMBENCH_PGSIZE;
  for(long pg = first; pg <= last; pg++){
    char *a = g_arena + pg * VMBENCH_PGSIZE;
    if(a < obj)
      a = obj;
    if(access == VMBENCH_WRITE)
      *(volatile uchar *)a = val;
    else
      *sum += *(volatile uchar *)a;
    htrace(a, access);
  }
}

static uint
draw_size(struct vmbench_rng *rng, int mixed)
{
  if(mixed && vmbench_rng_below(rng, 100) >= 95)
    return 1024 + (uint)vmbench_rng_below(rng, 15361);
  return 16 + (uint)vmbench_rng_below(rng, 241);
}

static const struct heap_mode *
find_mode(const char *s)
{
  for(int i = 0; i < NMODES; i++)
    if(strcmp(s, MODES[i].name) == 0)
      return &MODES[i];
  printf("heapbench: unknown mode '%s' (want small|mixed|churn)\n", s);
  exit(1);
}

int
main(int argc, char *argv[])
{
  if(argc != 6 && argc != 7){
    printf("usage: heapbench <footprint_pages> <resident_margin> <ops> "
           "<seed> <small|mixed|churn> [trace: 1=console, 9=file]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  long ops = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  const struct heap_mode *m = find_mode(argv[5]);
  int trace_flags = argc == 7 ? atoi(argv[6]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(footprint_pages <= HEAP_TABLE_PAGES + 16 ||
     footprint_pages > HEAP_MAX_PAGES){
    printf("heapbench: footprint_pages must be %d-%d\n",
           HEAP_TABLE_PAGES + 17, HEAP_MAX_PAGES);
    exit(1);
  }
  if(ops < 1){
    printf("heapbench: ops must be at least 1\n");
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("heapbench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }

  vmbench_banner("heapbench", "setup");
  printf("[info] mode %s: K&R free-list allocator in a %d-page arena, %ld "
         "operations from the integer PRNG\n", m->name, footprint_pages, ops);
  g_arena = vmbench_arena(footprint_pages);
  if(g_arena == SBRK_ERROR){
    printf("heapbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }
  struct live *table = (struct live *)g_arena;
  g_base = (Header *)(g_arena + HEAP_TABLE_PAGES * VMBENCH_PGSIZE);
  g_heap_end = g_arena + (long)footprint_pages * VMBENCH_PGSIZE;

  // Touch only the first page before the burn.
  *(volatile int *)g_arena = 0;
  uint64 settled;
  int proven = vmbench_burn(g_arena, footprint_pages, &settled);
  if(proven < 0){
    printf("heapbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("heapbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  // Setup: the empty free list -- the base header pointing at itself, as
  // umalloc's first malloc() makes it -- and the break just above it.
  g_base->s.ptr = g_base;
  g_base->s.size = 0;
  g_freep = g_base;
  g_brk = (char *)(g_base + 1);
  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("heapbench", "workload");
  if(trace)
    vmbench_trace_start("heapbench", m->name, seed, g_arena,
                        footprint_pages, resident_margin);
  long live = 0, peak_live = 0, live_bytes = 0;
  long allocs = 0, frees = 0, reads = 0;
  uint64 checksum = 0, read_sum = 0;
  for(long op = 0; op < ops; op++){
    uint64 r = vmbench_rng_below(&rng, 100);
    if(r < (uint64)m->alloc_pct || live == 0){
      uint bytes = draw_size(&rng, m->mixed_sizes);
      char *obj = hmalloc(bytes);
      if(obj == 0){
        printf("heapbench: heap exhausted after %ld operations\n", op);
        exit(1);
      }
      if(live == HEAP_MAX_LIVE){
        printf("heapbench: more than %d live objects\n", HEAP_MAX_LIVE);
        exit(1);
      }
      touch_object(obj, bytes, VMBENCH_WRITE, (uchar)op, &read_sum);
      uint unit = (uint)((Header *)obj - g_base);
      table[live].unit = unit;
      table[live].bytes = bytes;
      htrace(&table[live], VMBENCH_WRITE);
      live++;
      allocs++;
      live_bytes += bytes;
      if(live > peak_live)
        peak_live = live;
      checksum += unit;
    } else if(r < (uint64)(m->alloc_pct + m->free_pct)){
      long i = (long)vmbench_rng_below(&rng, (uint64)live);
      htrace(&table[i], VMBENCH_READ);
      uint unit = table[i].unit;
      uint bytes = table[i].bytes;
      hfree((void *)(g_base + unit));
      long last = live - 1;
      if(i != last){
        htrace(&table[last], VMBENCH_READ);
        table[i] = table[last];
        htrace(&table[i], VMBENCH_WRITE);
      }
      live--;
      frees++;
      live_bytes -= bytes;
    } else {
      long i = (long)vmbench_rng_below(&rng, (uint64)live);
      htrace(&table[i], VMBENCH_READ);
      touch_object((char *)(g_base + table[i].unit), table[i].bytes,
                   VMBENCH_READ, 0, &read_sum);
      reads++;
    }
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("heapbench workload", &d);

  // After the snapshot, so it is outside both the trace and the counters.
  long free_blocks = 0;
  Header *fp = g_freep->s.ptr;
  for(;;){
    free_blocks++;
    if(fp == g_freep)
      break;
    fp = fp->s.ptr;
  }
  long heap_bytes = g_brk - (char *)g_base;

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("ops", ops);
  vmbench_result("seed", (long)seed);
  vmbench_result("alloc_pct", m->alloc_pct);
  vmbench_result("free_pct", m->free_pct);
  vmbench_result("max_object", m->mixed_sizes ? 16384 : 256);
  vmbench_result("allocs", allocs);
  vmbench_result("frees", frees);
  vmbench_result("reads", reads);
  vmbench_result("live_objects", live);
  vmbench_result("peak_live", peak_live);
  vmbench_result("live_bytes", live_bytes);
  vmbench_result("heap_pages", (heap_bytes + VMBENCH_PGSIZE - 1) /
                                 VMBENCH_PGSIZE);
  vmbench_result("morecores", g_morecores);
  vmbench_result("free_list_blocks", free_blocks);
  vmbench_result("walk_steps", g_walk);
  vmbench_result("checksum", (long)checksum);
  vmbench_result("trace_refs", g_refs);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
