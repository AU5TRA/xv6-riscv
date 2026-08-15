#ifndef XV6_PREFETCH_H
#define XV6_PREFETCH_H

#define VM_PREFETCH_QUEUE_SIZE 16
#define VM_PREFETCH_SERVICE_ALL 16

struct proc;

struct vm_prefetch_request {
  uint64 va;
  uint64 request_id;
  uint64 generation;
  pagetable_t pagetable;
};

int vm_prefetch_hint(struct proc *, uint64, int);
int vm_prefetch_service(struct proc *, int);
void vm_prefetch_cancel_range(struct proc *, pagetable_t, uint64, uint64);
void vm_prefetch_init(void);
void vm_prefetch_drain(struct proc *);
void vm_prefetch_worker(void) __attribute__((noreturn));

#endif
