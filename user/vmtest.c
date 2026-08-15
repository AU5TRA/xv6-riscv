#include "kernel/types.h"
#include "user/user.h"
#include "kernel/vmstats.h"
#include "kernel/swap.h"
#include "kernel/vmtrace.h"

static int requested_policy = VM_POLICY_FIFO;
static uint requested_seed = 1;
static int requested_iterations = 10000;

static int
trace_schema(void)
{
  if(vmctl(VM_TRACE_ENABLE, 0) < 0 || vmctl(VM_TRACE_RESET, 0) < 0)
    return -1;
  char *output_memory = sbrklazy(3 * 4096);
  char *fault_memory = sbrklazy(4096);
  if(output_memory == SBRK_ERROR || fault_memory == SBRK_ERROR ||
     vmctl(VM_TRACE_ENABLE, 1) < 0)
    return -1;
  fault_memory[0] = 7;
  if(vmctl(VM_TRACE_ENABLE, 0) < 0)
    return -1;

  // One record straddles two initially-lazy output pages. vmtrace_read must
  // release the trace lock before copyout faults those pages in.
  struct vmtrace_event *events = (struct vmtrace_event *)
    (output_memory + 4096 - 80);
  int count = vmtrace_read(events, 2);
  int saw_fault = 0;
  if(count != 2)
    return -1;
  for(int i = 0; i < count; i++){
    if(events[i].version != VMTRACE_VERSION ||
       events[i].size != sizeof(struct vmtrace_event) ||
       events[i].type == 0 || events[i].type >= VMTRACE_TYPE_COUNT ||
       (i && events[i].sequence <= events[i - 1].sequence))
      return -1;
    if(events[i].type == VMTRACE_ZERO_FAULT ||
       events[i].type == VMTRACE_MAP)
      saw_fault = 1;
  }
  if(!saw_fault || sbrk(-4 * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
trace_overflow(int require_drop)
{
  struct vmstats before;
  if(vmctl(VM_TRACE_ENABLE, 0) < 0 || vmctl(VM_TRACE_RESET, 0) < 0 ||
     vmstats(&before) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 4) < 0)
    return -1;
  char *memory = sbrklazy(80 * 4096);
  if(memory == SBRK_ERROR || vmctl(VM_TRACE_ENABLE, 1) < 0)
    return -1;
  for(int i = 0; i < 80; i++)
    memory[i * 4096] = i;
  if(vmctl(VM_TRACE_ENABLE, 0) < 0)
    return -1;

  struct vmtrace_event batch[VMTRACE_READ_MAX];
  uint64 previous = 0;
  int total = 0;
  int saw_drop = 0;
  for(;;){
    int count = vmtrace_read(batch, VMTRACE_READ_MAX);
    if(count < 0)
      return -1;
    if(count == 0)
      break;
    total += count;
    for(int i = 0; i < count; i++){
      if(batch[i].sequence <= previous)
        return -1;
      previous = batch[i].sequence;
      if(batch[i].type == VMTRACE_DROP && batch[i].status > 0)
        saw_drop = 1;
    }
  }
  if(total != VMTRACE_CAPACITY || (require_drop && !saw_drop) ||
     sbrk(-80 * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
trace_disabled(void)
{
  struct vmtrace_event event;
  if(vmctl(VM_TRACE_ENABLE, 0) < 0 || vmctl(VM_TRACE_RESET, 0) < 0)
    return -1;
  char *memory = sbrklazy(4096);
  if(memory == SBRK_ERROR)
    return -1;
  memory[0] = 1;
  if(vmtrace_read(&event, 1) != 0 || sbrk(-4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
harness(void)
{
  return 0;
}

static int
controls(void)
{
  struct vmstats stats;

  if(vmstats(&stats) < 0 || stats.version != VMSTATS_VERSION ||
     stats.resident_limit != VM_LIMIT_UNLIMITED ||
     stats.policy != VM_POLICY_FIFO || stats.prefetch_enabled != 0)
    return -1;
  if(vmctl(VM_SET_LIMIT, 8) < 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_CLOCK) < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 1) < 0)
    return -1;
  if(vmctl(VM_SET_LIMIT, VM_MAX_RESIDENT_LIMIT + 1) == 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_COUNT) == 0 ||
     vmctl(VM_PREFETCH_ENABLE, 2) == 0 || vmctl(999, 0) == 0)
    return -1;
  if(vmstats(&stats) < 0 || stats.resident_limit != 8 ||
     stats.policy != VM_POLICY_CLOCK || stats.prefetch_enabled != 1)
    return -1;
  return vmcheck();
}

static int
inherit(void)
{
  int status;
  if(vmctl(VM_SET_LIMIT, 7) < 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_AGING) < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 1) < 0)
    return -1;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    struct vmstats stats;
    int ok = vmstats(&stats) == 0 && stats.resident_limit == 7 &&
      stats.policy == VM_POLICY_AGING && stats.prefetch_enabled == 1 &&
      vmcheck() == 0;
    exit(ok ? 0 : 1);
  }
  if(wait(&status) != pid || status != 0)
    return -1;
  return vmcheck();
}

static int
limit_basic(void)
{
  struct vmstats before, after;
  if(vmstats(&before) < 0 || before.resident_count + 8 >
     VM_MAX_RESIDENT_LIMIT)
    return -1;
  if(vmctl(VM_SET_LIMIT, before.resident_count + 8) < 0)
    return -1;
  char *base = sbrk(16 * 4096);
  if(base == SBRK_ERROR)
    return -1;
  for(int i = 0; i < 16; i++)
    base[i * 4096] = i + 1;
  for(int i = 0; i < 16; i++)
    if(base[i * 4096] != i + 1)
      return -1;
  if(vmstats(&after) < 0 || after.resident_count > after.resident_limit ||
     after.evictions <= before.evictions)
    return -1;
  if(sbrk(-16 * 4096) == SBRK_ERROR || vmstats(&after) < 0 ||
     after.resident_count > after.resident_limit)
    return -1;
  return vmcheck();
}

static uchar
page_byte(int page, int offset)
{
  return (uchar)((page * 29 + offset * 7 + 3) % 251);
}

static int
lazy_zero(void)
{
  struct vmstats before, holes, after;
  if(vmstats(&before) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 4) < 0)
    return -1;
  char *memory = sbrklazy(32 * 4096);
  if(memory == SBRK_ERROR || vmstats(&holes) < 0 ||
     holes.resident_count != before.resident_count ||
     holes.free_swap_slots != before.free_swap_slots)
    return -1;
  if(memory[0] != 0 || memory[17 * 4096 + 123] != 0)
    return -1;
  if(vmstats(&after) < 0 || after.resident_count != before.resident_count + 2)
    return -1;
  if(sbrk(-32 * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
check_pages(uchar *memory, int pages, int reverse)
{
  for(int n = 0; n < pages; n++){
    int page = reverse ? pages - n - 1 : n;
    for(int offset = 0; offset < 4096; offset += 97)
      if(memory[page * 4096 + offset] != page_byte(page, offset))
        return -1;
  }
  return 0;
}

static int
swap_pattern_passes(int passes)
{
  const int pages = 64;
  struct vmstats before, after;
  if(vmstats(&before) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 8) < 0)
    return -1;
  uchar *memory = (uchar *)sbrklazy(pages * 4096);
  if((char *)memory == SBRK_ERROR)
    return -1;
  for(int page = 0; page < pages; page++)
    for(int offset = 0; offset < 4096; offset += 97)
      memory[page * 4096 + offset] = page_byte(page, offset);
  for(int pass = 0; pass < passes; pass++){
    if(check_pages(memory, pages, pass & 1) < 0)
      return -1;
  }
  uint seed = 0x2105069;
  for(int i = 0; i < 512; i++){
    seed = seed * 1664525 + 1013904223;
    int page = seed % pages;
    int offset = ((seed >> 8) % 42) * 97;
    if(memory[page * 4096 + offset] != page_byte(page, offset))
      return -1;
  }
  if(vmstats(&after) < 0 || after.evictions == 0 || after.swap_faults == 0 ||
     after.resident_count > after.resident_limit)
    return -1;
  if(sbrk(-pages * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
swap_full(void)
{
  struct vmstats baseline, after;
  if(vmstats(&baseline) < 0 || vmtestop(VM_TEST_SWAP_RESERVE, 8) < 0)
    return -1;
  int pid = fork();
  if(pid < 0){
    vmtestop(VM_TEST_SWAP_RELEASE, 0);
    return -1;
  }
  if(pid == 0){
    struct vmstats child;
    if(vmstats(&child) < 0 ||
       vmctl(VM_SET_LIMIT, child.resident_count + 2) < 0)
      exit(2);
    char *memory = sbrklazy(64 * 4096);
    if(memory == SBRK_ERROR)
      exit(3);
    for(int i = 0; i < 64; i++)
      memory[i * 4096] = i;
    exit(0); // Reaching this point means exhaustion was not enforced.
  }
  int status;
  int waited = wait(&status);
  int released = vmtestop(VM_TEST_SWAP_RELEASE, 0);
  if(waited != pid || status == 0 || released < 0 || vmstats(&after) < 0 ||
     after.free_swap_slots != baseline.free_swap_slots)
    return -1;
  return vmcheck();
}

static __attribute__((noinline)) int
permissions(void)
{
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    struct vmstats child;
    if(vmstats(&child) < 0 ||
       vmctl(VM_SET_LIMIT, child.resident_count + 4) < 0)
      exit(2);
    char *memory = sbrklazy(48 * 4096);
    if(memory == SBRK_ERROR)
      exit(3);
    for(int i = 0; i < 48; i++)
      memory[i * 4096] = i;
    volatile uchar *text = (volatile uchar *)(uint64)permissions;
    *text = 0; // Must fault: executable text must not regain PTE_W.
    exit(0);
  }
  int status;
  return wait(&status) == pid && status != 0 && vmcheck() == 0 ? 0 : -1;
}

static int
shrink_swapped_inner(void)
{
  const int pages = 48;
  struct vmstats before, pressured, after;
  if(vmstats(&before) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 6) < 0)
    return -1;
  uchar *memory = (uchar *)sbrklazy(pages * 4096);
  if((char *)memory == SBRK_ERROR)
    return -1;
  for(int i = 0; i < pages; i++)
    memory[i * 4096] = i + 1;
  if(vmstats(&pressured) < 0 || pressured.free_swap_slots >=
     before.free_swap_slots){
    printf("shrink: pressure free %ld before %ld\n",
           pressured.free_swap_slots, before.free_swap_slots);
    return -1;
  }
  if(sbrk(-pages * 4096) == SBRK_ERROR || vmstats(&after) < 0){
    printf("shrink: shrink/stats failed\n");
    return -1;
  }
  // Replacement may evict pages that existed before this allocation, and a
  // clean resident page may retain a backing slot.  The enclosing child-exit
  // check below verifies exact global recovery.
  if(after.free_swap_slots <= pressured.free_swap_slots ||
     after.resident_count > before.resident_count){
    printf("shrink: resident %ld/%ld free %ld/%ld (pressured %ld)\n",
           after.resident_count, before.resident_count, after.free_swap_slots,
           before.free_swap_slots, pressured.free_swap_slots);
    return -1;
  }
  return vmcheck();
}

static int
shrink_swapped(void)
{
  struct vmstats before, after;
  if(vmstats(&before) < 0)
    return -1;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0)
    exit(shrink_swapped_inner() == 0 ? 0 : 1);
  int status;
  if(wait(&status) != pid || status != 0 || vmstats(&after) < 0 ||
     after.free_swap_slots != before.free_swap_slots)
    return -1;
  return vmcheck();
}

static int
exit_leak(void)
{
  struct vmstats baseline, after;
  if(vmstats(&baseline) < 0)
    return -1;
  for(int iteration = 0; iteration < 50; iteration++){
    int pid = fork();
    if(pid < 0)
      return -1;
    if(pid == 0){
      struct vmstats child;
      if(vmstats(&child) < 0 ||
         vmctl(VM_SET_LIMIT, child.resident_count + 4) < 0)
        exit(1);
      uchar *memory = (uchar *)sbrklazy(32 * 4096);
      if((char *)memory == SBRK_ERROR)
        exit(1);
      for(int i = 0; i < 32; i++)
        memory[i * 4096] = i;
      exit(0);
    }
    int status;
    if(wait(&status) != pid || status != 0 || vmstats(&after) < 0 ||
       after.free_swap_slots != baseline.free_swap_slots)
      return -1;
  }
  return vmcheck();
}

static int
fault_cleanup(int kill_during_io)
{
  struct vmstats baseline, after;
  int ready[2];
  if(vmstats(&baseline) < 0 || pipe(ready) < 0)
    return -1;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    close(ready[0]);
    struct vmstats child;
    if(vmstats(&child) < 0 ||
       vmctl(VM_SET_LIMIT, child.resident_count + 4) < 0)
      exit(2);
    volatile char *memory = sbrklazy(40 * 4096);
    if((char *)memory == SBRK_ERROR)
      exit(3);
    for(int i = 0; i < 40; i++)
      memory[i * 4096] = i;
    if(write(ready[1], "R", 1) != 1)
      exit(4);
    close(ready[1]);
    if(vmfailinject(kill_during_io ? VM_FAIL_DELAY_TICKS : VM_FAIL_SWAP_READ,
                    kill_during_io ? 20 : 1) < 0)
      exit(5);
    char value = memory[0];
    (void)value;
    exit(0);
  }
  close(ready[1]);
  char signal;
  if(read(ready[0], &signal, 1) != 1){
    close(ready[0]);
    return -1;
  }
  close(ready[0]);
  if(kill_during_io){
    pause(2);
    if(kill(pid) < 0)
      return -1;
  }
  int status;
  if(wait(&status) != pid || status == 0 || vmstats(&after) < 0 ||
     after.free_swap_slots != baseline.free_swap_slots)
    return -1;
  return vmcheck();
}

static int
exec_fail_cleanup(void)
{
  struct vmstats before, after;
  char *args[] = {"echo", "unreachable", 0};
  if(vmstats(&before) < 0 || vmfailinject(VM_FAIL_FRAME_ALLOC, 4) < 0)
    return -1;
  if(exec("echo", args) >= 0)
    return -1;
  if(vmstats(&after) < 0 || after.resident_count != before.resident_count ||
     after.free_swap_slots != before.free_swap_slots)
    return -1;
  return vmcheck();
}

static int
fork_lifecycle(void)
{
  const int pages = 48;
  struct vmstats before;
  if(vmstats(&before) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 8) < 0)
    return -1;
  int *memory = (int *)sbrklazy(pages * 4096);
  if((char *)memory == SBRK_ERROR)
    return -1;
  for(int i = 0; i < 32; i++)
    memory[i * (4096 / sizeof(int))] = 0x510000 + i;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    for(int i = 0; i < 32; i++)
      if(memory[i * (4096 / sizeof(int))] != 0x510000 + i)
        exit(1);
    for(int i = 32; i < pages; i++)
      if(memory[i * (4096 / sizeof(int))] != 0)
        exit(1);
    memory[0] = 0x777777;
    exit(vmcheck() == 0 ? 0 : 1);
  }
  int status;
  if(wait(&status) != pid || status != 0 || memory[0] != 0x510000)
    return -1;
  if(sbrk(-pages * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
copy_paths(void)
{
  struct vmstats before, after;
  if(vmstats(&before) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 5) < 0)
    return -1;
  char *memory = sbrklazy(40 * 4096);
  if(memory == SBRK_ERROR)
    return -1;
  uint64 boundary = ((uint64)memory + 4095) & ~(uint64)4095;
  char *path = (char *)(boundary - 3);
  char *buffer = (char *)(boundary - 7);
  strcpy(path, "README");
  for(int i = 1; i < 40; i++)
    memory[i * 4096] = i;

  int fd = open(path, 0);
  if(fd < 0)
    return -1;
  char readbuf[8];
  if(read(fd, readbuf, sizeof(readbuf)) != sizeof(readbuf)){
    close(fd);
    return -1;
  }
  close(fd);

  int pipefd[2];
  if(pipe(pipefd) < 0)
    return -1;
  strcpy(buffer, "copy-path-ok");
  for(int i = 1; i < 40; i++)
    memory[i * 4096] ^= 1;
  if(write(pipefd[1], buffer, 13) != 13)
    return -1;
  memset(buffer, 0, 13);
  for(int i = 1; i < 40; i++)
    memory[i * 4096] ^= 1;
  if(read(pipefd[0], buffer, 13) != 13 ||
     memcmp(buffer, "copy-path-ok", 13) != 0)
    return -1;
  close(pipefd[0]);
  close(pipefd[1]);
  if(vmstats(&after) < 0 || after.swap_faults <= before.swap_faults)
    return -1;
  if(sbrk(-40 * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
exec_pressure(void)
{
  struct vmstats stats;
  char *args[] = {"vmtest", "exec-pressure-done", 0};
  if(vmstats(&stats) < 0 ||
     vmctl(VM_SET_LIMIT, stats.resident_count + 3) < 0)
    return -1;
  exec("vmtest", args);
  return -1;
}

static int
exec_loop(void)
{
  struct vmstats stats;
  char *args[] = {"vmtest", "exec-chain", "9", 0};
  if(vmstats(&stats) < 0 ||
     vmctl(VM_SET_LIMIT, stats.resident_count + 3) < 0)
    return -1;
  exec("vmtest", args);
  return -1;
}

static int
policy_correctness(int policy)
{
  if(vmctl(VM_SET_POLICY, policy) < 0)
    return -1;
  return swap_pattern_passes(4);
}

static int
invalid_policy_fallback(void)
{
  struct vmstats before, after;
  if(vmstats(&before) < 0 || vmctl(VM_SET_POLICY, VM_POLICY_AGING) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 4) < 0 ||
     vmtestop(VM_TEST_POLICY_INVALID, 0) < 0)
    return -1;
  char *memory = sbrklazy(24 * 4096);
  if(memory == SBRK_ERROR)
    return -1;
  for(int i = 0; i < 24; i++)
    memory[i * 4096] = i;
  if(vmstats(&after) < 0 ||
     after.policy_fallbacks <= before.policy_fallbacks)
    return -1;
  if(sbrk(-24 * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
dirty_writeback(void)
{
  const int pages = 24;
  struct vmstats before, warm, clean, dirty;
  if(vmstats(&before) < 0 || vmctl(VM_SET_POLICY, VM_POLICY_FIFO) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 4) < 0)
    return -1;
  volatile uchar *memory = (volatile uchar *)sbrklazy(pages * 4096);
  if((char *)memory == SBRK_ERROR)
    return -1;
  for(int i = 0; i < pages; i++)
    memory[i * 4096] = i + 1;

  // The first read-only pass gives every page a current backing slot.  A
  // second pass should recycle those slots without another page write.
  uint sum = 0;
  for(int i = 0; i < pages; i++)
    sum += memory[i * 4096];
  if(vmstats(&warm) < 0)
    return -1;
  for(int i = 0; i < pages; i++)
    sum += memory[i * 4096];
  if(vmstats(&clean) < 0 || clean.page_writes > warm.page_writes + 2 ||
     clean.swap_faults < warm.swap_faults + pages - 2){
    printf("dirty: clean writes %ld warm %ld\n", clean.page_writes,
           warm.page_writes);
    return -1;
  }

  memory[0] ^= 0x55;
  for(int i = 1; i < pages; i++)
    sum += memory[i * 4096];
  if(vmstats(&dirty) < 0 || dirty.page_writes <= clean.page_writes ||
     dirty.page_writes > clean.page_writes + 3 || sum == 0){
    printf("dirty: dirty writes %ld clean %ld sum %d\n", dirty.page_writes,
           clean.page_writes, sum);
    return -1;
  }
  if(sbrk(-pages * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
random_workload(uint seed, int iterations)
{
  enum { RANDOM_PAGES = 24 };
  uchar expected[RANDOM_PAGES];
  struct vmstats before, after;
  if(iterations <= 0 || vmstats(&before) < 0 ||
     vmctl(VM_SET_LIMIT, before.resident_count + 8) < 0)
    return -1;
  volatile uchar *memory = (volatile uchar *)
    sbrklazy(RANDOM_PAGES * 4096);
  if((char *)memory == SBRK_ERROR)
    return -1;
  for(int i = 0; i < RANDOM_PAGES; i++){
    expected[i] = i ^ 0x5a;
    memory[i * 4096] = expected[i];
  }
  uint state = seed ? seed : 1;
  for(int operation = 0; operation < iterations; operation++){
    state = state * 1664525U + 1013904223U;
    int page = state % RANDOM_PAGES;
    if(state & 3){
      if(memory[page * 4096] != expected[page])
        return -1;
    } else {
      expected[page] = state >> 24;
      memory[page * 4096] = expected[page];
    }
  }
  for(int i = 0; i < RANDOM_PAGES; i++)
    if(memory[i * 4096] != expected[i])
      return -1;
  if(vmstats(&after) < 0 || after.resident_count > after.resident_limit ||
     sbrk(-RANDOM_PAGES * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

static int
multiproc(void)
{
  int pids[4];
  for(int i = 0; i < 4; i++){
    pids[i] = fork();
    if(pids[i] < 0)
      return -1;
    if(pids[i] == 0)
      exit(random_workload(17 + i * 31, 4000) == 0 ? 0 : 1);
  }
  for(int i = 0; i < 4; i++){
    int status;
    if(wait(&status) < 0 || status != 0)
      return -1;
  }
  return vmcheck();
}

static int run(char *name);

static int
run_isolated(char *name)
{
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0)
    exit(run(name) == 0 ? 0 : 1);
  int status;
  if(wait(&status) != pid || status != 0)
    return -1;
  return vmcheck();
}

static int
run_all(void)
{
  char *common[] = {
    "controls", "inherit", "limit-basic", "lazy-zero", "swap-pattern",
    "swap-repeat", "permissions", "shrink-swapped", "exit-leak",
    "fork-resident", "copyin-swapped", "exec-pressure", "exec-loop",
    "dirty-writeback", "trace-schema", "trace-wrap", "trace-disabled",
    "trace-drop",
  };
  for(uint i = 0; i < sizeof(common) / sizeof(common[0]); i++){
    printf("vmtest all: %s\n", common[i]);
    if(run_isolated(common[i]) < 0)
      return -1;
  }
#ifdef VM_DEBUG
  char *debug[] = {
    "swapio", "swap-reuse", "swap-bounds", "swap-io-error", "pin",
    "metadata-reuse", "swap-full", "kill-fault", "swap-fault-io-error",
    "exec-fail-cleanup", "invalid-policy-fallback",
  };
  for(uint i = 0; i < sizeof(debug) / sizeof(debug[0]); i++){
    printf("vmtest all: %s\n", debug[i]);
    if(run_isolated(debug[i]) < 0)
      return -1;
  }
#endif
  return vmcheck();
}

static int
run(char *name)
{
  if(strcmp(name, "harness") == 0)
    return harness();
  if(strcmp(name, "controls") == 0)
    return controls();
  if(strcmp(name, "inherit") == 0)
    return inherit();
  if(strcmp(name, "swapio") == 0)
    return vmtestop(VM_TEST_SWAP_IO, 0);
  if(strcmp(name, "swap-reuse") == 0)
    return vmtestop(VM_TEST_SWAP_REUSE, 0);
  if(strcmp(name, "swap-bounds") == 0)
    return vmtestop(VM_TEST_SWAP_BOUNDS, 0);
  if(strcmp(name, "swap-io-error") == 0)
    return vmtestop(VM_TEST_SWAP_IO_ERROR, 0);
  if(strcmp(name, "limit-basic") == 0)
    return limit_basic();
  if(strcmp(name, "pin") == 0)
    return vmtestop(VM_TEST_FRAME_PIN, 0);
  if(strcmp(name, "metadata-reuse") == 0)
    return vmtestop(VM_TEST_FRAME_METADATA, 0);
  if(strcmp(name, "lazy-zero") == 0)
    return lazy_zero();
  if(strcmp(name, "swap-pattern") == 0)
    return swap_pattern_passes(2);
  if(strcmp(name, "swap-repeat") == 0)
    return swap_pattern_passes(100);
  if(strcmp(name, "swap-full") == 0)
    return swap_full();
  if(strcmp(name, "permissions") == 0)
    return permissions();
  if(strcmp(name, "shrink-swapped") == 0)
    return shrink_swapped();
  if(strcmp(name, "exit-leak") == 0)
    return exit_leak();
  if(strcmp(name, "kill-fault") == 0)
    return fault_cleanup(1);
  if(strcmp(name, "swap-fault-io-error") == 0)
    return fault_cleanup(0);
  if(strcmp(name, "exec-fail-cleanup") == 0)
    return exec_fail_cleanup();
  if(strcmp(name, "fork-resident") == 0 ||
     strcmp(name, "fork-swapped") == 0 ||
     strcmp(name, "fork-lazy-hole") == 0 ||
     strcmp(name, "fork-diverge") == 0 ||
     strcmp(name, "fork-low-limit") == 0)
    return fork_lifecycle();
  if(strcmp(name, "copyin-swapped") == 0 ||
     strcmp(name, "copyout-swapped") == 0 ||
     strcmp(name, "copyinstr-cross-page-swapped") == 0)
    return copy_paths();
  if(strcmp(name, "exec-pressure") == 0)
    return exec_pressure();
  if(strcmp(name, "exec-loop") == 0)
    return exec_loop();
  if(strcmp(name, "policies-correctness") == 0)
    return policy_correctness(requested_policy);
  if(strcmp(name, "clock-reference") == 0)
    return policy_correctness(VM_POLICY_CLOCK);
  if(strcmp(name, "aging-order") == 0)
    return policy_correctness(VM_POLICY_AGING);
  if(strcmp(name, "invalid-policy-fallback") == 0)
    return invalid_policy_fallback();
  if(strcmp(name, "dirty-writeback") == 0)
    return dirty_writeback();
  if(strcmp(name, "trace-schema") == 0)
    return trace_schema();
  if(strcmp(name, "trace-wrap") == 0)
    return trace_overflow(0);
  if(strcmp(name, "trace-disabled") == 0)
    return trace_disabled();
  if(strcmp(name, "trace-drop") == 0)
    return trace_overflow(1);
  if(strcmp(name, "all") == 0)
    return run_all();
  if(strcmp(name, "all-policy") == 0)
    return policy_correctness(requested_policy);
  if(strcmp(name, "random") == 0)
    return random_workload(requested_seed, requested_iterations);
  if(strcmp(name, "multiproc") == 0)
    return multiproc();
  printf("vmtest: unknown test %s\n", name);
  return -1;
}

int
main(int argc, char **argv)
{
  char *name = argc > 1 ? argv[1] : "harness";

  if(argc > 2 && (strcmp(name, "policies-correctness") == 0 ||
                  strcmp(name, "all-policy") == 0)){
    if(strcmp(argv[2], "fifo") == 0)
      requested_policy = VM_POLICY_FIFO;
    else if(strcmp(argv[2], "clock") == 0)
      requested_policy = VM_POLICY_CLOCK;
    else if(strcmp(argv[2], "aging") == 0)
      requested_policy = VM_POLICY_AGING;
    else {
      printf("vmtest: %s: FAIL\n", name);
      exit(1);
    }
  }
  if(strcmp(name, "random") == 0){
    if(argc < 4 || atoi(argv[2]) < 0 || atoi(argv[3]) <= 0){
      printf("vmtest: random: FAIL\n");
      exit(1);
    }
    requested_seed = atoi(argv[2]);
    requested_iterations = atoi(argv[3]);
    printf("vmtest random: seed=%d iterations=%d CPUS-reference=1\n",
           requested_seed, requested_iterations);
  }

  if(strcmp(name, "exec-pressure-done") == 0){
    struct vmstats stats;
    int ok = vmstats(&stats) == 0 &&
      stats.resident_count <= stats.resident_limit && vmcheck() == 0;
    printf("vmtest: exec-pressure: %s\n", ok ? "PASS" : "FAIL");
    exit(ok ? 0 : 1);
  }
  if(strcmp(name, "exec-chain") == 0){
    int remaining = argc > 2 ? argv[2][0] - '0' : 0;
    if(remaining > 0){
      char next[2] = {(char)('0' + remaining - 1), 0};
      char *args[] = {"vmtest", "exec-chain", next, 0};
      exec("vmtest", args);
      printf("vmtest: exec-loop: FAIL\n");
      exit(1);
    }
    int ok = vmcheck() == 0;
    printf("vmtest: exec-loop: %s\n", ok ? "PASS" : "FAIL");
    exit(ok ? 0 : 1);
  }

  if(run(name) < 0){
    printf("vmtest: %s: FAIL\n", name);
    exit(1);
  }
  printf("vmtest: %s: PASS\n", name);
  exit(0);
}
