// Native timing of the kernel's scoring code (S2 of the paper handoff).
//
// Compiles the kernel's own integer scoring headers (kernel/mlfeat.h, kernel/mlnet.h, kernel/mlnets.h) for the host CPU and times one eviction
// decision: compute each candidate's features, score it, pick the best (the same selection loop as choose_ml in kernel/vmpage.c, without the
// kernel-only parts: the page-table walk that reads and clears the accessed bits, the locks, the swap I/O). So it is a lower bound for the
// whole decision. For the sampled variant it includes the partial Fisher-Yates draw of k candidates.
//
//   gcc -O2 -I . -I kernel -o /tmp/native_timing tools/ml2/native_timing.c
//   taskset -c 2 /tmp/native_timing > report/results2/native_timing.csv ; taskset -c 2 /tmp/native_timing walk > report/results2/native_timing_walk.csv
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "kernel/mlfeat.h"
#include "kernel/mlnet.h"
#include "kernel/mlnets.h"
#include "kernel/mlweights.h"

#define MAXC 1024
struct cand { uint64 load_scan, last_seen, rdist, load_seq; uint32 sfreq, refaults; uint32 aging; uint8 seen, dirty; unsigned short lq_refaults, lq_rdist; };
static struct cand cs[MAXC];
static struct cand *cp[MAXC];
static struct mlcand mc[MAXC];
static long long sc[MAXC];
static uint64 now_scan = 1000000;

static int feature(const struct cand *c, int f) {
  switch (f) {
  case ML_F_REF: return c->seen ? 256 : 0;
  case ML_F_AGING: return ml_aging_q8(c->aging & 0xff);
  case ML_F_SFREQ: return ml_log1p_q8(c->sfreq);
  case ML_F_IDLE: return ml_log1p_q8(now_scan - c->last_seen);
  case ML_F_AGE: return ml_log1p_q8(now_scan - c->load_scan);
  case ML_F_DIRTY: return c->dirty ? 256 : 0;
  case ML_F_REFAULTS: return ml_log1p_q8(c->refaults);
  case ML_F_RDIST: return ml_log1p_q8(c->rdist);
  }
  return 0;
}

// The kernel's cheaper linear-score code (kernel/vmpage.c, ml_feature_linear): the logs of refaults and rdist are stored in the page,
// and the other logs use the byte-table highest-bit search. new_code = 0 times the code before the change.
static int new_code = 1;
static const unsigned char ml_msb8[256] = {
#define R2(n) n, n
#define R4(n) R2(n), R2(n)
#define R8(n) R4(n), R4(n)
#define R16(n) R8(n), R8(n)
#define R32(n) R16(n), R16(n)
#define R64(n) R32(n), R32(n)
#define R128(n) R64(n), R64(n)
  0, 0, R2(1), R4(2), R8(3), R16(4), R32(5), R64(6), R128(7)
};
static inline int log1p_fast(unsigned long long v) {
  if (v < 256) return ml_log1p_q8_small[v];
  unsigned long long x = v + 1;
  int e;
  if (x >> 32) e = x >> 48 ? (x >> 56 ? 56 + ml_msb8[x >> 56] : 48 + ml_msb8[x >> 48]) : (x >> 40 ? 40 + ml_msb8[x >> 40] : 32 + ml_msb8[x >> 32]);
  else e = x >> 16 ? (x >> 24 ? 24 + ml_msb8[x >> 24] : 16 + ml_msb8[x >> 16]) : 8 + ml_msb8[x >> 8];
  int m = (int)((e >= 10 ? (x >> (e - 10)) : (x << (10 - e))) & 0x3FF);
  return (int)(((long long)e * 45427 + 128) >> 8) + ml_ln_mant_q8[m];
}
static inline __attribute__((always_inline)) int feature_linear(const struct cand *c, int f) {
  switch (f) {
  case ML_F_REF: return c->seen ? 256 : 0;
  case ML_F_AGING: return ml_aging_q8(c->aging & 0xff);
  case ML_F_SFREQ: return log1p_fast(c->sfreq);
  case ML_F_IDLE: return log1p_fast(now_scan - c->last_seen);
  case ML_F_AGE: return log1p_fast(now_scan - c->load_scan);
  case ML_F_DIRTY: return c->dirty ? 256 : 0;
  case ML_F_REFAULTS: return c->lq_refaults;
  case ML_F_RDIST: return c->lq_rdist;
  }
  return 0;
}

static uint64 rng = 0x9E3779B97F4A7C15ULL;
static uint64 xs(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; }

static void sample(int count, int k) {            // partial Fisher-Yates, as ml_sample in kernel/vmpage.c
  uint64 x = rng;
  for (int i = 0; i < k; i++) {
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    int j = i + (int)(x % (uint64)(count - i));
    struct cand *t = cp[i]; cp[i] = cp[j]; cp[j] = t;
  }
  rng = x;
}

// Page table: the same three-level layout and the same walk() as kernel/vm.c (a PTE holds the next table's address in its upper bits;
// here a host pointer, which is 4096-aligned). Leaf PTEs carry PTE_V, PTE_A and PTE_D. Scattered virtual pages, as a resident set is.
#define PTE_V 1ULL
#define PTE_A (1ULL << 6)
#define PTE_D (1ULL << 7)
#define PX(level, va) (((va) >> (12 + 9 * (level))) & 0x1FF)
static uint64 *root;
static int use_walk;
static uint64 va_of[MAXC];

static uint64 *new_table(void) { uint64 *t; if (posix_memalign((void **)&t, 4096, 4096)) exit(1); memset(t, 0, 4096); return t; }

static uint64 *walk(uint64 *pt, uint64 va) {
  for (int level = 2; level > 0; level--) {
    uint64 *pte = &pt[PX(level, va)];
    if (*pte & PTE_V) pt = (uint64 *)(*pte & ~0xFFFULL);
    else { uint64 *n = new_table(); *pte = (uint64)n | PTE_V; pt = n; }
  }
  return &pt[PX(0, va)];
}

static void build_page_table(void) {
  root = new_table();
  for (int i = 0; i < MAXC; i++) {
    va_of[i] = (0x4000000ULL + (xs() % (4 * MAXC))) << 12;
    uint64 *pte = walk(root, va_of[i]);
    *pte = ((uint64)(i + 1) << 12) | PTE_V | PTE_D;   // frame number = i + 1, never dereferenced
    if (cs[i].seen) *pte |= PTE_A;
  }
}

// What sample_page + the bookkeeping of choose_ml do for each candidate (kernel/vmpage.c): walk, read A and D, update the page's
// counters, clear A.  The page-table walk is the part native_timing.c used to leave out.  Not included: the sfence.vma after the scan.
static void scan_candidates(int count) {
  for (int i = 0; i < count; i++) {
    struct cand *c = cp[i];
    uint64 *pte = walk(root, va_of[c - cs]);
    if (!(*pte & PTE_V) || (*pte & ~0xFFFULL) == 0) continue;
    int accessed = (*pte & PTE_A) != 0;
    c->dirty = (*pte & PTE_D) != 0;
    c->seen = accessed;
    c->aging = ((c->aging & 0xff) >> 1) | (accessed ? 0x80 : 0);
    if (accessed) { c->sfreq++; c->last_seen = now_scan; *pte &= ~PTE_A; }
    *pte |= PTE_A;      // the program touches the page again before the next scan (keeps every timed decision alike)
    c->sfreq &= 0xff; c->last_seen = now_scan - (c->last_seen & 0x7ff);
  }
}

static volatile long sink;
static int cold;
static char *junk;
#define JUNK (16 << 20)
static void churn(void) {            // the program runs between two evictions and pushes the page table and page structs out of the caches
  long t = 0;
  for (long i = 0; i < JUNK; i += 64) { junk[i]++; t += junk[i]; }
  sink += t;
}

static struct cand *decide(int model, int count, int k) {
  const struct vm_ml_weights *w = &ml_default_weights;
  if (k > 0 && count > k) { sample(count, k); count = k; }
  if (use_walk) scan_candidates(count);
  struct cand *victim = 0; long best = 0;
  if (model > 0) {
    for (int i = 0; i < count; i++) {
      for (int j = 0; j < 8; j++) mc[i].q[j] = feature(cp[i], j);
      mc[i].aging = cp[i]->aging & 0xff;
    }
    mlnet_score(ml_nets[model], mc, count, sc);
  }
  for (int i = 0; i < count; i++) {
    struct cand *p = cp[i];
    if (now_scan - p->load_scan < (uint64)w->protect_age && 0) continue;
    long score = 0;
    if (model > 0) score = (long)sc[i];
    else if (new_code) for (int j = 0; j < w->n; j++) score += (long)w->qa[j] * feature_linear(p, w->feat[j]);
    else for (int j = 0; j < w->n; j++) score += (long)w->qa[j] * feature(p, w->feat[j]);
    if (!victim || score > best || (score == best && p->load_seq < victim->load_seq)) { victim = p; best = score; }
  }
  return victim;
}

static double now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e9 + t.tv_nsec; }
static int cmpd(const void *a, const void *b) { double x = *(double *)a, y = *(double *)b; return (x > y) - (x < y); }

int main(int argc, char **argv) {
  use_walk = argc > 1 && argv[1][0] != 'v';
  cold = argc > 1 && argv[1][0] == 'c';
  if (cold) { junk = calloc(JUNK, 1); }      // ./native_timing walk : also walk the page table and update the counters for each candidate
  for (int i = 0; i < MAXC; i++) {
    cs[i].load_scan = now_scan - (xs() % 5000); cs[i].last_seen = now_scan - (xs() % 3000); cs[i].rdist = xs() % 400;
    cs[i].load_seq = i; cs[i].sfreq = xs() % 50; cs[i].refaults = xs() % 6; cs[i].aging = xs() & 0xff; cs[i].seen = xs() & 1; cs[i].dirty = (xs() % 3) == 0;
    cs[i].lq_refaults = ml_log1p_q8(cs[i].refaults); cs[i].lq_rdist = ml_log1p_q8(cs[i].rdist);
  }
  struct { const char *name; int model; int k; int code; } cfg[] = {
    {"linear score (global)", 0, 0, 1}, {"linear score (global) 32 sampled", 0, 32, 1}, {"linear score (global) 16 sampled", 0, 16, 1},
    {"linear score (global) 64 sampled", 0, 64, 1}, {"linear score (global) 8 sampled", 0, 8, 1}, {"linear score (global) 4 sampled", 0, 4, 1},
    {"linear score (global) [code before the change]", 0, 0, 0}, {"linear score (global) 32 sampled [code before the change]", 0, 32, 0},
    {"linear score (global) 16 sampled [code before the change]", 0, 16, 0},
    {"boosted trees", 10, 0, 1}, {"ranking trees", 9, 0, 1}, {"set-attention", 7, 0, 1}, {"CNN", 6, 0, 1}, {"deeper MLP", 8, 0, 1}};
  if (argc > 1 && argv[1][0] == 'v') {     // ./native_timing verify: the code before and after the change must pick the same victim
    long bad = 0, n = 0;
    for (int trial = 0; trial < 20000; trial++) {
      for (int i = 0; i < MAXC; i++) {
        cs[i].load_scan = now_scan - (xs() % 5000); cs[i].last_seen = now_scan - (xs() % 3000); cs[i].rdist = xs() % 100000;
        cs[i].load_seq = i; cs[i].sfreq = xs() % 500; cs[i].refaults = xs() % 60; cs[i].aging = xs() & 0xff; cs[i].seen = xs() & 1; cs[i].dirty = (xs() % 3) == 0;
        cs[i].lq_refaults = ml_log1p_q8(cs[i].refaults); cs[i].lq_rdist = ml_log1p_q8(cs[i].rdist);
      }
      for (int k = 0; k <= 32; k += 32) {
        int cnt = 40 + (int)(xs() % 900);
        uint64 saved = rng; struct cand *v[2];
        for (int code = 0; code < 2; code++) {
          new_code = code; rng = saved;
          for (int i = 0; i < cnt; i++) cp[i] = &cs[i];
          v[code] = decide(0, cnt, k);
        }
        n++; if (v[0] != v[1]) bad++;
      }
    }
    printf("verify: %ld decisions, %ld different victims\n", n, bad);
    return bad != 0;
  }
  build_page_table();
  printf("policy,candidates,decisions_timed,ns_per_decision_median,ns_per_decision_min,ns_per_candidate_median\n");
  int sizes[] = {68, 256};
  for (int s = 0; s < 2; s++)
    for (unsigned c = 0; c < sizeof cfg / sizeof cfg[0]; c++) {
      int n = sizes[s];
      new_code = cfg[c].code;
      int reps = cold ? (cfg[c].model == 8 || cfg[c].model == 6 || cfg[c].model == 7 ? 20 : 60) : cfg[c].model ? (cfg[c].model == 8 || cfg[c].model == 6 || cfg[c].model == 7 ? 300 : 2000) : 20000;
      double batch[25];
      for (int b = 0; b < 25; b++) {
        for (int i = 0; i < n; i++) cp[i] = &cs[i];
        double t0 = now_ns(), spent = 0;
        for (int r = 0; r < reps; r++) {
          if (cold) { churn(); t0 = now_ns(); }
          struct cand *v = decide(cfg[c].model, n, cfg[c].k);
          sink += (long)v->load_seq;
          if (cold) spent += now_ns() - t0;
        }
        batch[b] = cold ? spent / reps : (now_ns() - t0) / reps;
      }
      qsort(batch, 25, sizeof(double), cmpd);
      int scored = cfg[c].k && cfg[c].k < n ? cfg[c].k : n;
      printf("%s%s,%d,%d,%.0f,%.0f,%.1f\n", cfg[c].name, cold ? " + page-table walk (cold caches)" : use_walk ? " + page-table walk" : "", n, 25 * reps, batch[12], batch[0], batch[12] / scored);
    }
  return 0;
}
