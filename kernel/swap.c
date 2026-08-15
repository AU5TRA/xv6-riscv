#include "types.h"
#include "param.h"
#include "memlayout.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "fs.h"
#include "vmstats.h"
#include "swap.h"

static struct {
  struct spinlock lock;
  ushort refs[NSWAPSLOTS];
  uint free;
} slots;

#ifdef VM_DEBUG
static int test_slots[NSWAPSLOTS];
#endif

void
swap_init(void)
{
  initlock(&slots.lock, "swap slots");
  slots.free = NSWAPSLOTS;
}

int
swap_slot_alloc(void)
{
  int result = -1;
  acquire(&slots.lock);
  for(int i = 0; i < NSWAPSLOTS; i++){
    if(slots.refs[i] == 0){
      slots.refs[i] = 1;
      slots.free--;
      result = i;
      break;
    }
  }
  release(&slots.lock);
  return result;
}

int
swap_slot_get(int slot)
{
  int result = -1;
  acquire(&slots.lock);
  if(slot >= 0 && slot < NSWAPSLOTS && slots.refs[slot] != 0 &&
     slots.refs[slot] != (ushort)-1){
    slots.refs[slot]++;
    result = 0;
  }
  release(&slots.lock);
  return result;
}

int
swap_slot_put(int slot)
{
  int result = -1;
  acquire(&slots.lock);
  if(slot >= 0 && slot < NSWAPSLOTS && slots.refs[slot] != 0){
    slots.refs[slot]--;
    if(slots.refs[slot] == 0)
      slots.free++;
    result = 0;
  }
  release(&slots.lock);
  return result;
}

int
swap_slot_valid(int slot)
{
  int valid;
  acquire(&slots.lock);
  valid = slot >= 0 && slot < NSWAPSLOTS && slots.refs[slot] != 0;
  release(&slots.lock);
  return valid;
}

uint64
swap_free_slots(void)
{
  uint free;
  acquire(&slots.lock);
  free = slots.free;
  release(&slots.lock);
  return free;
}

static void
account_io(int write, int error)
{
  struct proc *p = myproc();
  if(p == 0)
    return;
  acquire(&p->vm.lock);
  if(write){
    p->vm.stats.page_writes++;
    p->vm.stats.block_writes += SWAP_BLOCKS_PER_PAGE;
  } else {
    p->vm.stats.page_reads++;
    p->vm.stats.block_reads += SWAP_BLOCKS_PER_PAGE;
  }
  if(error)
    p->vm.stats.io_errors++;
  release(&p->vm.lock);
}

static int
swap_page_io(int slot, uint64 pa, int write)
{
  if(pa % PGSIZE != 0 || !swap_slot_valid(slot))
    return -1;
#ifdef VM_DEBUG
  if(vmdebug_should_fail(write ? VM_FAIL_SWAP_WRITE : VM_FAIL_SWAP_READ)){
    account_io(write, 1);
    return -1;
  }
#endif
  int result = virtio_disk_raw_rw(SWAP_SECTOR(slot), (void *)pa, PGSIZE,
                                  write);
  account_io(write, result < 0);
  return result;
}

int
swap_page_read(int slot, uint64 pa)
{
  return swap_page_io(slot, pa, 0);
}

int
swap_page_write(int slot, uint64 pa)
{
  return swap_page_io(slot, pa, 1);
}

int
swap_check_invariants(void)
{
  uint free = 0;
  acquire(&slots.lock);
  for(int i = 0; i < NSWAPSLOTS; i++)
    if(slots.refs[i] == 0)
      free++;
  int ok = free == slots.free;
  release(&slots.lock);
  return ok ? 0 : -1;
}

#ifdef VM_DEBUG
static uchar
pattern(int slot, int offset)
{
  return (uchar)((slot * 31 + offset * 17 + 11) % 251);
}

static void
debug_release_slots(int count)
{
  for(int i = 0; i < count; i++)
    swap_slot_put(test_slots[i]);
}

static int
debug_swap_io(void)
{
  uchar *page = kalloc();
  if(page == 0)
    return -1;
  for(int expected = 0; expected < NSWAPSLOTS; expected++){
    int slot = swap_slot_alloc();
    if(slot != expected){
      printk("swapio alloc expected=%d got=%d\n", expected, slot);
      debug_release_slots(expected);
      kfree(page);
      return -1;
    }
    test_slots[expected] = slot;
    for(int i = 0; i < PGSIZE; i++)
      page[i] = pattern(slot, i);
    if(swap_page_write(slot, (uint64)page) < 0){
      printk("swapio write slot=%d failed\n", slot);
      debug_release_slots(expected + 1);
      kfree(page);
      return -1;
    }
    memset(page, 0, PGSIZE);
    if(swap_page_read(slot, (uint64)page) < 0){
      printk("swapio read slot=%d failed\n", slot);
      debug_release_slots(expected + 1);
      kfree(page);
      return -1;
    }
    for(int i = 0; i < PGSIZE; i++){
      if(page[i] != pattern(slot, i)){
        printk("swapio mismatch slot=%d offset=%d got=%d expected=%d\n",
               slot, i, page[i], pattern(slot, i));
        debug_release_slots(expected + 1);
        kfree(page);
        return -1;
      }
    }
  }
  debug_release_slots(NSWAPSLOTS);
  kfree(page);
  return swap_check_invariants();
}

static int
debug_swap_reuse(void)
{
  for(int i = 0; i < NSWAPSLOTS; i++){
    test_slots[i] = swap_slot_alloc();
    if(test_slots[i] != i)
      return -1;
  }
  if(swap_slot_alloc() != -1)
    return -1;
  for(int i = 0; i < NSWAPSLOTS; i += 2)
    if(swap_slot_put(test_slots[i]) < 0)
      return -1;
  for(int i = 0; i < NSWAPSLOTS; i += 2){
    int slot = swap_slot_alloc();
    if(slot != i)
      return -1;
    test_slots[i] = slot;
  }
  for(int i = 0; i < NSWAPSLOTS; i++)
    if(swap_slot_put(test_slots[i]) < 0)
      return -1;
  return swap_check_invariants();
}

static int
debug_swap_bounds(void)
{
  uchar *page = kalloc();
  if(page == 0)
    return -1;
  int ok = swap_slot_get(-1) < 0 && swap_slot_put(-1) < 0 &&
    swap_slot_get(NSWAPSLOTS) < 0 && swap_slot_put(NSWAPSLOTS) < 0 &&
    swap_page_read(-1, (uint64)page) < 0 &&
    swap_page_write(NSWAPSLOTS, (uint64)page) < 0;
  kfree(page);
  return ok ? swap_check_invariants() : -1;
}

static int
debug_swap_io_error(void)
{
  uchar *page = kalloc();
  int slot = swap_slot_alloc();
  if(page == 0 || slot < 0)
    return -1;
  vmdebug_failinject(VM_FAIL_SWAP_WRITE, 1);
  int ok = swap_page_write(slot, (uint64)page) < 0 &&
           swap_slot_valid(slot);
  swap_slot_put(slot);
  kfree(page);
  return ok ? swap_check_invariants() : -1;
}
#endif

int
swap_debug_test(int operation)
{
#ifdef VM_DEBUG
  switch(operation){
  case VM_TEST_SWAP_IO:
    return debug_swap_io();
  case VM_TEST_SWAP_REUSE:
    return debug_swap_reuse();
  case VM_TEST_SWAP_BOUNDS:
    return debug_swap_bounds();
  case VM_TEST_SWAP_IO_ERROR:
    return debug_swap_io_error();
  }
#endif
  return -1;
}
