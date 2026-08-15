#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmpage.h"
#include "fs.h"
#include "swap.h"

#define NPHYS_PAGES ((PHYSTOP - KERNBASE) / PGSIZE)

static struct {
  struct spinlock lock;
  struct vm_page pages[NPHYS_PAGES];
} frame_table;

static uint64 load_sequence;

static struct vm_page *
page_for_pa(uint64 pa)
{
  if(pa < KERNBASE || pa >= PHYSTOP || pa % PGSIZE != 0)
    return 0;
  return &frame_table.pages[(pa - KERNBASE) / PGSIZE];
}

static void
clear_page(struct vm_page *page)
{
  uint64 pa = page->pa;
  memset(page, 0, sizeof(*page));
  page->pa = pa;
  page->state = VM_PAGE_FREE;
  page->backing_slot = -1;
  page->policy_index = -1;
}

static void
setup_page(struct vm_page *page, struct proc *p, pagetable_t pagetable,
           uint64 va, int purpose)
{
  clear_page(page);
  page->owner = p;
  page->pagetable = pagetable;
  page->va = va;
  page->state = purpose == VM_FRAME_PREFETCH ? VM_PAGE_RESIDENT_PREFETCH :
                                                VM_PAGE_RESIDENT_DEMAND;
  page->pin_count = 1;
  page->busy = purpose == VM_FRAME_CONSTRUCTION;
  page->load_sequence = ++load_sequence;
}

static int
reclaim_frame(struct proc *p, pagetable_t newpt, uint64 newva, int purpose,
              uint64 *result)
{
  struct vm_page *victim = 0;
  uint64 oldest = (uint64)-1;

  acquire(&frame_table.lock);
  for(uint64 i = 0; i < NPHYS_PAGES; i++){
    struct vm_page *candidate = &frame_table.pages[i];
    if(candidate->owner == p && candidate->pin_count == 0 &&
       candidate->busy == 0 &&
       (candidate->state == VM_PAGE_RESIDENT_DEMAND ||
        candidate->state == VM_PAGE_RESIDENT_PREFETCH) &&
       candidate->load_sequence < oldest){
      victim = candidate;
      oldest = candidate->load_sequence;
    }
  }
  if(victim == 0){
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  victim->busy = 1;
  victim->state = VM_PAGE_EVICTING;
  victim->pin_count = 1;
  uint64 pa = victim->pa;
  uint64 victimva = victim->va;
  pagetable_t victimpt = victim->pagetable;
  release(&frame_table.lock);

  int slot = swap_slot_alloc();
  pte_t *pte = walk(victimpt, victimva, 0);
  if(slot < 0 || pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != pa){
    if(slot >= 0)
      swap_slot_put(slot);
    acquire(&frame_table.lock);
    victim = page_for_pa(pa);
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = VM_PAGE_RESIDENT_DEMAND;
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  uint flags = PTE_FLAGS(*pte) & ~(PTE_V | PTE_SWAPPED | PTE_BUSY);
  if(swap_page_write(slot, pa) < 0){
    swap_slot_put(slot);
    acquire(&frame_table.lock);
    victim = page_for_pa(pa);
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = VM_PAGE_RESIDENT_DEMAND;
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }

  acquire(&frame_table.lock);
  victim = page_for_pa(pa);
  if(victim->owner != p || victim->pagetable != victimpt ||
     victim->va != victimva || victim->state != VM_PAGE_EVICTING ||
     pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != pa){
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = VM_PAGE_RESIDENT_DEMAND;
    release(&frame_table.lock);
    swap_slot_put(slot);
    return VM_FRAME_ERROR;
  }
  *pte = SLOT2PTE(slot) | flags | PTE_SWAPPED;
  setup_page(victim, p, newpt, newva, purpose);
  release(&frame_table.lock);
  sfence_vma();

  acquire(&p->vm.lock);
  p->vm.stats.evictions++;
  release(&p->vm.lock);
  *result = pa;
  return VM_FRAME_OK;
}

void
vmpage_init(void)
{
  initlock(&frame_table.lock, "vmpage");
  for(uint64 i = 0; i < NPHYS_PAGES; i++){
    frame_table.pages[i].pa = KERNBASE + i * PGSIZE;
    clear_page(&frame_table.pages[i]);
  }
}

int
vm_frame_acquire(struct proc *p, pagetable_t pagetable, uint64 va,
                 int purpose, uint64 *pa)
{
  if(p == 0 || pagetable == 0 || pa == 0 || va % PGSIZE != 0)
    return VM_FRAME_ERROR;

#ifdef VM_DEBUG
  if(vmdebug_should_fail(VM_FAIL_FRAME_ALLOC))
    return VM_FRAME_ERROR;
#endif

  acquire(&p->vm.lock);
  if(p->vm.resident_limit != VM_LIMIT_UNLIMITED &&
     p->vm.resident_count >= p->vm.resident_limit){
    release(&p->vm.lock);
    return reclaim_frame(p, pagetable, va, purpose, pa);
  }
  p->vm.resident_count++;
  release(&p->vm.lock);

  uint64 mem = (uint64)kalloc();
  if(mem == 0){
    acquire(&p->vm.lock);
    p->vm.resident_count--;
    release(&p->vm.lock);
    return VM_FRAME_ERROR;
  }

  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(mem);
  if(page == 0 || page->owner != 0)
    panic("vm_frame_acquire metadata");
  setup_page(page, p, pagetable, va, purpose);
  release(&frame_table.lock);
  *pa = mem;
  return VM_FRAME_OK;
}

int
vm_frame_release(uint64 pa)
{
  struct proc *owner;

  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0){
    release(&frame_table.lock);
    return -1;
  }
  owner = page->owner;
  clear_page(page);
  release(&frame_table.lock);

  acquire(&owner->vm.lock);
  if(owner->vm.resident_count == 0)
    panic("vm_frame_release count");
  owner->vm.resident_count--;
  release(&owner->vm.lock);
  kfree((void *)pa);
  return 0;
}

int
vm_frame_pin(uint64 pa)
{
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0){
    release(&frame_table.lock);
    return -1;
  }
  page->pin_count++;
  release(&frame_table.lock);
  return 0;
}

int
vm_frame_unpin(uint64 pa)
{
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0 || page->pin_count == 0){
    release(&frame_table.lock);
    return -1;
  }
  page->pin_count--;
  if(page->pin_count == 0)
    page->busy = 0;
  release(&frame_table.lock);
  return 0;
}

int
vm_frame_is_candidate(struct proc *p, uint64 pa)
{
  int result;
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  result = page != 0 && page->owner == p && page->pin_count == 0 &&
           page->busy == 0 && (page->state == VM_PAGE_RESIDENT_DEMAND ||
                               page->state == VM_PAGE_RESIDENT_PREFETCH);
  release(&frame_table.lock);
  return result;
}

int
vm_reclaim_to_limit(struct proc *p)
{
  for(;;){
    acquire(&p->vm.lock);
    uint64 count = p->vm.resident_count;
    uint64 limit = p->vm.resident_limit;
    release(&p->vm.lock);
    if(limit == VM_LIMIT_UNLIMITED || count <= limit)
      return 0;
    uint64 pa;
    if(reclaim_frame(p, p->pagetable, TRAPFRAME, VM_FRAME_CONSTRUCTION, &pa) !=
       VM_FRAME_OK)
      return -1;
    if(vm_frame_release(pa) < 0)
      return -1;
  }
}

int
vmpage_debug_test(int operation)
{
#ifdef VM_DEBUG
  struct proc *p = myproc();
  uint64 pa;
  uint64 va = PGROUNDUP(p->sz);
  if(vm_frame_acquire(p, p->pagetable, va, VM_FRAME_DEMAND, &pa) !=
     VM_FRAME_OK)
    return -1;
  if(operation == VM_TEST_FRAME_PIN){
    int ok = !vm_frame_is_candidate(p, pa) && vm_frame_unpin(pa) == 0 &&
             vm_frame_is_candidate(p, pa);
    vm_frame_release(pa);
    return ok ? 0 : -1;
  }
  if(operation == VM_TEST_FRAME_METADATA){
    acquire(&frame_table.lock);
    struct vm_page *page = page_for_pa(pa);
    int clean = page->owner == p && page->pagetable == p->pagetable &&
                page->va == va && page->backing_slot == -1 &&
                page->prefetch_request_id == 0 && page->frequency == 0 &&
                page->aging_counter == 0;
    page->backing_slot = 17;
    page->prefetch_request_id = 99;
    page->frequency = 42;
    release(&frame_table.lock);
    vm_frame_release(pa);
    if(!clean)
      return -1;
    uint64 reused;
    if(vm_frame_acquire(p, p->pagetable, va, VM_FRAME_DEMAND, &reused) !=
       VM_FRAME_OK)
      return -1;
    acquire(&frame_table.lock);
    page = page_for_pa(reused);
    clean = reused == pa && page->backing_slot == -1 &&
            page->prefetch_request_id == 0 && page->frequency == 0 &&
            page->aging_counter == 0;
    release(&frame_table.lock);
    vm_frame_release(reused);
    return clean ? 0 : -1;
  }
  vm_frame_release(pa);
#endif
  return -1;
}

int
vmpage_check_proc(struct proc *p)
{
  uint64 count = 0;

  acquire(&frame_table.lock);
  for(uint64 i = 0; i < NPHYS_PAGES; i++){
    struct vm_page *page = &frame_table.pages[i];
    if(page->owner != p)
      continue;
    count++;
    if(page->pagetable != p->pagetable || page->va % PGSIZE != 0 ||
       page->state == VM_PAGE_FREE){
      printk("vmcheck pid=%d va=%p pa=%p state=%d owner mismatch\n",
             p->pid, (void *)page->va, (void *)page->pa, page->state);
      release(&frame_table.lock);
      return -1;
    }
    pte_t *pte = walk(page->pagetable, page->va, 0);
    if(pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != page->pa){
      printk("vmcheck pid=%d va=%p pa=%p state=%d pte mismatch\n",
             p->pid, (void *)page->va, (void *)page->pa, page->state);
      release(&frame_table.lock);
      return -1;
    }
  }
  release(&frame_table.lock);

  for(uint64 va = 0; va < p->sz; va += PGSIZE){
    pte_t *pte = walk(p->pagetable, va, 0);
    if(pte == 0)
      continue;
    if((*pte & PTE_V) && (*pte & PTE_SWAPPED)){
      printk("vmcheck pid=%d va=%p valid+swapped\n", p->pid, (void *)va);
      return -1;
    }
    if((*pte & PTE_SWAPPED) && !swap_slot_valid(PTE2SLOT(*pte))){
      printk("vmcheck pid=%d va=%p invalid slot=%d\n", p->pid,
             (void *)va, PTE2SLOT(*pte));
      return -1;
    }
  }

  acquire(&p->vm.lock);
  int ok = count == p->vm.resident_count &&
           (p->vm.resident_limit == VM_LIMIT_UNLIMITED ||
            count <= p->vm.resident_limit) &&
           p->vm.queued_prefetch == 0 && p->vm.inflight_io == 0;
  if(!ok)
    printk("vmcheck pid=%d resident=%d expected=%d limit=%d\n", p->pid,
           (int)count, (int)p->vm.resident_count, (int)p->vm.resident_limit);
  release(&p->vm.lock);
  return ok ? 0 : -1;
}
