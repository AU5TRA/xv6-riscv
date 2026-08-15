#ifndef XV6_VMSTATE_H
#define XV6_VMSTATE_H

#include "vmstats.h"
#include "prefetch.h"

struct vmstate {
  struct spinlock lock;
  uint64 resident_limit;
  uint64 resident_count;
  int policy;
  int prefetch_enabled;
  int prefetch_async;
  int prefetch_automatic;
  int exiting;
  uint64 queued_prefetch;
  uint64 inflight_io;
  uint64 generation;
  uint64 clock_hand;
  struct vm_prefetch_request prefetch_queue[VM_PREFETCH_QUEUE_SIZE];
  uint prefetch_head;
  uint prefetch_count;
  uint64 next_prefetch_id;
#ifdef VM_DEBUG
  int invalid_policy_once;
#endif
  struct vmstats stats;
};

#endif
