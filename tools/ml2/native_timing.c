// Native timing of the kernel's scoring code (S2 of the paper handoff).
//
// Compiles the kernel's own integer scoring headers (kernel/mlfeat.h, kernel/mlnet.h, kernel/mlnets.h) for the host CPU and times one eviction
// decision: compute each candidate's features, score it, pick the best (the same selection loop as choose_ml in kernel/vmpage.c, without the
// kernel-only parts: the page-table walk that reads and clears the accessed bits, the locks, the swap I/O). So it is a lower bound for the
// whole decision. For the sampled variant it includes the partial Fisher-Yates draw of k candidates.
//
//   gcc -O2 -I kernel -o /tmp/native_timing tools/ml2/native_timing.c && taskset -c 2 /tmp/native_timing > report/results2/native_timing.csv
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "kernel/mlfeat.h"
#include "kernel/mlnet.h"
#include "kernel/mlnets.h"
#include "kernel/mlweights.h"

#define MAXC 1024
struct cand { uint64 load_scan, last_seen, rdist, load_seq; uint32 sfreq, refaults; uint32 aging; uint8 seen, dirty; };
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

static volatile long sink;

static struct cand *decide(int model, int count, int k) {
  const struct vm_ml_weights *w = &ml_default_weights;
  if (k > 0 && count > k) { sample(count, k); count = k; }
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
    else for (int j = 0; j < w->n; j++) score += (long)w->qa[j] * feature(p, w->feat[j]);
    if (!victim || score > best || (score == best && p->load_seq < victim->load_seq)) { victim = p; best = score; }
  }
  return victim;
}

static double now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e9 + t.tv_nsec; }
static int cmpd(const void *a, const void *b) { double x = *(double *)a, y = *(double *)b; return (x > y) - (x < y); }

int main(void) {
  for (int i = 0; i < MAXC; i++) {
    cs[i].load_scan = now_scan - (xs() % 5000); cs[i].last_seen = now_scan - (xs() % 3000); cs[i].rdist = xs() % 400;
    cs[i].load_seq = i; cs[i].sfreq = xs() % 50; cs[i].refaults = xs() % 6; cs[i].aging = xs() & 0xff; cs[i].seen = xs() & 1; cs[i].dirty = (xs() % 3) == 0;
  }
  struct { const char *name; int model; int k; } cfg[] = {
    {"linear score (global)", 0, 0}, {"linear score (global) 32 sampled", 0, 32}, {"linear score (global) 16 sampled", 0, 16},
    {"boosted trees", 10, 0}, {"ranking trees", 9, 0}, {"set-attention", 7, 0}, {"CNN", 6, 0}, {"deeper MLP", 8, 0}};
  printf("policy,candidates,decisions_timed,ns_per_decision_median,ns_per_decision_min,ns_per_candidate_median\n");
  int sizes[] = {68, 256};
  for (int s = 0; s < 2; s++)
    for (unsigned c = 0; c < sizeof cfg / sizeof cfg[0]; c++) {
      int n = sizes[s];
      int reps = cfg[c].model ? (cfg[c].model == 8 || cfg[c].model == 6 || cfg[c].model == 7 ? 300 : 2000) : 20000;
      double batch[25];
      for (int b = 0; b < 25; b++) {
        for (int i = 0; i < n; i++) cp[i] = &cs[i];
        double t0 = now_ns();
        for (int r = 0; r < reps; r++) {
          struct cand *v = decide(cfg[c].model, n, cfg[c].k);
          sink += (long)v->load_seq;
        }
        batch[b] = (now_ns() - t0) / reps;
      }
      qsort(batch, 25, sizeof(double), cmpd);
      int scored = cfg[c].k && cfg[c].k < n ? cfg[c].k : n;
      printf("%s,%d,%d,%.0f,%.0f,%.1f\n", cfg[c].name, n, 25 * reps, batch[12], batch[0], batch[12] / scored);
    }
  return 0;
}
