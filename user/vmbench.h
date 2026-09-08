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
// "T <vpn>" line -- a full reference stream, not just faults. This is
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
// bt_node(), kvbench's kv_key_ptr(), graphbench's edge_dst()) rather
// than at every call site individually.
extern int vmbench_trace_on;

static inline void
vmbench_trace_ref(char *base, uint64 page)
{
  if(vmbench_trace_on)
    printf("T %ld\n", (long)(((uint64)base + page * VMBENCH_PGSIZE) /
                              VMBENCH_PGSIZE));
}

// ---- Touch primitives -------------------------------------------------
static inline uchar
touch_r(char *base, uint64 page)
{
  uchar v = *(volatile uchar *)(base + page * VMBENCH_PGSIZE);
  vmbench_trace_ref(base, page);
  return v;
}

static inline void
touch_w(char *base, uint64 page, uchar val)
{
  *(volatile uchar *)(base + page * VMBENCH_PGSIZE) = val;
  vmbench_trace_ref(base, page);
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

#endif
