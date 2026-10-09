// chasebench: pointer chasing, the serial-dependence pattern of SPEC's
// mcf (GAWWY_HANDOFF_NEW_BENCHMARKS.md, section 4.3).
//
//   chasebench <footprint_pages> <resident_margin> <ops> <seed> <mode>
//              [trace: 1=console, 9=file]
//
// The arena holds N = footprint_pages * 4096 / node_bytes nodes, each
// {int link; int payload;} padded to node_bytes, and node i is stored at
// slot perm(i) of a seeded permutation (vmbench_perm), so nodes that
// follow each other in the structure sit on unrelated pages: there is no
// stride to find. A step reads the node it is on to learn the next one --
// one reference -- and on CHASE_WRITE_PCT of steps also updates its
// payload, which makes that reference a W. Modes:
//
//   list     CHASE_LISTS linked lists of N / CHASE_LISTS nodes each. An
//            operation picks a list and walks 1..len steps from its head
//            (uniform), so a node's chance of a visit falls linearly with
//            its position. A whole-list walk every time would be the
//            cyclic loop in disguise.
//   tree     a random recursive tree: node 0 is the root and node i's
//            parent is uniform over 0..i-1. An operation picks a node
//            uniformly and walks its parent links to the root, as mcf's
//            network simplex walks its basis tree. The nodes near the
//            root are on nearly every walk, the leaves on few: the skew
//            comes from depth.
//   list256  the same with 256-byte nodes, 16 to a page instead of 64.
//   tree256  (Variant chase-n256 is tree256.)
//
// The PRNG draws, in order, which the host model
// (tools/hostmodel/chasebench.py) repeats to reproduce the trace:
//   setup:   key = next() (the placement); tree: parent of node i =
//            below(i) for i = 1..N-1
//   per op:  list: k = below(lists), steps = 1 + below(len); tree:
//            start = below(N)
//   per step: write = below(100) < CHASE_WRITE_PCT
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define CHASE_LISTS 64
#define CHASE_WRITE_PCT 10
#define CHASE_MAX_PAGES 4096 // well under the swap area's 8192 slots
#define CHASE_NONE (-1)

struct chase_mode {
  const char *name;
  int tree;       // 0 = list, 1 = tree
  int node_bytes; // divides the page size, so a node never straddles two
};

static const struct chase_mode MODES[] = {
  {"list", 0, 64},
  {"tree", 1, 64},
  {"list256", 0, 256},
  {"tree256", 1, 256},
};
#define NMODES ((int)(sizeof(MODES) / sizeof(MODES[0])))

struct chase_node {
  int link;    // slot of the next node (list) or the parent (tree), or -1
  int payload;
};

static char *g_arena;
static int g_node_bytes;

static struct chase_node *
node_at(uint64 slot)
{
  return (struct chase_node *)(g_arena + slot * g_node_bytes);
}

static uint64
page_of(uint64 slot)
{
  return slot * g_node_bytes / VMBENCH_PGSIZE;
}

static const struct chase_mode *
find_mode(const char *s)
{
  for(int i = 0; i < NMODES; i++)
    if(strcmp(s, MODES[i].name) == 0)
      return &MODES[i];
  printf("chasebench: unknown mode '%s' (want list|tree|list256|tree256)\n",
         s);
  exit(1);
}

int
main(int argc, char *argv[])
{
  if(argc != 6 && argc != 7){
    printf("usage: chasebench <footprint_pages> <resident_margin> <ops> "
           "<seed> <list|tree|list256|tree256> [trace: 1=console, 9=file]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  long ops = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  const struct chase_mode *m = find_mode(argv[5]);
  int trace_flags = argc == 7 ? atoi(argv[6]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(footprint_pages < 1 || footprint_pages > CHASE_MAX_PAGES){
    printf("chasebench: footprint_pages must be 1-%d\n", CHASE_MAX_PAGES);
    exit(1);
  }
  if(ops < 1){
    printf("chasebench: ops must be at least 1\n");
    exit(1);
  }
  g_node_bytes = m->node_bytes;
  uint64 n = (uint64)footprint_pages * (VMBENCH_PGSIZE / g_node_bytes);
  uint64 list_len = n / CHASE_LISTS;
  if(!m->tree && list_len < 1){
    printf("chasebench: footprint too small for %d lists\n", CHASE_LISTS);
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("chasebench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }

  vmbench_banner("chasebench", "setup");
  printf("[info] mode %s: %ld nodes of %d bytes, synthetic structure from "
         "the integer PRNG\n", m->name, (long)n, g_node_bytes);
  g_arena = vmbench_arena(footprint_pages);
  if(g_arena == SBRK_ERROR){
    printf("chasebench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }

  // Touch only the first page before the burn; the structure is built
  // after the limit is set.
  *(volatile int *)g_arena = 0;
  uint64 settled;
  int proven = vmbench_burn(g_arena, footprint_pages, &settled);
  if(proven < 0){
    printf("chasebench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("chasebench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  // Setup, untraced: link every node into its list or to its parent.
  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);
  struct vmbench_perm place;
  vmbench_perm_init(&place, n, vmbench_rng_next(&rng));
  if(m->tree){
    struct chase_node *root = node_at(vmbench_perm_fwd(&place, 0));
    root->link = CHASE_NONE;
    root->payload = 0;
    for(uint64 i = 1; i < n; i++){
      struct chase_node *nd = node_at(vmbench_perm_fwd(&place, i));
      nd->link = (int)vmbench_perm_fwd(&place, vmbench_rng_below(&rng, i));
      nd->payload = 0;
    }
  } else {
    for(uint64 i = 0; i < CHASE_LISTS * list_len; i++){
      struct chase_node *nd = node_at(vmbench_perm_fwd(&place, i));
      nd->link = (i + 1) % list_len == 0
                     ? CHASE_NONE
                     : (int)vmbench_perm_fwd(&place, i + 1);
      nd->payload = 0;
    }
  }

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("chasebench", "workload");
  if(trace)
    vmbench_trace_start("chasebench", m->name, seed, g_arena,
                        footprint_pages, resident_margin);
  long steps = 0, writes = 0, longest = 0;
  uint64 checksum = 0;
  for(long op = 0; op < ops; op++){
    uint64 slot;
    long budget; // steps this operation may take
    if(m->tree){
      slot = vmbench_perm_fwd(&place, vmbench_rng_below(&rng, n));
      budget = -1; // to the root
    } else {
      uint64 k = vmbench_rng_below(&rng, CHASE_LISTS);
      budget = 1 + (long)vmbench_rng_below(&rng, list_len);
      slot = vmbench_perm_fwd(&place, k * list_len);
    }
    long taken = 0;
    for(;;){
      int is_write = vmbench_rng_below(&rng, 100) < CHASE_WRITE_PCT;
      volatile struct chase_node *nd = node_at(slot);
      int link = nd->link;
      int payload = nd->payload;
      checksum += (uint64)payload;
      if(is_write){
        nd->payload = payload + 1;
        writes++;
      }
      vmbench_trace_ref(g_arena, page_of(slot),
                        is_write ? VMBENCH_WRITE : VMBENCH_READ);
      steps++;
      taken++;
      if(taken == budget || link == CHASE_NONE)
        break;
      slot = (uint64)link;
    }
    if(taken > longest)
      longest = taken;
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("chasebench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("ops", ops);
  vmbench_result("seed", (long)seed);
  vmbench_result("tree", m->tree);
  vmbench_result("node_bytes", g_node_bytes);
  vmbench_result("nodes", (long)n);
  vmbench_result("lists", m->tree ? 0 : CHASE_LISTS);
  vmbench_result("list_len", m->tree ? 0 : (long)list_len);
  vmbench_result("write_pct", CHASE_WRITE_PCT);
  vmbench_result("steps", steps);
  vmbench_result("longest_op", longest);
  vmbench_result("writes", writes);
  vmbench_result("checksum", (long)checksum);
  vmbench_result("trace_refs", steps);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
