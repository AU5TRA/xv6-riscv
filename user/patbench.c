// patbench: six synthetic page-access patterns, each isolating one
// behaviour and most with a textbook answer the simulator and the kernel
// can be checked against (GAWWY_HANDOFF_NEW_BENCHMARKS.md, section 5.1).
//
//   patbench <footprint_pages> <resident_margin> <accesses> <seed> <mode>
//            [trace: 1=console, 9=file]
//
// One arena of P = footprint_pages pages. Each access touches one 64-bit
// word at the start of one page: a read, or for PAT_WRITE_PCT of accesses
// (drawn from the PRNG) a read-modify-write that adds one to it. Every
// access is exactly one reference in the trace, R or W. The modes, by
// the variant name the mode argument takes:
//
//   loop        a fixed order of all P pages, repeated. With C < P frames
//               LRU, FIFO and Clock miss on every access once warm; MRU
//               and Belady miss about P - C times per pass.
//   scanhot     a hot set of H = P/16 pages takes 50% of accesses; the
//   scanhotlo   rest walk a sequential scan over the other P - H pages in
//               address order, wrapping. scanhotlo: 20% hot. Once more
//               than about C - H scan pages pass between two touches of a
//               hot page, LRU and FIFO lose the hot set.
//   zipf060     Zipf ranks at skew 0.60/0.80/0.99/1.20 over P = 1024
//   zipf080     ranks (user/zipf_table_<skew>.h), mapped to pages by a
//   zipf099     seeded permutation so the hottest pages are scattered.
//   zipf120     Independent references: LFU is the best online policy.
//   uniform     every page equally likely (GUPS-style). Every online
//               policy misses 1 - C/P of accesses; a learned policy that
//               beats Clock here has a bug or sees the future.
//   phase       a hot set of H = P/16 pages takes 80% of accesses, the
//   phaseshort  rest uniform over P; every K accesses (accesses/8, or
//               accesses/32 for phaseshort) a new hot set is drawn. LFU
//               keeps the old hot pages; LRU and Aging adapt.
//   switch      alternating phases of K = accesses/8: the loop over all P
//               pages (recency hurts), then zipf099 over P (frequency
//               helps). No single classic policy is good in both; ARC
//               (tools/sim.py) is designed for it.
//
// Page orders, hot sets and the Zipf rank-to-page map all come from
// seeded permutations of [0, P) computed on the fly (vmbench_perm in
// user/vmbench.h, a Feistel network cycle-walked into range), so there is
// no table to keep untraced outside the arena or to trace inside it. The
// Zipf CDF tables are const data, one page each, like kvbench's.
//
// The draws from the PRNG, in order, fix the reference string; the host
// model (tools/hostmodel/patbench.py) makes the same draws and must
// reproduce the trace byte for byte:
//   setup:      key_a = next(), key_b = next()
//   per access: the mode's draws (below), then write = below(100) < 10
//     loop        none (page = perm_a(position))
//     scanhot     hot = below(100) < pct; if hot, j = below(H) and
//                 page = perm_a(j); else the scan's next page whose
//                 perm_a inverse is >= H
//     zipf        rank = zipf(next()); page = perm_a(rank)
//     uniform     page = below(P)
//     phase       at every multiple of K, key = next() (a new hot set);
//                 then hot = below(100) < 80; page = perm_key(below(H))
//                 if hot, else below(P)
//     switch      even phases as loop (one position carried across them),
//                 odd phases rank = zipf099(next()), page = perm_b(rank)
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"
#include "user/zipf_table_060.h"
#include "user/zipf_table_080.h"
#include "user/zipf_table_099.h"
#include "user/zipf_table_120.h"

#define PAT_WRITE_PCT 10   // w: read-modify-write share of accesses
#define PAT_HOT_DIV 16     // hot set H = P / 16 (scanhot, phase)
#define PAT_MAX_PAGES 4096 // well under the swap area's 8192 slots
#define PAT_ZIPF_N 1024    // ranks in every zipf table; zipf modes need P = 1024

#if VMBENCH_ZIPF_N_060 != PAT_ZIPF_N || VMBENCH_ZIPF_N_080 != PAT_ZIPF_N || \
    VMBENCH_ZIPF_N_099 != PAT_ZIPF_N || VMBENCH_ZIPF_N_120 != PAT_ZIPF_N
#error "patbench: every zipf table must have PAT_ZIPF_N ranks"
#endif

enum { PAT_LOOP, PAT_SCANHOT, PAT_ZIPF, PAT_UNIFORM, PAT_PHASE, PAT_SWITCH };

struct pat_mode {
  const char *name;
  int kind;
  int hot_pct;       // scanhot, phase: share of accesses to the hot set
  int phase_div;     // phase, switch: K = accesses / phase_div
  int theta_x100;    // zipf, switch: the table's skew, for the RESULT line
  const uint32 *cdf; // zipf, switch: PAT_ZIPF_N-rank CDF
};

static const struct pat_mode MODES[] = {
  {"loop", PAT_LOOP, 0, 0, 0, 0},
  {"scanhot", PAT_SCANHOT, 50, 0, 0, 0},
  {"scanhotlo", PAT_SCANHOT, 20, 0, 0, 0},
  {"zipf060", PAT_ZIPF, 0, 0, 60, vmbench_zipf_cdf_060},
  {"zipf080", PAT_ZIPF, 0, 0, 80, vmbench_zipf_cdf_080},
  {"zipf099", PAT_ZIPF, 0, 0, 99, vmbench_zipf_cdf_099},
  {"zipf120", PAT_ZIPF, 0, 0, 120, vmbench_zipf_cdf_120},
  {"uniform", PAT_UNIFORM, 0, 0, 0, 0},
  {"phase", PAT_PHASE, 80, 8, 0, 0},
  {"phaseshort", PAT_PHASE, 80, 32, 0, 0},
  {"switch", PAT_SWITCH, 0, 8, 99, vmbench_zipf_cdf_099},
};
#define NMODES ((int)(sizeof(MODES) / sizeof(MODES[0])))

static const struct pat_mode *
find_mode(const char *s)
{
  for(int i = 0; i < NMODES; i++)
    if(strcmp(s, MODES[i].name) == 0)
      return &MODES[i];
  printf("patbench: unknown mode '%s' (want loop|scanhot|scanhotlo|zipf060|"
         "zipf080|zipf099|zipf120|uniform|phase|phaseshort|switch)\n", s);
  exit(1);
}

int
main(int argc, char *argv[])
{
  if(argc != 6 && argc != 7){
    printf("usage: patbench <footprint_pages> <resident_margin> <accesses> "
           "<seed> <mode> [trace: 1=console, 9=file]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  long accesses = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  const struct pat_mode *m = find_mode(argv[5]);
  int trace_flags = argc == 7 ? atoi(argv[6]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(footprint_pages < PAT_HOT_DIV || footprint_pages > PAT_MAX_PAGES){
    printf("patbench: footprint_pages must be %d-%d\n", PAT_HOT_DIV,
           PAT_MAX_PAGES);
    exit(1);
  }
  if(accesses < 1){
    printf("patbench: accesses must be at least 1\n");
    exit(1);
  }
  if(m->cdf && footprint_pages != PAT_ZIPF_N){
    printf("patbench: mode %s needs footprint_pages = %d (the zipf table's "
           "ranks)\n", m->name, PAT_ZIPF_N);
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("patbench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }

  vmbench_banner("patbench", "setup");
  printf("[info] mode %s: synthetic pattern over %d pages, %ld accesses\n",
         m->name, footprint_pages, accesses);
  char *arena = vmbench_arena(footprint_pages);
  if(arena == SBRK_ERROR){
    printf("patbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }

  // Touch only the first page, so the burn has something in the arena's
  // own VPN range to observe; nothing else in the arena is touched before
  // the measured window.
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

  // Setup. There is no data to build: the arena starts untouched, and the
  // only state is the PRNG and two permutation keys.
  uint64 P = (uint64)footprint_pages;
  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);
  struct vmbench_perm perm_a, perm_b, perm_hot;
  vmbench_perm_init(&perm_a, P, vmbench_rng_next(&rng));
  vmbench_perm_init(&perm_b, P, vmbench_rng_next(&rng));
  perm_hot = perm_a;
  uint64 hot = P / PAT_HOT_DIV;
  long phase_len = 0;
  if(m->phase_div){
    phase_len = accesses / m->phase_div;
    if(phase_len < 1)
      phase_len = 1;
  }

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("patbench", "workload");
  if(trace)
    vmbench_trace_start("patbench", m->name, seed, arena, footprint_pages,
                        resident_margin);
  uint64 loop_pos = 0, scan_pos = 0, checksum = 0;
  long reads = 0, writes = 0, refs = 0;
  for(long i = 0; i < accesses; i++){
    uint64 page;
    switch(m->kind){
    case PAT_LOOP:
      page = vmbench_perm_fwd(&perm_a, loop_pos);
      if(++loop_pos == P)
        loop_pos = 0;
      break;
    case PAT_SCANHOT:
      if(vmbench_rng_below(&rng, 100) < (uint64)m->hot_pct){
        page = vmbench_perm_fwd(&perm_a, vmbench_rng_below(&rng, hot));
      } else {
        do {
          page = scan_pos;
          if(++scan_pos == P)
            scan_pos = 0;
        } while(vmbench_perm_inv(&perm_a, page) < hot);
      }
      break;
    case PAT_ZIPF:
      page = vmbench_perm_fwd(&perm_a,
                      vmbench_zipf_sample_cdf(&rng, m->cdf, PAT_ZIPF_N));
      break;
    case PAT_UNIFORM:
      page = vmbench_rng_below(&rng, P);
      break;
    case PAT_PHASE:
      if(i % phase_len == 0)
        vmbench_perm_init(&perm_hot, P, vmbench_rng_next(&rng));
      if(vmbench_rng_below(&rng, 100) < (uint64)m->hot_pct)
        page = vmbench_perm_fwd(&perm_hot, vmbench_rng_below(&rng, hot));
      else
        page = vmbench_rng_below(&rng, P);
      break;
    default: // PAT_SWITCH
      if((i / phase_len) % 2 == 0){
        page = vmbench_perm_fwd(&perm_a, loop_pos);
        if(++loop_pos == P)
          loop_pos = 0;
      } else {
        page = vmbench_perm_fwd(&perm_b,
                        vmbench_zipf_sample_cdf(&rng, m->cdf, PAT_ZIPF_N));
      }
      break;
    }
    int is_write = vmbench_rng_below(&rng, 100) < PAT_WRITE_PCT;
    volatile uint64 *word = (volatile uint64 *)(arena + page * VMBENCH_PGSIZE);
    uint64 v = *word;
    checksum += v;
    if(is_write){
      *word = v + 1;
      writes++;
    } else {
      reads++;
    }
    vmbench_trace_ref(arena, page, is_write ? VMBENCH_WRITE : VMBENCH_READ);
    refs++;
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("patbench workload", &d);

  int loops = m->kind == PAT_LOOP || m->kind == PAT_SWITCH;
  int hots = m->kind == PAT_SCANHOT || m->kind == PAT_PHASE;
  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("accesses", accesses);
  vmbench_result("seed", (long)seed);
  vmbench_result("loop_pages", loops ? (long)P : 0);
  vmbench_result("hot_pages", hots ? (long)hot : 0);
  vmbench_result("hot_pct", m->hot_pct);
  vmbench_result("phase_len", phase_len);
  vmbench_result("zipf_theta_x100", m->theta_x100);
  vmbench_result("write_pct", PAT_WRITE_PCT);
  vmbench_result("reads", reads);
  vmbench_result("writes", writes);
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
