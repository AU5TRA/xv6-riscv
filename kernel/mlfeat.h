// Integer-only features for the learned eviction policy (VM_POLICY_ML).
//
// Shared, byte for byte, by the kernel (kernel/vmpage.c) and the host
// simulator's integer mode (tools/ml2/pagesim.c), so a model scores a page
// identically in both. Every feature is a Q8 fixed-point value (real value
// x 256); a model's score is sum_j qa[j] * X_j with integer weights qa[j]
// (tools/ml2/export_kernel.py folds the training-time standardisation into
// them). No floating point anywhere.
#ifndef XV6_MLFEAT_H
#define XV6_MLFEAT_H

// Feature ids (ML_F_*) and struct vm_ml_weights are in vmstats.h, which user
// programs share; this header holds only the integer arithmetic, included by
// kernel/vmpage.c and tools/ml2/pagesim.c.

// round(256 * ln(1 + v)) for v < 256, and round(256 * ln(1 + m/1024)) for
// the mantissa correction used above that.
static const unsigned short ml_log1p_q8_small[256] = {
#include "mlfeat_table.h"
};
static const unsigned short ml_ln_mant_q8[1024] = {
#include "mlfeat_mant.h"
};

// 256 * ln(1 + v) in integers: exact table below 256; above, write
// v + 1 = 2^e * (1 + f) with f from the next 10 bits, and use
// 256 * (e * ln 2 + ln(1 + f)), ln 2 * 256 = 177.4457 (= 45427 / 256).
// Within 1.04 Q8 units (0.004 in log space) of the exact value, checked for
// every v < 300,000 and samples up to 10^10.
// Index of the highest set bit (x > 0). A plain binary search: the kernel
// links without libgcc, so __builtin_clzll (-> __clzdi2 on rv64gc) is out.
static inline int
ml_msb(unsigned long long x)
{
  int e = 0;
  if(x >> 32) { x >>= 32; e += 32; }
  if(x >> 16) { x >>= 16; e += 16; }
  if(x >> 8)  { x >>= 8;  e += 8; }
  if(x >> 4)  { x >>= 4;  e += 4; }
  if(x >> 2)  { x >>= 2;  e += 2; }
  if(x >> 1)  { e += 1; }
  return e;
}

static inline int
ml_log1p_q8(unsigned long long v)
{
  if(v < 256)
    return ml_log1p_q8_small[v];
  unsigned long long x = v + 1;
  int e = ml_msb(x);
  int m = (int)((e >= 10 ? (x >> (e - 10)) : (x << (10 - e))) & 0x3FF);
  return (int)(((long long)e * 45427 + 128) >> 8) + ml_ln_mant_q8[m];
}

// Q8 aging counter: round(aging * 256 / 255).
static inline int
ml_aging_q8(int aging)
{
  return (aging * 256 + 127) / 255;
}

#endif
