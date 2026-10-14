#include <stdio.h>
#include <stdlib.h>
typedef unsigned char uint8; typedef unsigned long long uint64;
#include "kernel/mlfeat.h"
static const uint8 ml_msb8[256] = {
#define R2(n) n, n
#define R4(n) R2(n), R2(n)
#define R8(n) R4(n), R4(n)
#define R16(n) R8(n), R8(n)
#define R32(n) R16(n), R16(n)
#define R64(n) R32(n), R32(n)
#define R128(n) R64(n), R64(n)
  0, 0, R2(1), R4(2), R8(3), R16(4), R32(5), R64(6), R128(7)
};
static inline int f2(unsigned long long v){
  if(v < 256) return ml_log1p_q8_small[v];
  unsigned long long x = v + 1; int e;
  if(x >> 32){ e = x >> 48 ? (x >> 56 ? 56 + ml_msb8[x >> 56] : 48 + ml_msb8[x >> 48]) : (x >> 40 ? 40 + ml_msb8[x >> 40] : 32 + ml_msb8[x >> 32]); }
  else { e = x >> 16 ? (x >> 24 ? 24 + ml_msb8[x >> 24] : 16 + ml_msb8[x >> 16]) : 8 + ml_msb8[x >> 8]; }
  int m = (int)((e >= 10 ? (x >> (e - 10)) : (x << (10 - e))) & 0x3FF);
  return (int)(((long long)e * 45427 + 128) >> 8) + ml_ln_mant_q8[m];
}
int main(void){
  long bad = 0;
  for(unsigned long long v = 0; v < (1ULL << 26); v++) if(ml_log1p_q8(v) != f2(v)) bad++;
  unsigned long long r = 88172645463325252ULL;
  for(long i = 0; i < 20000000; i++){ r ^= r << 13; r ^= r >> 7; r ^= r << 17; unsigned long long v = r >> (r & 63); if(v == ~0ULL) continue; if(ml_log1p_q8(v) != f2(v)) bad++; }
  for(int b = 0; b < 64; b++){ unsigned long long v = 1ULL << b; for(int d = -2; d <= 2; d++){ unsigned long long w = v + d; if(w == ~0ULL) continue; if(ml_log1p_q8(w) != f2(w)) bad++; } }
  printf("mismatches: %ld\n", bad); return bad != 0;
}
