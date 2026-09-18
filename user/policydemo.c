// xv6 policy comparison demo.
//
// Runs the identical, deliberately-designed access pattern under FIFO,
// Clock, and Aging in turn, to visibly demonstrate the one thing that
// actually distinguishes them: whether a recently-touched page survives
// an eviction it would otherwise be the natural (oldest) victim for.
//
// Scenario, per policy:
//   1. Touch 4 distinct heap pages (P0..P3), filling a small +4 budget.
//   2. Touch a 5th page (P4) -- forces the first eviction. Every
//      candidate is equally "fresh" at this point (none previously
//      sampled), so every policy picks the same victim here (P0, the
//      oldest by insertion order) -- this round is a clean baseline,
//      not the interesting part.
//   3. Re-touch P1 (still resident) -- an ordinary memory access, not a
//      fault, but it silently sets P1's hardware accessed bit again.
//   4. Touch a 6th page (P5) -- forces a second eviction among the
//      remaining candidates {P1, P2, P3, P4}. THIS is where the
//      policies should diverge:
//        FIFO  ignores recency entirely -- P1 is still the oldest by
//              insertion order, so it should get evicted anyway.
//        Clock should give P1 a "second chance" since it was just
//              touched, and pick a different (cold) candidate instead.
//        Aging should show the same recency-sensitivity via its
//              access-history counter.
//   5. Re-touch P1 again and compare vmstats().swap_faults before/after:
//      if it climbed, P1 was evicted (recency ignored); if not, P1
//      survived (recency respected).
//
// The +4 margin is sized to the heap pages actually used here, not to
// baseline -- unlike pagingdemo.c, which deliberately let the program's
// own code become a victim, this demo keeps baseline pages completely
// out of play so the comparison isn't muddied by anything but policy
// choice.

#include "kernel/types.h"
#include "user/user.h"
#include "kernel/vmstats.h"
#include "kernel/vmtrace.h"

#define PGSIZE 4096

static int tracing;

static const char *
trace_name(uint64 type)
{
  switch(type){
  case VMTRACE_ZERO_FAULT:       return "ZERO_FAULT";
  case VMTRACE_SWAP_FAULT:       return "SWAP_FAULT";
  case VMTRACE_PROTECTION_FAULT: return "PROTECTION_FAULT";
  case VMTRACE_MAP:              return "MAP";
  case VMTRACE_UNMAP:            return "UNMAP";
  case VMTRACE_VICTIM_SELECTED:  return "VICTIM_SELECTED";
  case VMTRACE_EVICT_BEGIN:      return "EVICT_BEGIN";
  case VMTRACE_EVICT_END:        return "EVICT_END";
  case VMTRACE_SWAP_READ_BEGIN:  return "SWAP_READ_BEGIN";
  case VMTRACE_SWAP_READ_END:    return "SWAP_READ_END";
  case VMTRACE_SWAP_WRITE_BEGIN: return "SWAP_WRITE_BEGIN";
  case VMTRACE_SWAP_WRITE_END:   return "SWAP_WRITE_END";
  case VMTRACE_POLICY_FALLBACK:  return "POLICY_FALLBACK";
  case VMTRACE_DROP:             return "TRACE_DROP";
  default:                       return "PREFETCH_OR_OTHER";
  }
}

static long
fld(uint64 v)
{
  return (long)v;
}

static long
fld32(uint32 v)
{
  // Schema v2/v3 (kernel/vmtrace.h, merged from Austra-dev) narrowed most
  // record fields to 32 bits, so a field that does not apply carries
  // VMTRACE_NONE32, not the 64-bit VMTRACE_NONE. fld() above widens a
  // uint32 by zero-extension, so VMTRACE_NONE32 (0xFFFFFFFF) would print
  // as 4294967295 instead of -1 without this -- the same latent bug
  // pagingdemo.c had, fixed there when this schema was merged in.
  return v == VMTRACE_NONE32 ? -1 : (long)v;
}

static void
explain_event(int type, long vpn, long slot, long frame, long victim,
              long status)
{
  printf("      in plain words: ");
  if(type == VMTRACE_ZERO_FAULT){
    printf("page %ld was touched for the first time -- a fresh zeroed "
           "frame (#%ld) was handed to it, no disk involved.\n", vpn, frame);
  } else if(type == VMTRACE_MAP && slot == -1){
    printf("page %ld is now mapped in frame #%ld (a fresh allocation, "
           "not a restore from disk).\n", vpn, frame);
  } else if(type == VMTRACE_MAP){
    printf("page %ld is now mapped in frame #%ld -- restored from swap "
           "slot %ld.\n", vpn, frame, slot);
  } else if(type == VMTRACE_SWAP_FAULT){
    printf("page %ld was touched, but it is on disk in slot %ld. "
           "Starting fetch-back.\n", vpn, slot);
  } else if(type == VMTRACE_VICTIM_SELECTED){
    printf("a frame is needed for page %ld, budget is full -> page %ld "
           "was chosen as the victim (frame #%ld).\n", vpn, victim, frame);
  } else if(type == VMTRACE_EVICT_BEGIN){
    printf("eviction of page %ld (frame #%ld) starting -- locked "
           "against other access until this finishes.\n", vpn, frame);
  } else if(type == VMTRACE_SWAP_WRITE_BEGIN){
    printf("page %ld's contents (frame #%ld) being written to swap "
           "slot %ld.\n", vpn, frame, slot);
  } else if(type == VMTRACE_SWAP_WRITE_END && status == 0){
    printf("disk write of page %ld to slot %ld completed.\n", vpn, slot);
  } else if(type == VMTRACE_SWAP_WRITE_END){
    printf("disk write of page %ld to slot %ld FAILED.\n", vpn, slot);
  } else if(type == VMTRACE_EVICT_END){
    printf("page %ld (frame #%ld) fully replaced -- its data is in slot "
           "%ld, and that frame is being handed to page %ld.\n",
           vpn, frame, slot, victim);
  } else if(type == VMTRACE_SWAP_READ_BEGIN){
    printf("page %ld being read back from slot %ld into frame #%ld.\n",
           vpn, slot, frame);
  } else if(type == VMTRACE_SWAP_READ_END && status == 0){
    printf("disk read of page %ld from slot %ld completed.\n", vpn, slot);
  } else if(type == VMTRACE_SWAP_READ_END){
    printf("disk read of page %ld from slot %ld FAILED.\n", vpn, slot);
  } else if(type == VMTRACE_DROP){
    printf("trace ring was full, an older event was dropped (%ld lost "
           "so far).\n", status);
  } else {
    printf("(no translation written for this event type yet).\n");
  }
}

static void
dump_trace(const char *label)
{
  struct vmtrace_event ev[8];
  int n;

  if(!tracing)
    return;
  printf("\n-- trace events: %s --\n", label);
  while((n = vmtrace_read(ev, 8)) > 0){
    for(int i = 0; i < n; i++){
      printf("  #%ld %s vpn=%ld slot=%ld frame=%ld victim_vpn=%ld status=%d\n",
             fld(ev[i].sequence), trace_name(ev[i].type),
             fld32(ev[i].vpn), fld32(ev[i].swap_slot),
             fld32(ev[i].frame_index), fld32(ev[i].victim_vpn),
             (int)ev[i].status);
      explain_event((int)ev[i].type, fld32(ev[i].vpn), fld32(ev[i].swap_slot),
                    fld32(ev[i].frame_index), fld32(ev[i].victim_vpn),
                    (long)(int)ev[i].status);
    }
  }
  printf("-- end trace --\n");
}

static void
fail(const char *why)
{
  printf("\n*** FAIL: %s ***\n", why);
  exit(1);
}

static const char *
policy_name(int policy)
{
  if(policy == VM_POLICY_FIFO)
    return "FIFO";
  if(policy == VM_POLICY_CLOCK)
    return "Clock";
  if(policy == VM_POLICY_AGING)
    return "Aging";
  return "unknown";
}

// Runs the full scenario under one policy. Returns 1 if P1 (the
// recently re-touched page) survived the second eviction, 0 if it got
// evicted anyway.
static int
run_scenario(int policy)
{
  struct vmstats before, mid, before_second, after_second, before_check,
      after_check;

  printf("\n================================================\n");
  printf("POLICY: %s\n", policy_name(policy));
  printf("================================================\n");

  if(vmstats(&before) < 0)
    fail("vmstats");
  if(vmctl(VM_SET_POLICY, policy) < 0)
    fail("vmctl VM_SET_POLICY");
  int limit = (int)before.resident_count + 4;
  if(vmctl(VM_SET_LIMIT, limit) < 0)
    fail("vmctl VM_SET_LIMIT");
  vmctl(VM_RESET_STATS, 0);

  char *mem = sbrklazy(6 * PGSIZE);
  if(mem == SBRK_ERROR)
    fail("sbrklazy");
  long heap_start_vpn = (long)mem / PGSIZE;

  printf("filling the budget with P0..P3 (4 pages)...\n");
  for(int i = 0; i < 4; i++)
    mem[i * PGSIZE] = (char)(i + 1);

  if(vmstats(&mid) < 0)
    fail("vmstats");

  // Burn phase. The pages this process inherited from exec() were
  // loaded before P0..P3 ever existed, so under FIFO/aging they are
  // unconditionally the oldest thing this process owns -- older than
  // P0..P3 will ever be, no matter how generous a margin the budget
  // gets. Left alone, that means the very first eviction this
  // scenario forces always lands on a leftover startup page, not on
  // the heap pages the comparison is actually about. So: keep
  // touching throwaway scratch pages, under the SAME budget, and
  // watch the trace ring for the moment a victim's vpn finally falls
  // inside the P0..P3 range -- that is the signal that every leftover
  // startup page has been either permanently evicted (genuinely idle
  // ones) or evicted-and-reloaded with a fresh, newer load-order
  // position (ones the CPU is still actively executing), and P0..P3
  // have become the true oldest resident pages. That event *is* the
  // "first eviction, same outcome for every policy" round -- it just
  // needed a variable amount of throwaway preamble to get there,
  // since different builds/policies can leave a different number of
  // startup pages resident.
  int burn_touches = 0;
  {
    int max_burn = 32;
    char *scratch = sbrklazy(max_burn * PGSIZE);
    if(scratch == SBRK_ERROR)
      fail("sbrklazy (burn)");
    int reached_heap = 0;
    for(burn_touches = 0; burn_touches < max_burn && !reached_heap;
        burn_touches++){
      scratch[burn_touches * PGSIZE] = 1;
      struct vmtrace_event ev[8];
      int n;
      while(tracing && (n = vmtrace_read(ev, 8)) > 0){
        for(int j = 0; j < n; j++){
          if(ev[j].type == VMTRACE_VICTIM_SELECTED){
            // fld32(), not a plain (long) cast -- see the identical fix
            // in dump_trace() above and in user/vmbench.c's
            // vmbench_burn(): victim_vpn is uint32 as of the vmtrace
            // schema v3 merge, and a real VMTRACE_NONE32 sentinel would
            // otherwise zero-extend into a huge positive number instead
            // of -1. Currently harmless here (VICTIM_SELECTED's
            // victim_vpn is never actually the sentinel), but this
            // keeps that fact from being load-bearing.
            long victim_vpn = fld32(ev[j].victim_vpn);
            printf("[debug]   burn touch %d: victim vpn=%ld (heap "
                   "range is [%ld,%ld))\n", burn_touches,
                   victim_vpn, heap_start_vpn,
                   heap_start_vpn + 4);
            if(victim_vpn >= heap_start_vpn &&
               victim_vpn < heap_start_vpn + 4)
              reached_heap = 1;
          }
        }
      }
    }
    if(!reached_heap)
      fail("burn phase never reached the heap -- max_burn too small");
    if(sbrk(-max_burn * PGSIZE) == SBRK_ERROR)
      fail("sbrk shrink (burn)");
  }
  printf("burn phase: %d throwaway touches were needed to exhaust "
         "this process's own startup pages -- the last one is the "
         "FIRST eviction (same outcome for every policy: nothing had "
         "a recency edge yet)\n", burn_touches);

  // The burn phase's own cascade just evicted a batch of pages (some
  // never came back), so resident_count is now well under the budget
  // computed at the top of this function -- touching P4 next would
  // just be a free allocation, not the deliberate second eviction
  // this scenario needs. Re-tighten the limit to exactly where things
  // actually stand right now, so P4 has no slack to land in.
  struct vmstats settled;
  if(vmstats(&settled) < 0)
    fail("vmstats");
  if(vmctl(VM_SET_LIMIT, (int)settled.resident_count) < 0)
    fail("vmctl VM_SET_LIMIT (post-burn)");
  vmctl(VM_RESET_STATS, 0);

  printf("re-touching P1 (an ordinary access, no fault) -- silently "
         "marks it recently-used again\n");
  // volatile: a plain read whose result is otherwise unused is fair
  // game for the compiler to delete outright (and, at -O, it did --
  // confirmed by checking the generated code, which had no load
  // instruction here at all). The hardware side effect we actually
  // want (setting the PTE's accessed bit) only happens if the load
  // genuinely executes.
  char refresh = *(volatile char *)(mem + 1 * PGSIZE);
  (void)refresh;

  if(vmstats(&before_second) < 0)
    fail("vmstats");
  printf("touching P4 -- forces a SECOND eviction among {P1,P2,P3}. "
         "This is where %s's real behavior shows.\n", policy_name(policy));
  mem[4 * PGSIZE] = 5;
  dump_trace("second eviction -- this is where policies diverge");

  if(vmstats(&after_second) < 0)
    fail("vmstats");
  printf("evictions caused by touching P4 (stats reset just before "
         "this touch): %ld\n", after_second.evictions);

  printf("re-touching P1 to check whether it survived...\n");
  if(vmstats(&before_check) < 0)
    fail("vmstats");
  char v = mem[1 * PGSIZE];
  if(vmstats(&after_check) < 0)
    fail("vmstats");

  int survived = (after_check.swap_faults == before_check.swap_faults);
  printf("P1 read back as %d (expected 2). swap_faults %ld -> %ld.\n",
         v, before_check.swap_faults, after_check.swap_faults);
  if(v != 2)
    fail("P1's data was not byte-exact -- a correctness bug, not a "
         "policy question");

  printf("RESULT: P1 %s the second eviction.\n",
         survived ? "SURVIVED" : "was EVICTED despite being just touched");

  if(sbrk(-6 * PGSIZE) == SBRK_ERROR)
    fail("sbrk shrink");

  return survived;
}

int
main(void)
{
  printf("xv6 policy comparison demo\n");
  printf("===========================\n");
  printf("Same scenario, three policies: fill a small budget, force one\n");
  printf("eviction (baseline), re-touch one survivor, force a second\n");
  printf("eviction. Does the just-touched page survive, or get evicted\n");
  printf("anyway? That answer is the one thing that actually tells\n");
  printf("FIFO, Clock, and Aging apart.\n");

  tracing = vmctl(VM_TRACE_ENABLE, 1) == 0;
  if(tracing)
    vmctl(VM_TRACE_RESET, 0);
  if(tracing)
    printf("[trace ring enabled]\n");
  else
    printf("[trace ring unavailable -- continuing with counters only]\n");

  int fifo_survived = run_scenario(VM_POLICY_FIFO);
  int clock_survived = run_scenario(VM_POLICY_CLOCK);
  int aging_survived = run_scenario(VM_POLICY_AGING);

  printf("\n================================================\n");
  printf("SUMMARY\n");
  printf("================================================\n");
  printf("FIFO : recently-touched page %s\n",
         fifo_survived ? "SURVIVED (unexpected!)"
                        : "was EVICTED anyway (expected -- FIFO ignores recency)");
  printf("Clock: recently-touched page %s\n",
         clock_survived ? "SURVIVED (expected -- Clock gives a second chance)"
                         : "was EVICTED (unexpected!)");
  printf("Aging: recently-touched page %s\n",
         aging_survived ? "SURVIVED (expected -- Aging respects recency)"
                         : "was EVICTED (unexpected!)");

  if(fifo_survived || !clock_survived || !aging_survived)
    fail("policy behavior did not match expectations -- see SUMMARY above");

  printf("\nALL POLICIES BEHAVED AS EXPECTED.\n");
  exit(0);
}
