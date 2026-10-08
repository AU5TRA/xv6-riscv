// Shared scaffolding for the workload/trace-collection benchmark suite
// (WORK_PROMPT.md Phase 1). Every workload program should use these
// primitives instead of re-inventing them, so traces stay interpretable
// and comparable across workloads.
//
// touch_r/touch_w are the ONLY touch primitives any workload may use --
// both are volatile-qualified. A plain `char c = mem[i]; (void)c;` was
// confirmed (in a prior session, via disassembly) to be fully
// dead-code-eliminated at -O, silently defeating the whole point of the
// touch. Never bypass these with a raw pointer dereference.
#ifndef XV6_VMBENCH_H
#define XV6_VMBENCH_H

#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "kernel/vmtrace.h"
#include "user/user.h"

#define VMBENCH_PGSIZE 4096

// ---- Arena allocation -----------------------------------------------
// sbrk()s a contiguous, page-aligned arena of `npages` pages and
// returns its base. Deliberately not malloc: callers need an exact,
// known VPN<->offset mapping (page i of the arena is always at
// `base + i*VMBENCH_PGSIZE`) so traces stay interpretable. Returns
// SBRK_ERROR on failure, same convention as sbrk()/sbrklazy().
char *vmbench_arena(int npages);

// Shrinks an arena previously returned by vmbench_arena back down.
// Always call this before the process exits if you plan to allocate
// another arena in the same process (e.g. vmbenchselftest.c).
int vmbench_arena_free(int npages);

// ---- Reference logging -------------------------------------------------
// When reference tracing is on (vmbench_trace_on != 0, toggled by
// vmbench_trace_start/stop below), vmbench_trace_ref prints a compact
// "R <vpn>" or "W <vpn>" line -- a full reference stream, not just
// faults. W means the access modified the page at all, R that it only
// read it; that is what an offline replay needs to know which evictions
// cost a write-back. (Captures made before the access type was recorded
// use "T <vpn>" for every reference; the host tools accept all three.)
// This is
// what Phase 3 (trace collection) needs for Belady labeling: the
// kernel's own vmtrace ring only records FAULTS, so it can't see a
// benign re-touch of an already-resident page, which Belady's
// next-use-distance calculation needs to know about. Printed (not
// written into xv6's own filesystem) so the host-side test harness's
// existing transcript capture is the trace sink -- consistent with
// this project's established preference for host-side trace storage.
//
// Call this from a workload's OWN page-accessor function (the one
// thing every access already funnels through -- e.g. btreebench's
// bt_node(), kvbench's kv_key_ptr()) rather than at every call site
// individually. It has to be an accessor that EVERY arena access goes
// through: graphbench once traced only edge_dst(), which left four of
// its five arrays -- and most of its faults -- out of the trace.
extern int vmbench_trace_on;

// Reference logging is buffered, because xv6's printf() calls putc() which
// issues write(fd, &c, 1) -- ONE SYSCALL PER CHARACTER. A "T 12345\n" line
// is eight of them, so an unbuffered reference stream costs eight syscalls
// per memory touch and tops out near 780 references/second. That, not the
// UART and not the disk, is what made the graph/sort/matmul workloads
// impossible to run to completion: they need millions of references.
//
// vmbench_trace_fd selects the sink: 1 (the default) keeps the stream in the
// harness transcript exactly as before; a file descriptor sends it into the
// guest filesystem instead, to be extracted host-side afterwards.
#define VMBENCH_TRACE_BUFSZ 4096
extern int vmbench_trace_fd;
extern char vmbench_trace_buf[VMBENCH_TRACE_BUFSZ];
extern int vmbench_trace_len;
// Totals since vmbench_trace_start(), printed by vmbench_trace_stop() as
// "TRACEEND refs=N bytes=M" for the host to check the extracted file against.
extern long vmbench_trace_refs;
extern long vmbench_trace_bytes;
void vmbench_trace_flush(void);

// Bit 3 of a benchmark's trace argument routes the reference string to a
// file in the guest filesystem instead of the console. The file is pulled
// out host-side from fs.img by tools/extract_file.py, so the stream never
// pays the console's per-character syscall cost. Bit 0 keeps its original
// meaning, so an existing script passing 1 behaves exactly as before, and
// 9 means "trace, to a file".
#define VMBENCH_TRACE_FILE 8
#define VMBENCH_TRACE_PATH "reftrace.txt"
int vmbench_trace_sink(int flags);

// The access argument of vmbench_trace_ref(). There is deliberately no
// "unknown" value: every call site has to say which one it is.
#define VMBENCH_READ 'R'
#define VMBENCH_WRITE 'W'

static inline void
vmbench_trace_ref(char *base, uint64 page, char access)
{
  if(!vmbench_trace_on)
    return;
  uint64 vpn = ((uint64)base + page * VMBENCH_PGSIZE) / VMBENCH_PGSIZE;
  // "R " + at most 20 digits + newline
  if(vmbench_trace_len > VMBENCH_TRACE_BUFSZ - 24)
    vmbench_trace_flush();
  char *p = vmbench_trace_buf + vmbench_trace_len;
  *p++ = access;
  *p++ = ' ';
  char digits[24];
  int n = 0;
  if(vpn == 0)
    digits[n++] = '0';
  while(vpn){
    digits[n++] = (char)('0' + (int)(vpn % 10));
    vpn /= 10;
  }
  while(n > 0)
    *p++ = digits[--n];
  *p++ = '\n';
  vmbench_trace_len = (int)(p - vmbench_trace_buf);
  vmbench_trace_refs++;
}

// ---- Touch primitives -------------------------------------------------
static inline uchar
touch_r(char *base, uint64 page)
{
  uchar v = *(volatile uchar *)(base + page * VMBENCH_PGSIZE);
  vmbench_trace_ref(base, page, VMBENCH_READ);
  return v;
}

static inline void
touch_w(char *base, uint64 page, uchar val)
{
  *(volatile uchar *)(base + page * VMBENCH_PGSIZE) = val;
  vmbench_trace_ref(base, page, VMBENCH_WRITE);
}

// Prints a documented trace-file header (workload name + parameters +
// seed + resident limit + policy + prefetch state + arena base VPN +
// arena page count), disables prefetch (Phase 3 SS2: prefetch changes
// which pages fault and when, contaminating labels -- logged here so
// it's explicit in the trace itself), then turns reference tracing on.
// Call this AFTER vmctl(VM_SET_LIMIT, ...) so the printed limit is the
// real one. `params` is a caller-formatted string (already using only
// supported printf conversions) describing workload-specific args.
void vmbench_trace_start(const char *workload, const char *params,
                          uint64 seed, char *arena_base, int arena_pages,
                          int arena_cache_budget);

// Turns reference tracing back off. Always call this before printing
// RESULT lines, so they aren't interleaved with the reference stream.
void vmbench_trace_stop(void);

// ---- Burn phase ---------------------------------------------------
// Ports the dynamic self-sizing burn discovered in user/policydemo.c:
// a process's own exec()-loaded pages are always resident before any
// arena page, so they always have the oldest load_sequence -- meaning
// FIFO/Aging will pick them as the eviction victim ahead of anything
// in the arena, no matter how generous the resident-limit margin is.
// This is an ordering problem, not a sizing problem (see
// WORK_PROMPT.md SS1 item 5).
//
// This function touches throwaway scratch pages, one at a time, under
// the process's current resident limit, until a VICTIM_SELECTED trace
// event's victim VPN falls inside [arena_start_vpn, arena_start_vpn +
// arena_pages) -- proof that every leftover startup page has either
// been permanently evicted (genuinely idle ones) or evicted-and-
// reloaded with a fresh, newer load-order position (ones the CPU is
// still actively executing), and the arena is now the true oldest
// resident content.
//
// IMPORTANT: burning itself evicts things, which can drop
// resident_count below whatever budget the caller had in mind (a later
// deliberate touch might then not force an eviction at all). This
// function re-measures resident_count after burning and writes it to
// *settled_resident -- the caller MUST compute their real resident
// limit from *that* value, not from a reading taken before burning.
//
// Returns:
//    1 if VM_DEBUG is available and the trace ring proved the burn
//      actually reached the arena's own VPN range.
//    0 if VM_DEBUG is unavailable (no trace ring) and a best-effort
//      burn was used instead: a generous, fixed number of scratch
//      touches, with NO proof it actually flushed everything.
//      Callers must print a warning noting the weaker guarantee.
//   -1 on error (sbrklazy/vmctl/vmstats failure, or burn exhausted
//      max_burn without reaching the arena -- caller should treat this
//      as fatal, not silently continue).
int vmbench_burn(char *arena_base, int arena_pages, uint64 *settled_resident);

// ---- Stats delta helper ----------------------------------------------
struct vmbench_delta {
  long zero_faults;
  long swap_faults;
  long evictions;
  long page_reads;
  long page_writes;
  long resident_count;
  long free_swap_slots;
  long select_ticks;        // victim-selection time (r_time ticks)
  long candidates_scanned;  // candidates examined by the policy
};

// Snapshot wrapper (exits the process with a message on failure --
// vmstats() should never fail in practice, and every call site would
// otherwise need identical boilerplate).
void vmbench_snapshot(struct vmstats *out);

// Resets the stats counters THEN snapshots (into *out, which will read
// all zero for the delta-relevant fields). Use this instead of hand
// -rolling "snapshot; vmctl(VM_RESET_STATS, ...)" for a "before"
// baseline -- doing the reset AFTER the snapshot silently produces
// negative deltas later (the "after" snapshot is measured from the
// post-reset zero point, while "before" still holds pre-reset values).
void vmbench_reset_and_snapshot(struct vmstats *out);

void vmbench_delta(const struct vmstats *before, const struct vmstats *after,
                    struct vmbench_delta *out);

void vmbench_print_delta(const char *label, const struct vmbench_delta *d);

// ---- Result / banner printing -----------------------------------------
// The one stable, machine-parseable result format every workload uses:
// a line of the exact form "RESULT key=value". Emit one call per
// metric -- do not hand-roll printf calls for results, so tooling can
// grep a stable pattern across every workload's output.
void vmbench_result(const char *key, long value);

void vmbench_banner(const char *workload, const char *phase);

// ---- Integer PRNG: xorshift64 -----------------------------------------
// Deterministic, explicitly seeded, no floating point. Never seed with
// 0 (xorshift's fixed point) -- vmbench_rng_seed() guards against this.
struct vmbench_rng {
  uint64 state;
};

void vmbench_rng_seed(struct vmbench_rng *r, uint64 seed);
uint64 vmbench_rng_next(struct vmbench_rng *r);
// Uniform in [0, bound) via rejection-free modulo (adequate for this
// suite's bound sizes; not claiming cryptographic-quality uniformity).
uint64 vmbench_rng_below(struct vmbench_rng *r, uint64 bound);

// ---- Fixed-point Zipf sampler ------------------------------------------
// Table generated on the host by tools/gen_zipf_table.py (skew s=0.99,
// VMBENCH_ZIPF_N=1024 ranks, rank 0 = hottest) and committed as
// user/zipf_table.h. 1024 uint32 entries = 4KB (one page) -- kept
// deliberately small so the table's own footprint doesn't pollute a
// workload's own resident-page measurements.
//
// Returns a rank in [0, VMBENCH_ZIPF_N) skewed per the table (rank 0
// most likely). Workloads that need a shifting hot set should NOT
// regenerate the table -- rotate the mapping from rank to actual
// key/page index instead (e.g. `key = (rank + epoch_offset) %
// n_keys`), keeping the underlying skew fixed. See user/kvbench.c.
// VMBENCH_ZIPF_N itself is defined in the generated user/zipf_table.h
// (included by vmbench.c), not here, so there is exactly one source of
// truth for the table's size.
uint64 vmbench_zipf_sample(struct vmbench_rng *r);

// The same sampler over any table: `cdf` holds `n` ranks, as written by
// tools/gen_zipf_table.py --name (user/zipf_table_<name>.h). For skews
// and sizes other than kvbench's. One draw from the PRNG per sample,
// exactly as vmbench_zipf_sample(), so a host model reproduces both the
// same way. Inline here rather than in vmbench.c so the programs that do
// not use it keep byte-identical binaries -- and so the same arena
// addresses -- as the ones their traces were collected with.
static inline uint64
vmbench_zipf_sample_cdf(struct vmbench_rng *r, const uint32 *cdf, int n)
{
  uint32 draw = (uint32)vmbench_rng_next(r);
  int lo = 0, hi = n - 1;
  while(lo < hi){
    int mid = lo + (hi - lo) / 2;
    if(cdf[mid] >= draw)
      hi = mid;
    else
      lo = mid + 1;
  }
  return (uint64)lo;
}

// A bucketed table (tools/gen_zipf_table.py --buckets): pick bucket b by
// its exact probability with one draw, exactly as above, then a rank
// uniformly in [start[b], start[b+1]) with a second -- drawn even for a
// one-rank bucket, so every sample costs two draws.
static inline uint64
vmbench_zipf_sample_bucketed(struct vmbench_rng *r, const uint32 *cdf,
                             const uint32 *start, int nbuckets)
{
  uint64 b = vmbench_zipf_sample_cdf(r, cdf, nbuckets);
  return start[b] + vmbench_rng_below(r, start[b + 1] - start[b]);
}

// ---- Seeded permutation of [0, n) -----------------------------------------
// Scatters logical items (pages, nodes, keys) over [0, n) in a seeded
// order without a table: a table would itself be working data, needing
// either a place outside the arena (untraced) or traced lookups that are
// not part of the workload. A balanced Feistel network on the smallest
// even number of bits covering n, with splitmix64's finalizer as the round
// function, made a permutation of [0, n) by cycle-walking: re-encrypt
// until the value lands in range. The walk always ends, because the cycle
// through x contains x itself. Inline for the same reason as the sampler
// above. tools/hostmodel/common.py's Perm is the host model of it.
struct vmbench_perm {
  uint64 n;
  uint64 key;
  int half;    // bits per half
  uint64 mask; // (1 << half) - 1
};

static inline uint64
vmbench_mix64(uint64 z)
{
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}

static inline void
vmbench_perm_init(struct vmbench_perm *pm, uint64 n, uint64 key)
{
  int bits = 2;
  while((1ULL << bits) < n)
    bits++;
  bits += bits & 1;
  pm->n = n;
  pm->key = key;
  pm->half = bits / 2;
  pm->mask = (1ULL << pm->half) - 1;
}

static inline uint64
vmbench_perm_round(const struct vmbench_perm *pm, uint64 v, int round)
{
  return vmbench_mix64(v + pm->key +
                       (uint64)(round + 1) * 0x9E3779B97F4A7C15ULL) &
         pm->mask;
}

// x's position in the seeded order: a value in [0, n).
static inline uint64
vmbench_perm_fwd(const struct vmbench_perm *pm, uint64 x)
{
  do {
    uint64 l = x >> pm->half, r = x & pm->mask;
    for(int i = 0; i < 4; i++){
      uint64 t = l ^ vmbench_perm_round(pm, r, i);
      l = r;
      r = t;
    }
    x = (l << pm->half) | r;
  } while(x >= pm->n);
  return x;
}

// The inverse: vmbench_perm_inv(pm, vmbench_perm_fwd(pm, x)) == x.
static inline uint64
vmbench_perm_inv(const struct vmbench_perm *pm, uint64 x)
{
  do {
    uint64 l = x >> pm->half, r = x & pm->mask;
    for(int i = 3; i >= 0; i--){
      uint64 t = r ^ vmbench_perm_round(pm, l, i);
      r = l;
      l = t;
    }
    x = (l << pm->half) | r;
  } while(x >= pm->n);
  return x;
}

#endif
