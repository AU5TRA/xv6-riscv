// joinbench: an in-memory hash join, build then probe
// (GAWWY_HANDOFF_NEW_BENCHMARKS.md, section 4.4).
//
//   joinbench <footprint_pages> <resident_margin> <r_tuples> <seed> <mode>
//             [trace: 1=console, 9=file]
//
// Four page-aligned regions in one arena:
//   R  the build relation, r_tuples 16-byte tuples {key, payload, two
//      columns the join does not read}, keys unique;
//   T  the hash table: open addressing with linear probing, 8-byte slots
//      {key, payload}, twice as many slots as R has tuples (rounded up to
//      a whole page), so it is never more than 50% full -- lzwbench's old
//      table filled to 100% and every miss then scanned all of it;
//   S  the probe relation, 16-byte tuples whose keys are R's keys;
//   O  the output, one 8-byte {R payload, S payload} row per match.
// Key 0 marks an empty slot, so the table needs no clearing pass: its
// pages arrive zero-filled, as calloc'd memory would. R's keys are
// 1 + a seeded permutation of [0, 4 * r_tuples), in row order.
//
// The two relations are loaded in setup, after the limit is set and
// outside the measured window, as tables read from disk would be. The
// measured window is the join itself:
//   build: scan R (R), and insert each tuple: read the slots it probes
//          (R) until an empty one, which it fills (W);
//   probe: scan S (R); probe the table (R per slot) until the key or an
//          empty slot; append each match to O (W).
// Every probe key is one of R's, so every S tuple matches exactly once.
// Modes:
//   uni   |S| = 2|R|, each S key uniform over R's keys
//   zipf  |S| = 2|R|, Zipf(0.99) over R's keys (r_tuples must be 65536,
//         the ranks of user/zipf_table_64k099.h): a few keys, and so a few
//         table slots, take most of the probes
//   r4    |S| = 4|R|, uniform
// The table is the random-access hot structure; S streams through once.
//
// PRNG draws, in order (the host model, tools/hostmodel/joinbench.py,
// repeats them): key permutation = next(); then for each S tuple its R
// row, below(|R|) (uni, r4) or a bucketed Zipf sample, two draws (zipf).
// The join itself draws nothing.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "user/user.h"
#include "user/vmbench.h"
#include "user/zipf_table_64k099.h"

#define JOIN_EMPTY 0
#define JOIN_KEY_SPACE 4  // keys come from [1, 4 * r_tuples]
#define JOIN_MAX_PAGES 4096

struct join_tuple {
  int key;
  int payload;
  int other[2]; // columns the join does not touch
};

struct join_slot {
  int key;
  int payload;
};

struct join_out {
  int r_payload;
  int s_payload;
};

struct join_mode {
  const char *name;
  int s_ratio; // |S| = s_ratio * |R|
  int zipf;
};

static const struct join_mode MODES[] = {
  {"uni", 2, 0},
  {"zipf", 2, 1},
  {"r4", 4, 0},
};
#define NMODES ((int)(sizeof(MODES) / sizeof(MODES[0])))

static char *g_arena;

static void
join_trace(const void *p, char access)
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

static const struct join_mode *
find_mode(const char *s)
{
  for(int i = 0; i < NMODES; i++)
    if(strcmp(s, MODES[i].name) == 0)
      return &MODES[i];
  printf("joinbench: unknown mode '%s' (want uni|zipf|r4)\n", s);
  exit(1);
}

int
main(int argc, char *argv[])
{
  if(argc != 6 && argc != 7){
    printf("usage: joinbench <footprint_pages> <resident_margin> <r_tuples> "
           "<seed> <uni|zipf|r4> [trace: 1=console, 9=file]\n");
    exit(1);
  }
  int footprint_pages = atoi(argv[1]);
  int resident_margin = atoi(argv[2]);
  long nr = atoi(argv[3]);
  uint64 seed = (uint64)atoi(argv[4]);
  const struct join_mode *m = find_mode(argv[5]);
  int trace_flags = argc == 7 ? atoi(argv[6]) : 0;
  int trace = (trace_flags & 1) != 0;
  if(nr < 1){
    printf("joinbench: r_tuples must be at least 1\n");
    exit(1);
  }
  if(m->zipf && nr != VMBENCH_ZIPF_N_64k099){
    printf("joinbench: mode zipf needs r_tuples = %d (the zipf table's "
           "ranks)\n", VMBENCH_ZIPF_N_64k099);
    exit(1);
  }
  long ns = nr * m->s_ratio;
  long slots_per_page = VMBENCH_PGSIZE / sizeof(struct join_slot);
  long nslots = (2 * nr + slots_per_page - 1) / slots_per_page *
                slots_per_page;
  long r_pages = pages_for(nr * (long)sizeof(struct join_tuple));
  long t_pages = pages_for(nslots * (long)sizeof(struct join_slot));
  long s_pages = pages_for(ns * (long)sizeof(struct join_tuple));
  long o_pages = pages_for(ns * (long)sizeof(struct join_out));
  long need = r_pages + t_pages + s_pages + o_pages;
  if(footprint_pages < need || footprint_pages > JOIN_MAX_PAGES){
    printf("joinbench: footprint_pages must be %ld-%d for these sizes\n",
           need, JOIN_MAX_PAGES);
    exit(1);
  }
  if(trace && vmbench_trace_sink(trace_flags) < 0){
    printf("joinbench: cannot create %s\n", VMBENCH_TRACE_PATH);
    exit(1);
  }

  vmbench_banner("joinbench", "setup");
  printf("[info] mode %s: |R| = %ld, |S| = %ld, %ld table slots; synthetic "
         "relations from the integer PRNG\n", m->name, nr, ns, nslots);
  g_arena = vmbench_arena(footprint_pages);
  if(g_arena == SBRK_ERROR){
    printf("joinbench: vmbench_arena(%d) failed\n", footprint_pages);
    exit(1);
  }
  struct join_tuple *rel_r = (struct join_tuple *)g_arena;
  struct join_slot *table =
    (struct join_slot *)(g_arena + r_pages * VMBENCH_PGSIZE);
  struct join_tuple *rel_s =
    (struct join_tuple *)(g_arena + (r_pages + t_pages) * VMBENCH_PGSIZE);
  struct join_out *out =
    (struct join_out *)(g_arena +
                        (r_pages + t_pages + s_pages) * VMBENCH_PGSIZE);

  // Touch only the first page before the burn; the relations are loaded
  // after the limit is set.
  *(volatile int *)g_arena = 0;
  uint64 settled;
  int proven = vmbench_burn(g_arena, footprint_pages, &settled);
  if(proven < 0){
    printf("joinbench: vmbench_burn failed\n");
    exit(1);
  }
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, best-effort burn "
           "used -- baseline-priority guarantee is weaker here\n");
  if(vmctl(VM_SET_LIMIT, (int)settled + resident_margin) < 0){
    printf("joinbench: vmctl VM_SET_LIMIT failed\n");
    exit(1);
  }

  // Setup, untraced: load R and S.
  struct vmbench_rng rng;
  vmbench_rng_seed(&rng, seed);
  struct vmbench_perm keys;
  vmbench_perm_init(&keys, (uint64)(JOIN_KEY_SPACE * nr),
                    vmbench_rng_next(&rng));
  for(long i = 0; i < nr; i++){
    rel_r[i].key = 1 + (int)vmbench_perm_fwd(&keys, (uint64)i);
    rel_r[i].payload = (int)i;
    rel_r[i].other[0] = rel_r[i].other[1] = 0;
  }
  for(long j = 0; j < ns; j++){
    uint64 row = m->zipf
      ? vmbench_zipf_sample_bucketed(&rng, vmbench_zipf_cdf_64k099,
                                     vmbench_zipf_start_64k099,
                                     VMBENCH_ZIPF_B_64k099)
      : vmbench_rng_below(&rng, (uint64)nr);
    rel_s[j].key = 1 + (int)vmbench_perm_fwd(&keys, row);
    rel_s[j].payload = (int)j;
    rel_s[j].other[0] = rel_s[j].other[1] = 0;
  }

  struct vmstats before;
  vmbench_reset_and_snapshot(&before);

  vmbench_banner("joinbench", "workload");
  if(trace)
    vmbench_trace_start("joinbench", m->name, seed, g_arena, footprint_pages,
                        resident_margin);
  long refs = 0, build_probes = 0, probe_probes = 0, longest = 0;

  // Build.
  for(long i = 0; i < nr; i++){
    join_trace(&rel_r[i], VMBENCH_READ);
    refs++;
    int key = rel_r[i].key;
    int payload = rel_r[i].payload;
    long h = (long)(vmbench_mix64((uint64)key) % (uint64)nslots);
    long len = 0;
    for(;;){
      len++;
      if(table[h].key == JOIN_EMPTY){
        table[h].key = key;
        table[h].payload = payload;
        join_trace(&table[h], VMBENCH_WRITE);
        refs++;
        break;
      }
      join_trace(&table[h], VMBENCH_READ);
      refs++;
      h = h + 1 == nslots ? 0 : h + 1;
    }
    build_probes += len;
    if(len > longest)
      longest = len;
  }

  // Probe.
  long matches = 0;
  uint64 checksum = 0;
  for(long j = 0; j < ns; j++){
    join_trace(&rel_s[j], VMBENCH_READ);
    refs++;
    int key = rel_s[j].key;
    int s_payload = rel_s[j].payload;
    long h = (long)(vmbench_mix64((uint64)key) % (uint64)nslots);
    long len = 0;
    for(;;){
      len++;
      int k = table[h].key;
      join_trace(&table[h], VMBENCH_READ);
      refs++;
      if(k == key){
        out[matches].r_payload = table[h].payload;
        out[matches].s_payload = s_payload;
        join_trace(&out[matches], VMBENCH_WRITE);
        refs++;
        checksum += (uint64)(table[h].payload ^ s_payload);
        matches++;
        break;
      }
      if(k == JOIN_EMPTY)
        break;
      h = h + 1 == nslots ? 0 : h + 1;
    }
    probe_probes += len;
    if(len > longest)
      longest = len;
  }

  if(trace)
    vmbench_trace_stop();

  struct vmstats after;
  vmbench_snapshot(&after);
  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  vmbench_print_delta("joinbench workload", &d);

  vmbench_result("footprint_pages", footprint_pages);
  vmbench_result("resident_margin", resident_margin);
  vmbench_result("r_tuples", nr);
  vmbench_result("seed", (long)seed);
  vmbench_result("s_tuples", ns);
  vmbench_result("zipf_theta_x100", m->zipf ? 99 : 0);
  vmbench_result("table_slots", nslots);
  vmbench_result("pages_needed", need);
  vmbench_result("build_probes", build_probes);
  vmbench_result("probe_probes", probe_probes);
  vmbench_result("longest_probe", longest);
  vmbench_result("matches", matches);
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
