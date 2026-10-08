// bloombench: a Bloom filter -- k random bit probes per operation over a
// fixed bit array (GAWWY_HANDOFF_NEW_BENCHMARKS.md, section 4.5).
//
//   bloombench <footprint_pages> <resident_margin> <n_keys> <seed> <mode>
//              [trace: 1=console, 9=file]
//
// The whole arena is the bit array: m = footprint_pages * 32768 bits. The
// mode is the number of hash functions, k3 or k7; hash j of a key is
// vmbench_mix64(key ^ salt_j) % m, the k salts drawn from the PRNG.
//   insert: n_keys keys, setting k bits each. A bit is set by a
//           read-modify-write of its byte: one W reference per bit.
//   query:  4 * n_keys lookups, each a coin flip between a key that was
//           inserted and one that never was, reading its bits in order (R
//           each) and stopping at the first zero, as a real filter does.
// Keys are vmbench_mix64(base + i) for an index i, a bijection, so an
// absent key (i >= n_keys) never equals a present one; whether the filter
// says yes to it anyway is a false positive.
//
// The filter is sized by pages, not by a target false-positive rate: the
// handoff asks for a few hundred to ~1000 pages and a few million
// references, and a conventional 10 bits per key over 512 pages would take
// 1.7 million keys and ~12M insert references. The paging behaviour -- k
// uniform probes per operation over the array, read-mostly -- does not
// depend on the fill; the RESULT lines report it (bits_set) and the false
// positives it gives.
//
// PRNG draws, in order (tools/hostmodel/bloombench.py repeats them):
// setup: salt_0..salt_{k-1} = next(), base = next(); per query:
// present = below(2), then below(n_keys) for a present key or
// n_keys + below(2^40) for an absent one. Inserting draws nothing.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"

#define BLOOM_MAX_K 7
#define BLOOM_QUERY_RATIO 4
#define BLOOM_ABSENT_SPACE (1ULL << 40)
#define BLOOM_MAX_PAGES 4096
#define BLOOM_BITS_PER_PAGE (VMBENCH_PGSIZE * 8)

static char *g_bits;
static uint64 g_m;
static uint64 g_salt[BLOOM_MAX_K];

static uint64
bit_of(uint64 key, int j)
{
  return vmbench_mix64(key ^ g_salt[j]) % g_m;
}

int
main(int argc, char *argv[])
{
  if(argc != 6 && argc != 7){
    printf("usage: bloombench <footprint_pages> <resident_margin> <n_keys> "
           "<seed> <k3|k7> [trace: 1=console, 9=file]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  long n = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  int k;
  if(strcmp(argv[5], "k3") == 0)
    k = 3;
  else if(strcmp(argv[5], "k7") == 0)
    k = 7;
  else {
    printf("bloombench: unknown mode '%s' (want k3|k7)\n", argv[5]);
    exit(1);
  }
  int trace_flags = argc == 7 ? atoi(argv[6]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(footprint_pages < 1 || footprint_pages > BLOOM_MAX_PAGES){
    printf("bloombench: footprint_pages must be 1-%d\n", BLOOM_MAX_PAGES);
    exit(1);
  }
  if(n < 1){
    printf("bloombench: n_keys must be at least 1\n");
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("bloombench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }
  g_m = (uint64)footprint_pages * BLOOM_BITS_PER_PAGE;
  long queries = BLOOM_QUERY_RATIO * n;

  vmbench_banner("bloombench", "setup");
  printf("[info] mode %s: %ld-bit filter, %ld keys, %ld queries; synthetic "
         "keys from the integer PRNG\n", argv[5], (long)g_m, n, queries);
  g_bits = vmbench_arena(footprint_pages);
  if(g_bits == SBRK_ERROR){
    printf("bloombench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }

  // Touch only the first page before the burn. The filter starts empty:
  // its pages arrive zero-filled, so there is nothing else to set up.
  *(volatile int *)g_bits = 0;
  uint64 settled;
  int proven = vmbench_burn(g_bits, footprint_pages, &settled);
  if(proven < 0){
    printf("bloombench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("bloombench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);
  for(int j = 0; j < k; j++)
    g_salt[j] = vmbench_rng_next(&rng);
  uint64 base = vmbench_rng_next(&rng);

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("bloombench", "workload");
  if(trace)
    vmbench_trace_start("bloombench", argv[5], seed, g_bits, footprint_pages,
                        resident_margin);
  long refs = 0, bits_set = 0;

  // Insert.
  for(long i = 0; i < n; i++){
    uint64 key = vmbench_mix64(base + (uint64)i);
    for(int j = 0; j < k; j++){
      uint64 b = bit_of(key, j);
      volatile uchar *byte = (volatile uchar *)(g_bits + b / 8);
      uchar v = *byte;
      uchar mask = (uchar)(1 << (b % 8));
      if((v & mask) == 0)
        bits_set++;
      *byte = v | mask;
      vmbench_trace_ref(g_bits, b / BLOOM_BITS_PER_PAGE, VMBENCH_WRITE);
      refs++;
    }
  }

  // Query.
  long present = 0, positives = 0, false_positives = 0, probes = 0;
  uint64 checksum = 0;
  for(long q = 0; q < queries; q++){
    int is_present = vmbench_rng_below(&rng, 2) == 0;
    uint64 i = is_present ? vmbench_rng_below(&rng, (uint64)n)
                          : (uint64)n + vmbench_rng_below(&rng,
                                                          BLOOM_ABSENT_SPACE);
    uint64 key = vmbench_mix64(base + i);
    int yes = 1;
    for(int j = 0; j < k; j++){
      uint64 b = bit_of(key, j);
      uchar v = *(volatile uchar *)(g_bits + b / 8);
      vmbench_trace_ref(g_bits, b / BLOOM_BITS_PER_PAGE, VMBENCH_READ);
      refs++;
      probes++;
      if((v & (1 << (b % 8))) == 0){
        yes = 0;
        break;
      }
    }
    present += is_present;
    if(yes){
      positives++;
      checksum += (uint64)q;
      if(!is_present)
        false_positives++;
    }
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("bloombench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("n_keys", n);
  vmbench_result("seed", (long)seed);
  vmbench_result("hashes", k);
  vmbench_result("filter_bits", (long)g_m);
  vmbench_result("queries", queries);
  vmbench_result("present_queries", present);
  vmbench_result("bits_set", bits_set);
  vmbench_result("query_probes", probes);
  vmbench_result("positives", positives);
  vmbench_result("false_positives", false_positives);
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
