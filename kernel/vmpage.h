#ifndef XV6_VMPAGE_H
#define XV6_VMPAGE_H

enum vm_page_state {
  VM_PAGE_FREE,
  VM_PAGE_RESIDENT_DEMAND,
  VM_PAGE_RESIDENT_PREFETCH,
  VM_PAGE_EVICTING,
};

enum vm_frame_result {
  VM_FRAME_OK = 0,
  VM_FRAME_ERROR = -1,
  VM_FRAME_NEED_EVICTION = -2,
};

enum vm_frame_purpose {
  VM_FRAME_DEMAND,
  VM_FRAME_PREFETCH,
  VM_FRAME_CONSTRUCTION,
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

int vm_frame_acquire(struct proc *, pagetable_t, uint64,
                     int, uint64 *);
int vm_frame_release(uint64);
int vm_frame_pin(uint64);
int vm_frame_unpin(uint64);
int vm_frame_set_backing(uint64, int);
int vm_frame_is_candidate(struct proc *, uint64);
int vmpage_debug_test(int);
int vm_reclaim_to_limit(struct proc *);

#endif
