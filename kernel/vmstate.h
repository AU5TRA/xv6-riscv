#ifndef XV6_VMSTATE_H
#define XV6_VMSTATE_H

#include "vmstats.h"
#include "prefetch.h"

struct vm_page;

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
  // VM_POLICY_ML: the weights this process scores with (set by vmctl
  // VM_SET_ML_WEIGHTS, inherited on fork, kept across exec) and the number
  // of eviction scans so far -- the time base of every ML feature.
  // ml_scans is protected by vmpage.c's frame_table.lock, like owned_head.
  struct vm_ml_weights ml;
  uint64 ml_scans;
  // Head/tail of this process's owned-frame list (vm_page.owner_next/prev).
  // Protected by vmpage.c's frame_table.lock, NOT this struct's own .lock --
  // every mutation site already holds frame_table.lock for other reasons.
  struct vm_page *owned_head;
  struct vm_page *owned_tail;
};

#endif
