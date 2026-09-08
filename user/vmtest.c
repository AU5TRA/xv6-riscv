#include "kernel/types.h"
#include "user/user.h"
#include "kernel/vmstats.h"
#include "kernel/swap.h"
#include "kernel/vmtrace.h"

static int requested_policy = VM_POLICY_FIFO;
static uint requested_seed = 1;
static int requested_iterations = 10000;

// A full vmtrace_read() batch is 16 KiB, which does not belong on the
// user stack even at USERSTACK=16.
static struct vmtrace_event trace_batch[VMTRACE_READ_MAX];

// The trace ring is global kernel state, so a test that shrinks it has to put
// it back on every exit path -- run_isolated() children share the same ring as
// everything that runs after them.
static int
trace_restore(int result)
{
  if(vmctl(VM_TRACE_ENABLE, 0) < 0 ||
     vmctl(VM_TRACE_SET_CAPACITY, VMTRACE_CAPACITY) < 0)
    return -1;
  return result;
}

// Reads until the ring is empty, checking that sequence numbers are
// contiguous and that no in-band drop marker appears. Returns the number of
// records read, or -1 on any loss.
static int
drain_contiguous(uint64 *expected)
{
  int total = 0;
  for(;;){
    int count = vmtrace_read(trace_batch, VMTRACE_READ_MAX);
    if(count < 0)
      return -1;
    if(count == 0)
      return total;
    for(int i = 0; i < count; i++){
      if(trace_batch[i].type == VMTRACE_DROP ||
         trace_batch[i].type == 0 ||
         trace_batch[i].type >= VMTRACE_TYPE_COUNT)
        return -1;
      if(trace_batch[i].sequence != ++(*expected))
        return -1;
      total++;
    }
  }
}

// The schema now lives in a one-time header rather than in every record, so
// this checks the header and then checks that a record straddling two lazily
// allocated user pages still copies out correctly (vmtrace_read must release
// the ring lock before copyout can fault those pages in).
static int
trace_schema(void)
{
  struct vmtrace_header header;

  if(vmctl(VM_TRACE_ENABLE, 0) < 0 || vmctl(VM_TRACE_RESET, 0) < 0)
    return -1;
  if(vmtrace_info(&header) < 0 ||
     header.version != VMTRACE_VERSION ||
     header.record_size != sizeof(struct vmtrace_event) ||
     header.record_size != 64 ||
     header.capacity != VMTRACE_CAPACITY ||
     header.read_max != VMTRACE_READ_MAX ||
     header.enabled != 0 || header.buffered != 0 ||
     header.sequence != 0 || header.dropped != 0)
    return -1;

  // Five pages so four page-aligned ones are available whatever offset sbrk
  // happens to return.
  char *output_memory = sbrklazy(5 * 4096);
  char *fault_memory = sbrklazy(4096);
  if(output_memory == SBRK_ERROR || fault_memory == SBRK_ERROR)
    return -1;
  char *aligned = (char *)(((uint64)output_memory + 4095) & ~(uint64)4095);

  if(vmctl(VM_TRACE_ENABLE, 1) < 0)
    return -1;
  fault_memory[0] = 7;
  if(vmctl(VM_TRACE_ENABLE, 0) < 0)
    return -1;

  // Start 32 bytes before a page boundary: record 0 straddles it.
  struct vmtrace_event *events =
    (struct vmtrace_event *)(aligned + 4096 - 32);
  int count = vmtrace_read(events, 2);
  if(count != 2)
    return -1;
  int saw_fault = 0;
  int saw_self = 0;
  for(int i = 0; i < count; i++){
    if(events[i].type == 0 || events[i].type >= VMTRACE_TYPE_COUNT ||
       (i && events[i].sequence <= events[i - 1].sequence))
      return -1;
    // Emission is a global switch, so another process could in principle
    // land a record here; at least one of these has to be ours.
    if(events[i].pid == (uint32)getpid())
      saw_self = 1;
    if(events[i].type == VMTRACE_ZERO_FAULT ||
       events[i].type == VMTRACE_MAP)
      saw_fault = 1;
  }
  if(!saw_fault || !saw_self)
    return -1;

  // The header must have followed along.
  if(vmtrace_info(&header) < 0 || header.sequence < 2 || header.dropped != 0)
    return -1;
  // And it must copy out into a lazily allocated page too.
  struct vmtrace_header *lazy_header =
    (struct vmtrace_header *)(aligned + 2 * 4096 + 4096 - 24);
  if(vmtrace_info(lazy_header) < 0 ||
     lazy_header->version != VMTRACE_VERSION ||
     lazy_header->record_size != sizeof(struct vmtrace_event))
    return -1;

  if(sbrk(-6 * 4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

// The capacity control is what keeps the overflow tests affordable, so its
// bounds are worth checking directly.
static int
trace_capacity(void)
{
  struct vmtrace_header header;

  if(vmctl(VM_TRACE_ENABLE, 0) < 0)
    return -1;
  if(vmctl(VM_TRACE_SET_CAPACITY, 0) == 0 ||
     vmctl(VM_TRACE_SET_CAPACITY, VMTRACE_CAPACITY + 1) == 0)
    return -1;
  if(vmtrace_info(&header) < 0 || header.capacity != VMTRACE_CAPACITY)
    return -1;
  if(vmctl(VM_TRACE_SET_CAPACITY, 64) < 0)
    return -1;
  if(vmtrace_info(&header) < 0 || header.capacity != 64 ||
     header.buffered != 0 || header.sequence != 0)
    return trace_restore(-1);
  return trace_restore(vmcheck());
}

// Head and tail must wrap past the end of the array without losing anything.
// With a 64-record ring, draining every few faults cycles the indices around
// many times over a cheap workload; the real 65536-record ring would need tens
// of thousands of faults to wrap even once.
static int
trace_wrap(void)
{
  const int pages = 96;

  if(vmctl(VM_TRACE_ENABLE, 0) < 0 ||
     vmctl(VM_TRACE_SET_CAPACITY, 64) < 0)
    return -1;

  char *memory = sbrklazy(pages * 4096);
  if(memory == SBRK_ERROR)
    return trace_restore(-1);
  if(vmctl(VM_TRACE_ENABLE, 1) < 0)
    return trace_restore(-1);

  uint64 expected = 0;
  int total = 0;
  for(int i = 0; i < pages; i++){
    memory[i * 4096] = (char)i;
    // Two events per zero fault, so the 64-record ring wraps every 32 pages
    // while staying well short of overflowing between drains.
    int moved = drain_contiguous(&expected);
    if(moved < 0)
      return trace_restore(-1);
    total += moved;
  }
  if(vmctl(VM_TRACE_ENABLE, 0) < 0)
    return trace_restore(-1);

  int moved = drain_contiguous(&expected);
  if(moved < 0)
    return trace_restore(-1);
  total += moved;

  struct vmtrace_header header;
  if(vmtrace_info(&header) < 0 || header.dropped != 0 ||
     header.buffered != 0 || (uint64)total != header.sequence ||
     total < 2 * pages)
    return trace_restore(-1);
  if(sbrk(-pages * 4096) == SBRK_ERROR)
    return trace_restore(-1);
  return trace_restore(vmcheck());
}

// Overrunning the ring must be loud: the drop counter climbs, an in-band DROP
// marker appears, and the surviving records show a sequence gap.
static int
trace_drop(void)
{
  const int capacity = 64;
  const int pages = 256;

  if(vmctl(VM_TRACE_ENABLE, 0) < 0 ||
     vmctl(VM_TRACE_SET_CAPACITY, capacity) < 0)
    return -1;

  char *memory = sbrklazy(pages * 4096);
  if(memory == SBRK_ERROR)
    return trace_restore(-1);
  if(vmctl(VM_TRACE_ENABLE, 1) < 0)
    return trace_restore(-1);
  // No draining at all, so the ring is guaranteed to overrun.
  for(int i = 0; i < pages; i++)
    memory[i * 4096] = (char)i;
  if(vmctl(VM_TRACE_ENABLE, 0) < 0)
    return trace_restore(-1);

  struct vmtrace_header header;
  if(vmtrace_info(&header) < 0 || header.buffered != (uint64)capacity ||
     header.sequence <= (uint64)capacity ||
     header.dropped != header.sequence - (uint64)capacity)
    return trace_restore(-1);

  uint64 previous = 0;
  uint64 first = 0;
  int total = 0;
  int saw_drop = 0;
  for(;;){
    int count = vmtrace_read(trace_batch, VMTRACE_READ_MAX);
    if(count < 0)
      return trace_restore(-1);
    if(count == 0)
      break;
    for(int i = 0; i < count; i++){
      if(first == 0)
        first = trace_batch[i].sequence;
      // The survivors are the newest records, so they are contiguous
      // among themselves; the loss shows up as the window starting late.
      else if(trace_batch[i].sequence != previous + 1)
        return trace_restore(-1);
      previous = trace_batch[i].sequence;
      if(trace_batch[i].type == VMTRACE_DROP && trace_batch[i].status > 0)
        saw_drop = 1;
      total++;
    }
  }
  // Exactly one ring's worth survives, the window does not start at
  // sequence 1 (so a reader cannot mistake it for a complete capture),
  // and an in-band drop marker is present.
  if(total != capacity || !saw_drop || first != previous - capacity + 1 ||
     first <= 1)
    return trace_restore(-1);
  if(sbrk(-pages * 4096) == SBRK_ERROR)
    return trace_restore(-1);
  return trace_restore(vmcheck());
}

static int
trace_disabled(void)
{
  struct vmtrace_event event;
  struct vmtrace_header header;
  if(vmctl(VM_TRACE_ENABLE, 0) < 0 || vmctl(VM_TRACE_RESET, 0) < 0)
    return -1;
  char *memory = sbrklazy(4096);
  if(memory == SBRK_ERROR)
    return -1;
  memory[0] = 1;
  if(vmtrace_read(&event, 1) != 0)
    return -1;
  if(vmtrace_info(&header) < 0 || header.enabled != 0 ||
     header.sequence != 0 || header.buffered != 0 || header.dropped != 0)
    return -1;
  if(sbrk(-4096) == SBRK_ERROR)
    return -1;
  return vmcheck();
}

// The Phase 0 requirement in one test: a dataset-scale event stream captured
// with zero drops and no sequence gaps, at the ring's real capacity.
static int
trace_lossless(void)
{
  const int pages = 64;
  const int passes = 100;
  struct vmstats stats;

  if(vmctl(VM_TRACE_ENABLE, 0) < 0 ||
     vmctl(VM_TRACE_SET_CAPACITY, VMTRACE_CAPACITY) < 0 ||
     vmstats(&stats) < 0 ||
     vmctl(VM_SET_LIMIT, stats.resident_count + 8) < 0)
    return -1;

  uchar *memory = (uchar *)sbrklazy(pages * 4096);
  if((char *)memory == SBRK_ERROR)
    return trace_restore(-1);
  for(int page = 0; page < pages; page++)
    memory[page * 4096] = (uchar)page;

  if(vmctl(VM_TRACE_ENABLE, 1) < 0)
    return trace_restore(-1);

  uint64 expected = 0;
  int total = 0;
  for(int pass = 0; pass < passes; pass++){
    for(int n = 0; n < pages; n++){
      // Alternate direction so the resident set never predicts the next miss.
      int page = (pass & 1) ? pages - n - 1 : n;
      if(memory[page * 4096] != (uchar)page)
        return trace_restore(-1);
    }
    int moved = drain_contiguous(&expected);
    if(moved < 0)
      return trace_restore(-1);
    total += moved;
  }
  if(vmctl(VM_TRACE_ENABLE, 0) < 0)
    return trace_restore(-1);
  int moved = drain_contiguous(&expected);
  if(moved < 0)
    return trace_restore(-1);
  total += moved;

  struct vmtrace_header header;
  if(vmtrace_info(&header) < 0 || header.dropped != 0 ||
     header.buffered != 0 || (uint64)total != header.sequence)
    return trace_restore(-1);
  // A stream this small would mean the workload never really paged, which
  // would make the zero-drop result meaningless.
  if(total < 20000)
    return trace_restore(-1);
  printf("vmtest trace-lossless: %d records, 0 drops, 0 gaps\n", total);
  if(sbrk(-pages * 4096) == SBRK_ERROR)
    return trace_restore(-1);
  return trace_restore(vmcheck());
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

  // requested_policy is VM_POLICY_FIFO (its static default) for every
  // invocation except "all-policy clock"/"all-policy aging", which forces
  // it onto this process's parent specifically so run_all()'s
  // run_isolated() children inherit it -- so a freshly-inherited process
  // is expected to start on whichever policy that is, not unconditionally
  // FIFO.
  if(vmstats(&stats) < 0 || stats.version != VMSTATS_VERSION ||
     stats.resident_limit != VM_LIMIT_UNLIMITED ||
     stats.policy != (uint64)requested_policy || stats.prefetch_enabled != 0)
    return -1;
  // A limit below the current resident count is refused by design, and a
  // process fresh out of exec holds USERSTACK stack pages plus its image,
  // so target a count relative to what is resident rather than a fixed
  // small number.
  uint64 limit = stats.resident_count + 4;
  if(limit > VM_MAX_RESIDENT_LIMIT)
    return -1;
  if(vmctl(VM_SET_LIMIT, limit) < 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_CLOCK) < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 1) < 0)
    return -1;
  if(vmctl(VM_SET_LIMIT, VM_MAX_RESIDENT_LIMIT + 1) == 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_COUNT) == 0 ||
     vmctl(VM_PREFETCH_ENABLE, 2) == 0 || vmctl(999, 0) == 0)
    return -1;
  // A rejected request must leave the previous value in place.
  if(vmstats(&stats) < 0 || stats.resident_limit != limit ||
     stats.policy != VM_POLICY_CLOCK || stats.prefetch_enabled != 1)
    return -1;
  return vmcheck();
}

static int
inherit(void)
{
  int status;
  struct vmstats before;
  // Relative for the same reason as controls(). fork copies memory, so
  // the child below sees this value.
  if(vmstats(&before) < 0)
    return -1;
  uint64 limit = before.resident_count + 3;
  if(limit > VM_MAX_RESIDENT_LIMIT ||
     vmctl(VM_SET_LIMIT, limit) < 0 ||
     vmctl(VM_SET_POLICY, VM_POLICY_AGING) < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 1) < 0)
    return -1;
  int pid = fork();
  if(pid < 0)
    return -1;
  if(pid == 0){
    struct vmstats stats;
    int ok = vmstats(&stats) == 0 && stats.resident_limit == limit &&
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
  for(int iteration = 0; iteration < 500; iteration++){
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
    // The region has to exceed the resident limit, so it is sized from
    // the count rather than fixed: at USERSTACK=16 a fixed 40 pages no
    // longer dominated the pages the process arrives from exec with.
    int pages = (int)child.resident_count + 40;
    volatile char *memory = sbrklazy(pages * 4096);
    if((char *)memory == SBRK_ERROR)
      exit(3);
    for(int i = 0; i < pages; i++)
      memory[i * 4096] = i;
    // Page 0 must be in swap when the delayed fault below runs, whatever
    // the replacement policy is. A second pass over every *other* page
    // guarantees it: page 0 goes unreferenced while more pages than the
    // resident limit are touched, so FIFO, Clock and Aging all evict it.
    for(int i = 1; i < pages; i++)
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

// Phase 2 acceptance criterion: "All policy and prefetch modes produce
// identical application data results."  Every other policy test fixes one
// policy and checks that process in isolation; this one runs the *same*
// deterministic workload under all VM_POLICY_COUNT policies crossed with
// synchronous and asynchronous prefetch, and requires byte-exact agreement
// across the whole matrix.
//
// The two guards matter as much as the comparison (see the dirty-writeback
// lesson): a configuration that never evicted anything would agree
// trivially, and a prefetch mode that never accepted a hint would not be
// testing prefetch at all.  Both are asserted per configuration, so the
// test cannot pass vacuously.
// Stop taking new prefetch hints and wait for the queue and the in-flight
// I/O count to reach zero.  Both the VM_PREFETCH_MODE switch and vmcheck()
// require a quiescent process: an async prefetch still in flight owns a
// frame in VM_PAGE_RESIDENT_PREFETCH whose PTE is not installed yet, which
// vmcheck() reports -- correctly -- as a pte mismatch.
static int
quiesce_prefetch(struct vmstats *out)
{
  if(vmctl(VM_PREFETCH_ENABLE, 0) < 0 ||
     vmctl(VM_PREFETCH_AUTOMATIC, 0) < 0)
    return -1;
  for(int i = 0; i < 200; i++){
    if(vmstats(out) < 0)
      return -1;
    if(out->queued_prefetch == 0 && out->inflight_io == 0)
      return 0;
    pause(1);
  }
  return -1;
}

// The workload both data-invariance and baseline run: write the pattern
// across a lazy region larger than the resident limit, then read it back
// four times, alternating direction, then 1024 pseudorandom probes.
#define INVARIANT_PAGES 64

// The checksum the workload must produce, derived from the pattern
// definition alone -- no memory is touched, nothing pages.  Comparing each
// configuration against this rather than against another configuration's
// result means a bug that corrupted *every* configuration identically
// would still be caught.
static uint
expected_workload_checksum(void)
{
  uint sum = 0;
  for(int pass = 0; pass < 4; pass++)
    for(int page = 0; page < INVARIANT_PAGES; page++)
      for(int offset = 0; offset < 4096; offset += 97)
        sum = sum * 31 + page_byte(page, offset);
  uint seed = 0x2105069;
  for(int i = 0; i < 1024; i++){
    seed = seed * 1664525 + 1013904223;
    int page = seed % INVARIANT_PAGES;
    int offset = ((seed >> 8) % 42) * 97;
    sum = sum * 31 + page_byte(page, offset);
  }
  return sum;
}

// Runs the workload once and leaves the observed checksum in *checksum and
// the end-of-run counters in *out.  Byte-exactness is checked against the
// pattern on every read pass, so a mixed-up frame fails here rather than
// hiding inside a summed checksum.
static int
run_invariant_workload(uint64 limit, uint *checksum, struct vmstats *out)
{
  const int pages = INVARIANT_PAGES;

  if(vmctl(VM_SET_LIMIT, limit) < 0)
    return -1;
  uchar *memory = (uchar *)sbrklazy(pages * 4096);
  if((char *)memory == SBRK_ERROR)
    return -1;
  for(int page = 0; page < pages; page++)
    for(int offset = 0; offset < 4096; offset += 97)
      memory[page * 4096 + offset] = page_byte(page, offset);

  uint sum = 0;
  for(int pass = 0; pass < 4; pass++){
    if(check_pages(memory, pages, pass & 1) < 0)
      return -1;
    for(int page = 0; page < pages; page++)
      for(int offset = 0; offset < 4096; offset += 97)
        sum = sum * 31 + memory[page * 4096 + offset];
  }
  uint seed = 0x2105069;
  for(int i = 0; i < 1024; i++){
    seed = seed * 1664525 + 1013904223;
    int page = seed % pages;
    int offset = ((seed >> 8) % 42) * 97;
    if(memory[page * 4096 + offset] != page_byte(page, offset))
      return -1;
    sum = sum * 31 + memory[page * 4096 + offset];
  }

  if(vmstats(out) < 0)
    return -1;
  // The region really did cycle through swap: a configuration that never
  // evicted anything would agree with every other one trivially.
  if(out->evictions == 0 || out->swap_faults == 0 ||
     out->resident_count > out->resident_limit)
    return -1;

  struct vmstats idle;
  if(quiesce_prefetch(&idle) < 0)
    return -1;
  if(sbrk(-pages * 4096) == SBRK_ERROR)
    return -1;
  if(vmctl(VM_SET_LIMIT, VM_LIMIT_UNLIMITED) < 0)
    return -1;
  *checksum = sum;
  return vmcheck();
}

// Phase 2 acceptance criterion: "All policy and prefetch modes produce
// identical application data results."  Every other policy test fixes one
// policy and checks that process in isolation; this one runs the *same*
// deterministic workload under all VM_POLICY_COUNT policies crossed with
// synchronous and asynchronous prefetch, and requires byte-exact agreement
// across the whole matrix.
//
// Each configuration runs in its own forked child, and the resident limit
// is computed once in the parent and passed down.  Reconfiguring a single
// process in a loop looked simpler and was wrong: the region is freed at
// the end of each configuration, so the second and later iterations
// observed a much smaller resident_count and derived a much smaller limit
// from it.  FIFO then appeared to evict 1593 pages against Clock's 2404 --
// entirely an artefact of FIFO having run first with a limit of 34 while
// Clock ran with 12.  Same failure mode as sections 2.4 to 2.7 of the
// Phase 0/1 report: a magnitude derived from observed state that had
// already been perturbed by the measurement itself.
static int
data_invariance_child(int policy, int async, uint64 limit)
{
  struct vmstats before, stats;
  uint checksum = 0;

  // VM_PREFETCH_MODE is refused while anything is queued or in flight.
  if(quiesce_prefetch(&before) < 0 ||
     vmctl(VM_SET_LIMIT, VM_LIMIT_UNLIMITED) < 0 ||
     vmctl(VM_SET_POLICY, policy) < 0 ||
     vmctl(VM_PREFETCH_MODE, async) < 0 ||
     vmctl(VM_PREFETCH_ENABLE, 1) < 0 ||
     vmctl(VM_PREFETCH_AUTOMATIC, 1) < 0 ||
     vmctl(VM_RESET_STATS, 0) < 0)
    return -1;
  if(vmstats(&before) < 0 || before.policy != (uint64)policy ||
     before.prefetch_async != (uint64)async ||
     before.resident_count > limit)
    return -1;

  if(run_invariant_workload(limit, &checksum, &stats) < 0)
    return -1;

  // Prefetch really was exercised in this mode.
  if(stats.prefetch_accepted == 0)
    return -1;
  // Swap read I/O is attributed to this process whoever issued it. Every
  // demand fault either performs a read or is satisfied by a prefetch
  // already in flight (useful/late); every completed prefetch performs
  // exactly one read.  So page_reads can never fall below
  //   swap_faults - prefetch_useful - prefetch_late + prefetch_completed.
  // Before the async worker was made to bill its reads to the requesting
  // process, async runs reported page_reads == swap_faults exactly and
  // this inequality failed by roughly the number of completed prefetches.
  if(stats.page_reads + stats.prefetch_useful + stats.prefetch_late <
     stats.swap_faults + stats.prefetch_completed)
    return -1;

  printf("vmtest data-invariance: policy=%d async=%d limit=%d checksum=%x "
         "evict=%d faults=%d reads=%d writes=%d pf_accepted=%d "
         "pf_completed=%d pf_useful=%d pf_late=%d pf_wasted=%d "
         "fallbacks=%d\n",
         policy, async, (int)limit, checksum, (int)stats.evictions,
         (int)stats.swap_faults, (int)stats.page_reads,
         (int)stats.page_writes, (int)stats.prefetch_accepted,
         (int)stats.prefetch_completed, (int)stats.prefetch_useful,
         (int)stats.prefetch_late, (int)stats.prefetch_wasted,
         (int)stats.policy_fallbacks);

  if(checksum != expected_workload_checksum()){
    printf("vmtest data-invariance: checksum %x != expected %x\n",
           checksum, expected_workload_checksum());
    return -1;
  }
  return 0;
}

static int
data_invariance(void)
{
  struct vmstats base;
  if(vmstats(&base) < 0)
    return -1;
  uint64 limit = base.resident_count + 8;
  if(limit > VM_MAX_RESIDENT_LIMIT)
    return -1;

  for(int policy = 0; policy < VM_POLICY_COUNT; policy++){
    for(int async = 0; async < 2; async++){
      int pid = fork();
      if(pid < 0)
        return -1;
      if(pid == 0)
        exit(data_invariance_child(policy, async, limit) == 0 ? 0 : 1);
      int status;
      if(wait(&status) != pid || status != 0){
        printf("vmtest data-invariance: policy=%d async=%d FAILED\n",
               policy, async);
        return -1;
      }
    }
  }
  return vmcheck();
}

// Phase 2 Step 9: the recorded per-policy baseline.  Same deterministic
// workload as data-invariance, prefetch disabled, so the numbers isolate
// victim selection from prefetch behaviour.  These are the counts a later
// change is bisected against; they are printed rather than asserted,
// because their value is as a reference, not as a pass condition.  What is
// asserted is that the workload really did page, and that every policy saw
// the same limit -- a baseline table whose rows ran at different
// capacities would be worse than no baseline.
static int
baseline_child(int policy, uint64 limit)
{
  struct vmstats before, stats;
  uint checksum = 0;

  if(quiesce_prefetch(&before) < 0 ||
     vmctl(VM_SET_LIMIT, VM_LIMIT_UNLIMITED) < 0 ||
     vmctl(VM_SET_POLICY, policy) < 0 ||
     vmctl(VM_RESET_STATS, 0) < 0)
    return -1;
  if(vmstats(&before) < 0 || before.resident_count > limit)
    return -1;

  if(run_invariant_workload(limit, &checksum, &stats) < 0)
    return -1;
  if(checksum != expected_workload_checksum())
    return -1;

  printf("vmtest baseline: policy=%d limit=%d start_resident=%d pages=%d "
         "zero_faults=%d swap_faults=%d evictions=%d page_reads=%d "
         "page_writes=%d block_reads=%d block_writes=%d fallbacks=%d\n",
         policy, (int)limit, (int)before.resident_count, INVARIANT_PAGES,
         (int)stats.zero_faults, (int)stats.swap_faults,
         (int)stats.evictions, (int)stats.page_reads,
         (int)stats.page_writes, (int)stats.block_reads,
         (int)stats.block_writes, (int)stats.policy_fallbacks);
  return 0;
}

static int
policy_baseline(void)
{
  struct vmstats base;
  if(vmstats(&base) < 0)
    return -1;
  uint64 limit = base.resident_count + 8;
  if(limit > VM_MAX_RESIDENT_LIMIT)
    return -1;

  for(int policy = 0; policy < VM_POLICY_COUNT; policy++){
    int pid = fork();
    if(pid < 0)
      return -1;
    if(pid == 0)
      exit(baseline_child(policy, limit) == 0 ? 0 : 1);
    int status;
    if(wait(&status) != pid || status != 0){
      printf("vmtest baseline: policy=%d FAILED\n", policy);
      return -1;
    }
  }
  return vmcheck();
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
  struct vmstats before, warm, clean, dirty;
  if(vmstats(&before) < 0 || vmctl(VM_SET_POLICY, VM_POLICY_FIFO) < 0)
    return -1;
  // The region has to be bigger than the frames the process may keep, or
  // FIFO evicts the text, data and USERSTACK stack pages it arrived from
  // exec with and the region under test never reaches swap -- which is
  // what a fixed 24 pages did once USERSTACK grew to 16. Sizing both the
  // limit and the region from resident_count keeps the cyclic scan longer
  // than the resident capacity whatever the baseline happens to be.
  const int headroom = 4;
  const int pages = (int)before.resident_count + 24;
  if(before.resident_count + headroom > VM_MAX_RESIDENT_LIMIT ||
     vmctl(VM_SET_LIMIT, before.resident_count + headroom) < 0)
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
    printf("dirty: writes warm=%ld clean=%ld  faults warm=%ld clean=%ld  "
           "resident=%ld limit=%ld base=%ld\n",
           warm.page_writes, clean.page_writes, warm.swap_faults,
           clean.swap_faults, clean.resident_count, clean.resident_limit,
           before.resident_count);
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
  // The region must stay strictly larger than the resident capacity for
  // the whole run, or the soak stops being a paging soak.  A fixed 24
  // pages did that when a process arrived from exec holding about eleven
  // frames; at USERSTACK=16 it holds 27, the limit derived from it is 35,
  // and 24 random pages fit inside it with room to spare.  The workload
  // then paged eighteen times during warm-up and never again: a capture of
  // 400,000 operations emitted 174 events, and every "soak" in the matrix
  // was really a 4-second test of a steady state.  Same failure as
  // sections 2.5 to 2.7 of the Phase 0/1 report -- a fixed magnitude
  // competing against a baseline that grew underneath it.
  enum { RANDOM_MAX_PAGES = 160 };
  uchar expected[RANDOM_MAX_PAGES];
  struct vmstats before, after;
  if(iterations <= 0 || vmstats(&before) < 0)
    return -1;
  int pages = (int)before.resident_count + 24;
  if(pages > RANDOM_MAX_PAGES ||
     before.resident_count + 8 > VM_MAX_RESIDENT_LIMIT ||
     vmctl(VM_SET_LIMIT, before.resident_count + 8) < 0)
    return -1;
  volatile uchar *memory = (volatile uchar *)
    sbrklazy(pages * 4096);
  if((char *)memory == SBRK_ERROR)
    return -1;
  for(int i = 0; i < pages; i++){
    expected[i] = i ^ 0x5a;
    memory[i * 4096] = expected[i];
  }
  uint state = seed ? seed : 1;
  for(int operation = 0; operation < iterations; operation++){
    state = state * 1664525U + 1013904223U;
    int page = state % pages;
    if(state & 3){
      if(memory[page * 4096] != expected[page])
        return -1;
    } else {
      expected[page] = state >> 24;
      memory[page * 4096] = expected[page];
    }
  }
  for(int i = 0; i < pages; i++)
    if(memory[i * 4096] != expected[i])
      return -1;
  // Precondition guard, not a property: if the run did not actually page
  // it proved nothing, and a soak that silently stopped paging is exactly
  // what this assertion exists to catch next time.
  if(vmstats(&after) < 0 || after.resident_count > after.resident_limit ||
     after.swap_faults <= before.swap_faults ||
     after.evictions <= before.evictions ||
     sbrk(-pages * 4096) == SBRK_ERROR)
    return -1;
  printf("vmtest random: pages=%d limit=%d swap_faults=%d evictions=%d "
         "page_reads=%d page_writes=%d\n",
         pages, (int)after.resident_limit,
         (int)(after.swap_faults - before.swap_faults),
         (int)(after.evictions - before.evictions),
         (int)(after.page_reads - before.page_reads),
         (int)(after.page_writes - before.page_writes));
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
    "dirty-writeback", "data-invariance", "baseline",
    "trace-schema", "trace-capacity", "trace-wrap",
    "trace-disabled", "trace-drop", "trace-lossless",
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
  if(strcmp(name, "data-invariance") == 0)
    return data_invariance();
  if(strcmp(name, "baseline") == 0)
    return policy_baseline();
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
  if(strcmp(name, "trace-capacity") == 0)
    return trace_capacity();
  if(strcmp(name, "trace-wrap") == 0)
    return trace_wrap();
  if(strcmp(name, "trace-disabled") == 0)
    return trace_disabled();
  if(strcmp(name, "trace-drop") == 0)
    return trace_drop();
  if(strcmp(name, "trace-lossless") == 0)
    return trace_lossless();
  if(strcmp(name, "all") == 0)
    return run_all();
  if(strcmp(name, "all-policy") == 0)
    // Unlike "policies-correctness" (a single targeted check),
    // "all-policy" is meant to run the whole lifecycle matrix under a
    // forced policy. main() sets that policy on this process before we
    // get here, so every run_isolated() child below inherits it via
    // vmstate_inherit() at fork time (a handful of subtests, e.g.
    // dirty-writeback and invalid-policy-fallback, deliberately pin their
    // own policy regardless -- that's intentional and unrelated to which
    // policy was requested here).
    return run_all();
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
    // "all-policy" runs run_all()'s children under this policy via fork
    // inheritance; "policies-correctness" instead passes requested_policy
    // straight to policy_correctness() and doesn't need this process's own
    // policy touched.
    if(strcmp(name, "all-policy") == 0 &&
       vmctl(VM_SET_POLICY, requested_policy) < 0){
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
