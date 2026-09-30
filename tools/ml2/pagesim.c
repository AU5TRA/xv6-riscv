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
#include <stdlib.h>
#include <string.h>

#define NEVER 0xFFFFFFFFu
#define INF_T INT64_MAX
#define LABEL_CAP (1 << 20)

enum policy {
  P_FIFO, P_CLOCK, P_AGING, P_LRU, P_LFU_EXACT, P_LFU_KERNEL, P_BELADY,
  P_LEARNED, P_SD_OLD, P_GRU, P_EMBED,
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
};

struct result {
  int64_t faults, evictions, writebacks;
  int64_t rows, overflow;
};

struct recorder {
  double p;                 // probability an eviction is recorded
  uint64_t rng;
  int64_t cap;              // row capacity of the buffers
  float *feat;              // [cap][NF]
  float *label;             // [cap]  log1p(next-use distance), capped
  int32_t *group;           // [cap]  eviction id
  uint8_t *is_opt;          // [cap]  1 if Belady would evict this candidate
  // GRU/embedding training inputs (optional; NULL to skip)
  float *hist;              // [cap][GRU_K] past intervals, oldest first
  int32_t *page;            // [cap] candidate dense page id
  int32_t *ctx;             // [cap][EMB_W] last EMB_W pages referenced
};

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
  int64_t seq, scans, distinct_seen;
  int32_t *order; int order_n; int64_t hand;   // Clock candidate list
  int32_t ring[EMB_W]; int ring_i;             // last EMB_W pages referenced
};

static float feature(const struct state *s, int p, int64_t t, int f) {
  switch (f) {
  case F_REC: return log1pf((float)(t - s->last_acc[p]));
  case F_FREQ: return log1pf((float)s->freq[p]);
  case F_SD: {
    int64_t d = bit_sum(s->bit, t - 1) - bit_sum(s->bit, s->last_acc[p]);
    return log1pf((float)d);
  }
  case F_WR: return s->freq[p] ? (float)s->writes[p] / s->freq[p] : 0;
  case K_REF: return s->seen_now[p];
  case K_AGING: return s->aging[p] / 255.0f;
  case K_SFREQ: return log1pf((float)s->sfreq[p]);
  case K_IDLE: return log1pf((float)(s->scans - s->last_seen[p]));
  case K_AGE: return log1pf((float)(s->scans - s->load_scan[p]));
  case K_DIRTY: return s->dbit[p];
  case K_REFAULTS: return log1pf((float)s->refaults[p]);
  case K_RDIST: return log1pf((float)s->rdist[p]);
  }
  return 0;
}

// Kernel-style full scan of every candidate: read and clear A, update the
// aging counter, the sampled counts and the decayed LFU counter exactly as
// sample_page() + choose_aging()/choose_lfu() would.
static void scan_all(struct state *s) {
  for (int k = 0; k < s->count; k++) {
    int p = s->res[k];
    int a = s->abit[p];
    s->seen_now[p] = a;
    s->aging[p] = (s->aging[p] >> 1) | (a ? 0x80 : 0);
    if (a) {
      s->sfreq[p]++;
      s->last_seen[p] = s->scans;
      s->kfreq[p]++;                       // sample_page()'s frequency++
    }
    s->kfreq[p] = (s->kfreq[p] >> 1) + (a ? 1 : 0);  // choose_lfu decay
    s->abit[p] = 0;
  }
}

static int argmax_by(const struct state *s, const float *score) {
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

static float score_one(struct state *s, const struct model *m, int p,
                       int64_t t, const float *ctx_h) {
  float x[NF + 64];
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

static int choose(struct state *s, int policy, const struct model *m,
                  int64_t t, float *score) {
  switch (policy) {
  case P_FIFO: case P_AGING: case P_LFU_KERNEL: case P_LFU_EXACT:
  case P_LRU: case P_BELADY: case P_SD_OLD:
    for (int k = 0; k < s->count; k++) {
      int p = s->res[k];
      switch (policy) {
      case P_FIFO: score[k] = 0; break;           // tie-break = oldest load
      case P_AGING: score[k] = -(float)s->aging[p]; break;
      case P_LFU_KERNEL: score[k] = -(float)s->kfreq[p]; break;
      case P_LFU_EXACT: score[k] = -(float)s->freq[p]; break;
      case P_LRU: score[k] = (float)(t - s->last_acc[p]); break;
      case P_BELADY:
        score[k] = s->nxt[p] == INF_T ? INFINITY : (float)(s->nxt[p] - t);
        break;
      case P_SD_OLD:  // the old tools/sim.py StackDistance, kept for the record
        score[k] = (float)(s->distinct_seen - s->last_distinct[p]);
        break;
      }
    }
    if (policy == P_LRU || policy == P_BELADY) {  // exact: no float ties
      int best = 0;
      for (int k = 1; k < s->count; k++) {
        int p = s->res[k], q = s->res[best];
        int64_t a = policy == P_LRU ? -s->last_acc[p] : s->nxt[p];
        int64_t b = policy == P_LRU ? -s->last_acc[q] : s->nxt[q];
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
    for (int k = 0; k < s->count; k++)
      score[k] = score_one(s, m, s->res[k], t, ctx_h);
    return argmax_by(s, score);
  }
  }
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

// Append every current candidate as one training row each.
static void record(struct state *s, struct recorder *r, struct result *o,
                   int64_t t, int32_t group) {
  if (o->rows + s->count > r->cap) { o->overflow = 1; return; }
  int opt = 0;
  for (int k = 1; k < s->count; k++)
    if (s->nxt[s->res[k]] > s->nxt[s->res[opt]]) opt = k;
  for (int k = 0; k < s->count; k++) {
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
             const struct model *m, struct recorder *r, struct result *o) {
  struct state S = {0}, *s = &S;
  memset(o, 0, sizeof(*o));
  s->n = n; s->n_pages = n_pages; s->cap = cap;
  s->pg = pg; s->wr = wr; s->nu = nu;
  int learned = policy == P_LEARNED || policy == P_GRU || policy == P_EMBED;
  int need_scan = policy == P_AGING || policy == P_LFU_KERNEL || learned ||
                  (r && r->p > 0);
  int need_bit = learned || (r && r->p > 0);
  float *score = NULL;
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
           ALLOC(s->order, cap + 1) && ALLOC(score, cap + 1);
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
  uint64_t rng = r ? (r->rng ? r->rng : 88172645463325252ull) : 1;
  int32_t group = 0;

  for (int64_t t = 0; t < n; t++) {
    int p = (int)pg[t];
    int w = wr[t];
    if (s->pos[p] < 0) {                      // ---- fault ----
      o->faults++;
      if (s->count >= cap) {                  // ---- evict ----
        if (need_scan) scan_all(s);
        if (r && r->p > 0 && (double)(xs(&rng) >> 11) / 9007199254740992.0 < r->p)
          record(s, r, o, t, group++);
        int k;
        if (policy == P_CLOCK) {
          int idx = clock_choose(s);
          k = s->pos[s->order[idx]];
          memmove(s->order + idx, s->order + idx + 1,
                  sizeof(int32_t) * (s->order_n - idx - 1));
          s->order_n--;
        } else {
          k = choose(s, policy, m, t, score);
        }
        int v = s->res[k];
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
    } else {                                  // ---- hit ----
      s->abit[p] = 1;
      s->dbit[p] |= (uint8_t)w;
    }
    // ---- exact (full-stream) bookkeeping, every access ----
    if (s->last_acc[p] >= 0) {
      float *h = s->hist + (int64_t)p * GRU_K;
      memmove(h, h + 1, sizeof(float) * (GRU_K - 1));
      h[GRU_K - 1] = log1pf((float)(t - s->last_acc[p]));
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
  free(s->hist); free(s->order); free(score); free(s->bit);
  free(s->gru_cache); free(s->gru_dirty);
  return 0;
}

int pagesim_nf(void) { return NF; }
int pagesim_gru_k(void) { return GRU_K; }
int pagesim_emb_w(void) { return EMB_W; }
