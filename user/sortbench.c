// sortbench: external (bottom-up) merge sort over an arena larger than
// the resident limit.
//
// Justification against the "no single heuristic wins" property
// (WORK_PROMPT.md SS0): this workload is included specifically as a
// SANITY CHECK, not a novel access pattern -- classic external merge
// sort has extremely well-understood, purely sequential locality
// (each pass does forward scans over two input runs and one output
// run), so its fault/eviction counts should match textbook prediction
// almost exactly (approximately total_elements / elements_per_page
// page touches per pass, times log2(runs) passes). If this workload's
// measured numbers DON'T match that prediction, it means the
// measurement pipeline itself (vmstats, the arena, the burn phase) has
// a bug -- investigate that before trusting any other workload's
// numbers. It is deliberately the least interesting workload from a
// "does the ML model have headroom" perspective (sequential access is
// exactly what plain read-ahead/FIFO already handles well), which is
// the point: it calibrates the measurement pipeline, it does not
// exercise the FIFO/Clock/Aging distinction.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

static int *g_a, *g_b;
static long g_n;

// One accessor both arrays funnel through for trace purposes: g_a and
// g_b are contiguous within the same arena (g_b = g_a + g_n), so a
// pointer's offset from g_a directly gives its page.
static void
sort_trace(int *p)
{
  vmbench_trace_ref((char *)g_a, (uint64)(((char *)p - (char *)g_a) /
                                           VMBENCH_PGSIZE));
}

static void
merge_pass(int *src, int *dst, long run)
{
  for(long lo = 0; lo < g_n; lo += 2 * run){
    long mid = lo + run;
    if(mid > g_n)
      mid = g_n;
    long hi = lo + 2 * run;
    if(hi > g_n)
      hi = g_n;

    long i = lo, j = mid, k = lo;
    while(i < mid && j < hi){
      sort_trace(&src[i]);
      sort_trace(&src[j]);
      sort_trace(&dst[k]);
      dst[k++] = (src[i] <= src[j]) ? src[i++] : src[j++];
    }
    while(i < mid){
      sort_trace(&src[i]);
      sort_trace(&dst[k]);
      dst[k++] = src[i++];
    }
    while(j < hi){
      sort_trace(&src[j]);
      sort_trace(&dst[k]);
      dst[k++] = src[j++];
    }
  }
}

int
main(int argc, char *argv[])
{
  if(argc != 5 && argc != 6){
    printf("usage: sortbench <footprint_pages> <resident_margin> "
           "<n_elements> <seed> [trace]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  g_n = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  int trace = argc == 6 && atoi(argv[5]) != 0;

  vmbench_banner("sortbench", "setup");
  char *arena = vmbench_arena(footprint_pages);
  if(arena == SBRK_ERROR){
    printf("sortbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }

  long ints_per_page = VMBENCH_PGSIZE / (long)sizeof(int);
  long need_ints = g_n * 2; // two ping-pong buffers
  long have_ints = (long)footprint_pages * ints_per_page;
  if(need_ints > have_ints){
    printf("sortbench: footprint too small: need %ld ints (2x n_elements), "
           "have %ld\n", need_ints, have_ints);
    exit(1);
  }

  g_a = (int *)arena;
  g_b = g_a + g_n;

  *(volatile int *)arena = 0;
  uint64 settled;
  int proven = vmbench_burn(arena, footprint_pages, &settled);
  if(proven < 0){
    printf("sortbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("sortbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);

  vmbench_banner("sortbench", "populate");
  for(long i = 0; i < g_n; i++)
    g_a[i] = (int)vmbench_rng_below(&rng, 1000000000);

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("sortbench", "workload");
  if(trace)
    vmbench_trace_start("sortbench", "see RESULT lines below for full "
                        "parameters", seed, arena, footprint_pages,
                        resident_margin);
  int *src = g_a, *dst = g_b;
  long passes = 0;
  for(long run = 1; run < g_n; run *= 2){
    merge_pass(src, dst, run);
    int *tmp = src;
    src = dst;
    dst = tmp;
    passes++;
  }

  long inversions = 0;
  for(long i = 1; i < g_n; i++)
    if(src[i - 1] > src[i])
      inversions++;

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("sortbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("n_elements", g_n);
  vmbench_result("passes", passes);
  vmbench_result("inversions", inversions);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  if(inversions != 0){
    printf("\n*** FAIL: result is not sorted (%ld inversions) ***\n",
           inversions);
    exit(1);
  }
  printf("\nPASS\n");
  exit(0);
}
