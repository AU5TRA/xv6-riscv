#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmpage.h"
#include "prefetch.h"
#include "swap.h"

#define VM_ASYNC_REQUESTS 16

enum async_state {
  ASYNC_FREE,
  ASYNC_QUEUED,
  ASYNC_INFLIGHT,
};

struct async_prefetch {
  enum async_state state;
  int canceled;
  struct proc *owner;
  uint64 generation;
  pagetable_t pagetable;
  uint64 va;
  pte_t *pte;
  int slot;
  uint flags;
  uint64 pa;
  uint64 request_id;
};

static struct {
  struct spinlock lock;
  struct async_prefetch requests[VM_ASYNC_REQUESTS];
} async_queue;

void
vm_prefetch_init(void)
{
  initlock(&async_queue.lock, "prefetch queue");
}

static void
prefetch_stat(struct proc *p, uint64 *counter)
{
  acquire(&p->vm.lock);
  (*counter)++;
  release(&p->vm.lock);
}

int
vm_prefetch_hint(struct proc *p, uint64 va, int source)
{
  (void)source;
  va = PGROUNDDOWN(va);
  acquire(&p->vm.lock);
  p->vm.stats.prefetch_hints++;
  if(!p->vm.prefetch_enabled || p->vm.exiting || va >= p->sz){
    p->vm.stats.prefetch_dropped_invalid++;
    release(&p->vm.lock);
    return -1;
  }
  for(uint i = 0; i < p->vm.prefetch_count; i++){
    uint index = (p->vm.prefetch_head + i) % VM_PREFETCH_QUEUE_SIZE;
    if(p->vm.prefetch_queue[index].pagetable == p->pagetable &&
       p->vm.prefetch_queue[index].va == va){
      p->vm.stats.prefetch_coalesced++;
      release(&p->vm.lock);
      return 0;
    }
  }
  pte_t *pte = walk(p->pagetable, va, 0);
  if(pte == 0 || (*pte & PTE_SWAPPED) == 0 || (*pte & PTE_BUSY)){
    if(pte && (*pte & PTE_BUSY))
      p->vm.stats.prefetch_coalesced++;
    else
      p->vm.stats.prefetch_dropped_invalid++;
    release(&p->vm.lock);
    return -1;
  }
  if(p->vm.prefetch_count == VM_PREFETCH_QUEUE_SIZE){
    p->vm.stats.prefetch_dropped_pressure++;
    release(&p->vm.lock);
    return -1;
  }
  uint tail = (p->vm.prefetch_head + p->vm.prefetch_count) %
    VM_PREFETCH_QUEUE_SIZE;
  struct vm_prefetch_request *request = &p->vm.prefetch_queue[tail];
  request->va = va;
  request->pagetable = p->pagetable;
  request->generation = p->vm.generation;
  request->request_id = p->vm.next_prefetch_id++;
  p->vm.prefetch_count++;
  p->vm.queued_prefetch = p->vm.prefetch_count;
  p->vm.stats.prefetch_accepted++;
  release(&p->vm.lock);
  return 0;
}

static int
prefetch_one(struct proc *p, struct vm_prefetch_request *request)
{
  if(request->generation != p->vm.generation ||
     request->pagetable != p->pagetable || request->va >= p->sz){
    prefetch_stat(p, &p->vm.stats.prefetch_canceled);
    return -1;
  }
  pte_t *pte = walk(request->pagetable, request->va, 0);
  if(pte == 0 || (*pte & PTE_SWAPPED) == 0 || (*pte & PTE_BUSY)){
    prefetch_stat(p, &p->vm.stats.prefetch_canceled);
    return -1;
  }

  acquire(&p->vm.lock);
  uint64 limit = p->vm.resident_limit;
  p->vm.stats.prefetch_issued++;
  p->vm.inflight_io++;
  release(&p->vm.lock);
  if(limit != VM_LIMIT_UNLIMITED && limit < 2){
    acquire(&p->vm.lock);
    p->vm.stats.prefetch_dropped_pressure++;
    p->vm.inflight_io--;
    release(&p->vm.lock);
    return -1;
  }

  int slot = PTE2SLOT(*pte);
  uint flags = PTE_FLAGS(*pte) &
    ~(PTE_V | PTE_SWAPPED | PTE_BUSY | PTE_A | PTE_D);
  *pte |= PTE_BUSY;
  uint64 pa;
  if(vm_frame_acquire(p, request->pagetable, request->va,
                      VM_FRAME_PREFETCH, &pa) != VM_FRAME_OK){
    *pte = SLOT2PTE(slot) | flags | PTE_SWAPPED;
    wakeup(pte);
    acquire(&p->vm.lock);
    p->vm.stats.prefetch_dropped_pressure++;
    p->vm.inflight_io--;
    release(&p->vm.lock);
    return -1;
  }
  if(swap_page_read(slot, pa) < 0){
    vm_frame_release(pa);
    *pte = SLOT2PTE(slot) | flags | PTE_SWAPPED;
    wakeup(pte);
    acquire(&p->vm.lock);
    p->vm.stats.prefetch_read_errors++;
    p->vm.inflight_io--;
    release(&p->vm.lock);
    return -1;
  }
  if((*pte & (PTE_SWAPPED | PTE_BUSY)) !=
       (PTE_SWAPPED | PTE_BUSY) || PTE2SLOT(*pte) != slot ||
     request->generation != p->vm.generation ||
     request->pagetable != p->pagetable){
    vm_frame_release(pa);
    acquire(&p->vm.lock);
    p->vm.stats.prefetch_canceled++;
    p->vm.inflight_io--;
    release(&p->vm.lock);
    wakeup(pte);
    return -1;
  }
  *pte = PA2PTE(pa) | flags | PTE_V;
  sfence_vma();
  if(vm_frame_set_backing(pa, slot) < 0)
    panic("prefetch backing");
  vm_frame_unpin(pa);
  wakeup(pte);
  acquire(&p->vm.lock);
  p->vm.stats.prefetch_completed++;
  p->vm.inflight_io--;
  release(&p->vm.lock);
  return 0;
}

static int
prefetch_async_one(struct proc *p, struct vm_prefetch_request *request)
{
  if(request->generation != p->vm.generation ||
     request->pagetable != p->pagetable || request->va >= p->sz)
    return -1;
  pte_t *pte = walk(request->pagetable, request->va, 0);
  if(pte == 0 || (*pte & PTE_SWAPPED) == 0 || (*pte & PTE_BUSY))
    return -1;

  acquire(&p->vm.lock);
  uint64 limit = p->vm.resident_limit;
  int exiting = p->vm.exiting;
  release(&p->vm.lock);
  if(exiting || (limit != VM_LIMIT_UNLIMITED && limit < 2)){
    prefetch_stat(p, &p->vm.stats.prefetch_dropped_pressure);
    return -1;
  }

  int slot = PTE2SLOT(*pte);
  uint flags = PTE_FLAGS(*pte) &
    ~(PTE_V | PTE_SWAPPED | PTE_BUSY | PTE_A | PTE_D);
  *pte |= PTE_BUSY;
  uint64 pa;
  if(vm_frame_acquire(p, request->pagetable, request->va,
                      VM_FRAME_PREFETCH, &pa) != VM_FRAME_OK){
    *pte = SLOT2PTE(slot) | flags | PTE_SWAPPED;
    wakeup(pte);
    prefetch_stat(p, &p->vm.stats.prefetch_dropped_pressure);
    return -1;
  }

  acquire(&async_queue.lock);
  struct async_prefetch *async = 0;
  for(int i = 0; i < VM_ASYNC_REQUESTS; i++)
    if(async_queue.requests[i].state == ASYNC_FREE){
      async = &async_queue.requests[i];
      break;
    }
  if(async == 0){
    release(&async_queue.lock);
    vm_frame_release(pa);
    *pte = SLOT2PTE(slot) | flags | PTE_SWAPPED;
    wakeup(pte);
    prefetch_stat(p, &p->vm.stats.prefetch_dropped_pressure);
    return -1;
  }
  memset(async, 0, sizeof(*async));
  async->state = ASYNC_QUEUED;
  async->owner = p;
  async->generation = request->generation;
  async->pagetable = request->pagetable;
  async->va = request->va;
  async->pte = pte;
  async->slot = slot;
  async->flags = flags;
  async->pa = pa;
  async->request_id = request->request_id;
  release(&async_queue.lock);

  acquire(&p->vm.lock);
  p->vm.stats.prefetch_issued++;
  p->vm.inflight_io++;
  release(&p->vm.lock);
  wakeup(&async_queue);
  return 0;
}

int
vm_prefetch_service(struct proc *p, int max_pages)
{
  if(max_pages <= 0)
    return 0;
  if(max_pages > VM_PREFETCH_SERVICE_ALL)
    max_pages = VM_PREFETCH_SERVICE_ALL;
  int completed = 0;
  for(int i = 0; i < max_pages; i++){
    struct vm_prefetch_request request;
    acquire(&p->vm.lock);
    if(p->vm.prefetch_count == 0){
      release(&p->vm.lock);
      break;
    }
    request = p->vm.prefetch_queue[p->vm.prefetch_head];
    p->vm.prefetch_head = (p->vm.prefetch_head + 1) % VM_PREFETCH_QUEUE_SIZE;
    p->vm.prefetch_count--;
    p->vm.queued_prefetch = p->vm.prefetch_count;
    release(&p->vm.lock);
    acquire(&p->vm.lock);
    int asynchronous = p->vm.prefetch_async;
    release(&p->vm.lock);
    int result = asynchronous ? prefetch_async_one(p, &request) :
                                prefetch_one(p, &request);
    if(result == 0)
      completed++;
  }
  return completed;
}

static int
async_matches(struct proc *p, pagetable_t pagetable, uint64 start, uint64 end)
{
  int found = 0;
  acquire(&async_queue.lock);
  for(int i = 0; i < VM_ASYNC_REQUESTS; i++){
    struct async_prefetch *request = &async_queue.requests[i];
    if(request->state != ASYNC_FREE && request->owner == p &&
       request->pagetable == pagetable && request->va >= start &&
       request->va < end){
      found = 1;
      break;
    }
  }
  release(&async_queue.lock);
  return found;
}

void
vm_prefetch_cancel_range(struct proc *p, pagetable_t pagetable, uint64 start,
                         uint64 end)
{
  acquire(&p->vm.lock);
  struct vm_prefetch_request kept[VM_PREFETCH_QUEUE_SIZE];
  uint kept_count = 0;
  for(uint i = 0; i < p->vm.prefetch_count; i++){
    uint index = (p->vm.prefetch_head + i) % VM_PREFETCH_QUEUE_SIZE;
    struct vm_prefetch_request request = p->vm.prefetch_queue[index];
    if(request.pagetable == pagetable && request.va >= start &&
       request.va < end)
      p->vm.stats.prefetch_canceled++;
    else
      kept[kept_count++] = request;
  }
  for(uint i = 0; i < kept_count; i++)
    p->vm.prefetch_queue[i] = kept[i];
  p->vm.prefetch_head = 0;
  p->vm.prefetch_count = kept_count;
  p->vm.queued_prefetch = kept_count;
  release(&p->vm.lock);

  acquire(&async_queue.lock);
  for(int i = 0; i < VM_ASYNC_REQUESTS; i++){
    struct async_prefetch *request = &async_queue.requests[i];
    if(request->state != ASYNC_FREE && request->owner == p &&
       request->pagetable == pagetable && request->va >= start &&
       request->va < end)
      request->canceled = 1;
  }
  release(&async_queue.lock);
  wakeup(&async_queue);

  while(async_matches(p, pagetable, start, end)){
    sleep_prepare(&p->vm.inflight_io);
    if(async_matches(p, pagetable, start, end))
      sleep();
    else
      wakeup(&p->vm.inflight_io);
  }
}

void
vm_prefetch_drain(struct proc *p)
{
  acquire(&p->vm.lock);
  p->vm.exiting = 1;
  release(&p->vm.lock);
  vm_prefetch_cancel_range(p, p->pagetable, 0, MAXVA);
}

void
vm_prefetch_worker(void)
{
  // The scheduler enters a fresh kernel process holding its process lock.
  release(&myproc()->lock);
  for(;;){
    acquire(&async_queue.lock);
    int index = -1;
    for(int i = 0; i < VM_ASYNC_REQUESTS; i++)
      if(async_queue.requests[i].state == ASYNC_QUEUED){
        index = i;
        async_queue.requests[i].state = ASYNC_INFLIGHT;
        break;
      }
    if(index < 0){
      sleep_prepare(&async_queue);
      release(&async_queue.lock);
      sleep();
      continue;
    }
    struct async_prefetch request = async_queue.requests[index];
    release(&async_queue.lock);

    int io_result = request.canceled ? -1 :
      swap_page_read(request.slot, request.pa);

    acquire(&async_queue.lock);
    int canceled = async_queue.requests[index].canceled;
    release(&async_queue.lock);
    struct proc *p = request.owner;
    acquire(&p->vm.lock);
    int stale = p->vm.exiting || p->vm.generation != request.generation ||
      p->pagetable != request.pagetable;
    release(&p->vm.lock);

    int pte_matches = request.pte &&
      (*request.pte & (PTE_SWAPPED | PTE_BUSY)) ==
        (PTE_SWAPPED | PTE_BUSY) && PTE2SLOT(*request.pte) == request.slot;
    if(io_result == 0 && !canceled && !stale && pte_matches){
      *request.pte = PA2PTE(request.pa) | request.flags | PTE_V;
      sfence_vma();
      if(vm_frame_set_backing(request.pa, request.slot) < 0)
        panic("async prefetch backing");
      vm_frame_unpin(request.pa);
      prefetch_stat(p, &p->vm.stats.prefetch_completed);
    } else {
      if(pte_matches)
        *request.pte = SLOT2PTE(request.slot) | request.flags | PTE_SWAPPED;
      vm_frame_release(request.pa);
      if(io_result < 0 && !canceled)
        prefetch_stat(p, &p->vm.stats.prefetch_read_errors);
      else
        prefetch_stat(p, &p->vm.stats.prefetch_canceled);
    }
    if(request.pte)
      wakeup(request.pte);
    acquire(&p->vm.lock);
    if(p->vm.inflight_io == 0)
      panic("prefetch inflight");
    p->vm.inflight_io--;
    release(&p->vm.lock);

    acquire(&async_queue.lock);
    memset(&async_queue.requests[index], 0,
           sizeof(async_queue.requests[index]));
    release(&async_queue.lock);
    wakeup(&p->vm.inflight_io);
    wakeup(&async_queue);
  }
}
