#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "vmpage.h"

#define NPHYS_PAGES ((PHYSTOP - KERNBASE) / PGSIZE)

static struct {
  struct spinlock lock;
  struct vm_page pages[NPHYS_PAGES];
} frame_table;

void
vmpage_init(void)
{
  initlock(&frame_table.lock, "vmpage");
  for(uint64 i = 0; i < NPHYS_PAGES; i++){
    frame_table.pages[i].pa = KERNBASE + i * PGSIZE;
    frame_table.pages[i].backing_slot = -1;
    frame_table.pages[i].policy_index = -1;
  }
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
