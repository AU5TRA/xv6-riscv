#include "kernel/types.h"
#include "user/user.h"
#include "kernel/vmstats.h"

#define PGSIZE 4096
#define PAGES 40
#define TARGET_PAGE 4
#define TARGET(memory) ((memory) + TARGET_PAGE * PGSIZE)

// Pages of scratch swept after the region is loaded, so that nothing of
// the region can still be resident. Recorded here because finish() has to
// give the memory back.
static int scratch_pages;

static char *
make_swapped(struct vmstats *before)
{
  if(vmstats(before) < 0 || vmctl(VM_PREFETCH_ENABLE, 0) < 0 ||
     vmctl(VM_PREFETCH_MODE, 0) < 0 ||
     vmctl(VM_PREFETCH_AUTOMATIC, 0) < 0 ||
     vmctl(VM_SET_LIMIT, before->resident_count + 5) < 0)
    return SBRK_ERROR;
  // Scratch is allocated first so the region under test stays the topmost
  // allocation: unmap_queued() and shrink_inflight() unmap it with
  // sbrk(-PAGES * PGSIZE) and would otherwise unmap the scratch instead.
  scratch_pages = (int)before->resident_count + 8;
  char *scratch = sbrklazy(scratch_pages * PGSIZE);
  if(scratch == SBRK_ERROR){
    scratch_pages = 0;
    return SBRK_ERROR;
  }
  char *memory = sbrklazy(PAGES * PGSIZE);
  if(memory == SBRK_ERROR)
    return SBRK_ERROR;
  for(int i = 0; i < PAGES; i++)
    memory[i * PGSIZE] = i + 1;

  // Every subtest below assumes the whole region is in swap. Loading it
  // is not enough to guarantee that: the resident limit is relative to
  // the pages the process already holds, so those are eligible victims
  // too and which of the region survives depends on the policy. Sweeping
  // the scratch region -- larger than the limit -- twice afterwards
  // leaves no frame for a region page under FIFO, Clock or Aging.
  for(int pass = 0; pass < 2; pass++)
    for(int i = 0; i < scratch_pages; i++)
      scratch[i * PGSIZE] = (char)(i + pass);

  if(vmctl(VM_PREFETCH_ENABLE, 1) < 0)
    return SBRK_ERROR;
  return memory;
}

static int
finish(char *memory)
{
  (void)memory;
  struct vmstats stats;
  if(vmstats(&stats) < 0 || stats.queued_prefetch != 0 ||
     stats.inflight_io != 0 || vmctl(VM_PREFETCH_ENABLE, 0) < 0 ||
     vmctl(VM_PREFETCH_AUTOMATIC, 0) < 0 ||
     vmctl(VM_PREFETCH_MODE, 0) < 0 ||
     sbrk(-(PAGES + scratch_pages) * PGSIZE) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
wait_idle(struct vmstats *out)
{
  for(int i = 0; i < 200; i++){
    if(vmstats(out) < 0)
      return -1;
    if(out->queued_prefetch == 0 && out->inflight_io == 0)
      return 0;
    pause(1);
  }
  return -1;
}

static int
enable_async(void)
{
  return vmctl(VM_PREFETCH_MODE, 1);
}

static int
sequential(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR){
    printf("sequential: setup failed\n");
    return -1;
  }
  if(vmctl(VM_PREFETCH_AUTOMATIC, 1) < 0)
    return -1;
  char trigger = memory[(TARGET_PAGE - 1) * PGSIZE];
  if(trigger != TARGET_PAGE || TARGET(memory)[0] != TARGET_PAGE + 1 ||
     vmctl(VM_PREFETCH_ENABLE, 0) < 0){
    printf("sequential: trigger=%d value=%d\n", trigger, TARGET(memory)[0]);
    return -1;
  }
  for(int i = 1; i < PAGES; i++)
    if(memory[i * PGSIZE] != i + 1)
      return -1;
  if(vmstats(&after) < 0 || after.prefetch_completed == 0 ||
     after.prefetch_useful == 0){
    printf("sequential: completed=%ld useful=%ld wasted=%ld\n",
           after.prefetch_completed, after.prefetch_useful,
           after.prefetch_wasted);
    return -1;
  }
  return finish(memory);
}

static int
duplicate(void)
{
  struct vmstats before, queued, after;
  char *memory = make_swapped(&before);
  int h1 = memory == SBRK_ERROR ? -1 :
    vmprefetch((uint64)TARGET(memory), 0);
  int h2 = vmprefetch((uint64)TARGET(memory), 0);
  int h3 = vmprefetch((uint64)TARGET(memory), 0);
  if(memory == SBRK_ERROR || h1 < 0 || h2 < 0 || h3 < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 0) < 0 ||
     vmstats(&queued) < 0 ||
     queued.prefetch_accepted != before.prefetch_accepted + 1 ||
     queued.prefetch_coalesced < before.prefetch_coalesced + 2){
    printf("duplicate: hints %d/%d/%d accepted %ld/%ld coalesced %ld/%ld\n",
           h1, h2, h3, queued.prefetch_accepted, before.prefetch_accepted,
           queued.prefetch_coalesced, before.prefetch_coalesced);
    return -1;
  }
  int serviced = vmprefetch(VM_PREFETCH_NO_HINT, 1);
  if(serviced != 1 || vmstats(&after) < 0 ||
     after.page_reads != queued.page_reads + 1){
    printf("duplicate: serviced %d reads %ld/%ld\n", serviced,
           after.page_reads, queued.page_reads);
    return -1;
  }
  return finish(memory);
}

static int
invalid(void)
{
  struct vmstats before, baseline, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR)
    return -1;
  char *hole = sbrklazy(3 * PGSIZE);
  uint64 lazyva = ((uint64)hole + PGSIZE - 1) & ~(uint64)(PGSIZE - 1);
  char resident = memory[(PAGES - 1) * PGSIZE];
  if(vmstats(&baseline) < 0)
    return -1;
  int lazy_result = vmprefetch(lazyva + PGSIZE, 0);
  int outside_result = vmprefetch((uint64)hole + 4 * PGSIZE, 0);
  int resident_result = vmprefetch(
    (uint64)memory + (PAGES - 1) * PGSIZE, 0);
  if(hole == SBRK_ERROR || resident != PAGES || lazy_result >= 0 ||
     outside_result >= 0 || resident_result >= 0 ||
     vmctl(VM_PREFETCH_ENABLE, 0) < 0 || vmstats(&after) < 0 ||
     after.prefetch_issued != baseline.prefetch_issued ||
     after.prefetch_dropped_invalid < baseline.prefetch_dropped_invalid + 3 ||
     sbrk(-3 * PGSIZE) == SBRK_ERROR){
    printf("invalid: results %d/%d/%d resident=%d drops=%ld/%ld reads=%ld/%ld\n",
           lazy_result, outside_result, resident_result, resident,
           after.prefetch_dropped_invalid, baseline.prefetch_dropped_invalid,
           after.prefetch_issued, baseline.prefetch_issued);
    return -1;
  }
  return finish(memory);
}

static int
waste(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || vmprefetch((uint64)TARGET(memory), 1) != 1 ||
     vmctl(VM_PREFETCH_ENABLE, 0) < 0)
    return -1;
  for(int i = 1; i < PAGES; i++){
    if(i == TARGET_PAGE)
      continue;
    if(memory[i * PGSIZE] != i + 1)
      return -1;
  }
  if(vmstats(&after) < 0 || after.prefetch_wasted == 0)
    return -1;
  return finish(memory);
}

static int
pressure(void)
{
  struct vmstats before, queued, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR)
    return -1;
  for(int i = 0; i < 24; i++)
    vmprefetch((uint64)memory + i * PGSIZE, 0);
  if(vmctl(VM_PREFETCH_ENABLE, 0) < 0 || vmstats(&queued) < 0 ||
     queued.queued_prefetch > 16 ||
     queued.prefetch_dropped_pressure == 0 ||
     vmprefetch(VM_PREFETCH_NO_HINT, 16) <= 0 || vmstats(&after) < 0 ||
     after.queued_prefetch != 0 || after.inflight_io != 0 || memory[0] != 1)
    return -1;
  return finish(memory);
}

static int
demand_race(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || enable_async() < 0 ||
     vmprefetch((uint64)TARGET(memory), 0) < 0 ||
     vmfailinject(VM_FAIL_DELAY_TICKS, 10) < 0 ||
     vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1 ||
     TARGET(memory)[0] != TARGET_PAGE + 1 || wait_idle(&after) < 0 ||
     after.prefetch_completed <= before.prefetch_completed ||
     after.prefetch_late <= before.prefetch_late)
    return -1;
  return finish(memory);
}

static int
fork_race(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || enable_async() < 0 ||
     vmprefetch((uint64)TARGET(memory), 0) < 0 ||
     vmfailinject(VM_FAIL_DELAY_TICKS, 20) < 0 ||
     vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1)
    return -1;
  // TARGET(memory)'s PTE is now SWAPPED|BUSY: the async worker has an
  // in-flight, deliberately slow fetch on it. fork() must wait for that
  // fetch to resolve rather than failing the whole copy.
  int pid = fork();
  if(pid < 0){
    printf("fork-race: fork failed while a fetch was in flight\n");
    return -1;
  }
  if(pid == 0){
    int ok = TARGET(memory)[0] == TARGET_PAGE + 1;
    for(int i = 0; i < PAGES; i++)
      if(memory[i * PGSIZE] != i + 1)
        ok = 0;
    exit(ok && vmcheck() == 0 ? 0 : 1);
  }
  int status;
  if(wait(&status) != pid || status != 0 ||
     TARGET(memory)[0] != TARGET_PAGE + 1 || wait_idle(&after) < 0 ||
     after.prefetch_completed <= before.prefetch_completed)
    return -1;
  return finish(memory);
}

static int
unmap_queued(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || enable_async() < 0 ||
     vmprefetch((uint64)TARGET(memory), 0) < 0 ||
     vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1 ||
     sbrk(-PAGES * PGSIZE) == SBRK_ERROR || vmstats(&after) < 0 ||
     after.queued_prefetch != 0 || after.inflight_io != 0 ||
     after.prefetch_canceled <= before.prefetch_canceled ||
     vmctl(VM_PREFETCH_MODE, 0) < 0 ||
     sbrk(-scratch_pages * PGSIZE) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
shrink_inflight(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || enable_async() < 0 ||
     vmprefetch((uint64)TARGET(memory), 0) < 0 ||
     vmfailinject(VM_FAIL_DELAY_TICKS, 10) < 0 ||
     vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1 ||
     sbrk(-PAGES * PGSIZE) == SBRK_ERROR || vmstats(&after) < 0 ||
     after.queued_prefetch != 0 || after.inflight_io != 0 ||
     after.prefetch_canceled <= before.prefetch_canceled ||
     vmctl(VM_PREFETCH_MODE, 0) < 0 ||
     sbrk(-scratch_pages * PGSIZE) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
io_error(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || enable_async() < 0 ||
     vmprefetch((uint64)TARGET(memory), 0) < 0 ||
     vmfailinject(VM_FAIL_SWAP_READ, 1) < 0 ||
     vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1 || wait_idle(&after) < 0 ||
     TARGET(memory)[0] != TARGET_PAGE + 1 ||
     after.prefetch_read_errors <= before.prefetch_read_errors)
    return -1;
  return finish(memory);
}

static int
exit_inflight(void)
{
  struct vmstats baseline, after;
  if(vmstats(&baseline) < 0)
    return -1;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    struct vmstats child;
    char *memory = make_swapped(&child);
    if(memory == SBRK_ERROR || enable_async() < 0 ||
       vmprefetch((uint64)TARGET(memory), 0) < 0 ||
       vmfailinject(VM_FAIL_DELAY_TICKS, 10) < 0 ||
       vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1)
      exit(1);
    exit(0);
  }
  int status;
  if(wait(&status) != pid || status != 0 || vmstats(&after) < 0 ||
     after.free_swap_slots != baseline.free_swap_slots)
    return -1;
  return vmcheck();
}

static int
kill_inflight(void)
{
  struct vmstats baseline, after;
  int fds[2];
  if(vmstats(&baseline) < 0 || pipe(fds) < 0)
    return -1;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    close(fds[0]);
    struct vmstats child;
    char *memory = make_swapped(&child);
    char ready = 'r';
    if(memory == SBRK_ERROR || enable_async() < 0 ||
       vmprefetch((uint64)TARGET(memory), 0) < 0 ||
       vmfailinject(VM_FAIL_DELAY_TICKS, 20) < 0 ||
       vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1 ||
       write(fds[1], &ready, 1) != 1)
      exit(1);
    for(;;)
      pause(10);
  }
  close(fds[1]);
  char ready;
  int status;
  if(read(fds[0], &ready, 1) != 1 || ready != 'r' || kill(pid) < 0 ||
     wait(&status) != pid || vmstats(&after) < 0 ||
     after.free_swap_slots != baseline.free_swap_slots)
    return -1;
  close(fds[0]);
  return vmcheck();
}

static int
duplicate_race(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || enable_async() < 0 ||
     vmprefetch((uint64)TARGET(memory), 0) < 0 ||
     vmfailinject(VM_FAIL_DELAY_TICKS, 10) < 0 ||
     vmprefetch(VM_PREFETCH_NO_HINT, 1) != 1 ||
     vmprefetch((uint64)TARGET(memory), 0) >= 0 ||
     TARGET(memory)[0] != TARGET_PAGE + 1 || wait_idle(&after) < 0 ||
     after.prefetch_issued != before.prefetch_issued + 1 ||
     after.prefetch_coalesced <= before.prefetch_coalesced)
    return -1;
  return finish(memory);
}

static int
worker_stress(void)
{
  struct vmstats before, after;
  char *memory = make_swapped(&before);
  if(memory == SBRK_ERROR || enable_async() < 0)
    return -1;
  for(int i = 0; i < 20; i++)
    vmprefetch((uint64)memory + i * PGSIZE, 0);
  if(vmprefetch(VM_PREFETCH_NO_HINT, 16) <= 0 || wait_idle(&after) < 0 ||
     after.prefetch_completed <= before.prefetch_completed)
    return -1;
  for(int i = 0; i < PAGES; i++)
    if(memory[i * PGSIZE] != i + 1)
      return -1;
  return finish(memory);
}

static int
run(char *name)
{
  if(strcmp(name, "harness") == 0)
    return 0;
  if(strcmp(name, "sequential") == 0)
    return sequential();
  if(strcmp(name, "duplicate") == 0)
    return duplicate();
  if(strcmp(name, "invalid") == 0)
    return invalid();
  if(strcmp(name, "waste") == 0)
    return waste();
  if(strcmp(name, "pressure") == 0)
    return pressure();
  if(strcmp(name, "demand-race") == 0)
    return demand_race();
  if(strcmp(name, "fork-race") == 0)
    return fork_race();
  if(strcmp(name, "unmap-queued") == 0)
    return unmap_queued();
  if(strcmp(name, "shrink-inflight") == 0)
    return shrink_inflight();
  if(strcmp(name, "exit-inflight") == 0)
    return exit_inflight();
  if(strcmp(name, "kill-inflight") == 0)
    return kill_inflight();
  if(strcmp(name, "io-error") == 0)
    return io_error();
  if(strcmp(name, "duplicate-race") == 0)
    return duplicate_race();
  if(strcmp(name, "worker-stress") == 0)
    return worker_stress();
  if(strcmp(name, "all") == 0){
    printf("prefetchtest: all: synchronous\n");
    if(sequential() < 0 || duplicate() < 0 || invalid() < 0 || waste() < 0 ||
       pressure() < 0)
      return -1;
    printf("prefetchtest: all: asynchronous\n");
#ifdef VM_DEBUG
    printf("  demand-race\n");
    if(demand_race() < 0)
      return -1;
    printf("  fork-race\n");
    if(fork_race() < 0)
      return -1;
    printf("  unmap-queued\n");
    if(unmap_queued() < 0)
      return -1;
    printf("  shrink-inflight\n");
    if(shrink_inflight() < 0)
      return -1;
    printf("  exit-inflight\n");
    if(exit_inflight() < 0)
      return -1;
    printf("  kill-inflight\n");
    if(kill_inflight() < 0)
      return -1;
    printf("  io-error\n");
    if(io_error() < 0)
      return -1;
    printf("  duplicate-race\n");
    if(duplicate_race() < 0)
      return -1;
    printf("  worker-stress\n");
    if(worker_stress() < 0)
      return -1;
#else
    if(unmap_queued() < 0 || worker_stress() < 0)
      return -1;
#endif
    return 0;
  }
  return -1;
}

int
main(int argc, char **argv)
{
  char *name = argc > 1 ? argv[1] : "harness";

  // Optional second argument forces a replacement policy for this run,
  // mirroring "vmtest all-policy <policy>". Every subtest here allocates
  // and evicts in this process (or in children that inherit vm state at
  // fork), so setting it once up front covers the whole run.
  if(argc > 2){
    int policy = -1;
    if(strcmp(argv[2], "fifo") == 0)
      policy = VM_POLICY_FIFO;
    else if(strcmp(argv[2], "clock") == 0)
      policy = VM_POLICY_CLOCK;
    else if(strcmp(argv[2], "aging") == 0)
      policy = VM_POLICY_AGING;
    if(policy < 0 || vmctl(VM_SET_POLICY, policy) < 0){
      printf("prefetchtest: %s: FAIL\n", name);
      exit(1);
    }
  }

  if(run(name) < 0){
    printf("prefetchtest: %s: FAIL\n", name);
    exit(1);
  }
  printf("prefetchtest: %s: PASS\n", name);
  exit(0);
}
