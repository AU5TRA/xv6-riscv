// Integer-only evaluation of the extra learned scorers (deeper MLP, CNN over the
// aging bits, set-attention, boosted trees), shared byte for byte by the kernel
// (kernel/vmpage.c) and the host simulator (tools/ml2/pagesim.c), like mlfeat.h.
//
// Inputs per candidate: the 8 kernel features in Q8 (value * 256, the order of
// the ML_F_* ids) and the 8-bit aging register. Weights are Q8 integers, biases
// Q16; activations are Q8 and rounded after every layer ((acc + 128) >> 8), the
// last layer's Q16 sum is the score. Standardisation of the inputs is folded
// into the first layer by tools/ml2/netint.py. No floating point, no libgcc.
//
// Scratch buffers are static: the kernel calls this with frame_table.lock held,
// and kernel stacks are one page.
#ifndef XV6_MLNET_H
#define XV6_MLNET_H

#define MLNET_MLP 1      // dense layers over the 8 features
#define MLNET_CNN 2      // CNN over the 8 aging bits, concatenated with the features, dense head
#define MLNET_SET 3      // per-candidate encoder, attention pooling over the set, dense head
#define MLNET_TREES 4    // sum of regression trees over the Q8 features
#define MLNET_MAXN 1024  // most candidates scored at once by the set model
#define MLNET_CTX 48     // most candidates the set context is pooled over
#define MLNET_ENC 32     // width of the set encoder

struct mlnet {
  int kind;
  int n_layers;            // dense head: layer l maps sizes[l] -> sizes[l + 1]
  int sizes[6];
  const int *w;            // per layer: W[out][in] (Q8) then b[out] (Q16)
  const int *c1w, *c1b;    // CNN: conv 1 -> 8, kernel 3: c1w[8][3]; conv 8 -> 8: c2w[8][24]
  const int *c2w, *c2b;
  const int *encw, *encb, *qw;   // set: encw[32][8], encb[32], attention vector qw[32] (Q8)
  int n_trees;             // trees: root[t], per node nf (feature 0..7, -1 = leaf), nthr
  const int *root, *nf, *nthr, *nl, *nr;   // (leaf value, Q16, is in nthr)
};

// One candidate's inputs.
struct mlcand {
  int q[8];                // Q8 kernel features
  int aging;               // aging register, 0..255
};

static const int mlnet_pow2neg[256] = {
#include "mlnet_exp.h"
};

static int mlnet_a[128], mlnet_b[128];
static int mlnet_c1[8 * 6];
static int mlnet_e[MLNET_MAXN * MLNET_ENC];
static int mlnet_ctx[MLNET_ENC], mlnet_mean[MLNET_ENC], mlnet_in[3 * MLNET_ENC];
static int mlnet_sc[MLNET_CTX];
static long long mlnet_ctxs[MLNET_ENC], mlnet_means[MLNET_ENC];

static inline int
mlnet_rs8(long long acc)
{
  return (int)((acc + 128) >> 8);
}

// 2^(x * log2 e) for x <= 0 in Q8, as Q16.
static inline int
mlnet_exp_q16(int x)
{
  long long t = -(long long)x * 369;     // -x * log2(e), Q16
  int y = (int)(t >> 8);                 // Q8
  int n = y >> 8;
  if(n >= 16)
    return 0;
  return mlnet_pow2neg[y & 255] >> n;
}

// Dense head over x (Q8): returns the Q16 score of the last layer.
static long long
mlnet_head(const struct mlnet *m, const int *x)
{
  const int *w = m->w;
  int *cur = mlnet_a, *nxt = mlnet_b;
  for(int i = 0; i < m->sizes[0]; i++)
    cur[i] = x[i];
  for(int l = 0; l < m->n_layers; l++){
    int in = m->sizes[l], out = m->sizes[l + 1];
    const int *W = w, *B = w + out * in;
    for(int o = 0; o < out; o++){
      long long acc = B[o];
      const int *wo = W + o * in;
      for(int i = 0; i < in; i++)
        acc += (long long)wo[i] * cur[i];
      if(l + 1 == m->n_layers)
        return acc;                       // output width is 1
      if(acc < 0)
        acc = 0;
      nxt[o] = mlnet_rs8(acc);
    }
    w = B + out;
    int *t = cur; cur = nxt; nxt = t;
  }
  return 0;
}

// CNN features of the 8 aging bits (oldest first), 32 values in out.
static void
mlnet_conv(const struct mlnet *m, int aging, int *out)
{
  int bits[8];
  for(int j = 0; j < 8; j++)
    bits[j] = ((aging >> (7 - j)) & 1) << 8;
  for(int co = 0; co < 8; co++)
    for(int t = 0; t < 6; t++){
      long long acc = m->c1b[co];
      for(int k = 0; k < 3; k++)
        acc += (long long)m->c1w[co * 3 + k] * bits[t + k];
      if(acc < 0)
        acc = 0;
      mlnet_c1[co * 6 + t] = mlnet_rs8(acc);
    }
  for(int co = 0; co < 8; co++)
    for(int t = 0; t < 4; t++){
      long long acc = m->c2b[co];
      for(int ci = 0; ci < 8; ci++)
        for(int k = 0; k < 3; k++)
          acc += (long long)m->c2w[co * 24 + ci * 3 + k] * mlnet_c1[ci * 6 + t + k];
      if(acc < 0)
        acc = 0;
      out[co * 4 + t] = mlnet_rs8(acc);
    }
}

// Scores of n candidates into out[] (Q16; higher = evict sooner).
static void
mlnet_score(const struct mlnet *m, const struct mlcand *c, int n, long long *out)
{
  if(m->kind == MLNET_MLP){
    for(int i = 0; i < n; i++)
      out[i] = mlnet_head(m, c[i].q);
  } else if(m->kind == MLNET_CNN){
    int x[8 + 32];
    for(int i = 0; i < n; i++){
      for(int j = 0; j < 8; j++)
        x[j] = c[i].q[j];
      mlnet_conv(m, c[i].aging, x + 8);
      out[i] = mlnet_head(m, x);
    }
  } else if(m->kind == MLNET_TREES){
    for(int i = 0; i < n; i++){
      long long s = 0;
      for(int t = 0; t < m->n_trees; t++){
        int k = m->root[t];
        while(m->nf[k] >= 0)
          k = c[i].q[m->nf[k]] <= m->nthr[k] ? m->nl[k] : m->nr[k];
        s += m->nthr[k];
      }
      out[i] = s;
    }
  } else {   // MLNET_SET
    for(int i = 0; i < n; i++)
      for(int o = 0; o < MLNET_ENC; o++){
        long long acc = m->encb[o];
        for(int j = 0; j < 8; j++)
          acc += (long long)m->encw[o * 8 + j] * c[i].q[j];
        if(acc < 0)
          acc = 0;
        mlnet_e[i * MLNET_ENC + o] = mlnet_rs8(acc);
      }
    int ns = n <= MLNET_CTX ? n : MLNET_CTX;
    int *sc = mlnet_sc;
    int smax = -2147483647;
    for(int t = 0; t < ns; t++){
      int idx = n <= MLNET_CTX ? t : (int)(((long long)t * (n - 1)) / (MLNET_CTX - 1));
      long long acc = 0;
      for(int o = 0; o < MLNET_ENC; o++)
        acc += (long long)m->qw[o] * mlnet_e[idx * MLNET_ENC + o];
      sc[t] = mlnet_rs8(acc);
      if(sc[t] > smax)
        smax = sc[t];
    }
    long long asum = 0;
    long long *ctx = mlnet_ctxs, *mean = mlnet_means;
    for(int o = 0; o < MLNET_ENC; o++)
      ctx[o] = mean[o] = 0;
    for(int t = 0; t < ns; t++){
      int idx = n <= MLNET_CTX ? t : (int)(((long long)t * (n - 1)) / (MLNET_CTX - 1));
      long long a = mlnet_exp_q16(sc[t] - smax);
      asum += a;
      for(int o = 0; o < MLNET_ENC; o++){
        ctx[o] += a * mlnet_e[idx * MLNET_ENC + o];
        mean[o] += mlnet_e[idx * MLNET_ENC + o];
      }
    }
    for(int o = 0; o < MLNET_ENC; o++){
      mlnet_ctx[o] = (int)((ctx[o] + asum / 2) / asum);
      mlnet_mean[o] = (int)((mean[o] + ns / 2) / ns);
    }
    for(int i = 0; i < n; i++){
      for(int o = 0; o < MLNET_ENC; o++){
        mlnet_in[o] = mlnet_e[i * MLNET_ENC + o];
        mlnet_in[MLNET_ENC + o] = mlnet_ctx[o];
        mlnet_in[2 * MLNET_ENC + o] = mlnet_e[i * MLNET_ENC + o] - mlnet_mean[o];
      }
      out[i] = mlnet_head(m, mlnet_in);
    }
  }
}

#endif
