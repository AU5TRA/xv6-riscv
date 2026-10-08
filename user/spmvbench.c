// spmvbench: sparse matrix times vector in CSR form, the core of NAS CG
// (GAWWY_HANDOFF_NEW_BENCHMARKS.md, section 4.2).
//
//   spmvbench <footprint_pages> <resident_margin> <iters> <seed> <mode>
//             [trace: 1=console, 9=file]
//
// A SPMV_N x SPMV_N matrix in CSR: row_ptr[n+1], col[nnz] and val[nnz],
// all int32, and two vectors x[n] and y[n]. The vectors are 64-bit, the
// size of the doubles a real CG uses -- so x alone spans 256 pages -- and
// hold integers: xv6 user programs cannot use floating point. Each
// iteration is
//   y[i] = sum over row i of val[j] * x[col[j]]    (the SpMV)
//   x[i] = 1 + y[i] % 65521                         (CG's vector update,
//                                                    as an integer rescale)
// so the next iteration reads new values through the same pattern.
// Every element access is one reference: row_ptr, col, val and y are
// streamed in order, and x[col[j]] is the irregular one. Modes:
//   rand  NAS CG-like: each row's columns uniform over all n
//   band  columns within +-SPMV_BAND = n/4 of the diagonal, so the
//         indirect access has locality: a window of x 128 pages wide (half
//         of x) that slides along with the row. Narrower bands fit in the
//         smallest sweep capacity (5% of the 1667 pages) and leave only
//         compulsory misses; this one thrashes there and fits from ~10%.
// Row lengths are uniform in 1..2*SPMV_K-1 (mean SPMV_K) for both, with
// distinct, sorted columns, as in a real CSR matrix. Graphbench's PageRank
// is an SpMV over a scale-free graph; these two structures are the ones it
// does not cover.
//
// Layout, each region page-aligned: x, y, row_ptr, col, val. col and val
// are sized by the matrix's actual non-zeros, so the pages needed vary by
// a page or two with the seed; footprint_pages must cover them.
//
// PRNG draws, in order (tools/hostmodel/spmvbench.py repeats them): for
// each row, its length 1 + below(2k-1), then its columns one at a time
// (rand: below(n); band: lo + below(hi - lo + 1)), each redrawn while it
// repeats one already in the row. Then, once all rows are drawn and val[]
// can be placed, the values 1 + below(15) in CSR order, and x[i] =
// 1 + below(1000). The iterations draw nothing.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define SPMV_N 131072
#define SPMV_K 4           // mean non-zeros per row
#define SPMV_MAX_ROW (2 * SPMV_K - 1)
#define SPMV_BAND 32768    // band: |column - row| <= SPMV_BAND, n/4
#define SPMV_MOD 65521     // the update's modulus, the largest 16-bit prime
#define SPMV_MAX_PAGES 4096

static char *g_arena;

static void
spmv_trace(const void *p, char access)
{
  vmbench_trace_ref(g_arena,
                    (uint64)(((const char *)p - g_arena) / VMBENCH_PGSIZE),
                    access);
}

static long
pages_for(long bytes)
{
  return (bytes + VMBENCH_PGSIZE - 1) / VMBENCH_PGSIZE;
}

int
main(int argc, char *argv[])
{
  if(argc != 6 && argc != 7){
    printf("usage: spmvbench <footprint_pages> <resident_margin> <iters> "
           "<seed> <rand|band> [trace: 1=console, 9=file]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  int iters = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  int band;
  if(strcmp(argv[5], "rand") == 0)
    band = 0;
  else if(strcmp(argv[5], "band") == 0)
    band = 1;
  else {
    printf("spmvbench: unknown mode '%s' (want rand|band)\n", argv[5]);
    exit(1);
  }
  int trace_flags = argc == 7 ? atoi(argv[6]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(iters < 1){
    printf("spmvbench: iters must be at least 1\n");
    exit(1);
  }
  if(footprint_pages < 1 || footprint_pages > SPMV_MAX_PAGES){
    printf("spmvbench: footprint_pages must be 1-%d\n", SPMV_MAX_PAGES);
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("spmvbench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }

  long n = SPMV_N;
  long x_pages = pages_for(n * (long)sizeof(long));
  long y_pages = x_pages;
  long rp_pages = pages_for((n + 1) * (long)sizeof(int));
  // col and val come after these, sized by the matrix's non-zeros; the
  // generator checks they fit as it goes.
  long fixed = x_pages + y_pages + rp_pages;
  if(fixed + 2 > footprint_pages){
    printf("spmvbench: footprint_pages must be at least %ld\n", fixed + 2);
    exit(1);
  }

  vmbench_banner("spmvbench", "setup");
  printf("[info] mode %s: %ld x %ld matrix, ~%d non-zeros per row, %d "
         "iterations; synthetic matrix from the integer PRNG\n", argv[5], n,
         n, SPMV_K, iters);
  g_arena = vmbench_arena(footprint_pages);
  if(g_arena == SBRK_ERROR){
    printf("spmvbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }
  long *x = (long *)g_arena;
  long *y = (long *)(g_arena + x_pages * VMBENCH_PGSIZE);
  int *row_ptr = (int *)(g_arena + (x_pages + y_pages) * VMBENCH_PGSIZE);
  int *col = (int *)(g_arena + fixed * VMBENCH_PGSIZE);

  // Touch only the first page before the burn; the matrix is generated
  // after the limit is set.
  *(volatile int *)g_arena = 0;
  uint64 settled;
  int proven = vmbench_burn(g_arena, footprint_pages, &settled);
  if(proven < 0){
    printf("spmvbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("spmvbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  // Setup, untraced: generate the matrix. col[] starts at a fixed place,
  // but val[] follows it and so cannot be placed until nnz is known: every
  // row's length and columns are drawn first, then all the values.
  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);
  long nnz = 0;
  row_ptr[0] = 0;
  for(long i = 0; i < n; i++){
    long len = 1 + (long)vmbench_rng_below(&rng, SPMV_MAX_ROW);
    // col[] and then val[], each this long, must stay inside the arena.
    if(fixed + 2 * pages_for((nnz + len) * (long)sizeof(int)) >
       footprint_pages){
      printf("spmvbench: footprint_pages %d too small for this matrix "
             "(row %ld)\n", footprint_pages, i);
      exit(1);
    }
    long lo = 0, hi = n - 1;
    if(band){
      lo = i - SPMV_BAND < 0 ? 0 : i - SPMV_BAND;
      hi = i + SPMV_BAND > n - 1 ? n - 1 : i + SPMV_BAND;
    }
    int *row = &col[nnz];
    for(long e = 0; e < len; e++){
      int c, dup;
      do {
        c = (int)(lo + (long)vmbench_rng_below(&rng, (uint64)(hi - lo + 1)));
        dup = 0;
        for(long f = 0; f < e; f++)
          if(row[f] == c)
            dup = 1;
      } while(dup);
      // insertion into sorted position
      long f = e;
      while(f > 0 && row[f - 1] > c){
        row[f] = row[f - 1];
        f--;
      }
      row[f] = c;
    }
    nnz += len;
    row_ptr[i + 1] = (int)nnz;
  }
  long col_pages = pages_for(nnz * (long)sizeof(int));
  long need = fixed + 2 * col_pages;
  int *val = (int *)(g_arena + (fixed + col_pages) * VMBENCH_PGSIZE);
  for(long j = 0; j < nnz; j++)
    val[j] = 1 + (int)vmbench_rng_below(&rng, 15);
  for(long i = 0; i < n; i++)
    x[i] = 1 + (long)vmbench_rng_below(&rng, 1000);

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("spmvbench", "workload");
  if(trace)
    vmbench_trace_start("spmvbench", argv[5], seed, g_arena,
                        footprint_pages, resident_margin);
  long refs = 0;
  uint64 checksum = 0;
  for(int it = 0; it < iters; it++){
    spmv_trace(&row_ptr[0], VMBENCH_READ);
    refs++;
    long lo = row_ptr[0];
    for(long i = 0; i < n; i++){
      spmv_trace(&row_ptr[i + 1], VMBENCH_READ);
      refs++;
      long hi = row_ptr[i + 1];
      long sum = 0;
      for(long j = lo; j < hi; j++){
        spmv_trace(&col[j], VMBENCH_READ);
        int c = col[j];
        spmv_trace(&val[j], VMBENCH_READ);
        int v = val[j];
        spmv_trace(&x[c], VMBENCH_READ);
        sum += (long)v * x[c];
        refs += 3;
      }
      y[i] = sum;
      spmv_trace(&y[i], VMBENCH_WRITE);
      refs++;
      checksum += (uint64)sum;
      lo = hi;
    }
    for(long i = 0; i < n; i++){
      spmv_trace(&y[i], VMBENCH_READ);
      long v = y[i];
      x[i] = 1 + v % SPMV_MOD;
      spmv_trace(&x[i], VMBENCH_WRITE);
      refs += 2;
    }
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("spmvbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("iters", iters);
  vmbench_result("seed", (long)seed);
  vmbench_result("rows", n);
  vmbench_result("band", band ? SPMV_BAND : 0);
  vmbench_result("nnz", nnz);
  vmbench_result("pages_needed", need);
  vmbench_result("checksum", (long)checksum);
  vmbench_result("trace_refs", refs);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  printf("\nPASS\n");
  exit(0);
}
