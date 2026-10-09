// Host-side page-replacement simulator for the traces2/ ML study.
//
// Replays one reference stream (dense page ids 0..n_pages-1, a write flag and
// the Belady next-use distance per reference) at a fixed number of frames,
// starting from empty memory, and counts faults, evictions and page writes.
//
// Classical policies mirror kernel/vmpage.c, including the kernel's accessed/
// dirty-bit semantics: a page faulted in has PTE_A set (and PTE_D on a write
// fault, kernel/vm.c), hits set A (and D on writes), and a scan reads and
// clears A. That differs from tools/sim.py, whose Clock/Aging start a new page
// unreferenced.
//
// Learned policies score every resident candidate at each eviction from a
// chosen subset of NF features and evict the highest predicted next-use.
// The same pass can record every candidate's features at sampled evictions,
// labelled with its true next-use distance, as training data.
//
// Build: see tools/ml2/pagesim.py (compiled on first use).
#include <math.h>
#include <stdint.h>
#include "../../kernel/mlfeat.h"   // the kernel's own integer features
#include "../../kernel/mlnet.h"    // the kernel's own integer networks / trees
#include <stdlib.h>
#include <string.h>

#define NEVER 0xFFFFFFFFu
#define INF_T INT64_MAX
#define LABEL_CAP (1 << 20)

enum policy {
  P_FIFO, P_CLOCK, P_AGING, P_LRU, P_LFU_EXACT, P_LFU_KERNEL, P_BELADY,
  P_LEARNED, P_SD_OLD, P_GRU, P_EMBED,
  // list-based and reference policies (pagesim.py POLICIES keeps this order)
  P_MRU, P_ARC, P_S3FIFO, P_S3SCAN, P_MGLRU, P_LHD,
};

// Feature layout of every recorded / scored candidate row.
enum feature {
  // F: full-stream (needs every access; not observable by a kernel)
  F_REC,      // references since the page's last access
  F_FREQ,     // exact number of accesses so far
  F_SD,       // stack distance: distinct pages accessed since its last access
  F_WR,       // exact fraction of its accesses that were writes
  // K: observable by a kernel at an eviction scan (accessed/dirty bits)
  K_REF,      // accessed bit seen at this scan
  K_AGING,    // 8-bit aging counter (as choose_aging), /255
  K_SFREQ,    // number of scans that found it accessed since it was loaded
  K_IDLE,     // scans since it was last seen accessed
  K_AGE,      // scans since it was loaded
  K_DIRTY,    // dirty bit
  // K+: cheap kernel bookkeeping Linux already does (mm/workingset.c)
  K_REFAULTS, // times this page was evicted and faulted back in
  K_RDIST,    // evictions between its last eviction and refault
  NF,
};

#define MAXL 6      // max MLP layers
#define GRU_K 8     // interval-history length for the GRU scorer
#define EMB_W 16    // global context window for the embedding scorer
#define MAXB 256    // candidates per block in the batched MLP scorer

struct model {
  int kind;                 // 0 = MLP (linear is a 1-layer MLP)
  int n_in;
  int feat[NF];             // indices into the NF feature row
  float mean[NF], std[NF];  // input standardisation
  int n_layers;
  int sizes[MAXL + 1];      // sizes[0] = n_in ... sizes[n_layers] = 1
  const float *w;           // per layer: W[out][in] then b[out]
  // GRU scorer (policy P_GRU): input 1, hidden H, head takes [h, log1p(rec)]
  int gru_h;
  const float *gru_w;       // W_ih[3H][1], W_hh[3H][H], b_ih[3H], b_hh[3H]
  const float *head_w;      // MLP over H+1 inputs, same layout as w
  int head_layers;
  int head_sizes[MAXL + 1];
  // embedding scorer (P_EMBED): E[n_pages+1][D]; GRU over window; head
  int emb_d;
  const float *emb;
  // Integer-only linear scoring, as a kernel without floating point would do
  // it: features in Q8 fixed point (round(f * 256), what an integer log1p
  // table would hold), weights with the standardisation folded in and
  // rounded to integers qa[j] = round(W[j] / std[j] * 2^quant_w). The mean
  // and bias terms are the same for every candidate, so they are dropped.
  int quant_w;              // 0 = float scoring
  int32_t qa[NF];
  // Probation: a candidate loaded fewer than protect_age scans ago is not
  // evicted while any older one exists (Clock's second chance for a new
  // page, applied to a learned score). 0 = off.
  int protect_age;
  // Sampled scoring (like cache_ext's bpf_cache_ext_list_sample): each eviction
  // considers only sample_k random residents instead of all of them.
  // sample_scan = 0: every resident is still scanned (A bit read and cleared,
  // features updated), only the scoring is sampled. sample_scan = 1: only the
  // sampled pages are scanned, so the scan-driven features (idle, aging, sfreq)
  // of the others go stale. sample_k = 0 turns sampling off.
  int sample_k;
  int sample_scan;
  int sample_seed;
  // Callback scorer (kind 3): cb(n, feat[n][NF], hist[n][GRU_K], out[n]) scores
  // the whole candidate set at once (set / sequence models run in Python).
  void *cb;
  // Tree ensemble (kind 4): score = base + sum of trees. Node f < 0 is a leaf
  // (value in thr); f in [0, NF) tests the raw feature, f in [NF, 2NF) tests the
  // candidate's percentile rank of feature f - NF within the candidate set.
  int tree_n; float tree_base;
  const int32_t *tree_root, *nd_l, *nd_r; const int16_t *nd_f; const float *nd_t;
  uint32_t raw_mask, rank_mask;
  // Integer network (kind 5): evaluated by kernel/mlnet.h on the kernel's own Q8 features.
  const struct mlnet *net;
  // Optional log of every eviction: victim page id and candidate count (2 ints per eviction).
  int32_t *vlog; int64_t vlog_cap, vlog_n;
};

struct result {
  int64_t faults, evictions, writebacks;
  int64_t rows, overflow;
  int64_t aborted;          // stopped early: faults exceeded max_faults
  int64_t scanned, scored;  // pages scanned / scored, summed over evictions
};

struct recorder {
  double p;                 // probability an eviction is recorded
  uint64_t rng;
  int max_cand;             // record at most this many candidates per eviction
                            // (Belady's choice + a random subset); 0 = all
  int64_t cap;              // row capacity of the buffers
  float *feat;              // [cap][NF]
  float *label;             // [cap]  log1p(next-use distance), capped
  int32_t *group;           // [cap]  eviction id
  uint8_t *is_opt;          // [cap]  1 if Belady would evict this candidate
  // GRU/embedding training inputs (optional; NULL to skip)
  float *hist;              // [cap][GRU_K] past intervals, oldest first
  int32_t *page;            // [cap] candidate dense page id
  int32_t *ctx;             // [cap][EMB_W] last EMB_W pages referenced
  int n_recent;             // when subsampling, always keep this many of the
                            // most recently accessed candidates too
};

// log1p of a non-negative integer count, from a table for small values.
#define LUT_N (1 << 16)
static float lut[LUT_N];
static int lut_ready;
static void lut_init(void) {
  if (lut_ready) return;
  for (int i = 0; i < LUT_N; i++) lut[i] = log1pf((float)i);
  lut_ready = 1;
}
static inline float lg(int64_t v) {
  return v < LUT_N ? lut[v] : log1pf((float)v);
}

static uint64_t xs(uint64_t *s) {
  uint64_t x = *s;
  x ^= x << 13; x ^= x >> 7; x ^= x << 17;
  return *s = x;
}

// ---- Fenwick tree over reference positions (stack distance) --------------
static void bit_add(int32_t *t, int64_t n, int64_t i, int d) {
  for (i++; i <= n; i += i & -i) t[i] += d;
}
static int64_t bit_sum(const int32_t *t, int64_t i) {  // sum of [0, i]
  int64_t s = 0;
  for (i++; i > 0; i -= i & -i) s += t[i];
  return s;
}

static float mlp_forward(int n_layers, const int *sizes, const float *w,
                         const float *x) {
  float a[64], b[64];
  memcpy(a, x, sizeof(float) * sizes[0]);
  for (int l = 0; l < n_layers; l++) {
    int ni = sizes[l], no = sizes[l + 1];
    const float *W = w, *B = w + no * ni;
    for (int o = 0; o < no; o++) {
      float s = B[o];
      for (int i = 0; i < ni; i++) s += W[o * ni + i] * a[i];
      b[o] = (l + 1 < n_layers && s < 0) ? 0 : s;  // ReLU except last
    }
    w = B + no;
    memcpy(a, b, sizeof(float) * no);
  }
  return a[0];
}

static float sigm(float x) { return 1.0f / (1.0f + expf(-x)); }

// One GRU step, PyTorch gate order (r, z, n). x has n_x entries.
static void gru_step(int H, int n_x, const float *gw, const float *x,
                     float *h) {
  const float *Wih = gw, *Whh = gw + 3 * H * n_x, *bih = Whh + 3 * H * H,
              *bhh = bih + 3 * H;
  float gi[3 * 64], gh[3 * 64], hn[64];
  for (int g = 0; g < 3 * H; g++) {
    float s = bih[g], t = bhh[g];
    for (int i = 0; i < n_x; i++) s += Wih[g * n_x + i] * x[i];
    for (int i = 0; i < H; i++) t += Whh[g * H + i] * h[i];
    gi[g] = s; gh[g] = t;
  }
  for (int j = 0; j < H; j++) {
    float r = sigm(gi[j] + gh[j]);
    float z = sigm(gi[H + j] + gh[H + j]);
    float n = tanhf(gi[2 * H + j] + r * gh[2 * H + j]);
    hn[j] = (1 - z) * n + z * h[j];
  }
  memcpy(h, hn, sizeof(float) * H);
}

struct state {
  int64_t n; int n_pages, cap;
  const uint32_t *pg; const uint8_t *wr; const uint32_t *nu;
  int32_t *pos, *res; int count;
  int64_t *last_acc, *load_seq, *nxt, *load_scan, *last_seen, *evicted_at;
  int64_t *rdist, *last_distinct;
  uint32_t *freq, *writes, *sfreq, *kfreq, *refaults;
  uint8_t *abit, *dbit, *aging, *has_copy, *seen_now;
  float *hist;          // [n_pages][GRU_K] last intervals (log1p), newest last
  float *gru_cache;     // [n_pages][H] GRU state over hist (P_GRU)
  uint8_t *gru_dirty;
  int32_t *bit;
  int64_t bit_now;      // bit_sum(t - 1) at the current eviction
  int64_t seq, scans, distinct_seen;
  int32_t *order; int order_n; int64_t hand;   // Clock candidate list
  int32_t ring[EMB_W]; int ring_i;             // last EMB_W pages referenced
  uint64_t srng; int32_t *samp;                // sampled-scoring rng / chosen indices
  // doubly linked lists over page ids (ARC, S3-FIFO); head = MRU / newest
  int32_t *lnx, *lpv; int8_t *lin; int32_t lhead[4], ltail[4]; int llen[4];
  int arc_p;                                   // ARC target size of T1
  uint8_t *s3freq, *s3fresh;                   // S3-FIFO per-page counter / "ignore load touch"
  int s3_small_cap, s3_main_cap;
  // MGLRU (generations): gen[p] = sequence number, gst[p] = order within it
  int64_t *gen, *gst; int gcnt[4]; int64_t gmin, gmax, gctr;
  // LHD (scan form): hit ages of the last two hits, per-class age histograms
  int32_t *la1, *la2;
  int64_t lh[16][256], le[16][256], ld[16][256]; int lshift; int64_t lnev, lrec;
};

static float feature(const struct state *s, int p, int64_t t, int f) {
  switch (f) {
  case F_REC: return lg(t - s->last_acc[p]);
  case F_FREQ: return lg(s->freq[p]);
  case F_SD: {
    int64_t d = s->bit_now - bit_sum(s->bit, s->last_acc[p]);
    return lg(d);
  }
  case F_WR: return s->freq[p] ? (float)s->writes[p] / s->freq[p] : 0;
  case K_REF: return s->seen_now[p];
  case K_AGING: return s->aging[p] / 255.0f;
  case K_SFREQ: return lg(s->sfreq[p]);
  case K_IDLE: return lg(s->scans - s->last_seen[p]);
  case K_AGE: return lg(s->scans - s->load_scan[p]);
  case K_DIRTY: return s->dbit[p];
  case K_REFAULTS: return lg(s->refaults[p]);
  case K_RDIST: return lg(s->rdist[p]);
  }
  return 0;
}

// Kernel-style full scan of every candidate: read and clear A, update the
// aging counter, the sampled counts and the decayed LFU counter exactly as
// sample_page() + choose_aging()/choose_lfu() would.
static void scan_one(struct state *s, int p) {
  int a = s->abit[p];
  s->seen_now[p] = a;
  s->aging[p] = (s->aging[p] >> 1) | (a ? 0x80 : 0);
  if (a) {
    s->sfreq[p]++;
    s->last_seen[p] = s->scans;
    s->kfreq[p]++;                         // sample_page()'s frequency++
  }
  s->kfreq[p] = (s->kfreq[p] >> 1) + (a ? 1 : 0);  // choose_lfu decay
  s->abit[p] = 0;
}

static void scan_all(struct state *s) {
  for (int k = 0; k < s->count; k++) scan_one(s, s->res[k]);
}

static int argmax_by(const struct state *s, const double *score) {
  int best = 0;
  for (int k = 1; k < s->count; k++) {
    int p = s->res[k], q = s->res[best];
    if (score[k] > score[best] ||
        (score[k] == score[best] && s->load_seq[p] < s->load_seq[q]))
      best = k;
  }
  return best;
}

static void gru_refresh(struct state *s, const struct model *m, int p) {
  float *h = s->gru_cache + (int64_t)p * m->gru_h;
  memset(h, 0, sizeof(float) * m->gru_h);
  for (int j = 0; j < GRU_K; j++)
    gru_step(m->gru_h, 1, m->gru_w, &s->hist[(int64_t)p * GRU_K + j], h);
  s->gru_dirty[p] = 0;
}

// A feature in Q8 fixed point exactly as kernel/vmpage.c computes it
// (kernel/mlfeat.h). Full-stream features have no kernel form; they are
// rounded from the float value.
static int64_t feature_q8(const struct state *s, int p, int64_t t, int f) {
  switch (f) {
  case K_REF: return s->seen_now[p] ? 256 : 0;
  case K_AGING: return ml_aging_q8(s->aging[p]);
  case K_SFREQ: return ml_log1p_q8(s->sfreq[p]);
  case K_IDLE: return ml_log1p_q8((uint64_t)(s->scans - s->last_seen[p]));
  case K_AGE: return ml_log1p_q8((uint64_t)(s->scans - s->load_scan[p]));
  case K_DIRTY: return s->dbit[p] ? 256 : 0;
  case K_REFAULTS: return ml_log1p_q8(s->refaults[p]);
  case K_RDIST: return ml_log1p_q8((uint64_t)s->rdist[p]);
  }
  return lrintf(feature(s, p, t, f) * 256.0f);
}

static double score_one(struct state *s, const struct model *m, int p,
                        int64_t t, const float *ctx_h) {
  float x[NF + 64];
  if (m->kind == 0 && m->quant_w > 0) {
    int64_t acc = 0;
    for (int j = 0; j < m->n_in; j++)
      acc += (int64_t)m->qa[j] * feature_q8(s, p, t, m->feat[j]);
    return (double)acc;
  }
  if (m->kind == 0) {
    for (int j = 0; j < m->n_in; j++) {
      int f = m->feat[j];
      x[j] = (feature(s, p, t, f) - m->mean[j]) / m->std[j];
    }
    return mlp_forward(m->n_layers, m->sizes, m->w, x);
  }
  if (m->kind == 1) {  // GRU over the page's own interval history
    if (s->gru_dirty[p]) gru_refresh(s, m, p);
    memcpy(x, s->gru_cache + (int64_t)p * m->gru_h, sizeof(float) * m->gru_h);
    x[m->gru_h] = (feature(s, p, t, F_REC) - m->mean[0]) / m->std[0];
    return mlp_forward(m->head_layers, m->head_sizes, m->head_w, x);
  }
  // kind 2: embedding -- [GRU(global context), E[p]]
  memcpy(x, ctx_h, sizeof(float) * m->gru_h);
  memcpy(x + m->gru_h, m->emb + (int64_t)p * m->emb_d,
         sizeof(float) * m->emb_d);
  return mlp_forward(m->head_layers, m->head_sizes, m->head_w, x);
}

// Percentile rank of x[i] among the n candidates' values of one feature:
// (#less + 0.5 * (#equal - 1)) / (n - 1), 0.5 when n == 1.
static int cmpf(const void *a, const void *b) {
  float x = *(const float *)a, y = *(const float *)b;
  return x < y ? -1 : x > y;
}
static void rank_column(const float *X, int n, int f, float *out) {
  static float *srt; static int cap_s;
  if (n > cap_s) { cap_s = n; srt = realloc(srt, sizeof(float) * cap_s); }
  for (int i = 0; i < n; i++) srt[i] = X[(int64_t)i * NF + f];
  qsort(srt, n, sizeof(float), cmpf);
  for (int i = 0; i < n; i++) {
    float v = X[(int64_t)i * NF + f];
    int lo = 0, hi = n;                         // first index with srt >= v
    while (lo < hi) { int mid = (lo + hi) / 2; if (srt[mid] < v) lo = mid + 1; else hi = mid; }
    int less = lo;
    hi = n;                                     // first index with srt > v
    while (lo < hi) { int mid = (lo + hi) / 2; if (srt[mid] <= v) lo = mid + 1; else hi = mid; }
    int eq = lo - less;
    out[i] = n > 1 ? (less + 0.5f * (eq - 1)) / (n - 1) : 0.5f;
  }
}

static void tree_scores(const struct model *m, const float *X, int n, float *out) {
  static float *R; static int cap_r;
  if ((int64_t)n * NF > cap_r) { cap_r = n * NF; R = realloc(R, sizeof(float) * cap_r); }
  static float col[1 << 16];
  for (int f = 0; f < NF; f++)
    if (m->rank_mask >> f & 1) {
      float *c = n <= (1 << 16) ? col : malloc(sizeof(float) * n);
      rank_column(X, n, f, c);
      for (int i = 0; i < n; i++) R[(int64_t)i * NF + f] = c[i];
      if (c != col) free(c);
    }
  for (int i = 0; i < n; i++) {
    float acc = m->tree_base;
    for (int t = 0; t < m->tree_n; t++) {
      int k = m->tree_root[t];
      while (m->nd_f[k] >= 0) {
        int f = m->nd_f[k];
        float v = f < NF ? X[(int64_t)i * NF + f] : R[(int64_t)i * NF + f - NF];
        k = v <= m->nd_t[k] ? m->nd_l[k] : m->nd_r[k];
      }
      acc += m->nd_t[k];
    }
    out[i] = acc;
  }
}

typedef void (*cand_cb)(int n, const float *feat, const float *hist, float *out);

static int choose(struct state *s, int policy, const struct model *m,
                  int64_t t, double *score) {
  switch (policy) {
  case P_FIFO: case P_AGING: case P_LFU_KERNEL: case P_LFU_EXACT:
  case P_LRU: case P_BELADY: case P_SD_OLD: case P_MRU:
    for (int k = 0; k < s->count; k++) {
      int p = s->res[k];
      switch (policy) {
      case P_FIFO: score[k] = 0; break;           // tie-break = oldest load
      case P_AGING: score[k] = -(double)s->aging[p]; break;
      case P_LFU_KERNEL: score[k] = -(double)s->kfreq[p]; break;
      case P_LFU_EXACT: score[k] = -(double)s->freq[p]; break;
      case P_LRU: score[k] = (double)(t - s->last_acc[p]); break;
      case P_MRU: score[k] = (double)(s->last_acc[p]); break;
      case P_BELADY:
        score[k] = s->nxt[p] == INF_T ? INFINITY : (double)(s->nxt[p] - t);
        break;
      case P_SD_OLD:  // the old tools/sim.py StackDistance, kept for the record
        score[k] = (double)(s->distinct_seen - s->last_distinct[p]);
        break;
      }
    }
    if (policy == P_LRU || policy == P_BELADY || policy == P_MRU) {  // exact: no float ties
      int best = 0;
      for (int k = 1; k < s->count; k++) {
        int p = s->res[k], q = s->res[best];
        int64_t a = policy == P_LRU ? -s->last_acc[p] : policy == P_MRU ? s->last_acc[p] : s->nxt[p];
        int64_t b = policy == P_LRU ? -s->last_acc[q] : policy == P_MRU ? s->last_acc[q] : s->nxt[q];
        if (a > b) best = k;
      }
      return best;
    }
    return argmax_by(s, score);
  default: {  // learned
    float ctx_h[64];
    if (m->kind == 2) {
      memset(ctx_h, 0, sizeof(ctx_h));
      for (int j = 0; j < EMB_W; j++) {
        int q = s->ring[(s->ring_i + j) % EMB_W];
        gru_step(m->gru_h, m->emb_d, m->gru_w,
                 m->emb + (int64_t)(q < 0 ? s->n_pages : q) * m->emb_d, ctx_h);
      }
    }
    int any_old = 0;
    if (m->kind == 5) {
      static struct mlcand *CD; static long long *CO; static int cap_c;
      int n = s->count;
      if (n > cap_c) {
        cap_c = n;
        CD = realloc(CD, sizeof(struct mlcand) * n);
        CO = realloc(CO, sizeof(long long) * n);
      }
      for (int k = 0; k < n; k++) {
        int p = s->res[k];
        for (int j = 0; j < 8; j++) CD[k].q[j] = (int)feature_q8(s, p, t, 4 + j);
        CD[k].aging = s->aging[p];
      }
      mlnet_score(m->net, CD, n, CO);
      for (int k = 0; k < n; k++) {
        score[k] = (double)CO[k];
        if (m->protect_age && s->scans - s->load_scan[s->res[k]] >= m->protect_age)
          any_old = 1;
      }
    } else
    if (m->kind == 3 || m->kind == 4) {
      static float *X, *H, *O; static int cap_x;
      int n = s->count;
      if (n > cap_x) {
        cap_x = n;
        X = realloc(X, sizeof(float) * (int64_t)n * NF);
        H = realloc(H, sizeof(float) * (int64_t)n * GRU_K);
        O = realloc(O, sizeof(float) * n);
      }
      uint32_t need = m->kind == 3 ? 0xFFFFFFFFu : (m->raw_mask | m->rank_mask);
      for (int k = 0; k < n; k++) {
        int p = s->res[k];
        for (int f = 0; f < NF; f++)
          X[(int64_t)k * NF + f] = (need >> f & 1) ? feature(s, p, t, f) : 0.0f;
        if (m->kind == 3) memcpy(H + (int64_t)k * GRU_K, s->hist + (int64_t)p * GRU_K,
                                 sizeof(float) * GRU_K);
      }
      if (m->kind == 3) ((cand_cb)m->cb)(n, X, H, O);
      else tree_scores(m, X, n, O);
      for (int k = 0; k < n; k++) {
        score[k] = O[k];
        if (m->protect_age && s->scans - s->load_scan[s->res[k]] >= m->protect_age)
          any_old = 1;
      }
    } else
    if (m->kind == 0 && m->n_layers > 1 && !m->quant_w) {
      // MLP over all candidates at once, candidates innermost so the loop
      // vectorises. Each candidate's sums are accumulated in the same order
      // as mlp_forward(), so the scores are bit-identical to it.
      static float A[MAXB * 64], Bv[MAXB * 64];
      int n = s->count;
      for (int k0 = 0; k0 < n; k0 += MAXB) {
        int nb = n - k0 < MAXB ? n - k0 : MAXB;
        for (int j = 0; j < m->n_in; j++)
          for (int k = 0; k < nb; k++)
            A[j * MAXB + k] = (feature(s, s->res[k0 + k], t, m->feat[j]) - m->mean[j]) /
                              m->std[j];
        const float *w = m->w;
        float *a = A, *b = Bv;
        for (int l = 0; l < m->n_layers; l++) {
          int ni = m->sizes[l], no = m->sizes[l + 1];
          const float *W = w, *B = w + no * ni;
          for (int o = 0; o < no; o++) {
            float *acc = b + o * MAXB;
            for (int k = 0; k < nb; k++) acc[k] = B[o];
            for (int i = 0; i < ni; i++) {
              float wi = W[o * ni + i];
              const float *ai = a + i * MAXB;
              for (int k = 0; k < nb; k++) acc[k] += wi * ai[k];
            }
            if (l + 1 < m->n_layers)
              for (int k = 0; k < nb; k++) acc[k] = acc[k] < 0 ? 0 : acc[k];
          }
          w = B + no;
          float *tmp = a; a = b; b = tmp;
        }
        for (int k = 0; k < nb; k++) score[k0 + k] = a[k];
      }
      for (int k = 0; k < n; k++)
        if (m->protect_age && s->scans - s->load_scan[s->res[k]] >= m->protect_age)
          any_old = 1;
    } else
    for (int k = 0; k < s->count; k++) {
      score[k] = score_one(s, m, s->res[k], t, ctx_h);
      if (m->protect_age && s->scans - s->load_scan[s->res[k]] >= m->protect_age)
        any_old = 1;
    }
    if (m->protect_age && any_old)
      for (int k = 0; k < s->count; k++)
        if (s->scans - s->load_scan[s->res[k]] < m->protect_age) score[k] = -INFINITY;
    return argmax_by(s, score);
  }
  }
}

// Draw k distinct resident indices (partial Fisher-Yates) into s->samp.
static void draw_sample(struct state *s, int k) {
  for (int i = 0; i < s->count; i++) s->samp[i] = i;
  for (int i = 0; i < k; i++) {
    int j = i + (int)(xs(&s->srng) % (uint64_t)(s->count - i));
    int32_t tmp = s->samp[i]; s->samp[i] = s->samp[j]; s->samp[j] = tmp;
  }
}

// choose() restricted to the k sampled candidates in s->samp[0..k-1]: same
// score, same probation (among the sampled), same tie-break (oldest load).
static int choose_sampled(struct state *s, const struct model *m, int64_t t, int k) {
  int any_old = 0;
  for (int i = 0; i < k; i++)
    if (m->protect_age && s->scans - s->load_scan[s->res[s->samp[i]]] >= m->protect_age)
      any_old = 1;
  int best = -1;
  double best_score = 0;
  for (int i = 0; i < k; i++) {
    int idx = s->samp[i], p = s->res[idx];
    if (any_old && s->scans - s->load_scan[p] < m->protect_age) continue;
    double sc = score_one(s, m, p, t, NULL);
    if (best < 0 || sc > best_score ||
        (sc == best_score && s->load_seq[p] < s->load_seq[s->res[best]])) {
      best = idx; best_score = sc;
    }
  }
  return best;
}

static int clock_choose(struct state *s) {
  // choose_clock(): hand advances over the candidate list; a referenced
  // candidate has A cleared and is skipped, at most two sweeps.
  int n = s->order_n;
  for (int scanned = 0; scanned < 2 * n; scanned++) {
    int idx = (int)(s->hand++ % n);
    int p = s->order[idx];
    if (!s->abit[p]) return idx;
    s->abit[p] = 0;
  }
  return (int)(s->hand++ % n);
}

// ---- doubly linked lists over page ids ---------------------------------------
enum { L_T1, L_T2, L_B1, L_B2 };        // ARC; S3-FIFO uses L_T1=small, L_T2=main, L_B1=ghost

static void dl_remove(struct state *s, int p) {
  int l = s->lin[p];
  if (l < 0) return;
  int a = s->lpv[p], b = s->lnx[p];
  if (a >= 0) s->lnx[a] = b; else s->lhead[l] = b;
  if (b >= 0) s->lpv[b] = a; else s->ltail[l] = a;
  s->llen[l]--; s->lin[p] = -1;
}

static void dl_push_head(struct state *s, int l, int p) {
  s->lpv[p] = -1; s->lnx[p] = s->lhead[l];
  if (s->lhead[l] >= 0) s->lpv[s->lhead[l]] = p; else s->ltail[l] = p;
  s->lhead[l] = p; s->lin[p] = (int8_t)l; s->llen[l]++;
}

// ---- ARC (Megiddo & Modha, FAST 2003), integer adaptation steps ---------------
// Called on every fault; returns the page to evict (-1 if the cache is not
// full) and puts p into T1 or T2. Hits go through arc_hit().
static void arc_hit(struct state *s, int p) {
  dl_remove(s, p); dl_push_head(s, L_T2, p);
}

static int arc_replace(struct state *s, int in_b2) {
  int c = s->cap, v;
  if (s->llen[L_T1] >= 1 && ((in_b2 && s->llen[L_T1] == s->arc_p) || s->llen[L_T1] > s->arc_p)) {
    v = s->ltail[L_T1]; dl_remove(s, v); dl_push_head(s, L_B1, v);
  } else {
    v = s->ltail[L_T2]; dl_remove(s, v); dl_push_head(s, L_B2, v);
  }
  (void)c;
  return v;
}

static int arc_fault(struct state *s, int p) {
  int c = s->cap, v = -1, w = s->lin[p];
  if (w == L_B1) {
    int d = s->llen[L_B1] >= s->llen[L_B2] ? 1 : s->llen[L_B2] / s->llen[L_B1];
    s->arc_p = s->arc_p + d < c ? s->arc_p + d : c;
    v = arc_replace(s, 0);
    dl_remove(s, p); dl_push_head(s, L_T2, p);
  } else if (w == L_B2) {
    int d = s->llen[L_B2] >= s->llen[L_B1] ? 1 : s->llen[L_B1] / s->llen[L_B2];
    s->arc_p = s->arc_p - d > 0 ? s->arc_p - d : 0;
    v = arc_replace(s, 1);
    dl_remove(s, p); dl_push_head(s, L_T2, p);
  } else {
    int l1 = s->llen[L_T1] + s->llen[L_B1];
    int tot = l1 + s->llen[L_T2] + s->llen[L_B2];
    if (l1 == c) {
      if (s->llen[L_T1] < c) { dl_remove(s, s->ltail[L_B1]); v = arc_replace(s, 0); }
      else { v = s->ltail[L_T1]; dl_remove(s, v); }
    } else if (tot >= c) {
      if (tot == 2 * c) dl_remove(s, s->ltail[L_B2]);
      v = arc_replace(s, 0);
    }
    dl_push_head(s, L_T1, p);
  }
  return v;
}

// ---- S3-FIFO (Yang et al., SOSP 2023) -----------------------------------------
// small queue (10% of the cache), main queue, ghost queue (main's size).
// per-access form: a hit adds 1 to the page's counter (cap 3).
// scan form: the counter is raised from the accessed bit when a page reaches a
// queue head (what a kernel that only scans A bits can do); the touch that
// loaded the page is ignored, as the original starts new objects at 0.
static void s3_examine(struct state *s, int p, int scan) {
  if (!scan) return;
  if (s->s3fresh[p]) { s->s3fresh[p] = 0; s->abit[p] = 0; return; }
  if (s->abit[p]) { if (s->s3freq[p] < 3) s->s3freq[p]++; s->abit[p] = 0; }
}

static int s3_evict_main(struct state *s, int scan) {
  for (;;) {
    int t = s->ltail[L_T2];
    s3_examine(s, t, scan);
    if (s->s3freq[t] > 0) { s->s3freq[t]--; dl_remove(s, t); dl_push_head(s, L_T2, t); }
    else { dl_remove(s, t); return t; }
  }
}

static int s3_evict(struct state *s, int scan) {
  if (s->llen[L_T1] * 10 >= s->cap || s->llen[L_T2] == 0) {
    while (s->llen[L_T1] > 0) {
      int t = s->ltail[L_T1];
      s3_examine(s, t, scan);
      dl_remove(s, t);
      if (s->s3freq[t] > 1) {
        dl_push_head(s, L_T2, t);
        if (s->llen[L_T2] > s->s3_main_cap) return s3_evict_main(s, scan);
      } else {
        dl_push_head(s, L_B1, t);
        if (s->llen[L_B1] > s->s3_main_cap) dl_remove(s, s->ltail[L_B1]);
        return t;
      }
    }
  }
  return s3_evict_main(s, scan);
}

static int s3_fault(struct state *s, int p, int scan) {
  int v = -1;
  if (s->count >= s->cap) v = s3_evict(s, scan);
  int ghost = s->lin[p] == L_B1;       // after evicting, as in the paper (the eviction can trim p)
  s->s3freq[p] = 0; s->s3fresh[p] = 1;
  if (ghost) { dl_remove(s, p); dl_push_head(s, L_T2, p); }
  else dl_push_head(s, L_T1, p);
  return v;
}

static void s3_hit(struct state *s, int p) {
  if (s->s3freq[p] < 3) s->s3freq[p]++;
}

// ---- MGLRU analogue for anonymous memory --------------------------------------
// Linux's multi-generational LRU as a kernel that only reads accessed bits sees
// it: up to 4 generations (>= 2 kept), new pages join the youngest; an aging
// walk (run only when too few older generations remain, rules from
// cache_ext's eBPF port) opens a new youngest generation and promotes every
// page found accessed into it; eviction takes the oldest page of the oldest
// generation and rescues it into the youngest if its accessed bit is set.
// (Tiers and the refault PID controller apply to file pages accessed through
// read/write; anonymous pages have a single tier, so they are not modelled.)
#define MG_MIN_GENS 2
#define MG_MAX_GENS 4
static inline int gi(int64_t q) { return (int)(q & 3); }

static void mg_move(struct state *s, int p, int64_t to) {
  if (s->gen[p] >= 0) s->gcnt[gi(s->gen[p])]--;
  s->gen[p] = to; s->gcnt[gi(to)]++; s->gst[p] = ++s->gctr;
}

static void mg_retire(struct state *s) {
  while (s->gcnt[gi(s->gmin)] == 0 && s->gmin < s->gmax) s->gmin++;
}

static int mg_should_age(struct state *s) {
  int64_t n = s->gmax - s->gmin + 1;
  if (n <= MG_MIN_GENS) return 1;
  if (n >= MG_MAX_GENS) return 0;
  int total = 0;
  for (int64_t q = s->gmin; q <= s->gmax; q++) total += s->gcnt[gi(q)];
  int young = s->gcnt[gi(s->gmax)], old = s->gcnt[gi(s->gmax - MG_MIN_GENS)];
  return young * MG_MIN_GENS > total || old * (MG_MIN_GENS + 2) < total;
}

static void mg_age(struct state *s) {
  if (s->gmax - s->gmin + 1 == MG_MAX_GENS) {
    if (s->gcnt[gi(s->gmin)] != 0) return;      // the oldest generation is still in use
    s->gmin++;
  }
  s->gmax++;
  // promote the accessed pages together, keeping their relative order (oldest
  // first), so the result does not depend on the resident array's layout
  int m = 0;
  for (int k = 0; k < s->count; k++)
    if (s->abit[s->res[k]]) s->samp[m++] = s->res[k];
  for (int i = 1; i < m; i++) {
    int x = s->samp[i], j = i - 1;
    while (j >= 0 && s->gst[s->samp[j]] > s->gst[x]) { s->samp[j + 1] = s->samp[j]; j--; }
    s->samp[j + 1] = x;
  }
  for (int i = 0; i < m; i++) { s->abit[s->samp[i]] = 0; mg_move(s, s->samp[i], s->gmax); }
}

static int mg_victim(struct state *s) {
  mg_retire(s);
  if (mg_should_age(s)) mg_age(s);
  for (;;) {
    mg_retire(s);
    int best = -1;
    for (int k = 0; k < s->count; k++) {
      int p = s->res[k];
      if (s->gen[p] == s->gmin && (best < 0 || s->gst[p] < s->gst[best])) best = p;
    }
    if (best < 0) return -1;
    if (s->abit[best]) { s->abit[best] = 0; mg_move(s, best, s->gmax); continue; }
    return best;
  }
}

// ---- LHD (Beckmann, Chen, Cidon, NSDI 2018), scan form ---------------------------
// Evict the page with the lowest hit density: expected future hits per unit of
// cache space-time, estimated per (class, age) from histograms of hit and
// eviction ages. Following cache_ext's port: 16 classes from the sum of a
// page's last two hit ages, 256 age buckets, histograms decayed by 0.9 at each
// re-estimation, densities initialised GDSF-like. Adapted to a kernel that
// sees accessed bits at scans: time is counted in eviction scans, a "hit" is
// a page found accessed at a scan (the load's own touch is ignored), and the
// densities are re-estimated every LHD_RECONF = 4*cap + 256 evictions. These
// parameters were fixed a priori, not tuned.
#define LHD_CL 16
#define LHD_AGES 256
#define LHD_HS 256
#define LHD_SCALE (1 << 20)

static int lhd_class(int64_t sum) {
  if (sum == 0) return 0;
  int c = 0;
  while (sum < LHD_AGES && c < LHD_CL - 1) { sum <<= 1; c++; }
  return c;
}
static int lhd_bucket(const struct state *s, int p) {
  int64_t a = (s->scans - s->last_seen[p]) >> s->lshift;
  return a >= LHD_AGES ? LHD_AGES - 1 : (int)a;
}
static void lhd_reconfigure(struct state *s) {
  for (int c = 0; c < LHD_CL; c++) {
    for (int a = 0; a < LHD_AGES; a++) { s->lh[c][a] = s->lh[c][a] * 9 / 10; s->le[c][a] = s->le[c][a] * 9 / 10; }
    int64_t hits = s->lh[c][LHD_AGES - 1], events = hits + s->le[c][LHD_AGES - 1], life = events;
    for (int a = LHD_AGES - 2; a >= 0; a--) {
      hits += s->lh[c][a]; events += s->lh[c][a] + s->le[c][a]; life += events;
      s->ld[c][a] = events > LHD_HS ? hits * LHD_SCALE / life : 0;
    }
  }
}
static void lhd_init(struct state *s, int cap) {
  int sh = 0;
  while (((int64_t)LHD_AGES << sh) < 4 * (int64_t)cap) sh++;
  s->lshift = sh;
  for (int c = 0; c < LHD_CL; c++)
    for (int a = 0; a < LHD_AGES; a++) s->ld[c][a] = (int64_t)LHD_SCALE * (c + 1) / (a + 1);
}
static void lhd_scan(struct state *s) {
  for (int k = 0; k < s->count; k++) {
    int p = s->res[k];
    if (s->s3fresh[p]) { s->s3fresh[p] = 0; s->abit[p] = 0; continue; }
    if (!s->abit[p]) continue;
    int b = lhd_bucket(s, p);
    s->lh[lhd_class((int64_t)s->la1[p] + s->la2[p])][b] += LHD_HS;
    s->la2[p] = s->la1[p]; s->la1[p] = b;
    s->last_seen[p] = s->scans; s->abit[p] = 0;
  }
}
static int lhd_victim(struct state *s) {
  int best = -1; int64_t bd = 0;
  for (int k = 0; k < s->count; k++) {
    int p = s->res[k], b = lhd_bucket(s, p);
    int64_t d = b == LHD_AGES - 1 ? 0 : s->ld[lhd_class((int64_t)s->la1[p] + s->la2[p])][b];
    if (best < 0 || d < bd || (d == bd && s->load_seq[p] < s->load_seq[best])) { best = p; bd = d; }
  }
  s->le[lhd_class((int64_t)s->la1[best] + s->la2[best])][lhd_bucket(s, best)] += LHD_HS;
  if (++s->lnev >= 4 * (int64_t)s->cap + 256) { s->lnev = 0; lhd_reconfigure(s); }
  return best;
}

// Append every current candidate as one training row each.
static void record(struct state *s, struct recorder *r, struct result *o,
                   int64_t t, int32_t group, uint64_t *rng, int32_t *pick) {
  int opt = 0;
  for (int k = 1; k < s->count; k++)
    if (s->nxt[s->res[k]] > s->nxt[s->res[opt]]) opt = k;
  // Candidates to record: all, or Belady's choice plus a random subset
  // (partial Fisher-Yates over the remaining indices).
  int m = s->count;
  for (int k = 0; k < s->count; k++) pick[k] = k;
  if (r->max_cand > 0 && s->count > r->max_cand) {
    // slot 0: Belady's choice; slots 1..n_recent: the most recently
    // accessed candidates (a uniform sample almost never contains the page
    // being streamed through, so a model never learns to keep it); the rest
    // uniformly at random.
    pick[opt] = pick[0]; pick[0] = opt;
    int fixed = 1;
    for (int q = 0; q < r->n_recent && fixed < r->max_cand; q++) {
      int best = -1;
      for (int j = fixed; j < s->count; j++)
        if (best < 0 || s->last_acc[s->res[pick[j]]] > s->last_acc[s->res[pick[best]]])
          best = j;
      int tmp = pick[fixed]; pick[fixed] = pick[best]; pick[best] = tmp;
      fixed++;
    }
    for (int j = fixed; j < r->max_cand; j++) {
      int i = j + (int)(xs(rng) % (uint64_t)(s->count - j));
      int tmp = pick[j]; pick[j] = pick[i]; pick[i] = tmp;
    }
    m = r->max_cand;
  }
  if (o->rows + m > r->cap) { o->overflow = 1; return; }
  for (int j = 0; j < m; j++) {
    int k = pick[j];
    int p = s->res[k];
    int64_t row = o->rows++;
    for (int f = 0; f < NF; f++) r->feat[row * NF + f] = feature(s, p, t, f);
    int64_t d = s->nxt[p] == INF_T ? LABEL_CAP : s->nxt[p] - t;
    if (d > LABEL_CAP) d = LABEL_CAP;
    r->label[row] = log1pf((float)d);
    r->group[row] = group;
    r->is_opt[row] = k == opt;
    if (r->hist)
      memcpy(r->hist + row * GRU_K, s->hist + (int64_t)p * GRU_K,
             sizeof(float) * GRU_K);
    if (r->page) r->page[row] = p;
    if (r->ctx)
      for (int j = 0; j < EMB_W; j++) {
        int q = s->ring[(s->ring_i + j) % EMB_W];
        r->ctx[row * EMB_W + j] = q < 0 ? s->n_pages : q;
      }
  }
}

#define ALLOC(ptr, cnt) ((ptr) = calloc((size_t)(cnt), sizeof(*(ptr))))

// Returns 0 on success, -1 on allocation failure.
int simulate(int64_t n, int n_pages, int cap, const uint32_t *pg,
             const uint8_t *wr, const uint32_t *nu, int policy,
             const struct model *m, struct recorder *r, int64_t max_faults,
             struct result *o) {
  struct state S = {0}, *s = &S;
  int32_t *pick = NULL;
  lut_init();
  memset(o, 0, sizeof(*o));
  s->n = n; s->n_pages = n_pages; s->cap = cap;
  s->pg = pg; s->wr = wr; s->nu = nu;
  int learned = policy == P_LEARNED || policy == P_GRU || policy == P_EMBED;
  int need_scan = policy == P_AGING || policy == P_LFU_KERNEL || learned ||
                  (r && r->p > 0);
  int need_bit = learned || (r && r->p > 0);
  double *score = NULL;
  int ok = ALLOC(s->pos, n_pages) && ALLOC(s->res, cap + 1) &&
           ALLOC(s->last_acc, n_pages) && ALLOC(s->load_seq, n_pages) &&
           ALLOC(s->nxt, n_pages) && ALLOC(s->load_scan, n_pages) &&
           ALLOC(s->last_seen, n_pages) && ALLOC(s->evicted_at, n_pages) &&
           ALLOC(s->rdist, n_pages) && ALLOC(s->last_distinct, n_pages) &&
           ALLOC(s->freq, n_pages) && ALLOC(s->writes, n_pages) &&
           ALLOC(s->sfreq, n_pages) && ALLOC(s->kfreq, n_pages) &&
           ALLOC(s->refaults, n_pages) && ALLOC(s->abit, n_pages) &&
           ALLOC(s->dbit, n_pages) && ALLOC(s->aging, n_pages) &&
           ALLOC(s->has_copy, n_pages) && ALLOC(s->seen_now, n_pages) &&
           ALLOC(s->hist, (int64_t)n_pages * GRU_K) &&
           ALLOC(s->order, cap + 1) && ALLOC(score, cap + 1) &&
           ALLOC(pick, cap + 1) && ALLOC(s->samp, cap + 1);
  int listpol = policy == P_ARC || policy == P_S3FIFO || policy == P_S3SCAN || policy == P_MGLRU || policy == P_LHD;
  if (ok && listpol)
    ok = ALLOC(s->lnx, n_pages) && ALLOC(s->lpv, n_pages) && ALLOC(s->lin, n_pages) &&
         ALLOC(s->s3freq, n_pages) && ALLOC(s->s3fresh, n_pages);
  if (ok && policy == P_MGLRU) ok = ALLOC(s->gen, n_pages) && ALLOC(s->gst, n_pages);
  if (ok && policy == P_LHD) ok = ALLOC(s->la1, n_pages) && ALLOC(s->la2, n_pages);
  if (ok && need_bit) ok = ALLOC(s->bit, n + 1) != NULL;
  if (ok && policy == P_GRU)
    ok = ALLOC(s->gru_cache, (int64_t)n_pages * m->gru_h) &&
         ALLOC(s->gru_dirty, n_pages);
  if (!ok) return -1;
  for (int p = 0; p < n_pages; p++) {
    s->pos[p] = -1; s->last_acc[p] = -1; s->evicted_at[p] = -1;
    if (s->gru_dirty) s->gru_dirty[p] = 1;
  }
  for (int j = 0; j < EMB_W; j++) s->ring[j] = -1;
  if (listpol) {
    for (int p = 0; p < n_pages; p++) s->lin[p] = -1;
    for (int l = 0; l < 4; l++) s->lhead[l] = s->ltail[l] = -1;
    s->s3_small_cap = cap / 10 > 0 ? cap / 10 : 1;
    s->s3_main_cap = cap - s->s3_small_cap;
  }
  if (policy == P_MGLRU)
    for (int p = 0; p < n_pages; p++) s->gen[p] = -1;
  if (policy == P_LHD) lhd_init(s, cap);
  uint64_t rng = r ? (r->rng ? r->rng : 88172645463325252ull) : 1;
  int32_t group = 0;
  s->srng = 0x9E3779B97F4A7C15ull ^ ((uint64_t)(m ? m->sample_seed : 0) * 0xD1B54A32D192ED03ull);
  if (!s->srng) s->srng = 1;
  int sampling = learned && m && m->kind == 0 && m->sample_k > 0;

  for (int64_t t = 0; t < n; t++) {
    int p = (int)pg[t];
    int w = wr[t];
    if (s->pos[p] < 0) {                      // ---- fault ----
      o->faults++;
      if (max_faults > 0 && o->faults > max_faults) { o->aborted = 1; break; }
      int lv = -1;                            // list policies: victim chosen first
      if (listpol)
        lv = policy == P_ARC ? arc_fault(s, p) : (policy == P_MGLRU || policy == P_LHD) ? -1 : s3_fault(s, p, policy == P_S3SCAN);
      if (s->count >= cap) {                  // ---- evict ----
        int sampled = sampling && s->count > m->sample_k;
        if (sampled) {
          draw_sample(s, m->sample_k);
          if (m->sample_scan) {
            for (int i = 0; i < m->sample_k; i++) scan_one(s, s->res[s->samp[i]]);
            o->scanned += m->sample_k;
          } else {
            scan_all(s);
            o->scanned += s->count;
          }
          o->scored += m->sample_k;
        } else if (need_scan) {
          scan_all(s);
          o->scanned += s->count;
          if (learned) o->scored += s->count;
        }
        if (need_bit) s->bit_now = bit_sum(s->bit, t - 1);
        if (r && r->p > 0 && (double)(xs(&rng) >> 11) / 9007199254740992.0 < r->p)
          record(s, r, o, t, group++, &rng, pick);
        int k;
        if (policy == P_MGLRU) lv = mg_victim(s);
        if (policy == P_LHD) { lhd_scan(s); lv = lhd_victim(s); }
        if (listpol) {
          if (lv < 0 || s->pos[lv] < 0) { o->aborted = -1; break; }   // invariant broken
          k = s->pos[lv];
        } else if (policy == P_CLOCK) {
          int idx = clock_choose(s);
          k = s->pos[s->order[idx]];
          memmove(s->order + idx, s->order + idx + 1,
                  sizeof(int32_t) * (s->order_n - idx - 1));
          s->order_n--;
        } else if (sampled) {
          k = choose_sampled(s, m, t, m->sample_k);
        } else {
          k = choose(s, policy, m, t, score);
        }
        int v = s->res[k];
        if (m && m->vlog && m->vlog_n < m->vlog_cap) {
          ((struct model *)m)->vlog[2 * m->vlog_n] = v;
          ((struct model *)m)->vlog[2 * m->vlog_n + 1] = s->count;
          ((struct model *)m)->vlog_n++;
        }
        if (policy == P_MGLRU) { s->gcnt[gi(s->gen[v])]--; s->gen[v] = -1; }
        if (s->dbit[v] || !s->has_copy[v]) { o->writebacks++; s->has_copy[v] = 1; }
        s->abit[v] = s->dbit[v] = 0;
        s->evicted_at[v] = s->scans;
        int last = s->res[--s->count];
        if (k != s->count) { s->res[k] = last; s->pos[last] = k; }
        s->pos[v] = -1;
        s->scans++;
        o->evictions++;
      }
      // ---- load: the kernel sets A (and D on a write fault) ----
      if (s->evicted_at[p] >= 0) {
        s->refaults[p]++;
        s->rdist[p] = s->scans - s->evicted_at[p];
      }
      s->pos[p] = s->count;
      s->res[s->count++] = p;
      s->load_seq[p] = ++s->seq;
      s->load_scan[p] = s->last_seen[p] = s->scans;
      s->aging[p] = 0xff;
      s->sfreq[p] = 0;
      s->kfreq[p] = 1;
      s->abit[p] = 1;
      s->dbit[p] = (uint8_t)w;
      if (policy == P_CLOCK) s->order[s->order_n++] = p;
      if (policy == P_MGLRU) mg_move(s, p, s->gmax);
      if (policy == P_LHD) { s->la1[p] = 0; s->la2[p] = LHD_AGES; s->s3fresh[p] = 1; }
    } else {                                  // ---- hit ----
      s->abit[p] = 1;
      s->dbit[p] |= (uint8_t)w;
      if (policy == P_ARC) arc_hit(s, p);
      else if (policy == P_S3FIFO) s3_hit(s, p);
    }
    // ---- exact (full-stream) bookkeeping, every access ----
    if (s->last_acc[p] >= 0) {
      float *h = s->hist + (int64_t)p * GRU_K;
      memmove(h, h + 1, sizeof(float) * (GRU_K - 1));
      h[GRU_K - 1] = lg(t - s->last_acc[p]);
      if (s->gru_dirty) s->gru_dirty[p] = 1;
    } else {
      s->distinct_seen++;                     // first touch (old SD metric)
    }
    s->last_distinct[p] = s->distinct_seen;
    if (need_bit) {
      if (s->last_acc[p] >= 0) bit_add(s->bit, n, s->last_acc[p], -1);
      bit_add(s->bit, n, t, +1);
    }
    s->last_acc[p] = t;
    s->freq[p]++;
    s->writes[p] += (uint32_t)w;
    s->nxt[p] = nu[t] == NEVER ? INF_T : t + (int64_t)nu[t];
    s->ring[s->ring_i] = p;
    s->ring_i = (s->ring_i + 1) % EMB_W;
  }

  free(s->pos); free(s->res); free(s->last_acc); free(s->load_seq);
  free(s->nxt); free(s->load_scan); free(s->last_seen); free(s->evicted_at);
  free(s->rdist); free(s->last_distinct); free(s->freq); free(s->writes);
  free(s->sfreq); free(s->kfreq); free(s->refaults); free(s->abit);
  free(s->dbit); free(s->aging); free(s->has_copy); free(s->seen_now);
  free(s->hist); free(s->order); free(score); free(s->bit); free(pick);
  free(s->gru_cache); free(s->gru_dirty); free(s->samp);
  free(s->gen); free(s->gst); free(s->la1); free(s->la2);
  free(s->lnx); free(s->lpv); free(s->lin); free(s->s3freq); free(s->s3fresh);
  return 0;
}

int pagesim_nf(void) { return NF; }
int pagesim_gru_k(void) { return GRU_K; }
int pagesim_emb_w(void) { return EMB_W; }

// Score n raw feature rows ([n][NF]) with an MLP/linear model exactly as the
// simulator does at an eviction -- used to check the C scorer against the
// trained model.
void score_rows(const struct model *m, const float *feat, int64_t n,
                float *out) {
  float x[NF];
  for (int64_t i = 0; i < n; i++) {
    if (m->quant_w > 0) {
      int64_t acc = 0;
      for (int j = 0; j < m->n_in; j++)
        acc += (int64_t)m->qa[j] * lrintf(feat[i * NF + m->feat[j]] * 256.0f);
      out[i] = (float)acc;
      continue;
    }
    for (int j = 0; j < m->n_in; j++)
      x[j] = (feat[i * NF + m->feat[j]] - m->mean[j]) / m->std[j];
    out[i] = mlp_forward(m->n_layers, m->sizes, m->w, x);
  }
}

// Tree ensemble over one candidate set ([n][NF] raw features), as at an eviction.
void score_tree_group(const struct model *m, const float *feat, int n, float *out) {
  tree_scores(m, feat, n, out);
}

// Integer network over one candidate set (q[n][8] Q8 kernel features, aging[n]): the kernel's scorer.
void score_net_group(const struct model *m, const int *q, const int *aging, int n, long long *out) {
  static struct mlcand *cd; static int cap_d;
  if (n > cap_d) { cap_d = n; cd = realloc(cd, sizeof(struct mlcand) * n); }
  for (int i = 0; i < n; i++) {
    for (int j = 0; j < 8; j++) cd[i].q[j] = q[i * 8 + j];
    cd[i].aging = aging[i];
  }
  mlnet_score(m->net, cd, n, out);
}

// GRU / embedding scorer over recorded rows, exactly as score_one() computes
// it at an eviction, for checking against the trained PyTorch model.
//   kind 1: GRU over hist[i][GRU_K] from h = 0, head([h, (rec - mean)/std])
//   kind 2: GRU over emb[ctx[i][j]], head([h, emb[page[i]]])
void score_seq_rows(const struct model *m, const float *hist, const float *rec,
                    const int32_t *page, const int32_t *ctx, int64_t n,
                    float *out) {
  float h[64], x[NF + 64];
  for (int64_t i = 0; i < n; i++) {
    memset(h, 0, sizeof(h));
    if (m->kind == 1) {
      for (int j = 0; j < GRU_K; j++)
        gru_step(m->gru_h, 1, m->gru_w, &hist[i * GRU_K + j], h);
      memcpy(x, h, sizeof(float) * m->gru_h);
      x[m->gru_h] = (rec[i] - m->mean[0]) / m->std[0];
    } else {
      for (int j = 0; j < EMB_W; j++)
        gru_step(m->gru_h, m->emb_d, m->gru_w,
                 m->emb + (int64_t)ctx[i * EMB_W + j] * m->emb_d, h);
      memcpy(x, h, sizeof(float) * m->gru_h);
      memcpy(x + m->gru_h, m->emb + (int64_t)page[i] * m->emb_d,
             sizeof(float) * m->emb_d);
    }
    out[i] = mlp_forward(m->head_layers, m->head_sizes, m->head_w, x);
  }
}
