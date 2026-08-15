#ifndef XV6_VMSTATS_H
#define XV6_VMSTATS_H

#define VMSTATS_VERSION 2

#define VM_SET_LIMIT 1
#define VM_SET_POLICY 2
#define VM_PREFETCH_ENABLE 3
#define VM_RESET_STATS 4
#define VM_PREFETCH_MODE 5
#define VM_PREFETCH_AUTOMATIC 6
#define VM_PREFETCH_NO_HINT ((uint64)-1)

#define VM_LIMIT_UNLIMITED 0
#define VM_MAX_RESIDENT_LIMIT 16384

#define VM_POLICY_FIFO 0
#define VM_POLICY_CLOCK 1
#define VM_POLICY_AGING 2
#define VM_POLICY_COUNT 3

#define VM_FAIL_NONE 0
#define VM_FAIL_SWAP_READ 1
#define VM_FAIL_SWAP_WRITE 2
#define VM_FAIL_DELAY_TICKS 3
#define VM_FAIL_FRAME_ALLOC 4

#define VM_TEST_FRAME_PIN 10
#define VM_TEST_FRAME_METADATA 11
#define VM_TEST_POLICY_INVALID 12

struct vmstats {
  uint64 version;
  uint64 resident_limit;
  uint64 resident_count;
  uint64 policy;
  uint64 prefetch_enabled;
  uint64 prefetch_async;
  uint64 prefetch_automatic;
  uint64 generation;

  uint64 zero_faults;
  uint64 swap_faults;
  uint64 protection_faults;
  uint64 evictions;
  uint64 page_reads;
  uint64 page_writes;
  uint64 block_reads;
  uint64 block_writes;
  uint64 io_errors;
  uint64 max_concurrent_io;
  uint64 policy_fallbacks;

  uint64 prefetch_hints;
  uint64 prefetch_accepted;
  uint64 prefetch_coalesced;
  uint64 prefetch_dropped_invalid;
  uint64 prefetch_dropped_pressure;
  uint64 prefetch_issued;
  uint64 prefetch_completed;
  uint64 prefetch_useful;
  uint64 prefetch_late;
  uint64 prefetch_wasted;
  uint64 prefetch_canceled;
  uint64 prefetch_read_errors;

  uint64 queued_prefetch;
  uint64 inflight_io;
  uint64 free_swap_slots;
};

#endif
