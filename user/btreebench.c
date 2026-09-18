// btreebench: SQLite B-tree pager stand-in.
//
// This reproduces SQLite's B-tree pager access pattern -- the
// kernel-visible page-reference behavior real SQLite would produce when
// its pager reads/writes 4KB database pages, independent of SQLite's own
// (unavailable) SQL layer. See HANDOFF_PROMPT.md SS0 for why we don't
// port SQLite itself (no lseek, no floating point, and, at the time this
// decision was made, xv6's ~268KB max file size meant a real database
// would fit entirely inside SQLite's own page cache anyway -- a later
// merge raised that cap to ~64MB, see tracereplay.c's header comment,
// but the native-workload approach and everything calibrated against it
// stand regardless of that).
//
// Justification against the "no single heuristic wins" property
// (WORK_PROMPT.md SS0): a B+tree's three operations each stress a
// DIFFERENT kind of locality, so no single simple policy dominates
// across a mixed run:
//   - insert:  newly-created leaves are touched once and often not
//              revisited soon -- pure recency (LRU/Clock) helps here,
//              but pure frequency does not (a fresh leaf has no history
//              yet).
//   - lookup:  root-to-leaf traversal repeatedly re-hits the SAME small
//              set of upper-level nodes (root, and a handful of
//              internal nodes near it) -- frequency/aging-style
//              "seen many times" tracking helps here, but plain FIFO
//              (which only knows load order, not how often a page is
//              re-used) does not, since those hot nodes may have been
//              loaded a long time ago.
//   - scan:    sequential leaf-chain traversal is pure spatial locality
//              -- favors read-ahead/prefetch, and is largely indifferent
//              to recency or frequency tracking.
// A workload that only inserted would teach a model "recency is
// everything"; one that only looked up existing keys would teach
// "frequency is everything"; one that only scanned would teach
// "sequential prefetch is everything". Mixing all three, with a
// configurable ratio, is what makes this workload actually exercise the
// distinction between FIFO/Clock/Aging instead of trivially favoring
// whichever one happens to match a single access mode.
//
// One B+tree node occupies exactly one arena page (4KB) -- this is the
// property that makes the tree's structure directly visible in the
// paging trace: a root-to-leaf lookup is literally a chain of page
// touches, one per tree level.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define BT_ORDER 16       // max keys per node (fanout = BT_ORDER+1 for internal)
#define BT_MAX_HEIGHT 32  // generous upper bound on tree height

struct bt_node {
  int is_leaf;
  int nkeys;
  int keys[BT_ORDER];
  int children[BT_ORDER + 1]; // internal nodes only
  int values[BT_ORDER];       // leaf nodes only
  int next_leaf;              // leaf nodes only, -1 if none
};

static char *g_arena;
static int g_footprint;
static int g_next_free;
static int g_root;

// ---- WORK_PROMPT2.md Phase 2 enrichment ---------------------------------
// Independently toggleable, default off (packed into a bitmask CLI arg
// like kvbench.c's -- see main()'s usage string -- since xv6's shell
// caps a command line at MAXARGS=10 tokens, user/sh.c).
//
// 2a. wal (highest priority): every tree modification is ALSO appended
//     to a sequential log region (separate arena, separate pages from
//     the tree) before being applied. Paging significance: this is the
//     signature database access pattern -- random tree reads
//     interleaved, in the SAME process, with strictly sequential
//     append writes to a log. Two fundamentally different patterns
//     competing for the same resident budget.
// 2b. transaction batching: folded into the WAL as a FIXED checkpoint
//     interval (WAL_CHECKPOINT_OPS) rather than a separately
//     configurable flag -- the log wraps back to its start every N
//     appends, modelling a periodic checkpoint/truncation, which is
//     the paging-relevant part (dirty pages accumulate in a burst,
//     then the log region is reused from the start).
// 2c. cache: a small internal LRU cache of node indices sitting in
//     front of the tree. bt_node() only counts as a kernel-visible
//     reference (calls vmbench_trace_ref) on a cache MISS -- modelling
//     how a real database's own buffer pool filters what the OS page
//     cache actually sees. Report how much the traced reference count
//     drops as cache_pages grows (see docs/workloads.md).
// 2d. free-list page reuse: NOT implemented. Doing this safely
//     requires real B+tree deletion (with merge/rebalance), which is a
//     substantial undertaking on its own; recycling a node without
//     real deletion risks silently corrupting the tree (a parent could
//     still reference a "freed" node). Flagged here rather than
//     building something that only looks like free-list reuse.
#define WAL_CHECKPOINT_OPS 32

static char *g_wal;
static long g_wal_capacity;
static long g_wal_pos;
static long g_wal_ops_since_checkpoint;

struct wal_record {
  int key;
  int value;
  int op;
};

static void
wal_append(int key, int value, int op)
{
  if(g_wal_pos + (long)sizeof(struct wal_record) > g_wal_capacity)
    g_wal_pos = 0; // wrap: simulates a checkpoint/truncation boundary
  vmbench_trace_ref(g_wal, (uint64)(g_wal_pos / VMBENCH_PGSIZE));
  struct wal_record *r = (struct wal_record *)(g_wal + g_wal_pos);
  r->key = key;
  r->value = value;
  r->op = op;
  g_wal_pos += (long)sizeof(struct wal_record);
  if(++g_wal_ops_since_checkpoint >= WAL_CHECKPOINT_OPS){
    g_wal_pos = 0;
    g_wal_ops_since_checkpoint = 0;
  }
}

#define BT_CACHE_MAX 256
static int g_cache_enabled;
static int g_cache_size;
static int g_cache_lru[BT_CACHE_MAX]; // MRU at index 0
static int g_cache_count;
static long g_cache_hits, g_cache_misses;

// Returns 1 if idx was already cached (a hit -- moved to MRU, no
// kernel-visible reference charged), 0 on a miss (inserted, evicting
// the LRU entry if the cache is full).
static int
cache_touch(int idx)
{
  for(int i = 0; i < g_cache_count; i++){
    if(g_cache_lru[i] == idx){
      for(int j = i; j > 0; j--)
        g_cache_lru[j] = g_cache_lru[j - 1];
      g_cache_lru[0] = idx;
      g_cache_hits++;
      return 1;
    }
  }
  if(g_cache_count < g_cache_size)
    g_cache_count++;
  for(int j = g_cache_count - 1; j > 0; j--)
    g_cache_lru[j] = g_cache_lru[j - 1];
  g_cache_lru[0] = idx;
  g_cache_misses++;
  return 0;
}

static struct bt_node *
bt_node(int idx)
{
  if(!g_cache_enabled || !cache_touch(idx))
    vmbench_trace_ref(g_arena, (uint64)idx);
  return (struct bt_node *)(g_arena + (uint64)idx * VMBENCH_PGSIZE);
}

static int
bt_alloc(void)
{
  if(g_next_free >= g_footprint){
    printf("btreebench: arena exhausted (footprint=%d pages) -- pass a "
           "larger footprint or a smaller op count\n", g_footprint);
    exit(1);
  }
  return g_next_free++;
}

static void
bt_init(void)
{
  g_next_free = 0;
  g_root = bt_alloc();
  struct bt_node *r = bt_node(g_root);
  r->is_leaf = 1;
  r->nkeys = 0;
  r->next_leaf = -1;
}

static int
bt_find_leaf(int key)
{
  int idx = g_root;
  struct bt_node *n = bt_node(idx);
  while(!n->is_leaf){
    int i = 0;
    while(i < n->nkeys && key >= n->keys[i])
      i++;
    idx = n->children[i];
    n = bt_node(idx);
  }
  return idx;
}

static int
bt_lookup(int key)
{
  int leaf = bt_find_leaf(key);
  struct bt_node *n = bt_node(leaf);
  for(int i = 0; i < n->nkeys; i++)
    if(n->keys[i] == key)
      return n->values[i];
  return -1;
}

static void
bt_insert(int key, int value)
{
  int path[BT_MAX_HEIGHT];
  int path_child[BT_MAX_HEIGHT];
  int depth = 0;

  int idx = g_root;
  struct bt_node *n = bt_node(idx);
  while(!n->is_leaf){
    int i = 0;
    while(i < n->nkeys && key >= n->keys[i])
      i++;
    if(depth >= BT_MAX_HEIGHT){
      printf("btreebench: tree height exceeded BT_MAX_HEIGHT\n");
      exit(1);
    }
    path[depth] = idx;
    path_child[depth] = i;
    depth++;
    idx = n->children[i];
    n = bt_node(idx);
  }

  int pos = 0;
  while(pos < n->nkeys && n->keys[pos] < key)
    pos++;
  if(pos < n->nkeys && n->keys[pos] == key){
    n->values[pos] = value;
    return;
  }
  for(int j = n->nkeys; j > pos; j--){
    n->keys[j] = n->keys[j - 1];
    n->values[j] = n->values[j - 1];
  }
  n->keys[pos] = key;
  n->values[pos] = value;
  n->nkeys++;

  if(n->nkeys < BT_ORDER)
    return;

  // Split the leaf.
  int mid = n->nkeys / 2;
  int new_idx = bt_alloc();
  n = bt_node(idx);
  struct bt_node *nn = bt_node(new_idx);
  nn->is_leaf = 1;
  nn->nkeys = n->nkeys - mid;
  for(int j = 0; j < nn->nkeys; j++){
    nn->keys[j] = n->keys[mid + j];
    nn->values[j] = n->values[mid + j];
  }
  n->nkeys = mid;
  nn->next_leaf = n->next_leaf;
  n->next_leaf = new_idx;

  int up_key = nn->keys[0];
  int up_child = new_idx;

  while(depth > 0){
    depth--;
    int pidx = path[depth];
    int ci = path_child[depth];
    struct bt_node *p = bt_node(pidx);
    for(int j = p->nkeys; j > ci; j--){
      p->keys[j] = p->keys[j - 1];
      p->children[j + 1] = p->children[j];
    }
    p->keys[ci] = up_key;
    p->children[ci + 1] = up_child;
    p->nkeys++;

    if(p->nkeys < BT_ORDER)
      return;

    int pmid = p->nkeys / 2;
    int mid_key = p->keys[pmid];
    int new_pidx = bt_alloc();
    p = bt_node(pidx);
    struct bt_node *np = bt_node(new_pidx);
    np->is_leaf = 0;
    np->nkeys = p->nkeys - pmid - 1;
    for(int j = 0; j < np->nkeys; j++)
      np->keys[j] = p->keys[pmid + 1 + j];
    for(int j = 0; j <= np->nkeys; j++)
      np->children[j] = p->children[pmid + 1 + j];
    p->nkeys = pmid;

    up_key = mid_key;
    up_child = new_pidx;
  }

  int new_root = bt_alloc();
  struct bt_node *nr = bt_node(new_root);
  nr->is_leaf = 0;
  nr->nkeys = 1;
  nr->keys[0] = up_key;
  nr->children[0] = g_root;
  nr->children[1] = up_child;
  g_root = new_root;
}

// Walks up to `count` entries starting from the leaf containing (or
// just after) `start_key`, following leaf-chain pointers -- the
// sequential-leaf-traversal access pattern a real range scan produces.
static int
bt_scan(int start_key, int count)
{
  int leaf = bt_find_leaf(start_key);
  int seen = 0;
  while(leaf >= 0 && seen < count){
    struct bt_node *n = bt_node(leaf);
    for(int i = 0; i < n->nkeys && seen < count; i++){
      if(n->keys[i] >= start_key)
        seen++;
    }
    leaf = n->next_leaf;
  }
  return seen;
}

enum { MIX_INSERT, MIX_LOOKUP, MIX_SCAN, MIX_MIXED };

static int
parse_mix(const char *s)
{
  if(strcmp(s, "insert") == 0)
    return MIX_INSERT;
  if(strcmp(s, "lookup") == 0)
    return MIX_LOOKUP;
  if(strcmp(s, "scan") == 0)
    return MIX_SCAN;
  if(strcmp(s, "mixed") == 0)
    return MIX_MIXED;
  printf("btreebench: unknown mix '%s' (want insert|lookup|scan|mixed)\n", s);
  exit(1);
}

int
main(int argc, char *argv[])
{
  // Packed bitmask (bit0=trace, bit1=wal, bit2=cache) for the same
  // MAXARGS=10 reason as kvbench.c.
  if(argc < 6 || argc > 9){
    printf("usage: btreebench <footprint_pages> <resident_margin> "
           "<op_count> <seed> <insert|lookup|scan|mixed> "
           "[flags_bitmask: 1=trace,2=wal,4=cache] [wal_pages] "
           "[cache_pages]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  int op_count = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  int mix = parse_mix(argv[5]);
  int flags = argc > 6 ? atoi(argv[6]) : 0;
  int trace = (flags & 1) != 0;
  int wal_enabled = (flags & 2) != 0;
  g_cache_enabled = (flags & 4) != 0;
  int wal_pages = argc > 7 ? atoi(argv[7]) : 4;
  g_cache_size = argc > 8 ? atoi(argv[8]) : 8;
  if(g_cache_size > BT_CACHE_MAX)
    g_cache_size = BT_CACHE_MAX;

  vmbench_banner("btreebench", "setup");
  g_footprint = footprint_pages;
  g_arena = vmbench_arena(footprint_pages);
  if(g_arena == SBRK_ERROR){
    printf("btreebench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }
  if(wal_enabled){
    g_wal = vmbench_arena(wal_pages);
    if(g_wal == SBRK_ERROR){
      printf("btreebench: vmbench_arena(wal) failed\n");
      exit(1);
    }
    g_wal_capacity = (long)wal_pages * VMBENCH_PGSIZE;
  }

  // bt_init() must run BEFORE the burn: it touches the arena's very
  // first page (the root node), giving the burn phase something inside
  // the arena's own VPN range to actually observe as a victim. Burning
  // over a completely untouched (lazy-hole) arena would never find
  // anything to reach, since nothing there is resident yet.
  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);
  bt_init();

  uint64 settled;
  int proven = vmbench_burn(g_arena, footprint_pages, &settled);
  if(proven < 0){
    printf("btreebench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("btreebench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  int key_space = op_count * 4 + 16;

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("btreebench", "workload");
  if(trace)
    vmbench_trace_start("btreebench", "see RESULT lines below for full "
                        "parameters (footprint/margin/op_count/mix)",
                        seed, g_arena, footprint_pages, resident_margin);
  long inserts = 0, lookups = 0, scans = 0, hits = 0;

  if(mix == MIX_LOOKUP || mix == MIX_SCAN){
    // Build a base tree first so lookups/scans have real data to find.
    int build_n = op_count / 2;
    if(build_n < 1)
      build_n = 1;
    for(int i = 0; i < build_n; i++){
      int key = (int)vmbench_rng_below(&rng, key_space);
      bt_insert(key, key * 2);
      inserts++;
    }
  }

  for(int i = 0; i < op_count; i++){
    int op = mix;
    if(mix == MIX_MIXED){
      uint64 r = vmbench_rng_below(&rng, 100);
      if(r < 40)
        op = MIX_INSERT;
      else if(r < 80)
        op = MIX_LOOKUP;
      else
        op = MIX_SCAN;
    }

    int key = (int)vmbench_rng_below(&rng, key_space);
    if(op == MIX_INSERT){
      if(wal_enabled)
        wal_append(key, key * 2, 1);
      bt_insert(key, key * 2);
      inserts++;
    } else if(op == MIX_LOOKUP){
      if(bt_lookup(key) >= 0)
        hits++;
      lookups++;
    } else {
      bt_scan(key, 20);
      scans++;
    }
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("btreebench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("op_count", op_count);
  vmbench_result("nodes_allocated", g_next_free);
  vmbench_result("inserts", inserts);
  vmbench_result("lookups", lookups);
  vmbench_result("lookup_hits", hits);
  vmbench_result("scans", scans);
  vmbench_result("wal_enabled", wal_enabled);
  vmbench_result("cache_enabled", g_cache_enabled);
  vmbench_result("cache_size", g_cache_size);
  vmbench_result("cache_hits", g_cache_hits);
  vmbench_result("cache_misses", g_cache_misses);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
