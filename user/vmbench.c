// Shared benchmark harness implementation. See vmbench.h for the API
// contract and the reasoning behind each piece.
#include "kernel/types.h"
#include "kernel/vmstats.h"
#include "kernel/vmtrace.h"
#include "user/user.h"
#include "user/vmbench.h"
#include "user/zipf_table.h"

int vmbench_trace_on;

char *
vmbench_arena(int npages)
{
  return sbrklazy(npages * VMBENCH_PGSIZE);
}

void
vmbench_trace_start(const char *workload, const char *params, uint64 seed,
                     char *arena_base, int arena_pages,
                     int arena_cache_budget)
{
  vmctl(VM_PREFETCH_ENABLE, 0);
  struct vmstats s;
  vmbench_snapshot(&s);
  long arena_start_vpn = (long)((uint64)arena_base / VMBENCH_PGSIZE);
  printf("TRACEHDR workload=%s params=%s seed=%ld resident_limit=%ld "
         "arena_cache_budget=%d policy=%ld prefetch_enabled=0 "
         "arena_start_vpn=%ld arena_pages=%d\n",
         workload, params, (long)seed, s.resident_limit,
         arena_cache_budget, s.policy, arena_start_vpn, arena_pages);
  vmbench_trace_on = 1;
}

void
vmbench_trace_stop(void)
{
  vmbench_trace_on = 0;
}

int
vmbench_arena_free(int npages)
{
  return sbrk(-(npages * VMBENCH_PGSIZE)) == SBRK_ERROR ? -1 : 0;
}

void
vmbench_snapshot(struct vmstats *out)
{
  if(vmstats(out) < 0){
    printf("vmbench: vmstats() failed\n");
    exit(1);
  }
}

void
vmbench_reset_and_snapshot(struct vmstats *out)
{
  vmctl(VM_RESET_STATS, 0);
  vmbench_snapshot(out);
}

void
vmbench_delta(const struct vmstats *before, const struct vmstats *after,
              struct vmbench_delta *out)
{
  out->zero_faults = (long)after->zero_faults - (long)before->zero_faults;
  out->swap_faults = (long)after->swap_faults - (long)before->swap_faults;
  out->evictions = (long)after->evictions - (long)before->evictions;
  out->page_reads = (long)after->page_reads - (long)before->page_reads;
  out->page_writes = (long)after->page_writes - (long)before->page_writes;
  out->resident_count = (long)after->resident_count;
  out->free_swap_slots = (long)after->free_swap_slots;
}

void
vmbench_print_delta(const char *label, const struct vmbench_delta *d)
{
  printf("[%s] zero_faults=%ld swap_faults=%ld evictions=%ld "
         "page_reads=%ld page_writes=%ld resident_count=%ld "
         "free_swap_slots=%ld\n",
         label, d->zero_faults, d->swap_faults, d->evictions,
         d->page_reads, d->page_writes, d->resident_count,
         d->free_swap_slots);
}

void
vmbench_result(const char *key, long value)
{
  printf("RESULT %s=%ld\n", key, value);
}

void
vmbench_banner(const char *workload, const char *phase)
{
  printf("\n== %s: %s ==\n", workload, phase);
}

void
vmbench_rng_seed(struct vmbench_rng *r, uint64 seed)
{
  r->state = seed ? seed : 0x9E3779B97F4A7C15ULL;
}

uint64
vmbench_rng_next(struct vmbench_rng *r)
{
  uint64 x = r->state;
  x ^= x << 13;
  x ^= x >> 7;
  x ^= x << 17;
  r->state = x;
  return x;
}

uint64
vmbench_rng_below(struct vmbench_rng *r, uint64 bound)
{
  if(bound == 0)
    return 0;
  return vmbench_rng_next(r) % bound;
}

uint64
vmbench_zipf_sample(struct vmbench_rng *r)
{
  uint32 draw = (uint32)vmbench_rng_next(r);
  int lo = 0, hi = VMBENCH_ZIPF_N - 1;
  while(lo < hi){
    int mid = lo + (hi - lo) / 2;
    if(vmbench_zipf_cdf[mid] >= draw)
      hi = mid;
    else
      lo = mid + 1;
  }
  return (uint64)lo;
}

int
vmbench_burn(char *arena_base, int arena_pages, uint64 *settled_resident)
{
  long arena_start_vpn = (long)arena_base / VMBENCH_PGSIZE;
  // Do not seize the trace ring if something else is already capturing
  // through it (vmdrain, say). Enabling and resetting it here wipes that
  // capture's buffered records and restarts its sequence numbering, and
  // the subsequent vmtrace_read() drain below eats records the other
  // reader never sees. The symptom downstream is a capture reporting
  // dropped=0 alongside sequence gaps -- 86 events vanished from a
  // 150-event capture of btreebench before this check existed.
  //
  // When the ring is already owned, take the best-effort path below
  // instead: the same fallback this function already documents for the
  // case where tracing is unavailable at all.
  struct vmtrace_header hdr;
  int ring_owned_elsewhere = vmtrace_info(&hdr) == 0 && hdr.enabled != 0;
  int tracing = !ring_owned_elsewhere && vmctl(VM_TRACE_ENABLE, 1) == 0;
  if(tracing)
    vmctl(VM_TRACE_RESET, 0);

  // Force a tight temporary budget ourselves -- don't rely on the
  // caller having already set one. If the process is still under
  // whatever limit it started with (possibly unlimited), nothing would
  // ever be evicted no matter how many scratch pages we touch, and the
  // burn could never observe a VICTIM_SELECTED event at all.
  struct vmstats current;
  vmbench_snapshot(&current);
  if(vmctl(VM_SET_LIMIT, (int)current.resident_count) < 0)
    return -1;

  int max_burn = 64;
  char *scratch = vmbench_arena(max_burn);
  if(scratch == SBRK_ERROR)
    return -1;

  if(tracing){
    int reached = 0;
    for(int i = 0; i < max_burn && !reached; i++){
      touch_w(scratch, i, 1);
      struct vmtrace_event ev[8];
      int n;
      while((n = vmtrace_read(ev, 8)) > 0){
        for(int j = 0; j < n; j++){
          // victim_vpn is uint32 as of the vmtrace schema v3 merge (was
          // uint64). A plain (long) cast would zero-extend a real
          // VMTRACE_NONE32 sentinel into a huge positive number instead
          // of -1 -- currently harmless here only because
          // VICTIM_SELECTED's victim_vpn is never actually the sentinel
          // (see kernel/vmpage.c's reclaim_frame()), not because this
          // code accounts for it. Route through the same NONE32 check
          // pagingdemo.c/policydemo.c use, for defense-in-depth.
          long victim_vpn = ev[j].victim_vpn == VMTRACE_NONE32
                               ? -1
                               : (long)ev[j].victim_vpn;
          if(ev[j].type == VMTRACE_VICTIM_SELECTED &&
             victim_vpn >= arena_start_vpn &&
             victim_vpn < arena_start_vpn + arena_pages){
            reached = 1;
            break;
          }
        }
      }
    }
    if(!reached){
      vmbench_arena_free(max_burn);
      return -1;
    }
  } else {
    // Best-effort fallback: no trace ring to prove the burn actually
    // reached the arena, so just touch a generous, fixed number of
    // scratch pages and hope for the best. Callers must warn that this
    // guarantee is weaker than the VM_DEBUG path.
    for(int i = 0; i < max_burn; i++)
      touch_w(scratch, i, 1);
  }

  if(vmbench_arena_free(max_burn) < 0)
    return -1;

  struct vmstats settled;
  vmbench_snapshot(&settled);
  *settled_resident = settled.resident_count;

  return tracing;
}
