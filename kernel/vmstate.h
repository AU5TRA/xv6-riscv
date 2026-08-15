#ifndef XV6_VMSTATE_H
#define XV6_VMSTATE_H

#include "vmstats.h"

struct vmstate {
  struct spinlock lock;
  uint64 resident_limit;
  uint64 resident_count;
  int policy;
  int prefetch_enabled;
  int exiting;
  uint64 queued_prefetch;
  uint64 inflight_io;
  uint64 generation;
  uint64 clock_hand;
#ifdef VM_DEBUG
  int invalid_policy_once;
#endif
  struct vmstats stats;
};

#endif
