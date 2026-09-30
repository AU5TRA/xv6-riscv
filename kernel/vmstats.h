#ifndef XV6_VMSTATS_H
#define XV6_VMSTATS_H

#define VMSTATS_VERSION 3

#define VM_SET_LIMIT 1
#define VM_SET_POLICY 2
#define VM_PREFETCH_ENABLE 3
#define VM_RESET_STATS 4
#define VM_PREFETCH_MODE 5
#define VM_PREFETCH_AUTOMATIC 6
#define VM_TRACE_ENABLE 7
#define VM_TRACE_RESET 8
#define VM_TRACE_SET_CAPACITY 9
#define VM_TRACE_SET_MASK 10
#define VM_SET_ML_WEIGHTS 11   // value: user address of a struct vm_ml_weights
#define VM_PREFETCH_NO_HINT ((uint64)-1)

#define VM_LIMIT_UNLIMITED 0
#define VM_MAX_RESIDENT_LIMIT 16384

#define VM_POLICY_FIFO 0
#define VM_POLICY_CLOCK 1
#define VM_POLICY_AGING 2
#define VM_POLICY_LFU 3
#define VM_POLICY_ML 4          // learned linear score (kernel/mlfeat.h)
#define VM_POLICY_COUNT 5

// VM_POLICY_ML features (kernel/mlfeat.h computes them), in the order of
// tools/ml2/pagesim.py FEATURES[4:].
#define ML_F_REF      0   // accessed bit seen at this scan         (0 or 256)
#define ML_F_AGING    1   // 8-bit aging counter / 255              (0..256)
#define ML_F_SFREQ    2   // log1p(scans that found it accessed)
#define ML_F_IDLE     3   // log1p(scans since last found accessed)
#define ML_F_AGE      4   // log1p(scans since it was loaded)
#define ML_F_DIRTY    5   // dirty bit                              (0 or 256)
#define ML_F_REFAULTS 6   // log1p(times evicted and faulted back)
#define ML_F_RDIST    7   // log1p(evictions between eviction and refault)
#define ML_NFEAT      8

// The weights a process scores with (vmctl VM_SET_ML_WEIGHTS).
struct vm_ml_weights {
  int n;                    // features used, <= ML_NFEAT
  int feat[ML_NFEAT];       // ML_F_* ids
  int qa[ML_NFEAT];         // integer weights: round(W / std * 2^8)
  int protect_age;          // probation, in scans
};


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

  // Cost of victim selection, for every policy: timer ticks spent choosing
  // (r_time(), 10 MHz on QEMU virt) and candidates examined.
  uint64 select_ticks;
  uint64 candidates_scanned;
};

#endif
