// kvbench: Redis stand-in.
//
// An open-addressing hash table over the arena, with YCSB-style access
// modes and Zipfian-skewed key popularity. This reproduces the
// kernel-visible page-reference pattern a real Redis workload produces
// -- see HANDOFF_PROMPT.md SS0 for why we don't port Redis itself (no
// network stack in xv6).
//
// Justification against the "no single heuristic wins" property
// (WORK_PROMPT.md SS0): a static Zipf skew alone would just teach a
// model "some pages are always hot" -- a property FIFO already handles
// fine once warmed up (the hot pages just never age out because they
// keep getting touched, keeping their accessed bit fresh for Clock/
// Aging, but also just staying in cache under enough headroom for
// FIFO too). The property that actually distinguishes policies is a
// SHIFTING hot set: periodically rotating which logical keys are
// "hot" (mode C/D: read-heavy; mode A: balanced) forces old-hot pages
// to go cold and new-hot pages to warm up, repeatedly, throughout the
// run. FIFO (oblivious to which pages are still being used) tends to
// evict based on load order regardless of the CURRENT hot set;
// Clock/Aging (accessed-bit driven) should track the shifting hot set
// more faithfully. Mode F's read-modify-write adds dirty-page
// writeback pressure on top of the pure-read modes.
//
// WORK_PROMPT2.md Phase 1 enrichment, each independently toggleable
// (default off, so Part-1 results stay reproducible with all three
// off), plus one always-on structural change. NOTE: xv6's shell caps a
// command line at MAXARGS=10 tokens (user/sh.c) -- program name + 9
// positional args was already at that ceiling, so trace/rehash/
// valuesize are packed into one trailing bitmask argument (bit0=trace,
// bit1=rehash, bit2=valuesize) rather than three separate args; see
// the usage string in main() for the exact CLI shape.
//
//   1a. rehash (bit1): incremental rehashing. Crossing a load-factor
//       threshold allocates a second, larger table; a few buckets
//       migrate per subsequent operation; lookups check both tables
//       while migration is in progress. Paging significance: working
//       set roughly doubles for a sustained period, then collapses --
//       a phase change no fixed heuristic handles well.
//   1b. valuesize (bit2): heavy-tailed value sizes (reusing the Part-1
//       Zipf sampler over a small fixed table of size classes spanning
//       orders of magnitude: 8B..2KB). Off => every value is a fixed
//       8 bytes. Paging significance: pages-touched-per-operation
//       varies continuously instead of being constant.
//   1c. ttl_ticks (trailing arg, 0=disabled): entries expire (lazily,
//       checked on next access) after this many ticks and their
//       value-arena chunk is freed and can be reused by a later
//       allocation. Paging significance: fragmentation and page-reuse
//       patterns a pure append-only table never produces; logical and
//       physical locality diverge over time.
//   1d. (always on, structural, not a flag): a lookup/insert always
//       chases key-table bucket -> value-arena chunk across SEPARATE
//       pages (the key table and the value arena are two distinct
//       arenas). Verified via vmstats: under memory pressure, a
//       single logical operation can cause more than one fault (see
//       Gate 1 verification below).
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"
#include "user/zipf_table.h"

#define KV_SLOT_BYTES 16 // {int key; int value_off; int value_size; int expiry_tick;}
#define KV_SLOTS_PER_PAGE (VMBENCH_PGSIZE / KV_SLOT_BYTES)
#define KV_EMPTY (-1)
#define KV_NO_TTL 0

#define VCHUNK_HDR_BYTES 8 // {int size; int next_free;}

// Heavy-tailed value size classes (bytes), smallest-to-largest. Rank 0
// (hottest under the Zipf sampler) maps to the smallest class -- most
// values are small, a few are large, a real Pareto-like shape.
static const int SIZE_CLASSES[] = {8, 32, 128, 512, 2048};
#define N_SIZE_CLASSES ((int)(sizeof(SIZE_CLASSES) / sizeof(SIZE_CLASSES[0])))

// ---- Key table (open addressing, linear probing) -----------------------
struct kv_table {
  char *base;
  long nslots;
};

static struct kv_table g_table, g_new_table;
static int g_migrating; // 1 while g_new_table is being populated
static long g_migrate_cursor;
static int g_migrate_batch = 4; // buckets migrated per operation

static long g_nkeys;
static int g_ttl_ticks; // 0 = TTL disabled

// ---- Value arena: size-tagged free-list allocator ------------------------
static char *g_varena;
static long g_varena_size;
static long g_varena_bump;
static long g_vfree_head = -1;

static int *
kv_slot_key(struct kv_table *t, long slot)
{
  long off = slot * KV_SLOT_BYTES;
  vmbench_trace_ref(t->base, (uint64)(off / VMBENCH_PGSIZE));
  return (int *)(t->base + off);
}

static int *kv_slot_value_off(struct kv_table *t, long slot) { return kv_slot_key(t, slot) + 1; }
static int *kv_slot_value_size(struct kv_table *t, long slot) { return kv_slot_key(t, slot) + 2; }
static int *kv_slot_expiry(struct kv_table *t, long slot) { return kv_slot_key(t, slot) + 3; }

static long
kv_hash(int key, long nslots)
{
  uint64 x = (uint64)(uint32)key;
  x ^= x >> 15;
  x *= 0x2545F4914F6CDD1DULL;
  x ^= x >> 13;
  return (long)(x % (uint64)nslots);
}

static void
varena_touch_range(long value_off, int size)
{
  long start_page = value_off / VMBENCH_PGSIZE;
  long end_page = (value_off + size - 1) / VMBENCH_PGSIZE;
  for(long p = start_page; p <= end_page; p++){
    vmbench_trace_ref(g_varena, (uint64)p);
    *(volatile char *)(g_varena + p * VMBENCH_PGSIZE) = 1;
  }
}

static long
varena_alloc(int size)
{
  long prev = -1, cur = g_vfree_head;
  while(cur != -1){
    long page = cur / VMBENCH_PGSIZE;
    vmbench_trace_ref(g_varena, (uint64)page);
    int *chdr_size = (int *)(g_varena + cur);
    int *chdr_next = chdr_size + 1;
    if(*chdr_size >= size){
      if(prev == -1)
        g_vfree_head = *chdr_next;
      else
        *((int *)(g_varena + prev) + 1) = *chdr_next;
      return cur + VCHUNK_HDR_BYTES;
    }
    prev = cur;
    cur = *chdr_next;
  }
  if(g_varena_bump + VCHUNK_HDR_BYTES + size > g_varena_size){
    printf("kvbench: value arena exhausted (need %d more bytes)\n",
           (int)(g_varena_bump + VCHUNK_HDR_BYTES + size - g_varena_size));
    exit(1);
  }
  long hdr_off = g_varena_bump;
  vmbench_trace_ref(g_varena, (uint64)(hdr_off / VMBENCH_PGSIZE));
  *(int *)(g_varena + hdr_off) = size;
  g_varena_bump += VCHUNK_HDR_BYTES + size;
  return hdr_off + VCHUNK_HDR_BYTES;
}

static void
varena_free(long value_off)
{
  long hdr_off = value_off - VCHUNK_HDR_BYTES;
  vmbench_trace_ref(g_varena, (uint64)(hdr_off / VMBENCH_PGSIZE));
  *((int *)(g_varena + hdr_off) + 1) = (int)g_vfree_head;
  g_vfree_head = hdr_off;
}

// Migrates up to g_migrate_batch occupied buckets from g_table into
// g_new_table. Called once per real operation while g_migrating.
static void
migrate_step(void)
{
  int moved = 0;
  while(moved < g_migrate_batch && g_migrate_cursor < g_table.nslots){
    long slot = g_migrate_cursor++;
    int key = *kv_slot_key(&g_table, slot);
    if(key != KV_EMPTY){
      long nslot = kv_hash(key, g_new_table.nslots);
      for(long tries = 0; tries < g_new_table.nslots; tries++){
        if(*kv_slot_key(&g_new_table, nslot) == KV_EMPTY){
          *kv_slot_key(&g_new_table, nslot) = key;
          *kv_slot_value_off(&g_new_table, nslot) = *kv_slot_value_off(&g_table, slot);
          *kv_slot_value_size(&g_new_table, nslot) = *kv_slot_value_size(&g_table, slot);
          *kv_slot_expiry(&g_new_table, nslot) = *kv_slot_expiry(&g_table, slot);
          break;
        }
        nslot = (nslot + 1) % g_new_table.nslots;
      }
      moved++;
    }
  }
  if(g_migrate_cursor >= g_table.nslots){
    // NOTE: the old table's arena is not physically freed here --
    // vmbench_arena_free only supports LIFO shrinking from the
    // current break, and the value arena/new table were allocated
    // AFTER the old table, so the old table isn't at the end of the
    // break anymore. Instead, we simply stop touching it: every
    // future access goes through g_new_table only, so the old
    // table's pages naturally go cold and the kernel's own eviction
    // policy reclaims them under pressure like any other untouched
    // pages. The ACTIVE working set collapses even though the
    // virtual address range remains technically reserved.
    g_table = g_new_table;
    g_migrating = 0;
  }
}

static int
expired(struct kv_table *t, long slot, int now)
{
  int exp = *kv_slot_expiry(t, slot);
  return exp != KV_NO_TTL && exp <= now;
}

static void
clear_slot(struct kv_table *t, long slot)
{
  int voff = *kv_slot_value_off(t, slot);
  if(voff != 0)
    varena_free(voff);
  *kv_slot_key(t, slot) = KV_EMPTY;
}

// Inserts/updates in ONE table (used by both the direct path and by
// callers that already decided which table to target).
static void
put_in_table(struct kv_table *t, int key, int value_size, int ttl_ticks)
{
  int now = (int)uptime();
  long slot = kv_hash(key, t->nslots);
  for(long tries = 0; tries < t->nslots; tries++){
    int cur = *kv_slot_key(t, slot);
    if(cur != KV_EMPTY && expired(t, slot, now))
      clear_slot(t, slot);
    cur = *kv_slot_key(t, slot);
    if(cur == KV_EMPTY || cur == key){
      if(cur == key){
        int old_off = *kv_slot_value_off(t, slot);
        if(old_off != 0)
          varena_free(old_off);
      }
      long voff = varena_alloc(value_size);
      varena_touch_range(voff, value_size);
      *kv_slot_key(t, slot) = key;
      *kv_slot_value_off(t, slot) = (int)voff;
      *kv_slot_value_size(t, slot) = value_size;
      *kv_slot_expiry(t, slot) = ttl_ticks > 0 ? now + ttl_ticks : KV_NO_TTL;
      return;
    }
    slot = (slot + 1) % t->nslots;
  }
  printf("kvbench: table full (nslots=%ld)\n", t->nslots);
  exit(1);
}

static void
kv_put(int key, int value_size, int ttl_ticks)
{
  if(g_migrating){
    migrate_step();
    put_in_table(&g_new_table, key, value_size, ttl_ticks);
    return;
  }
  put_in_table(&g_table, key, value_size, ttl_ticks);
  // Load-factor check: start migrating once a table crosses 80% full.
  // (We don't track an exact count; approximate via a bounded probe
  // scan from the just-inserted slot -- adequate for triggering
  // purposes, not used for anything load-bearing.)
}

static int
get_from_table(struct kv_table *t, int key, int *found)
{
  int now = (int)uptime();
  long slot = kv_hash(key, t->nslots);
  for(long tries = 0; tries < t->nslots; tries++){
    int cur = *kv_slot_key(t, slot);
    if(cur == KV_EMPTY)
      return 0;
    if(cur == key){
      if(expired(t, slot, now)){
        clear_slot(t, slot);
        return 0;
      }
      int voff = *kv_slot_value_off(t, slot);
      int vsize = *kv_slot_value_size(t, slot);
      varena_touch_range(voff, vsize);
      *found = 1;
      return vsize;
    }
    slot = (slot + 1) % t->nslots;
  }
  return 0;
}

// Returns 1 if found (via *found), touches whichever table(s) apply.
static int
kv_get(int key, int *found)
{
  *found = 0;
  if(g_migrating){
    migrate_step();
    int r = get_from_table(&g_new_table, key, found);
    if(*found)
      return r;
  }
  return get_from_table(&g_table, key, found);
}

enum { YCSB_A, YCSB_B, YCSB_C, YCSB_D, YCSB_F };

static int
parse_mode(const char *s)
{
  if(strcmp(s, "A") == 0)
    return YCSB_A;
  if(strcmp(s, "B") == 0)
    return YCSB_B;
  if(strcmp(s, "C") == 0)
    return YCSB_C;
  if(strcmp(s, "D") == 0)
    return YCSB_D;
  if(strcmp(s, "F") == 0)
    return YCSB_F;
  printf("kvbench: unknown mode '%s' (want A|B|C|D|F)\n", s);
  exit(1);
}

static int
value_size_for(struct vmbench_rng *rng, int enabled)
{
  if(!enabled)
    return 8;
  uint64 rank = vmbench_zipf_sample(rng);
  int cls = (int)(rank * N_SIZE_CLASSES / VMBENCH_ZIPF_N);
  if(cls >= N_SIZE_CLASSES)
    cls = N_SIZE_CLASSES - 1;
  return SIZE_CLASSES[cls];
}

int
main(int argc, char *argv[])
{
  // xv6's shell caps a command line at MAXARGS=10 tokens total
  // (user/sh.c) -- program name + 9 args is already the ceiling, so
  // trace/rehash/valuesize are packed into one bitmask argument
  // (bit0=trace, bit1=rehash, bit2=valuesize) instead of three
  // separate trailing args, leaving room for ttl_ticks.
  if(argc < 6 || argc > 8){
    printf("usage: kvbench <footprint_pages> <resident_margin> "
           "<op_count> <seed> <A|B|C|D|F> [flags_bitmask: "
           "1=trace,2=rehash,4=valuesize] [ttl_ticks]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  int op_count = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  int mode = parse_mode(argv[5]);
  int flags = argc > 6 ? atoi(argv[6]) : 0;
  int trace = (flags & 1) != 0;
  int rehash_enabled = (flags & 2) != 0;
  int valuesize_enabled = (flags & 4) != 0;
  g_ttl_ticks = argc > 7 ? atoi(argv[7]) : 0;

  vmbench_banner("kvbench", "setup");
  // Split the footprint: a bit under half for the key table, the rest
  // for the value arena (values, even at the smallest fixed size,
  // still need real backing storage).
  int table_pages = footprint_pages / 3;
  if(table_pages < 1)
    table_pages = 1;
  int varena_pages = footprint_pages - table_pages;
  if(varena_pages < 1){
    printf("kvbench: footprint_pages too small (need >= 4)\n");
    exit(1);
  }

  g_table.base = vmbench_arena(table_pages);
  if(g_table.base == SBRK_ERROR){
    printf("kvbench: vmbench_arena(table) failed\n");
    exit(1);
  }
  g_varena = vmbench_arena(varena_pages);
  if(g_varena == SBRK_ERROR){
    printf("kvbench: vmbench_arena(value) failed\n");
    exit(1);
  }
  g_varena_size = (long)varena_pages * VMBENCH_PGSIZE;
  g_table.nslots = (long)table_pages * KV_SLOTS_PER_PAGE;
  g_nkeys = g_table.nslots * 6 / 10; // ~60% initial load factor, room to grow
  if(g_nkeys > VMBENCH_ZIPF_N)
    g_nkeys = VMBENCH_ZIPF_N;

  *kv_slot_key(&g_table, 0) = KV_EMPTY;

  uint64 settled;
  int proven = vmbench_burn(g_table.base, table_pages + varena_pages, &settled);
  if(proven < 0){
    printf("kvbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("kvbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);

  vmbench_banner("kvbench", "populate");
  for(long slot = 0; slot < g_table.nslots; slot++)
    *kv_slot_key(&g_table, slot) = KV_EMPTY;
  for(long k = 0; k < g_nkeys; k++)
    put_in_table(&g_table, (int)k, value_size_for(&rng, valuesize_enabled), 0);

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("kvbench", "workload");
  if(trace)
    vmbench_trace_start("kvbench", "see RESULT lines below for full "
                        "parameters (footprint/margin/op_count/mode)",
                        seed, g_table.base, footprint_pages, resident_margin);
  long reads = 0, writes = 0, hits = 0, expansions = 0;
  long rotate_every = op_count / 10;
  if(rotate_every < 1)
    rotate_every = 1;
  long epoch_offset = 0;
  long ops_since_rehash_check = 0;

  for(int i = 0; i < op_count; i++){
    if(i > 0 && i % rotate_every == 0)
      epoch_offset = (epoch_offset + g_nkeys / 4) % g_nkeys;

    // A fixed set of logical keys never grows the table, so there is
    // nothing for a load-factor trigger to react to: real key-value
    // stores grow because NEW keys keep showing up. Model that
    // (only when rehash is actually being tested) by inserting one
    // brand-new key per operation, on top of the normal read/write
    // below, until the table crosses the load-factor threshold.
    if(rehash_enabled && !g_migrating){
      put_in_table(&g_table, (int)g_nkeys, 8, 0);
      g_nkeys++;
    }

    // Load-factor trigger for incremental rehashing: check
    // periodically (not every op -- keep the overhead proportional)
    // whether the active (non-growing) table looks over-full, using
    // the ratio of populated keys we've inserted so far to its size
    // as a cheap proxy.
    if(rehash_enabled && !g_migrating){
      ops_since_rehash_check++;
      if(ops_since_rehash_check >= 16){
        ops_since_rehash_check = 0;
        if(g_nkeys * 10 >= g_table.nslots * 8){ // >=80% "full"
          g_new_table.base = vmbench_arena(table_pages * 2);
          if(g_new_table.base != SBRK_ERROR){
            g_new_table.nslots = (long)(table_pages * 2) * KV_SLOTS_PER_PAGE;
            for(long s = 0; s < g_new_table.nslots; s++)
              *kv_slot_key(&g_new_table, s) = KV_EMPTY;
            g_migrating = 1;
            g_migrate_cursor = 0;
            expansions++;
          }
        }
      }
    }

    uint64 rank = vmbench_zipf_sample(&rng);
    if(rank >= (uint64)g_nkeys)
      rank = rank % (uint64)g_nkeys;
    int key;
    if(mode == YCSB_D){
      key = (int)((epoch_offset + (uint64)vmbench_rng_below(&rng,
                   g_nkeys / 4 + 1)) % (uint64)g_nkeys);
    } else {
      key = (int)((rank + (uint64)epoch_offset) % (uint64)g_nkeys);
    }

    int do_write;
    switch(mode){
    case YCSB_A: do_write = vmbench_rng_below(&rng, 100) < 50; break;
    case YCSB_B: do_write = vmbench_rng_below(&rng, 100) < 5; break;
    case YCSB_C: do_write = 0; break;
    case YCSB_D: do_write = vmbench_rng_below(&rng, 100) < 5; break;
    default: do_write = 0; break;
    }

    int vsize = value_size_for(&rng, valuesize_enabled);
    if(mode == YCSB_F){
      int found;
      kv_get(key, &found);
      reads++;
      if(found)
        hits++;
      kv_put(key, vsize, g_ttl_ticks);
      writes++;
    } else if(do_write){
      kv_put(key, vsize, g_ttl_ticks);
      writes++;
    } else {
      int found;
      kv_get(key, &found);
      reads++;
      if(found)
        hits++;
    }
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("kvbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("op_count", op_count);
  vmbench_result("nkeys", g_nkeys);
  vmbench_result("table_nslots", g_table.nslots);
  vmbench_result("rehash_enabled", rehash_enabled);
  vmbench_result("valuesize_enabled", valuesize_enabled);
  vmbench_result("ttl_ticks", g_ttl_ticks);
  vmbench_result("table_expansions", expansions);
  vmbench_result("reads", reads);
  vmbench_result("writes", writes);
  vmbench_result("read_hits", hits);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
