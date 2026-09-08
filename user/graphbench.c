// graphbench: pointer-chasing workload (BFS + fixed-point PageRank)
// over a scale-free graph in CSR-like layout.
//
// Justification against the "no single heuristic wins" property
// (WORK_PROMPT.md SS0): BFS visits vertices in FRONTIER order, which is
// data-dependent and effectively unpredictable from load order alone --
// a vertex touched early in the underlying array can be visited very
// late in BFS order (or never, if disconnected), so FIFO's "oldest
// resident = best victim" assumption is frequently wrong here. PageRank
// instead repeatedly re-visits the SAME high-degree ("hub") vertices
// across many iterations (a scale-free graph's defining property is a
// small set of hubs with very high degree), which is exactly the kind
// of recurring-frequency signal Aging is built to notice and FIFO is
// blind to. Combining a one-shot irregular traversal (BFS) with a
// repeated-hub-revisiting iteration (PageRank) over the SAME graph
// gives a workload where neither "recency" nor "frequency" alone
// explains the whole access pattern.
//
// Every vertex's out-edges point only to EARLIER vertices (an
// artifact of how preferential attachment below samples targets from
// the already-built edge list) -- structurally a directed acyclic
// graph, like a citation or dependency graph. BFS therefore starts
// from the LAST vertex and walks backward through real structure; see
// the bfs_visited assignment below.
//
// Graph generation: a simple Barabasi-Albert-style preferential
// attachment generator using only the integer PRNG (no floating
// point): each new vertex's out-edges are sampled uniformly from the
// edge list already written so far, which naturally biases toward
// vertices that already appear in many edges (i.e. high-degree hubs),
// producing a scale-free-shaped degree distribution. This is a
// SYNTHETIC graph, not real-world data -- printed explicitly below, as
// required.
//
// Layout: every vertex has a FIXED out-degree (AVG_DEGREE), so the
// CSR row-offset for vertex v is simply v*AVG_DEGREE -- no separate
// offsets array is needed, keeping the arena to two flat int arrays
// (edges, and the algorithm's own working arrays) rather than one
// "node per page" unit like btreebench/kvbench use. This is
// deliberate: a real graph engine's page-level unit is "one physical
// page's worth of adjacency data", not "one vertex", and CSR is
// exactly that kind of dense flat layout.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define AVG_DEGREE 8
#define PR_SCALE (1 << 16)
#define PR_DAMPING_NUM 85
#define PR_DAMPING_DEN 100

static int *g_edges; // [V * AVG_DEGREE]
static int *g_rank;
static int *g_next_rank;
static int *g_visited;
static int *g_queue;
static int g_v;

static int
edge_dst(int v, int k)
{
  return g_edges[v * AVG_DEGREE + k];
}

static void
build_graph(struct vmbench_rng *rng)
{
  // Seed: vertex 0's edges wrap around to bootstrap the sampling pool
  // (nothing exists yet to sample preferentially from).
  for(int k = 0; k < AVG_DEGREE; k++)
    g_edges[k] = (k + 1) % g_v;

  // Half of each vertex's edges are pure preferential attachment
  // (sampled from the edge list built so far, biasing toward
  // already-popular targets -- this is what gives the graph its
  // scale-free hub/degree skew, which PageRank's hub-revisiting
  // property depends on). Pure preferential sampling alone, though,
  // only ever points BACKWARD to earlier-created vertices (confirmed
  // empirically: a forward BFS from any single vertex collapsed into
  // the same ~7-9 vertex core, since nothing ever points forward to
  // the rest of the graph). The other half are uniformly random
  // across the WHOLE vertex range, forward and backward alike, giving
  // genuine reachability for BFS regardless of where it starts.
  for(int v = 1; v < g_v; v++){
    long pool_size = (long)v * AVG_DEGREE;
    for(int k = 0; k < AVG_DEGREE; k++){
      int target;
      if(k < AVG_DEGREE / 2){
        long sample_idx = (long)vmbench_rng_below(rng, (uint64)pool_size);
        target = g_edges[sample_idx];
      } else {
        target = (int)vmbench_rng_below(rng, (uint64)g_v);
      }
      if(target == v)
        target = (target + 1) % g_v;
      g_edges[v * AVG_DEGREE + k] = target;
    }
  }
}

static long
bfs(int start)
{
  for(int i = 0; i < g_v; i++)
    g_visited[i] = 0;
  int head = 0, tail = 0;
  g_queue[tail++] = start;
  g_visited[start] = 1;
  long visited_count = 1;

  while(head < tail){
    int u = g_queue[head++];
    for(int k = 0; k < AVG_DEGREE; k++){
      int w = edge_dst(u, k);
      if(!g_visited[w]){
        g_visited[w] = 1;
        g_queue[tail++] = w;
        visited_count++;
      }
    }
  }
  return visited_count;
}

// One fixed-point PageRank iteration. rank[]/next_rank[] hold
// probability * PR_SCALE.
static void
pagerank_iteration(void)
{
  int base = (int)(((long)(PR_DAMPING_DEN - PR_DAMPING_NUM) * PR_SCALE) /
                    ((long)PR_DAMPING_DEN * g_v));
  for(int v = 0; v < g_v; v++)
    g_next_rank[v] = base;

  for(int u = 0; u < g_v; u++){
    int share = (int)(((long)g_rank[u] * PR_DAMPING_NUM) /
                       ((long)PR_DAMPING_DEN * AVG_DEGREE));
    for(int k = 0; k < AVG_DEGREE; k++){
      int w = edge_dst(u, k);
      g_next_rank[w] += share;
    }
  }

  int *tmp = g_rank;
  g_rank = g_next_rank;
  g_next_rank = tmp;
}

int
main(int argc, char *argv[])
{
  if(argc != 6){
    printf("usage: graphbench <footprint_pages> <resident_margin> "
           "<pagerank_iters> <seed> <bfs|pagerank|both>\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  int pr_iters = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  char *which = argv[5];

  vmbench_banner("graphbench", "setup");
  printf("[info] synthetic scale-free graph (preferential attachment "
         "over the integer PRNG, not real-world data)\n");

  char *arena = vmbench_arena(footprint_pages);
  if(arena == SBRK_ERROR){
    printf("graphbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }

  // bytes_per_vertex = AVG_DEGREE*4 (edges) + 4*4 (rank, next_rank,
  // visited, queue).
  long bytes_per_vertex = (long)AVG_DEGREE * 4 + 4 * 4;
  long total_bytes = (long)footprint_pages * VMBENCH_PGSIZE;
  g_v = (int)(total_bytes / bytes_per_vertex);
  if(g_v < AVG_DEGREE + 2){
    printf("graphbench: footprint too small for even one vertex "
           "(need >= %ld bytes)\n", bytes_per_vertex * (AVG_DEGREE + 2));
    exit(1);
  }

  g_edges = (int *)arena;
  g_rank = g_edges + (long)g_v * AVG_DEGREE;
  g_next_rank = g_rank + g_v;
  g_visited = g_next_rank + g_v;
  g_queue = g_visited + g_v;

  // Touch the first page so the burn phase has something in the
  // arena's own VPN range to observe.
  *(volatile int *)arena = 0;

  uint64 settled;
  int proven = vmbench_burn(arena, footprint_pages, &settled);
  if(proven < 0){
    printf("graphbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("graphbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);

  vmbench_banner("graphbench", "build");
  build_graph(&rng);
  for(int v = 0; v < g_v; v++)
    g_rank[v] = PR_SCALE / g_v;

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("graphbench", "workload");
  long bfs_visited = 0;
  int pr_ran = 0;
  if(strcmp(which, "bfs") == 0 || strcmp(which, "both") == 0)
    // Preferential attachment makes every vertex's out-edges point
    // only to EARLIER vertices (like a citation graph: a new paper
    // cites older ones) -- a forward BFS from vertex 0 is trapped in
    // a tiny closed set near the start (confirmed empirically: 9 of
    // 1706 vertices). Starting from the LAST vertex instead lets BFS
    // walk backward through the graph's real structure, the same way
    // exploring "everything this recent commit/citation/dependency
    // transitively depends on" would.
    bfs_visited = bfs(g_v - 1);
  if(strcmp(which, "pagerank") == 0 || strcmp(which, "both") == 0){
    for(int it = 0; it < pr_iters; it++)
      pagerank_iteration();
    pr_ran = 1;
  }

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("graphbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("vertices", g_v);
  vmbench_result("avg_degree", AVG_DEGREE);
  vmbench_result("bfs_visited", bfs_visited);
  vmbench_result("pagerank_iters", pr_ran ? pr_iters : 0);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
