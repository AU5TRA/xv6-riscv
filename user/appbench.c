// appbench: application-shaped page-reference patterns with exact host models.
//
//   appbench <resident_margin> <accesses> <seed> <mode> [trace: 1=console, 9=file]
//
// Unlike patbench (one access = one chosen page), every access here is an element
// access of a data structure laid out in a single arena; its page is
// (element index * element size) / 4096. Each access touches the first word of
// that page and is traced, so the reference string is exactly the page
// sequence of the algorithm. tools/appbench_model.py re-implements every mode.
//
//   chase     pointer chasing (SPEC mcf-like): 64-byte nodes, 16384 of them (256
//             pages) visited in one seeded random cycle; 5% of visits update
//             the node (write)
//   spmv      CSR sparse matrix x vector, repeated: 16384 rows, 8 nonzeros per
//             row; per row: rowptr, then (col, val, x[col]) for each nonzero, then
//             y[r] write. 80% of columns fall within +-1024 of the diagonal,
//             the rest are uniform (the NAS CG access shape)
//   hashjoin  build a 16384-bucket hash table from R (8192 tuples, scanned),
//             then probe it with S (65536 tuples, scanned), writing matches to
//             an output buffer; a query is build + probe, repeated
//   bloom     Bloom filter of 2048 pages, 4 probes per lookup at hashed bit
//             positions; keys are Zipf(0.99)-popular; 5% of operations insert
//
// Arrays sit back to back in the arena (layout in the *_init functions below).
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"
#include "user/pat_zipf.h"

enum { M_CHASE, M_SPMV, M_HASHJOIN, M_BLOOM, M_COUNT };
static const char *mode_names[M_COUNT] = {"chase", "spmv", "hashjoin", "bloom"};

#define PG VMBENCH_PGSIZE

static char *g_arena;
static long g_reads, g_writes;
static uint64 g_checksum;
static long g_accesses, g_done;

// Touch the page holding byte offset `off` of the arena; returns false once
// the access budget is used up.
static int
touch(uint64 off, int write)
{
  if(g_done >= g_accesses)
    return 0;
  uint64 page = off / PG;
  volatile int *w = (volatile int *)(g_arena + page * PG);
  if(write){
    vmbench_trace_ref(g_arena, page, VMBENCH_WRITE);
    int v = *w + 1;
    *w = v;
    g_checksum += (uint64)v;
    g_writes++;
  } else {
    vmbench_trace_ref(g_arena, page, VMBENCH_READ);
    g_checksum += (uint64)*w;
    g_reads++;
  }
  g_done++;
  return 1;
}

// splitmix-style mixer: deterministic hash of (x, salt).
static uint64
mix(uint64 x, uint64 salt)
{
  uint64 z = x * 0x9E3779B97F4A7C15ULL + salt;
  z ^= z >> 30;
  z *= 0xBF58476D1CE4E5B9ULL;
  z ^= z >> 27;
  z *= 0x94D049BB133111EBULL;
  z ^= z >> 31;
  return z;
}

static uint64
zipf_rank(const uint32 *cdf, struct vmbench_rng *r)
{
  uint32 draw = (uint32)vmbench_rng_next(r);
  int lo = 0, hi = PAT_ZIPF_N - 1;
  while(lo < hi){
    int mid = lo + (hi - lo) / 2;
    if(cdf[mid] >= draw)
      hi = mid;
    else
      lo = mid + 1;
  }
  return (uint64)lo;
}

// ---- chase: nodes 64 B, order = seeded cycle (bijection on 2^14) --------------
#define CH_NODES 16384
#define CH_PAGES (CH_NODES * 64 / PG)

static uint64 ch_k1, ch_k2, ch_k3;

static void
ch_init(uint64 seed)
{
  struct vmbench_rng r;
  vmbench_rng_seed(&r, seed * 0x9E3779B97F4A7C15ULL + 1 * 0xD1B54A32D192ED03ULL + 1);
  ch_k1 = vmbench_rng_next(&r);
  ch_k2 = vmbench_rng_next(&r) | 1;
  ch_k3 = vmbench_rng_next(&r) | 1;
}

static uint64
ch_perm(uint64 x)
{
  uint64 m = CH_NODES - 1;
  x = (x + ch_k1) & m; x = (x * ch_k2) & m; x ^= x >> 7; x = (x * ch_k3) & m; x ^= x >> 7;
  return x;
}

static void
run_chase(uint64 seed)
{
  struct vmbench_rng rw;
  vmbench_rng_seed(&rw, seed * 2 + 2);
  ch_init(seed);
  for(long i = 0;; i++){
    uint64 node = ch_perm((uint64)i % CH_NODES);
    int wr = vmbench_rng_below(&rw, 100) < 5;
    if(!touch(node * 64, wr))
      return;
  }
}

// ---- spmv: rowptr | col | val | x | y ------------------------------------------
#define SP_ROWS 16384
#define SP_NNZ_ROW 8
#define SP_NNZ (SP_ROWS * SP_NNZ_ROW)
#define SP_ROWPTR 0ULL
#define SP_COL (((SP_ROWPTR + (uint64)(SP_ROWS + 1) * 4 + 4095) / PG) * PG)
#define SP_VAL (SP_COL + (uint64)SP_NNZ * 4)
#define SP_X (SP_VAL + (uint64)SP_NNZ * 4)
#define SP_Y (SP_X + (uint64)SP_ROWS * 4)
#define SP_PAGES ((SP_Y + (uint64)SP_ROWS * 4 + PG - 1) / PG)

static uint64
sp_col(uint64 seed, uint64 j)
{
  uint64 row = j / SP_NNZ_ROW;
  uint64 h = mix(j, seed);
  if(h % 100 < 80){
    uint64 off = (h >> 8) % 2049;                      // 0..2048 -> -1024..+1024
    return (row + SP_ROWS + off - 1024) % SP_ROWS;
  }
  return (h >> 8) % SP_ROWS;
}

static void
run_spmv(uint64 seed)
{
  for(;;)
    for(uint64 r = 0; r < SP_ROWS; r++){
      if(!touch(SP_ROWPTR + r * 4, 0))
        return;
      for(uint64 k = 0; k < SP_NNZ_ROW; k++){
        uint64 j = r * SP_NNZ_ROW + k;
        if(!touch(SP_COL + j * 4, 0) || !touch(SP_VAL + j * 4, 0) ||
           !touch(SP_X + sp_col(seed, j) * 4, 0))
          return;
      }
      if(!touch(SP_Y + r * 4, 1))
        return;
    }
}

// ---- hash join: R | table | S | out -------------------------------------------
#define HJ_R_TUP 8192
#define HJ_S_TUP 65536
#define HJ_BUCKETS 16384
#define HJ_R 0ULL
#define HJ_T (HJ_R + (uint64)HJ_R_TUP * 16)
#define HJ_S (HJ_T + (uint64)HJ_BUCKETS * 16)
#define HJ_OUT (HJ_S + (uint64)HJ_S_TUP * 16)
#define HJ_OUT_TUP 32768
#define HJ_PAGES ((HJ_OUT + (uint64)HJ_OUT_TUP * 16 + PG - 1) / PG)

static void
run_hashjoin(uint64 seed)
{
  uint64 outpos = 0;
  for(uint64 q = 0;; q++){
    for(uint64 i = 0; i < HJ_R_TUP; i++){                  // build
      if(!touch(HJ_R + i * 16, 0))
        return;
      uint64 b = mix(i, seed ^ (q << 32)) % HJ_BUCKETS;
      if(!touch(HJ_T + b * 16, 1))
        return;
    }
    for(uint64 i = 0; i < HJ_S_TUP; i++){                  // probe
      if(!touch(HJ_S + i * 16, 0))
        return;
      uint64 h = mix(i, seed + 0x51ED);
      uint64 key = h % (2 * HJ_R_TUP);                      // half the probe keys can match
      uint64 b = mix(key, seed ^ (q << 32)) % HJ_BUCKETS;
      if(!touch(HJ_T + b * 16, 0))
        return;
      if(key < HJ_R_TUP){                                   // match: emit an output tuple
        if(!touch(HJ_OUT + (outpos % HJ_OUT_TUP) * 16, 1))
          return;
        outpos++;
      }
    }
  }
}

// ---- bloom filter -------------------------------------------------------------
#define BL_PAGES 2048
#define BL_BITS ((uint64)BL_PAGES * PG * 8)
#define BL_K 4

static void
run_bloom(uint64 seed)
{
  struct vmbench_rng rp, rw;
  vmbench_rng_seed(&rp, seed * 2 + 1);
  vmbench_rng_seed(&rw, seed * 2 + 2);
  for(;;){
    uint64 rank = zipf_rank(pat_zipf_cdf_099, &rp);
    uint64 key = rank * 64 + vmbench_rng_below(&rp, 64);
    int ins = vmbench_rng_below(&rw, 100) < 5;
    for(int k = 0; k < BL_K; k++){
      uint64 bit = mix(key, seed + (uint64)k * 0x1234567ULL) % BL_BITS;
      if(!touch(bit / 8, ins))
        return;
    }
  }
}

static int
footprint_for(int mode)
{
  switch(mode){
  case M_CHASE: return CH_PAGES;
  case M_SPMV: return (int)SP_PAGES;
  case M_HASHJOIN: return (int)HJ_PAGES;
  default: return BL_PAGES;
  }
}

int
main(int argc, char *argv[])
{
  if(argc != 5 && argc != 6){
    printf("usage: appbench <resident_margin> <accesses> <seed> <mode> [trace: 1=console, 9=file]\n  modes:");
    for(int i = 0; i < M_COUNT; i++)
      printf(" %s", mode_names[i]);
    printf("\n");
    exit(1);
  }
  int resident_margin = atoi(argv[1]);
  g_accesses = atoi(argv[2]);
  uint64 seed = (uint64)atoi(argv[3]);
  int mode = -1;
  for(int i = 0; i < M_COUNT; i++)
    if(strcmp(argv[4], mode_names[i]) == 0)
      mode = i;
  int trace_flags = argc == 6 ? atoi(argv[5]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(mode < 0 || g_accesses < 1){
    printf("appbench: bad mode or access count\n");
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("appbench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }
  int footprint_pages = footprint_for(mode);

  vmbench_banner("appbench", "setup");
  g_arena = vmbench_arena(footprint_pages);
  if(g_arena == SBRK_ERROR){
    printf("appbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }
  *(volatile int *)g_arena = 0;
  uint64 settled;
  int proven = vmbench_burn(g_arena, footprint_pages, &settled);
  if(proven < 0){
    printf("appbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn used\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("appbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  vmbench_banner("appbench", "populate");
  for(int p = 0; p < footprint_pages; p++)
    *(volatile int *)(g_arena + (uint64)p * PG) = 0;

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);
  vmbench_banner("appbench", "workload");
  if(trace)
    vmbench_trace_start("appbench", "see RESULT lines below for full parameters",
                        seed, g_arena, footprint_pages, resident_margin);
  switch(mode){
  case M_CHASE: run_chase(seed); break;
  case M_SPMV: run_spmv(seed); break;
  case M_HASHJOIN: run_hashjoin(seed); break;
  default: run_bloom(seed); break;
  }
  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("appbench workload", &d);

  long word_sum = 0;
  for(int p = 0; p < footprint_pages; p++)
    word_sum += *(volatile int *)(g_arena + (uint64)p * PG);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("accesses", g_accesses);
  vmbench_result("mode", mode);
  vmbench_result("reads", g_reads);
  vmbench_result("writes", g_writes);
  vmbench_result("checksum", (long)(g_checksum & 0x7fffffffffffffffULL));
  vmbench_result("word_sum", word_sum);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);
  if(word_sum != g_writes){
    printf("\n*** FAIL: word sum %ld != writes %ld ***\n", word_sum, g_writes);
    exit(1);
  }
  printf("\nPASS\n");
  exit(0);
}
