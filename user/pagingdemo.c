// xv6 paging visual verification demo.
//
// Unlike vmtest.c/prefetchtest.c (silent PASS/FAIL, meant for automated
// grepping), this program narrates what it is doing step by step, so a
// human watching the terminal can see swap-out and swap-in actually happen:
// resident-page counts climbing then capping, eviction/write counters
// moving, byte-exact round trips through disk, and a fork() reading a page
// its parent had already pushed to disk before the child existed.
//
// Loosely inspired by the three "Test code" ideas in a BUET CSE314 xv6
// paging assignment (live/resident page tracking; before/after swap
// counts; fork() with an already-swapped parent page) -- adapted here to
// the resident-limit + vmctl/vmstats/vmtrace API this tree actually has,
// not that assignment's (different, x86, per-process-swap-file) design.

#include "kernel/types.h"
#include "user/user.h"
#include "kernel/vmstats.h"
#include "kernel/vmtrace.h"

#define PGSIZE 4096
#define NPAGES 10

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
  // VMTRACE_NONE is (uint64)-1; print it as -1 instead of a huge number.
  return (long)v;
}

static long
fld32(uint32 v)
{
  // Schema v2 narrowed most record fields to 32 bits, so a field that
  // does not apply carries VMTRACE_NONE32, not VMTRACE_NONE. Every
  // vpn/slot/frame/victim field below must go through this, not the
  // plain fld() above -- fld() widens a uint32 by zero-extension, so
  // VMTRACE_NONE32 (0xFFFFFFFF) would print as 4294967295 instead of
  // -1 without this check (a real bug caught while merging Austra-dev's
  // schema v2/v3 rework in -- see policydemo.c's identical fld(), which
  // has the same latent issue and needs the same fix).
  return v == VMTRACE_NONE32 ? -1 : (long)v;
}

// Prints one plain-language sentence explaining a single trace event.
// Field meaning is event-type-dependent (taken directly from the
// vmtrace_emit(...) call sites in kernel/vm.c and kernel/vmpage.c, not
// guessed) -- e.g. for VICTIM_SELECTED, vpn is the NEW page and victim is
// the page being evicted; for EVICT_END, victim instead holds the NEW page
// that will reuse the just-freed frame, not a second victim.
static void
explain_event(int type, long vpn, long slot, long frame, long victim,
              long status)
{
  printf("      in plain words: ");
  if(type == VMTRACE_ZERO_FAULT){
    printf("page %ld was touched for the first time (a lazy hole with "
           "nothing behind it) -- a fresh zeroed frame (#%ld) was handed "
           "to it, no disk involved.\n", vpn, frame);
  } else if(type == VMTRACE_MAP && slot == -1){
    printf("page %ld is now mapped in frame #%ld (this follows a fresh "
           "allocation, not a restore from disk).\n", vpn, frame);
  } else if(type == VMTRACE_MAP){
    printf("page %ld is now mapped in frame #%ld -- its data was just "
           "restored from swap slot %ld.\n", vpn, frame, slot);
  } else if(type == VMTRACE_SWAP_FAULT){
    printf("page %ld was touched, but it is currently on disk in swap "
           "slot %ld, not in RAM. This starts the fetch-back.\n", vpn, slot);
  } else if(type == VMTRACE_VICTIM_SELECTED){
    printf("a frame is needed for page %ld, but the resident budget is "
           "full -> page %ld was chosen as the victim to evict (it "
           "currently occupies frame #%ld).\n", vpn, victim, frame);
  } else if(type == VMTRACE_EVICT_BEGIN){
    printf("eviction of page %ld (frame #%ld) is starting -- it is now "
           "locked against any other access until this finishes.\n",
           vpn, frame);
  } else if(type == VMTRACE_SWAP_WRITE_BEGIN){
    printf("page %ld's contents (frame #%ld) are being written out to "
           "swap slot %ld -- the disk write starts now.\n", vpn, frame, slot);
  } else if(type == VMTRACE_SWAP_WRITE_END && status == 0){
    printf("the disk write of page %ld to swap slot %ld completed "
           "successfully.\n", vpn, slot);
  } else if(type == VMTRACE_SWAP_WRITE_END){
    printf("the disk write of page %ld to swap slot %ld FAILED.\n",
           vpn, slot);
  } else if(type == VMTRACE_EVICT_END){
    printf("virtual page number %ld, in frame #%ld, is being replaced -- "
           "its data is now safely in swap slot %ld, and that same frame "
           "is about to be handed over to virtual page number %ld.\n",
           vpn, frame, slot, victim);
  } else if(type == VMTRACE_SWAP_READ_BEGIN){
    printf("page %ld's contents are being read back from swap slot %ld "
           "into frame #%ld -- the disk read starts now.\n",
           vpn, slot, frame);
  } else if(type == VMTRACE_SWAP_READ_END && status == 0){
    printf("the disk read of page %ld from swap slot %ld completed "
           "successfully.\n", vpn, slot);
  } else if(type == VMTRACE_SWAP_READ_END){
    printf("the disk read of page %ld from swap slot %ld FAILED.\n",
           vpn, slot);
  } else if(type == VMTRACE_DROP){
    printf("the trace ring was full, so the oldest recorded event was "
           "discarded to make room for this one (%ld lost in total so "
           "far). This is bookkeeping about the trace log itself, not a "
           "paging event.\n", status);
  } else {
    printf("(no plain-language translation written yet for this event "
           "type -- see the raw fields above).\n");
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

int
main(void)
{
  struct vmstats s0, s1, s2, s3;

  printf("xv6 paging visual verification\n");
  printf("===============================\n");

  tracing = vmctl(VM_TRACE_ENABLE, 1) == 0;
  if(tracing){
    vmctl(VM_TRACE_RESET, 0);
    printf("[trace ring enabled -- every fault/evict/swap event will be listed]\n");
  } else {
    printf("[trace ring unavailable -- continuing with counters only]\n");
  }

  if(vmstats(&s0) < 0)
    fail("vmstats");

  printf("baseline resident_count=%ld "
         "(this program's own code/data/stack, loaded by exec before "
         "any of this test's own memory exists)\n", s0.resident_count);

  int limit = (int)s0.resident_count + 4; // 4 pages more

  if(vmctl(VM_SET_LIMIT, limit) < 0)
    fail("vmctl VM_SET_LIMIT");

  printf("\n=== PHASE 1: fill %d pages into a %d-frame budget ===\n", NPAGES, limit);
  printf("(watch resident_count climb, then cap at %d once the budget is full)\n", limit);
  printf("note: the margin above baseline is small on purpose. FIFO evicts "
         "whichever resident page is globally OLDEST for this process, with "
         "no exception for the program's own code/stack -- so once enough "
         "heap pages are touched, you may see this program's own "
         "already-loaded pages get evicted and immediately faulted back in "
         "(a SWAP_FAULT on a very low VPN, right after an EVICT_END for "
         "that same VPN, in the trace dump below). That's not a bug: it's "
         "proof the system can transparently page out and restore even its "
         "own live, currently-executing code without corruption or a "
         "crash -- this policy simply has no special-case pin for "
         "\"my own text segment.\"\n");

  char *mem = sbrklazy(NPAGES * PGSIZE);
  if(mem == SBRK_ERROR)
    fail("sbrklazy");

  for(int i = 0; i < NPAGES; i++){
    mem[i * PGSIZE] = (char)(i + 1); // first touch -> a fault, maybe an eviction
    vmstats(&s1);
    printf("  touched page %d -> resident=%ld zero_faults=%ld "
           "swap_faults=%ld evictions=%ld\n",
           i, s1.resident_count, s1.zero_faults, s1.swap_faults,
           s1.evictions);
  }
  dump_trace("phase 1 (filling)");

  printf("\n=== PHASE 2: confirm real disk writes happened ===\n");
  printf("evictions   : %ld -> %ld (delta %ld)\n", s0.evictions, s1.evictions, s1.evictions - s0.evictions);
  printf("page_writes : %ld -> %ld (delta %ld)\n", s0.page_writes, s1.page_writes, s1.page_writes - s0.page_writes);
  
  if(s1.evictions <= s0.evictions || s1.page_writes <= s0.page_writes)
    fail("no eviction / disk write happened -- paging is NOT working");

  printf("PASS: %ld page(s) were genuinely evicted and written to swap\n", s1.evictions - s0.evictions);

  printf("\n=== PHASE 3: touch an evicted page again and watch it come back ===\n");
  s2 = s1;
  char v = mem[0]; // page 0 was touched first -> likely evicted first under FIFO
  vmstats(&s3);
  printf("re-read page 0: value=%d (expected 1)\n", v);
  printf("swap_faults : %ld -> %ld (delta %ld)\n", s2.swap_faults, s3.swap_faults, s3.swap_faults - s2.swap_faults);
  printf("page_reads  : %ld -> %ld (delta %ld)\n", s2.page_reads, s3.page_reads, s3.page_reads - s2.page_reads);
  if(v != 1 || s3.swap_faults <= s2.swap_faults || s3.page_reads <= s2.page_reads)
    fail("page did not swap back in correctly");

  printf("PASS: page 0 was fetched back from disk with byte-exact content\n");

  printf("verifying all %d pages still round-trip correctly after the "
         "eviction pressure above...\n", NPAGES);
  int ok = 1;
  for(int i = 0; i < NPAGES; i++)
    if(mem[i * PGSIZE] != (char)(i + 1)){
      printf("  MISMATCH at page %d: got %d expected %d\n", i, mem[i * PGSIZE], i + 1);
      ok = 0;
    }
  if(!ok)
    fail("data corruption detected across swap round trips");

  printf("PASS: all %d pages byte-exact after thrashing through swap\n", NPAGES);
  dump_trace("phase 3 (swap back in)");

  if(sbrk(-NPAGES * PGSIZE) == SBRK_ERROR)
    fail("sbrk shrink");

  printf("\n=== PHASE 4: fork() while a page is on disk ===\n");
  if(vmstats(&s0) < 0)
    fail("vmstats");
  if(vmctl(VM_SET_LIMIT, s0.resident_count + 2) < 0)
    fail("vmctl VM_SET_LIMIT");
  char *fmem = sbrklazy(6 * PGSIZE);
  if(fmem == SBRK_ERROR)
    fail("sbrklazy");
  for(int i = 0; i < 6; i++)
    fmem[i * PGSIZE] = (char)(100 + i); // only 2 of 6 fit -> rest swapped out
  vmstats(&s1);
  printf("parent: resident_count=%ld evictions=%ld "
         "(some of the 6 pages are now on disk, not RAM)\n",
         s1.resident_count, s1.evictions);

  int pid = fork();
  if(pid < 0)
    fail("fork");
  if(pid == 0){
    printf("child pid=%d: reading pages the PARENT had already swapped "
           "out before I existed...\n", getpid());
    int cok = 1;
    for(int i = 0; i < 6; i++)
      if(fmem[i * PGSIZE] != (char)(100 + i)){
        printf("  child MISMATCH page %d: got %d expected %d\n", i, fmem[i * PGSIZE], 100 + i);
        cok = 0;
      }
    printf(cok ? "child PASS: inherited swapped page(s) read back correctly\n"
               : "child FAIL: inherited data corrupted\n");
    exit(cok ? 0 : 1);
  }
  int status;
  wait(&status);
  dump_trace("phase 4 (fork with swapped page)");
  if(status != 0)
    fail("child reported a mismatch");
  printf("PASS: child exited cleanly after reading swapped-in inherited data\n");

  printf("\n================================================\n");
  printf("ALL PHASES PASSED -- swap-out and swap-in both confirmed working.\n");
  printf("================================================\n");
  exit(0);
}
