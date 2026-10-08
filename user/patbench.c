// patbench: synthetic access patterns with known answers (one program, many modes).
//
//   patbench <footprint_pages> <resident_margin> <accesses> <seed> <mode> [flags]
//
// One arena of P pages (P a power of two, 1024 by default in the stream
// manifest). Each access touches the first word of one page: a read, or a
// read-modify-write (traced as W) for 10% of accesses. Page choices come
// from a seeded PRNG stream, write flags from a second one, so a mode's page
// sequence does not depend on which accesses are writes.
//
// A "permutation" below is a seeded bijection on [0, P) built from add,
// odd-multiply and xorshift steps (all bijective modulo a power of two), so
// no table is needed and every arena access is the traced page touch itself.
//
// Modes (the mode argument is the variant name):
//   loop       visit all P pages cyclically in a seeded order
//   scanhot    hot set H=P/16 gets 50% of accesses; the rest walk a scan
//              through the other P-H pages (wrapping)
//   scanhotlo  the same with 20% to the hot set
//   zipf060..zipf120   page = permutation(Zipf rank), skew theta = 0.60 ..
//              1.20 (tables in user/pat_zipf.h)
//   uniform    page uniform over P
//   phase      90% of accesses go to a hot set of P/16 pages redrawn every
//              accesses/8; the rest uniform
//   phaseshort the same, redrawn every accesses/32
//   switch     phases of accesses/8 alternate: loop over P/2 pages, then
//              Zipf 0.99 over P pages
//
// tools/patbench_model.py re-implements every mode on the host and checks the
// trace against it reference by reference.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"
#include "user/pat_zipf.h"

enum {
  M_LOOP, M_SCANHOT, M_SCANHOTLO, M_ZIPF060, M_ZIPF080, M_ZIPF099, M_ZIPF120,
  M_UNIFORM, M_PHASE, M_PHASESHORT, M_SWITCH, M_COUNT
};

static const char *mode_names[M_COUNT] = {
  "loop", "scanhot", "scanhotlo", "zipf060", "zipf080", "zipf099", "zipf120",
  "uniform", "phase", "phaseshort", "switch"
};

#define WRITE_PERMILLE 100   // share of accesses that are read-modify-write
#define HOT_DIV 16           // hot set = P / HOT_DIV
#define PHASE_HOT_PERMILLE 900

static uint64 g_mask;        // P - 1
static int g_bits;           // log2(P)

struct perm {
  uint64 k1, k2, k3;
};

// Seeded bijection on [0, P).
static void
perm_init(struct perm *p, uint64 seed, uint64 tag)
{
  struct vmbench_rng r;
  vmbench_rng_seed(&r, seed * 0x9E3779B97F4A7C15ULL + tag * 0xD1B54A32D192ED03ULL + 1);
  p->k1 = vmbench_rng_next(&r);
  p->k2 = vmbench_rng_next(&r) | 1;
  p->k3 = vmbench_rng_next(&r) | 1;
}

static uint64
perm_apply(const struct perm *p, uint64 x)
{
  int s = (g_bits + 1) / 2;
  x = (x + p->k1) & g_mask;
  x = (x * p->k2) & g_mask;
  x ^= x >> s;
  x = (x * p->k3) & g_mask;
  x ^= x >> s;
  return x;
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

static int
find_mode(const char *name)
{
  for(int i = 0; i < M_COUNT; i++)
    if(strcmp(name, mode_names[i]) == 0)
      return i;
  return -1;
}

int
main(int argc, char *argv[])
{
  if(argc != 6 && argc != 7){
    printf("usage: patbench <footprint_pages> <resident_margin> <accesses> "
           "<seed> <mode> [trace: 1=console, 9=file]\n  modes:");
    for(int i = 0; i < M_COUNT; i++)
      printf(" %s", mode_names[i]);
    printf("\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  long accesses = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  int mode = find_mode(argv[5]);
  int trace_flags = argc == 7 ? atoi(argv[6]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(mode < 0){
    printf("patbench: unknown mode '%s'\n", argv[5]);
    exit(1);
  }
  if(footprint_pages < 16 || (footprint_pages & (footprint_pages - 1)) != 0 ||
     footprint_pages > 4096){
    printf("patbench: footprint_pages must be a power of two in [16, 4096]\n");
    exit(1);
  }
  if(accesses < 1){
    printf("patbench: accesses must be >= 1\n");
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("patbench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }
  g_mask = (uint64)footprint_pages - 1;
  g_bits = 0;
  while((1 << g_bits) < footprint_pages)
    g_bits++;
  uint64 P = (uint64)footprint_pages;
  uint64 H = P / HOT_DIV;

  vmbench_banner("patbench", "setup");
  char *arena = vmbench_arena(footprint_pages);
  if(arena == SBRK_ERROR){
    printf("patbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }

  *(volatile int *)arena = 0;
  uint64 settled;
  int proven = vmbench_burn(arena, footprint_pages, &settled);
  if(proven < 0){
    printf("patbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("patbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  // Populate: every page exists and holds 0 before the traced run. Untraced
  // setup, like the other benchmarks' build step.
  vmbench_banner("patbench", "populate");
  for(uint64 p = 0; p < P; p++)
    *(volatile int *)(arena + p * VMBENCH_PGSIZE) = 0;

  // Mode parameters.
  const uint32 *cdf = 0;
  uint32 hot_permille = 0;
  long phase_len = 0;
  uint64 loop_len = P;
  switch(mode){
  case M_SCANHOT:    hot_permille = 500; break;
  case M_SCANHOTLO:  hot_permille = 200; break;
  case M_ZIPF060:    cdf = pat_zipf_cdf_060; break;
  case M_ZIPF080:    cdf = pat_zipf_cdf_080; break;
  case M_ZIPF099:    cdf = pat_zipf_cdf_099; break;
  case M_ZIPF120:    cdf = pat_zipf_cdf_120; break;
  case M_PHASE:      hot_permille = PHASE_HOT_PERMILLE; phase_len = accesses / 8; break;
  case M_PHASESHORT: hot_permille = PHASE_HOT_PERMILLE; phase_len = accesses / 32; break;
  case M_SWITCH:     cdf = pat_zipf_cdf_099; phase_len = accesses / 8;
                     loop_len = P / 2; break;
  }
  if(phase_len < 1)
    phase_len = 1;

  struct perm perm_a, perm_b, perm_ph;
  perm_init(&perm_a, seed, 1);     // loop order / hot-set choice / zipf scatter
  perm_init(&perm_b, seed, 2);     // switch: the Zipf phase's own scatter
  perm_init(&perm_ph, seed, 100);  // phase: redrawn per phase
  struct vmbench_rng rp, rw;
  vmbench_rng_seed(&rp, seed * 2 + 1);
  vmbench_rng_seed(&rw, seed * 2 + 2);

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("patbench", "workload");
  if(trace)
    vmbench_trace_start("patbench", "see RESULT lines below for full "
                        "parameters", seed, arena, footprint_pages,
                        resident_margin);

  long reads = 0, writes = 0;
  uint64 checksum = 0;
  uint64 scan_pos = 0;
  uint64 loop_pos = 0;
  long phase_no = -1;
  for(long i = 0; i < accesses; i++){
    uint64 page = 0;
    switch(mode){
    case M_LOOP:
      page = perm_apply(&perm_a, (uint64)i % P);
      break;
    case M_SCANHOT: case M_SCANHOTLO:
      if(vmbench_rng_below(&rp, 1000) < hot_permille){
        page = perm_apply(&perm_a, vmbench_rng_below(&rp, H));
      } else {
        page = perm_apply(&perm_a, H + scan_pos);
        scan_pos = (scan_pos + 1) % (P - H);
      }
      break;
    case M_ZIPF060: case M_ZIPF080: case M_ZIPF099: case M_ZIPF120:
      page = perm_apply(&perm_a, zipf_rank(cdf, &rp));
      break;
    case M_UNIFORM:
      page = vmbench_rng_below(&rp, P);
      break;
    case M_PHASE: case M_PHASESHORT: {
      long ph = i / phase_len;
      if(ph != phase_no){
        phase_no = ph;
        perm_init(&perm_ph, seed, 100 + (uint64)ph);
      }
      if(vmbench_rng_below(&rp, 1000) < hot_permille)
        page = perm_apply(&perm_ph, vmbench_rng_below(&rp, H));
      else
        page = vmbench_rng_below(&rp, P);
      break;
    }
    case M_SWITCH: {
      long ph = i / phase_len;
      if(ph % 2 == 0){
        page = perm_apply(&perm_a, loop_pos % loop_len);
        loop_pos++;
      } else {
        page = perm_apply(&perm_b, zipf_rank(cdf, &rp));
      }
      break;
    }
    }

    volatile int *word = (volatile int *)(arena + page * VMBENCH_PGSIZE);
    if(vmbench_rng_below(&rw, 1000) < WRITE_PERMILLE){
      vmbench_trace_ref(arena, page, VMBENCH_WRITE);
      int v = *word + 1;
      *word = v;
      checksum += (uint64)v;
      writes++;
    } else {
      vmbench_trace_ref(arena, page, VMBENCH_READ);
      checksum += (uint64)*word;
      reads++;
    }
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("patbench workload", &d);

  // Verification, after the trace stopped: the words sum to the number of
  // writes (every write adds 1 to one word).
  long word_sum = 0;
  for(uint64 p = 0; p < P; p++)
    word_sum += *(volatile int *)(arena + p * VMBENCH_PGSIZE);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("accesses", accesses);
  vmbench_result("mode", mode);
  vmbench_result("write_permille", WRITE_PERMILLE);
  vmbench_result("hot_pages", (long)H);
  vmbench_result("hot_permille", hot_permille);
  vmbench_result("phase_len", phase_len);
  vmbench_result("loop_len", (long)loop_len);
  vmbench_result("reads", reads);
  vmbench_result("writes", writes);
  vmbench_result("checksum", (long)(checksum & 0x7fffffffffffffffULL));
  vmbench_result("word_sum", word_sum);
  vmbench_result("zero_faults", d.zero_faults);
  vmbench_result("swap_faults", d.swap_faults);
  vmbench_result("evictions", d.evictions);
  vmbench_result("page_reads", d.page_reads);
  vmbench_result("page_writes", d.page_writes);

  if(word_sum != writes){
    printf("\n*** FAIL: word sum %ld != writes %ld ***\n", word_sum, writes);
    exit(1);
  }
  printf("\nPASS\n");
  exit(0);
}
