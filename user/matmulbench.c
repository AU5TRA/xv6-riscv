// matmulbench: naive vs. blocked (tiled) integer matrix multiply, same
// footprint, same computation -- only the ACCESS ORDER differs.
//
// Justification against the "no single heuristic wins" property
// (WORK_PROMPT.md SS0): like sortbench, this is a calibration pair, not
// a novel pattern -- it is a KNOWN-ANSWER check on whether the
// measurement pipeline is sane. Naive ijk-order multiply walks matrix
// B column-by-column, which for a large row-major matrix means each
// inner-loop step jumps a full row stride -- terrible spatial
// locality, touching many distinct pages per unit of work. Blocked
// (tiled) multiply restricts each pass to a small BLOCK x BLOCK tile
// that fits comfortably resident, reusing those same few pages many
// times before moving to the next tile -- excellent locality, far
// fewer distinct page touches for the IDENTICAL arithmetic result. If
// naive doesn't show markedly worse fault/eviction counts than blocked
// at the same resident limit, something is wrong with the harness, not
// with the theory.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define BLOCK 8

static int *g_a, *g_b, *g_c;
static long g_n;

// g_a/g_b/g_c are contiguous within one arena (g_a is its base), so an
// element's offset from g_a gives its page regardless of which matrix
// it belongs to.
static void
matmul_trace(int *p)
{
  vmbench_trace_ref((char *)g_a, (uint64)(((char *)p - (char *)g_a) /
                                           VMBENCH_PGSIZE));
}

static int
at(int *m, long i, long j)
{
  int *p = &m[i * g_n + j];
  matmul_trace(p);
  return *p;
}

static void
set_at(int *m, long i, long j, int v)
{
  int *p = &m[i * g_n + j];
  matmul_trace(p);
  *p = v;
}

static void
matmul_naive(void)
{
  for(long i = 0; i < g_n; i++){
    for(long j = 0; j < g_n; j++){
      int sum = 0;
      for(long k = 0; k < g_n; k++)
        sum += at(g_a, i, k) * at(g_b, k, j);
      set_at(g_c, i, j, sum);
    }
  }
}

static void
matmul_blocked(void)
{
  for(long i = 0; i < g_n; i++)
    for(long j = 0; j < g_n; j++)
      set_at(g_c, i, j, 0);

  for(long ii = 0; ii < g_n; ii += BLOCK){
    for(long jj = 0; jj < g_n; jj += BLOCK){
      for(long kk = 0; kk < g_n; kk += BLOCK){
        long imax = ii + BLOCK < g_n ? ii + BLOCK : g_n;
        long jmax = jj + BLOCK < g_n ? jj + BLOCK : g_n;
        long kmax = kk + BLOCK < g_n ? kk + BLOCK : g_n;
        for(long i = ii; i < imax; i++){
          for(long j = jj; j < jmax; j++){
            int sum = at(g_c, i, j);
            for(long k = kk; k < kmax; k++)
              sum += at(g_a, i, k) * at(g_b, k, j);
            set_at(g_c, i, j, sum);
          }
        }
      }
    }
  }
}

int
main(int argc, char *argv[])
{
  if(argc != 5 && argc != 6){
    printf("usage: matmulbench <footprint_pages> <resident_margin> "
           "<n> <naive|blocked> [trace]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  g_n = atoi(argv[3]);
  char *variant = argv[4];
  int trace = argc == 6 && atoi(argv[5]) != 0;
  int naive = strcmp(variant, "naive") == 0;
  if(!naive && strcmp(variant, "blocked") != 0){
    printf("matmulbench: unknown variant '%s' (want naive|blocked)\n",
           variant);
    exit(1);
  }

  vmbench_banner("matmulbench", "setup");
  char *arena = vmbench_arena(footprint_pages);
  if(arena == SBRK_ERROR){
    printf("matmulbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }

  long ints_per_page = VMBENCH_PGSIZE / (long)sizeof(int);
  long need_ints = g_n * g_n * 3; // A, B, C
  long have_ints = (long)footprint_pages * ints_per_page;
  if(need_ints > have_ints){
    printf("matmulbench: footprint too small: need %ld ints (3 x n^2), "
           "have %ld\n", need_ints, have_ints);
    exit(1);
  }

  g_a = (int *)arena;
  g_b = g_a + g_n * g_n;
  g_c = g_b + g_n * g_n;

  *(volatile int *)arena = 0;
  uint64 settled;
  int proven = vmbench_burn(arena, footprint_pages, &settled);
  if(proven < 0){
    printf("matmulbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("matmulbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, 1);

  vmbench_banner("matmulbench", "populate");
  for(long i = 0; i < g_n * g_n; i++){
    g_a[i] = (int)vmbench_rng_below(&rng, 100);
    g_b[i] = (int)vmbench_rng_below(&rng, 100);
  }

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("matmulbench", "workload");
  if(trace)
    vmbench_trace_start("matmulbench", "see RESULT lines below for full "
                        "parameters", 1, arena, footprint_pages,
                        resident_margin);
  if(naive)
    matmul_naive();
  else
    matmul_blocked();

  long checksum = 0;
  for(long i = 0; i < g_n * g_n; i++)
    checksum += g_c[i];

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("matmulbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("n", g_n);
  vmbench_result("naive", naive);
  vmbench_result("checksum", checksum);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
