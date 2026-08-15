#ifndef XV6_VMPAGE_H
#define XV6_VMPAGE_H

enum vm_page_state {
  VM_PAGE_FREE,
  VM_PAGE_RESIDENT_DEMAND,
  VM_PAGE_RESIDENT_PREFETCH,
  VM_PAGE_EVICTING,
};

struct vm_page {
  uint64 pa;
  struct proc *owner;
  pagetable_t pagetable;
  uint64 va;
  enum vm_page_state state;
  uint pin_count;
  int busy;
  int referenced_sample;
  int dirty_sample;
  uint64 load_sequence;
  uint64 last_access_epoch;
  uint64 frequency;
  uint aging_counter;
  int backing_slot;
  uint64 prefetch_request_id;
  int policy_index;
};

#endif
