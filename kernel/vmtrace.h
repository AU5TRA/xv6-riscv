#ifndef XV6_VMTRACE_H
#define XV6_VMTRACE_H

#define VMTRACE_VERSION 1
#define VMTRACE_CAPACITY 128
#define VMTRACE_READ_MAX 8
#define VMTRACE_NONE ((uint64)-1)

enum vmtrace_type {
  VMTRACE_ZERO_FAULT = 1,
  VMTRACE_SWAP_FAULT,
  VMTRACE_PROTECTION_FAULT,
  VMTRACE_MAP,
  VMTRACE_UNMAP,
  VMTRACE_VICTIM_SELECTED,
  VMTRACE_EVICT_BEGIN,
  VMTRACE_EVICT_END,
  VMTRACE_SWAP_READ_BEGIN,
  VMTRACE_SWAP_READ_END,
  VMTRACE_SWAP_WRITE_BEGIN,
  VMTRACE_SWAP_WRITE_END,
  VMTRACE_PREFETCH_HINT,
  VMTRACE_PREFETCH_QUEUE,
  VMTRACE_PREFETCH_BEGIN,
  VMTRACE_PREFETCH_END,
  VMTRACE_PREFETCH_USE,
  VMTRACE_PREFETCH_WASTE,
  VMTRACE_PREFETCH_CANCEL,
  VMTRACE_POLICY_FALLBACK,
  VMTRACE_DROP,
  VMTRACE_TYPE_COUNT,
};

struct vmtrace_event {
  uint64 version;
  uint64 size;
  uint64 sequence;
  uint64 cycle;
  uint64 ticks;
  uint64 pid;
  uint64 generation;
  uint64 type;
  uint64 vpn;
  uint64 access;
  uint64 page_state;
  uint64 pte_flags;
  uint64 frame_index;
  uint64 swap_slot;
  uint64 policy;
  uint64 victim_vpn;
  uint64 queue_id;
  uint64 resident_count;
  uint64 status;
};

#endif
