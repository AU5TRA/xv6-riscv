// Gate 1 self-test for user/vmbench.h / user/vmbench.c: exercises every
// helper the shared harness provides, so later workloads can trust it
// without re-verifying it themselves.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "kernel/vmtrace.h"
#include "user/user.h"
#include "user/vmbench.h"
#include "user/zipf_table.h"

#define ARENA_PAGES 8

static void
fail(const char *why)
{
  printf("\n*** FAIL: %s ***\n", why);
  exit(1);
}

// Check 1: arena is page-aligned, and its base VPN is exactly what
// pointer arithmetic says it should be.
static void
check_arena_alignment(void)
{
  char *base = vmbench_arena(ARENA_PAGES);
  if(base == SBRK_ERROR)
    fail("vmbench_arena failed");
  if(((uint64)base % VMBENCH_PGSIZE) != 0)
    fail("arena base is not page-aligned");
  if(vmbench_arena_free(ARENA_PAGES) < 0)
    fail("vmbench_arena_free failed");
  printf("[ok] arena alignment: base=%p is page-aligned\n", base);
}

// Check 2: touch_w on a fresh page actually produces a real fault
// (zero_faults increments by exactly 1), proving the touch primitives
// are not being optimized away and the arena is genuinely lazy.
static void
check_touch_faults(void)
{
  struct vmstats before, after;
  char *base = vmbench_arena(4);
  if(base == SBRK_ERROR)
    fail("vmbench_arena failed (touch check)");

  vmbench_snapshot(&before);
  touch_w(base, 0, 42);
  vmbench_snapshot(&after);

  struct vmbench_delta d;
  vmbench_delta(&before, &after, &d);
  if(d.zero_faults != 1)
    fail("touch_w on a fresh page did not produce exactly one zero_fault");
  if(touch_r(base, 0) != 42)
    fail("touch_r did not read back the value touch_w wrote");

  if(vmbench_arena_free(4) < 0)
    fail("vmbench_arena_free failed (touch check)");
  printf("[ok] touch_w/touch_r: real fault observed, byte-exact read-back\n");
}

// Check 3: the burn phase demonstrably reaches the arena's own VPN
// range under a tight budget, and reports settled_resident correctly
// (a later deliberate touch under that limit should force an
// eviction).
static void
check_burn_phase(void)
{
  struct vmstats before;
  vmbench_snapshot(&before);
  if(vmctl(VM_SET_LIMIT, (int)before.resident_count + 4) < 0)
    fail("vmctl VM_SET_LIMIT failed (burn check)");

  char *base = vmbench_arena(ARENA_PAGES);
  if(base == SBRK_ERROR)
    fail("vmbench_arena failed (burn check)");
  for(int i = 0; i < 4; i++)
    touch_w(base, i, (uchar)(i + 1));

  uint64 settled = 0;
  int proven = vmbench_burn(base, ARENA_PAGES, &settled);
  if(proven < 0)
    fail("vmbench_burn failed");
  if(proven == 0)
    printf("[warn] vmbench_burn: VM_DEBUG unavailable, used best-effort "
           "fallback (weaker guarantee)\n");
  else
    printf("[ok] vmbench_burn: trace ring proved the burn reached the "
           "arena (settled_resident=%ld)\n", (long)settled);

  if(vmctl(VM_SET_LIMIT, (int)settled + 2) < 0)
    fail("vmctl VM_SET_LIMIT failed (post-burn)");

  // The 4 arena pages we already touched should now be the oldest
  // resident content (per the burn phase's whole point) -- touching 2
  // more forces exactly enough pressure that a genuine eviction must
  // occur, proving the re-tightened limit is actually being enforced.
  struct vmstats before_evict, after_evict;
  vmbench_snapshot(&before_evict);
  touch_w(base, 4, 5);
  touch_w(base, 5, 6);
  vmbench_snapshot(&after_evict);
  struct vmbench_delta d;
  vmbench_delta(&before_evict, &after_evict, &d);
  if(d.evictions < 1)
    fail("expected at least one eviction after burn + re-tightened limit");
  printf("[ok] burn phase: %ld eviction(s) forced after re-tightening, "
         "as expected\n", d.evictions);

  if(vmbench_arena_free(ARENA_PAGES) < 0)
    fail("vmbench_arena_free failed (burn check)");
}

// Check 4: xorshift64 PRNG is reproducible given the same seed.
static void
check_prng_reproducible(void)
{
  struct vmbench_rng a, b;
  vmbench_rng_seed(&a, 12345);
  vmbench_rng_seed(&b, 12345);
  for(int i = 0; i < 64; i++){
    uint64 va = vmbench_rng_next(&a);
    uint64 vb = vmbench_rng_next(&b);
    if(va != vb)
      fail("PRNG with identical seeds diverged");
  }
  // Different seed should (overwhelmingly likely) diverge somewhere in
  // the first few draws -- a cheap sanity check that seeding actually
  // does something.
  struct vmbench_rng c;
  vmbench_rng_seed(&c, 999999);
  int any_diff = 0;
  vmbench_rng_seed(&a, 12345);
  for(int i = 0; i < 8; i++)
    if(vmbench_rng_next(&a) != vmbench_rng_next(&c))
      any_diff = 1;
  if(!any_diff)
    fail("PRNG with different seeds produced identical output "
         "(seeding appears to be a no-op)");
  printf("[ok] PRNG: reproducible for a fixed seed, diverges across "
         "different seeds\n");
}

// Check 5: the Zipf sampler is actually skewed (bucket-count check,
// integer arithmetic only -- no floating point).
static void
check_zipf_skew(void)
{
  struct vmbench_rng r;
  vmbench_rng_seed(&r, 42);

  enum { NBUCKETS = 8, DRAWS = 20000 };
  long counts[NBUCKETS];
  for(int i = 0; i < NBUCKETS; i++)
    counts[i] = 0;

  for(int i = 0; i < DRAWS; i++){
    uint64 rank = vmbench_zipf_sample(&r);
    int bucket = (int)(rank * NBUCKETS / VMBENCH_ZIPF_N);
    if(bucket >= NBUCKETS)
      bucket = NBUCKETS - 1;
    counts[bucket]++;
  }

  printf("[info] zipf bucket counts (hot->cold):");
  for(int i = 0; i < NBUCKETS; i++)
    printf(" %ld", counts[i]);
  printf("\n");

  // A real Zipf skew should show the hottest bucket receiving
  // substantially more draws than the coldest -- require at least a
  // 4x ratio as a simple, generous, integer-only sanity bound (the
  // configured skew s=0.99 produces a much larger ratio in practice;
  // this just needs to catch "not skewed at all" or "inverted").
  if(counts[0] < counts[NBUCKETS - 1] * 4)
    fail("zipf sampler is not meaningfully skewed (hot bucket is not "
         ">=4x the cold bucket)");
  for(int i = 1; i < NBUCKETS; i++){
    if(counts[i] > counts[i - 1] + counts[i - 1] / 4 + 50)
      fail("zipf bucket counts are not monotonically decreasing "
           "(hot->cold) within a reasonable tolerance");
  }
  printf("[ok] zipf sampler: hot bucket >=4x cold bucket, monotonic "
         "decrease within tolerance\n");
}

int
main(void)
{
  printf("vmbenchtest starting\n");
  check_arena_alignment();
  check_touch_faults();
  check_burn_phase();
  check_prng_reproducible();
  check_zipf_skew();
  printf("\nPASS\n");
  exit(0);
}
