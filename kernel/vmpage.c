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
#include "vmtrace.h"

#define NPHYS_PAGES ((PHYSTOP - KERNBASE) / PGSIZE)

static struct {
  struct spinlock lock;
  struct vm_page pages[NPHYS_PAGES];
  struct vm_page *candidates[NPHYS_PAGES];
} frame_table;

static uint64 load_sequence;

static struct vm_page *
page_for_pa(uint64 pa)
{
  if(pa < KERNBASE || pa >= PHYSTOP || pa % PGSIZE != 0)
    return 0;
  return &frame_table.pages[(pa - KERNBASE) / PGSIZE];
}

// owner_next/owner_prev thread every frame owned by a given process onto
// that process's vm.owned_head/owned_tail list. Every caller of these two
// helpers already holds frame_table.lock, matching the fields' documented
// protection (see vmpage.h and vmstate.h).
static void
owned_list_remove(struct vm_page *page)
{
  if(page->owner == 0)
    return;
  struct vmstate *vm = &page->owner->vm;
  if(page->owner_prev)
    page->owner_prev->owner_next = page->owner_next;
  else
    vm->owned_head = page->owner_next;
  if(page->owner_next)
    page->owner_next->owner_prev = page->owner_prev;
  else
    vm->owned_tail = page->owner_prev;
  page->owner_next = 0;
  page->owner_prev = 0;
}

static void
owned_list_insert(struct vm_page *page)
{
  struct vmstate *vm = &page->owner->vm;
  page->owner_prev = vm->owned_tail;
  page->owner_next = 0;
  if(vm->owned_tail)
    vm->owned_tail->owner_next = page;
  else
    vm->owned_head = page;
  vm->owned_tail = page;
}

static void
clear_page(struct vm_page *page)
{
  uint64 pa = page->pa;
  // Must run before memset wipes owner/owner_next/owner_prev below: this is
  // the single choke point (called directly by vm_frame_release(), and via
  // setup_page() for both a fresh frame and a reclaimed/repurposed one) that
  // detaches a frame from whichever process's owned-frame list it was on.
  owned_list_remove(page);
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
  page->aging_counter = 0xff;
  owned_list_insert(page);
}

static int
page_is_candidate(struct proc *p, struct vm_page *page)
{
  return page->owner == p && page->pin_count == 0 && page->busy == 0 &&
    (page->state == VM_PAGE_RESIDENT_DEMAND ||
     page->state == VM_PAGE_RESIDENT_PREFETCH);
}

static int
sample_page(struct vm_page *page, int clear_accessed)
{
  pte_t *pte = walk(page->pagetable, page->va, 0);
  if(pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != page->pa)
    return 0;
  int accessed = (*pte & PTE_A) != 0;
  page->referenced_sample = accessed;
  page->dirty_sample = (*pte & PTE_D) != 0;
  if(accessed){
    page->frequency++;
    page->last_access_epoch = load_sequence;
    if(page->state == VM_PAGE_RESIDENT_PREFETCH){
      page->state = VM_PAGE_RESIDENT_DEMAND;
      __sync_fetch_and_add(&page->owner->vm.stats.prefetch_useful, 1);
      vmtrace_emit(page->owner, VMTRACE_PREFETCH_USE, page->va, -1,
                   VM_PAGE_RESIDENT_DEMAND, PTE_FLAGS(*pte),
                   (page->pa - KERNBASE) / PGSIZE, page->backing_slot,
                   VMTRACE_NONE, VMTRACE_NONE, 0);
    }
  }
  if(clear_accessed && accessed)
    *pte &= ~PTE_A;
  return accessed;
}

static struct vm_page *
choose_fifo(struct vm_page **candidates, int count)
{
  struct vm_page *victim = 0;
  uint64 oldest = (uint64)-1;
  for(int i = 0; i < count; i++)
    if(candidates[i]->load_sequence < oldest){
      victim = candidates[i];
      oldest = candidates[i]->load_sequence;
    }
  return victim;
}

static struct vm_page *
choose_clock(struct proc *p, struct vm_page **candidates, int count)
{
  if(count == 0)
    return 0;
  int cleared = 0;
  for(int scanned = 0; scanned < count * 2; scanned++){
    int index = p->vm.clock_hand++ % count;
    struct vm_page *page = candidates[index];
    if(!sample_page(page, 1)){
      if(cleared)
        sfence_vma();
      return page;
    }
    cleared = 1;
  }
  if(cleared)
    sfence_vma();
  return candidates[p->vm.clock_hand++ % count];
}

static struct vm_page *
choose_aging(struct vm_page **candidates, int count)
{
  struct vm_page *victim = 0;
  int cleared = 0;
  for(int i = 0; i < count; i++){
    struct vm_page *page = candidates[i];
    int accessed = sample_page(page, 1);
    cleared |= accessed;
    page->aging_counter = (page->aging_counter >> 1) |
      (accessed ? 0x80 : 0);
    if(victim == 0 || page->aging_counter < victim->aging_counter ||
       (page->aging_counter == victim->aging_counter &&
        page->load_sequence < victim->load_sequence))
      victim = page;
  }
  if(cleared)
    sfence_vma();
  return victim;
}

static struct vm_page *
choose_policy_victim(struct proc *p, int count, int *fallback)
{
  if(count == 0)
    return 0;
  struct vm_page *victim;
#ifdef VM_DEBUG
  if(p->vm.invalid_policy_once){
    p->vm.invalid_policy_once = 0;
    victim = (struct vm_page *)1;
  } else
#endif
  if(p->vm.policy == VM_POLICY_FIFO)
    victim = choose_fifo(frame_table.candidates, count);
  else if(p->vm.policy == VM_POLICY_CLOCK)
    victim = choose_clock(p, frame_table.candidates, count);
  else if(p->vm.policy == VM_POLICY_AGING)
    victim = choose_aging(frame_table.candidates, count);
  else
    victim = 0;

  int valid = 0;
  for(int i = 0; i < count; i++)
    if(victim == frame_table.candidates[i] && page_is_candidate(p, victim)){
      valid = 1;
      break;
    }
  if(!valid){
    *fallback = 1;
    victim = choose_clock(p, frame_table.candidates, count);
  }
  return victim;
}

static int
reclaim_frame(struct proc *p, pagetable_t newpt, uint64 newva, int purpose,
              uint64 *result)
{
  struct vm_page *victim = 0;
  int fallback = 0;

  acquire(&frame_table.lock);
  // Walk only this process's own owned-frame list rather than scanning
  // every physical frame in the system: page_is_candidate() already
  // requires page->owner == p, so every frame reachable from any other
  // process's list can never contribute a candidate here anyway. This
  // bounds eviction cost by the faulting process's own resident set
  // instead of total physical memory.
  int candidate_count = 0;
  for(struct vm_page *candidate = p->vm.owned_head; candidate != 0;
      candidate = candidate->owner_next){
    if(page_is_candidate(p, candidate))
      frame_table.candidates[candidate_count++] = candidate;
  }
  victim = choose_policy_victim(p, candidate_count, &fallback);
  if(victim == 0){
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  sample_page(victim, 0);
  // The A and D bits the policy actually saw, captured before anything
  // clears them. Without this the trace recorded which page was evicted but
  // nothing about why: VICTIM_SELECTED and EVICT_BEGIN passed VMTRACE_NONE
  // for pte_flags and EVICT_END masked PTE_A and PTE_D out, so "was the
  // victim referenced" -- the single most informative feature a replacement
  // policy has -- was unrecoverable from a capture.
  pte_t *victim_pte = walk(victim->pagetable, victim->va, 0);
  uint64 victim_flags =
    victim_pte ? PTE_FLAGS(*victim_pte) : (uint64)VMTRACE_NONE;
  int wasted_prefetch = victim->state == VM_PAGE_RESIDENT_PREFETCH;
  enum vm_page_state victim_state = victim->state;
  victim->busy = 1;
  victim->state = VM_PAGE_EVICTING;
  victim->pin_count = 1;
  uint64 pa = victim->pa;
  uint64 victimva = victim->va;
  pagetable_t victimpt = victim->pagetable;
  int victim_backing = victim->backing_slot;
  release(&frame_table.lock);

  vmtrace_emit(p, VMTRACE_VICTIM_SELECTED, newva, -1, victim_state,
               victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
               victimva, VMTRACE_NONE, 0);
  vmtrace_emit(p, VMTRACE_EVICT_BEGIN, victimva, -1, victim_state,
               victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
               victimva, VMTRACE_NONE, 0);

  if(fallback){
    acquire(&p->vm.lock);
    p->vm.stats.policy_fallbacks++;
    release(&p->vm.lock);
    vmtrace_emit(p, VMTRACE_POLICY_FALLBACK, newva, -1, victim_state,
                 victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
                 victimva, VMTRACE_NONE, 0);
  }
  if(wasted_prefetch){
    acquire(&p->vm.lock);
    p->vm.stats.prefetch_wasted++;
    release(&p->vm.lock);
    vmtrace_emit(p, VMTRACE_PREFETCH_WASTE, victimva, -1, victim_state,
                 victim_flags, (pa - KERNBASE) / PGSIZE, victim_backing,
                 VMTRACE_NONE, VMTRACE_NONE, 0);
  }

  pte_t *pte = walk(victimpt, victimva, 0);
  int clean_backing = victim_backing >= 0 && swap_slot_valid(victim_backing) &&
    pte != 0 && (*pte & PTE_D) == 0;
  int slot = clean_backing ? victim_backing : swap_slot_alloc();
  int new_slot = !clean_backing;
  if(slot < 0 || pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != pa){
    if(new_slot && slot >= 0)
      swap_slot_put(slot);
    acquire(&frame_table.lock);
    victim = page_for_pa(pa);
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = victim_state;
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  uint report_flags = PTE_FLAGS(*pte);
  uint flags = report_flags &
    ~(PTE_V | PTE_SWAPPED | PTE_BUSY | PTE_A | PTE_D);
  if(new_slot)
    vmtrace_emit(p, VMTRACE_SWAP_WRITE_BEGIN, victimva, -1, victim_state,
                 report_flags, (pa - KERNBASE) / PGSIZE, slot, VMTRACE_NONE,
                 VMTRACE_NONE, 0);
  if(new_slot && swap_page_write(slot, pa) < 0){
    vmtrace_emit(p, VMTRACE_SWAP_WRITE_END, victimva, -1, victim_state,
                 report_flags, (pa - KERNBASE) / PGSIZE, slot, VMTRACE_NONE,
                 VMTRACE_NONE, -1);
    swap_slot_put(slot);
    acquire(&frame_table.lock);
    victim = page_for_pa(pa);
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = victim_state;
    release(&frame_table.lock);
    return VM_FRAME_ERROR;
  }
  if(new_slot)
    vmtrace_emit(p, VMTRACE_SWAP_WRITE_END, victimva, -1, victim_state,
                 report_flags, (pa - KERNBASE) / PGSIZE, slot, VMTRACE_NONE,
                 VMTRACE_NONE, 0);

  acquire(&frame_table.lock);
  victim = page_for_pa(pa);
  if(victim->owner != p || victim->pagetable != victimpt ||
     victim->va != victimva || victim->state != VM_PAGE_EVICTING ||
     pte == 0 || (*pte & PTE_V) == 0 || PTE2PA(*pte) != pa){
    victim->busy = 0;
    victim->pin_count = 0;
    victim->state = victim_state;
    release(&frame_table.lock);
    if(new_slot)
      swap_slot_put(slot);
    return VM_FRAME_ERROR;
  }
  *pte = SLOT2PTE(slot) | flags | PTE_SWAPPED;
  setup_page(victim, p, newpt, newva, purpose);
  release(&frame_table.lock);
  sfence_vma();
  vmtrace_emit(p, VMTRACE_EVICT_END, victimva, -1, victim_state,
               report_flags, (pa - KERNBASE) / PGSIZE, slot, newva,
               VMTRACE_NONE, 0);

  // A clean page transfers its retained backing reference to the swapped
  // PTE.  A dirty page receives a private slot, so release its old immutable
  // backing only after the new PTE is committed.
  if(new_slot && victim_backing >= 0)
    swap_slot_put(victim_backing);

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
  int backing_slot;

  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0){
    release(&frame_table.lock);
    return -1;
  }
  owner = page->owner;
  backing_slot = page->backing_slot;
  clear_page(page);
  release(&frame_table.lock);

  acquire(&owner->vm.lock);
  if(owner->vm.resident_count == 0)
    panic("vm_frame_release count");
  owner->vm.resident_count--;
  release(&owner->vm.lock);
  if(backing_slot >= 0 && swap_slot_put(backing_slot) < 0)
    panic("vm_frame_release backing");
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
vm_frame_set_backing(uint64 pa, int slot)
{
  if(!swap_slot_valid(slot))
    return -1;
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page == 0 || page->owner == 0 || page->backing_slot >= 0){
    release(&frame_table.lock);
    return -1;
  }
  page->backing_slot = slot;
  release(&frame_table.lock);
  return 0;
}

void
vm_frame_note_access(uint64 pa, int dirty)
{
  struct proc *owner = 0;
  uint64 useful_va = VMTRACE_NONE;
  int useful_slot = -1;
  acquire(&frame_table.lock);
  struct vm_page *page = page_for_pa(pa);
  if(page && page->owner){
    page->referenced_sample = 1;
    page->frequency++;
    if(dirty)
      page->dirty_sample = 1;
    if(page->state == VM_PAGE_RESIDENT_PREFETCH){
      page->state = VM_PAGE_RESIDENT_DEMAND;
      owner = page->owner;
      useful_va = page->va;
      useful_slot = page->backing_slot;
    }
  }
  release(&frame_table.lock);
  if(owner){
    acquire(&owner->vm.lock);
    owner->vm.stats.prefetch_useful++;
    release(&owner->vm.lock);
    vmtrace_emit(owner, VMTRACE_PREFETCH_USE, useful_va, -1,
                 VM_PAGE_RESIDENT_DEMAND, VMTRACE_NONE,
                 (pa - KERNBASE) / PGSIZE, useful_slot, VMTRACE_NONE,
                 VMTRACE_NONE, dirty);
  }
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
  if(operation == VM_TEST_POLICY_INVALID){
    acquire(&p->vm.lock);
    p->vm.invalid_policy_once = 1;
    release(&p->vm.lock);
    return 0;
  }
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
    int test_slot = swap_slot_alloc();
    if(test_slot < 0){
      vm_frame_release(pa);
      return -1;
    }
    acquire(&frame_table.lock);
    struct vm_page *page = page_for_pa(pa);
    int clean = page->owner == p && page->pagetable == p->pagetable &&
                page->va == va && page->backing_slot == -1 &&
                page->prefetch_request_id == 0 && page->frequency == 0 &&
                page->aging_counter == 0xff;
    page->backing_slot = test_slot;
    page->prefetch_request_id = 99;
    page->frequency = 42;
    page->aging_counter = 0x12;
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
            page->aging_counter == 0xff;
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

  // Cross-check the owned-frame list reclaim_frame() now relies on against
  // the full-table scan above, which remains the independent ground truth:
  // every page found by owner-field alone must also be reachable from
  // p->vm.owned_head exactly once, and the list must contain nothing else.
  uint64 listed = 0;
  for(struct vm_page *page = p->vm.owned_head; page != 0;
      page = page->owner_next){
    if(page->owner != p){
      printk("vmcheck pid=%d owned-list entry pa=%p owner mismatch\n",
             p->pid, (void *)page->pa);
      release(&frame_table.lock);
      return -1;
    }
    listed++;
  }
  if(listed != count){
    printk("vmcheck pid=%d owned-list count=%d scan count=%d mismatch\n",
           p->pid, (int)listed, (int)count);
    release(&frame_table.lock);
    return -1;
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
